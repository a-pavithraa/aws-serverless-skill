"""Baseline tests. The unit tests need nothing installed; IntegrationTest needs terraform,
tflint, checkov and network, like test_checks.py."""

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SCRIPTS = REPO / "skills" / "aws-iac-team-harness" / "scripts"
FIXTURES = REPO / "tests" / "fixtures" / "checks"
sys.path.insert(0, str(SCRIPTS))

import baseline  # noqa: E402
import check  # noqa: E402

TODAY = date(2026, 11, 8)


def finding(check_id, resource):
    return {"id": check_id, "name": check_id, "resource": resource, "file": "infra/main.tf", "fix": "x"}


def failing(*findings, root="infra [dev]"):
    return check.CheckResult("checkov", root, "FAIL", f"{len(findings)} failed", "", list(findings))


def entry(check_id, resource, expires="2027-05-01"):
    return {"id": check_id, "root": "infra", "resource": resource, "owner": "team-a",
            "reason": "legacy, tracked in ISSUE-1", "expires": expires}


class ApplyBaselineTest(unittest.TestCase):
    def test_recorded_finding_is_tolerated(self):
        [result], retired = baseline.apply([failing(finding("CKV_AWS_66", "aws_cloudwatch_log_group.old"))],
                                           [entry("CKV_AWS_66", "aws_cloudwatch_log_group.old")], TODAY)

        self.assertEqual("PASS", result.status)
        self.assertEqual([], result.findings)
        self.assertIn("1 baselined", result.detail)
        self.assertEqual([], retired)

    def test_new_finding_fails(self):
        [result], _ = baseline.apply([failing(finding("CKV_AWS_66", "aws_cloudwatch_log_group.old"),
                                              finding("CKV_AWS_66", "aws_cloudwatch_log_group.new"))],
                                     [entry("CKV_AWS_66", "aws_cloudwatch_log_group.old")], TODAY)

        self.assertEqual("FAIL", result.status)
        self.assertEqual(["aws_cloudwatch_log_group.new"], [f["resource"] for f in result.findings])

    def test_equal_count_substitution_fails(self):
        [result], retired = baseline.apply([failing(finding("CKV_AWS_66", "aws_cloudwatch_log_group.new"))],
                                           [entry("CKV_AWS_66", "aws_cloudwatch_log_group.old")], TODAY)

        self.assertEqual("FAIL", result.status)
        self.assertEqual(["CKV_AWS_66 infra aws_cloudwatch_log_group.old"], retired)

    def test_same_rule_on_another_resource_is_not_covered(self):
        [result], _ = baseline.apply([failing(finding("CKV_AWS_50", "aws_lambda_function.a"))],
                                     [entry("CKV_AWS_66", "aws_lambda_function.a")], TODAY)

        self.assertEqual("FAIL", result.status)

    def test_fixed_finding_is_retired(self):
        passing = check.CheckResult("checkov", "infra [dev]", "PASS", "40 passed")

        [result], retired = baseline.apply([passing], [entry("CKV_AWS_66", "aws_cloudwatch_log_group.old")], TODAY)

        self.assertEqual("PASS", result.status)
        self.assertEqual(["CKV_AWS_66 infra aws_cloudwatch_log_group.old"], retired)

    def test_expired_entry_no_longer_tolerates(self):
        [result], _ = baseline.apply([failing(finding("CKV_AWS_66", "aws_cloudwatch_log_group.old"))],
                                     [entry("CKV_AWS_66", "aws_cloudwatch_log_group.old", expires="2026-11-01")], TODAY)

        self.assertEqual("FAIL", result.status)
        self.assertIn("expired", result.findings[0]["fix"])

    def test_entry_without_owner_reason_or_expiry_is_rejected(self):
        for missing in ("owner", "reason", "expires"):
            with self.subTest(missing=missing):
                bad = entry("CKV_AWS_66", "aws_cloudwatch_log_group.old")
                del bad[missing]

                with self.assertRaises(baseline.BaselineError):
                    baseline.validate([bad])

    def test_unverified_results_are_untouched(self):
        unverified = check.CheckResult("checkov", "infra", "UNVERIFIED", "checkov not found")

        [result], _ = baseline.apply([unverified], [entry("CKV_AWS_66", "x")], TODAY)

        self.assertEqual("UNVERIFIED", result.status)


class IntegrationTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="baseline-"))
        self.project = self.tmp / "project"
        shutil.copytree(FIXTURES / "lambda-without-log-group", self.project / "infra")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def check(self):
        result = subprocess.run([sys.executable, str(SCRIPTS / "check.py"), str(self.project), "--json"],
                                capture_output=True, text=True)
        return json.loads(result.stdout)

    def test_recorded_legacy_passes_and_a_new_violation_fails(self):
        recorded = subprocess.run(
            [sys.executable, str(SCRIPTS / "baseline.py"), "record", str(self.project),
             "--owner", "platform-team", "--reason", "pre-harness code, ISSUE-7", "--expires", "2027-05-01"],
            capture_output=True, text=True)
        self.assertEqual(0, recorded.returncode, recorded.stderr)
        entries = json.loads((self.project / "harness" / "baseline.json").read_text(encoding="utf-8"))["findings"]
        self.assertIn(("HARNESS_AWS_1", "aws_lambda_function.worker"), {(e["id"], e["resource"]) for e in entries})

        checkov = [c for c in self.check()["checks"] if c["id"] == "checkov"]
        self.assertEqual(["PASS"], [c["status"] for c in checkov])

        function = (self.project / "infra" / "function.tf").read_text(encoding="utf-8")
        second = function.split('resource "aws_lambda_function" "worker"')[1].split("\n}\n")[0]
        with open(self.project / "infra" / "function.tf", "a", encoding="utf-8") as f:
            f.write('\nresource "aws_lambda_function" "second"' + second.replace("var.name", '"${var.name}-2"') + "\n}\n")

        checkov = [c for c in self.check()["checks"] if c["id"] == "checkov"][0]
        self.assertEqual("FAIL", checkov["status"])
        self.assertEqual({"aws_lambda_function.second"}, {f["resource"] for f in checkov["findings"]})


if __name__ == "__main__":
    unittest.main()
