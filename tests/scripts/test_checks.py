"""Tests for the shared check command.

Needs terraform, tflint 0.65.0 and checkov 3.4.3 on PATH, network for `terraform init`
and `tflint --init` (set GITHUB_TOKEN to avoid GitHub rate limits), and Copier:
    uv run --no-project --with copier==9.19.1 python -m unittest discover -s tests/scripts -p test_checks.py
"""

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
HARNESS = REPO / "skills" / "aws-iac-team-harness"
CHECK = HARNESS / "scripts" / "check.py"
NEW_PROJECT_CHECK = REPO / "skills" / "creating-aws-projects" / "scripts" / "check_new_project.py"
TEMPLATE = REPO / "skills" / "creating-aws-projects" / "templates" / "apigw-lambda"
FIXTURES = REPO / "tests" / "fixtures" / "checks"

sys.path.insert(0, str(HARNESS / "scripts"))

import check  # noqa: E402

ANSWERS = {"project_name": "check-test", "aws_region": "us-east-1", "environment": "dev",
           "auth_mode": "iam", "log_retention_days": 14}


def run(script, *args):
    result = subprocess.run([sys.executable, str(script), *args], capture_output=True, text=True)
    report = json.loads(result.stdout) if result.stdout.strip().startswith("{") else None
    return result, report


def statuses(report, check_id):
    return [c["status"] for c in report["checks"] if c["id"] == check_id]


def finding_ids(report):
    return {f["id"] for c in report["checks"] for f in c.get("findings", [])}


class AggregateTest(unittest.TestCase):
    def results(self, *values):
        return [check.CheckResult(id=f"c{i}", root=".", status=s) for i, s in enumerate(values)]

    def test_all_pass_exits_zero(self):
        self.assertEqual(("PASS", 0), check.aggregate(self.results("PASS", "PASS")))

    def test_fail_beats_unverified(self):
        self.assertEqual(("FAIL", 1), check.aggregate(self.results("PASS", "UNVERIFIED", "FAIL")))

    def test_unverified_without_fail_exits_two(self):
        self.assertEqual(("UNVERIFIED", 2), check.aggregate(self.results("PASS", "UNVERIFIED")))

    def test_no_checks_is_unverified(self):
        self.assertEqual(("UNVERIFIED", 2), check.aggregate([]))


class Workdir(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="checks-"))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def render(self):
        import copier

        dest = self.tmp / "project"
        copier.run_copy(str(TEMPLATE), str(dest), data=ANSWERS, defaults=True, quiet=True, unsafe=False)
        return dest

    def fixture(self, name):
        dest = self.tmp / name
        shutil.copytree(FIXTURES / name, dest)
        return dest

    def edit(self, path, pattern, replacement):
        text = path.read_text(encoding="utf-8")
        new_text, count = re.subn(pattern, replacement, text, flags=re.MULTILINE | re.DOTALL)
        self.assertGreater(count, 0, f"{pattern!r} not found in {path}")
        path.write_text(new_text, encoding="utf-8")


class RenderedProjectTest(Workdir):
    def test_clean_render_passes_every_check(self):
        project = self.render()

        result, report = run(CHECK, str(project), "--json")

        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertEqual("PASS", report["status"])
        for check_id in ["app-tests", "fmt", "init", "validate", "tflint", "checkov", "terraform-test"]:
            self.assertEqual(["PASS"], statuses(report, check_id), check_id)

    def test_new_project_check_delegates_and_adds_template_checks(self):
        project = self.render()
        subprocess.run([sys.executable, str(HARNESS / "scripts" / "apply_harness.py"), str(project)],
                       capture_output=True, check=True)

        result, report = run(NEW_PROJECT_CHECK, str(project), "--json")

        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertEqual(["PASS"], statuses(report, "template-syntax"))
        self.assertEqual(["PASS"], statuses(report, "runtime-profile"))
        self.assertEqual(["PASS"], statuses(report, "harness-installed"))
        self.assertEqual(["PASS"], statuses(report, "checkov"))

    def test_missing_retention_fails_with_fix(self):
        project = self.render()
        self.edit(project / "infra" / "main.tf",
                  r'(resource "aws_cloudwatch_log_group" "lambda" \{.*?)\n  retention_in_days = var.log_retention_days', r"\1")

        result, report = run(CHECK, str(project), "--json")

        self.assertEqual(1, result.returncode)
        self.assertIn("CKV_AWS_66", finding_ids(report))
        self.assertIn("retention_in_days", json.dumps(report))

    def test_unauthenticated_route_fails(self):
        project = self.render()
        self.edit(project / "infra" / "main.tf", r'authorization_type = local.authorization', 'authorization_type = "NONE"')

        result, report = run(CHECK, str(project), "--json")

        self.assertEqual(1, result.returncode)
        self.assertIn("CKV_AWS_309", finding_ids(report))

    def test_alarms_removed_in_another_file_fail_at_the_function(self):
        project = self.render()
        observability = project / "infra" / "observability.tf"
        self.edit(observability, r'resource "aws_cloudwatch_metric_alarm".*?(?=resource "aws_cloudwatch_dashboard")', "")
        self.edit(project / "infra" / "outputs.tf", r'output "alarm_names" \{.*?\n\}\n', "")

        result, report = run(CHECK, str(project), "--json")

        self.assertEqual(1, result.returncode)
        finding = [f for c in report["checks"] for f in c.get("findings", []) if f["id"] == "HARNESS_AWS_2"]
        self.assertTrue(finding, report)
        self.assertEqual("aws_lambda_function.api", finding[0]["resource"])
        self.assertTrue(finding[0]["file"].endswith("main.tf"))

    def test_alarm_topic_on_aws_managed_key_fails(self):
        project = self.render()
        self.edit(project / "infra" / "observability.tf",
                  r'kms_master_key_id = aws_kms_key.alarms.arn', 'kms_master_key_id = "alias/aws/sns"')

        result, report = run(CHECK, str(project), "--json")

        self.assertEqual(1, result.returncode)
        finding = [f for c in report["checks"] for f in c.get("findings", []) if f["id"] == "HARNESS_AWS_3"]
        self.assertEqual(["aws_sns_topic.alarms"], [f["resource"] for f in finding])

    def test_unformatted_file_fails(self):
        project = self.render()
        self.edit(project / "infra" / "outputs.tf", r'^  value\s+= var\.aws_region',
                  '      value    =    var.aws_region')

        result, report = run(CHECK, str(project), "--json")

        self.assertEqual(1, result.returncode)
        self.assertEqual(["FAIL"], statuses(report, "fmt"))
        self.assertIn("terraform fmt", json.dumps(report))

    def test_missing_tool_is_unverified_not_pass(self):
        project = self.render()

        result, report = run(CHECK, str(project), "--json", "--checkov", "no-such-checkov")

        self.assertEqual(2, result.returncode)
        self.assertEqual(["UNVERIFIED"], statuses(report, "checkov"))

    def test_init_failure_makes_dependent_checks_unverified(self):
        project = self.render()
        self.edit(project / "infra" / "versions.tf", r'">= 6.72.0, < 7.0.0"', '"= 99.0.0"')

        result, report = run(CHECK, str(project), "--json")

        self.assertEqual(2, result.returncode, result.stdout)
        for check_id in ["init", "validate", "tflint", "terraform-test"]:
            self.assertEqual(["UNVERIFIED"], statuses(report, check_id), check_id)


class FixtureTest(Workdir):
    def test_function_without_managed_log_group_fails(self):
        result, report = run(CHECK, str(self.fixture("lambda-without-log-group")), "--json")

        self.assertEqual(1, result.returncode)
        self.assertIn("HARNESS_AWS_1", finding_ids(report))

    def test_log_group_and_alarm_in_other_files_pass(self):
        result, report = run(CHECK, str(self.fixture("lambda-cross-file")), "--json")

        self.assertNotIn("HARNESS_AWS_1", finding_ids(report))
        self.assertNotIn("HARNESS_AWS_2", finding_ids(report))
        self.assertEqual(["PASS"], statuses(report, "checkov"), report)

    def test_managed_key_topic_without_alarm_passes(self):
        project = self.fixture("lambda-cross-file")
        (project / "topic.tf").write_text(
            'resource "aws_sns_topic" "events" {\n  name              = "events"\n'
            '  kms_master_key_id = "alias/aws/sns"\n}\n', encoding="utf-8")

        result, report = run(CHECK, str(project), "--json")

        self.assertNotIn("HARNESS_AWS_3", finding_ids(report))

    def test_unresolved_variables_are_unverified(self):
        project = self.fixture("lambda-cross-file")
        shutil.rmtree(project / "envs")

        result, report = run(CHECK, str(project), "--json")

        self.assertEqual(["UNVERIFIED"], statuses(report, "checkov"))
        self.assertIn("var-file", json.dumps(report))

    def test_var_files_in_env_directory_are_scanned(self):
        project = self.fixture("lambda-cross-file")
        (project / "envs").rename(project / "env")

        result, report = run(CHECK, str(project), "--json")

        self.assertEqual(["PASS"], statuses(report, "checkov"), report)

    def test_var_file_option_names_files_anywhere(self):
        project = self.fixture("lambda-cross-file")
        (project / "envs").rename(project / "config")
        var_file = next((project / "config").glob("*.tfvars"))

        result, report = run(CHECK, str(project), "--json", "--var-file", str(var_file))

        self.assertEqual(["PASS"], statuses(report, "checkov"), report)


class ChangedRootsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="roots-"))
        for name in ("a", "b"):
            (self.tmp / "infra" / name).mkdir(parents=True)
            (self.tmp / "infra" / name / "main.tf").write_text("", encoding="utf-8")
        (self.tmp / "modules" / "shared").mkdir(parents=True)
        (self.tmp / "modules" / "shared" / "main.tf").write_text("", encoding="utf-8")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def roots(self, *changed):
        return [r.relative_to(self.tmp).as_posix() for r in check.affected_roots(self.tmp, [self.tmp / c for c in changed])]

    def test_change_inside_a_root_checks_only_that_root(self):
        self.assertEqual(["infra/a"], self.roots("infra/a/main.tf"))

    def test_change_to_env_file_checks_its_root(self):
        self.assertEqual(["infra/b"], self.roots("infra/b/envs/dev.tfvars"))

    def test_change_outside_every_root_checks_all_roots(self):
        self.assertEqual(["infra/a", "infra/b"], self.roots("modules/shared/main.tf"))

    def test_no_changes_checks_all_roots(self):
        self.assertEqual(["infra/a", "infra/b"], self.roots())

    def test_harness_change_checks_all_roots(self):
        self.assertEqual(["infra/a", "infra/b"], self.roots("harness/checkov/HARNESS_AWS_1.yaml"))


class TimingTest(Workdir):
    def test_each_check_reports_seconds(self):
        result, report = run(CHECK, str(self.fixture("lambda-cross-file")), "--json",
                             "--terraform", "no-such-terraform", "--checkov", "no-such-checkov")

        self.assertTrue(all(isinstance(c["seconds"], float) for c in report["checks"]))
        self.assertIsInstance(report["seconds"], float)


if __name__ == "__main__":
    unittest.main()
