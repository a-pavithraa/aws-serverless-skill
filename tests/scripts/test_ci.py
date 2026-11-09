"""Plan summary, plan provenance and reference-workflow tests. Needs PyYAML (installed with Copier)."""

import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]
HARNESS = REPO / "skills" / "aws-iac-team-harness"
SCRIPTS = HARNESS / "scripts"
WORKFLOWS = HARNESS / "assets" / "project" / ".github" / "workflows"
PLANS = REPO / "tests" / "fixtures" / "plans"
sys.path.insert(0, str(SCRIPTS))

import plan_summary  # noqa: E402


def run(script, *args):
    return subprocess.run([sys.executable, str(SCRIPTS / script), *args], capture_output=True, text=True)


class PlanSummaryTest(unittest.TestCase):
    def test_lists_addresses_and_actions_without_values(self):
        result = run("plan_summary.py", str(PLANS / "replace-and-delete.json"))

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn("aws_dynamodb_table.orders", result.stdout)
        self.assertIn("replace", result.stdout)
        self.assertIn("aws_cloudwatch_log_group.old", result.stdout)
        for secret in ("hunter2", "orders-dev-v2", "/aws/lambda/old", "123456789012"):
            self.assertNotIn(secret, result.stdout)

    def test_counts_and_flags_destructive_changes(self):
        result = run("plan_summary.py", str(PLANS / "replace-and-delete.json"), "--json")

        summary = json.loads(result.stdout)
        self.assertEqual({"update": 1, "replace": 1, "delete": 1}, summary["counts"])
        self.assertEqual(["aws_cloudwatch_log_group.old", "aws_dynamodb_table.orders"],
                         sorted(c["address"] for c in summary["destructive"]))
        self.assertEqual(["aws_dynamodb_table.orders"], summary["stateful_destructive"])

    def test_values_known_only_after_apply_are_listed_not_hidden(self):
        summary = json.loads(run("plan_summary.py", str(PLANS / "replace-and-delete.json"), "--json").stdout)

        lambda_change = next(c for c in summary["changes"] if c["address"] == "aws_lambda_function.api")
        self.assertEqual(["qualified_arn", "version"], lambda_change["known_after_apply"])

    def test_nested_attributes_count_as_unknown_only_when_something_inside_is(self):
        self.assertEqual(["logging_config", "version"],
                         plan_summary.unknown_keys({"architectures": [False], "version": True,
                                                    "logging_config": [{"log_group": True}], "tags": {}}))

    def test_create_only_plan_has_no_destructive_changes(self):
        summary = json.loads(run("plan_summary.py", str(PLANS / "create-only.json"), "--json").stdout)

        self.assertEqual([], summary["destructive"])


class ProvenanceTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="prov-"))
        self.plan = self.tmp / "tfplan"
        self.plan.write_bytes(b"binary plan bytes")
        self.meta = self.tmp / "plan-meta.json"
        self.facts = ["--commit", "abc123", "--account", "111111111111", "--region", "us-east-1",
                      "--root", "infra", "--environment", "dev", "--terraform-version", "1.14.4",
                      "--backend", "s3://acme-tf/orders/dev.tfstate"]
        result = run("plan_provenance.py", "write", str(self.plan), str(self.meta), *self.facts)
        self.assertEqual(0, result.returncode, result.stderr)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def verify(self, **changes):
        facts = list(self.facts)
        for flag, value in changes.items():
            facts[facts.index(f"--{flag.replace('_', '-')}") + 1] = value
        return run("plan_provenance.py", "verify", str(self.plan), str(self.meta), *facts)

    def test_records_checksum_and_facts(self):
        meta = json.loads(self.meta.read_text(encoding="utf-8"))

        self.assertEqual(hashlib.sha256(b"binary plan bytes").hexdigest(), meta["plan_sha256"])
        self.assertEqual("abc123", meta["commit"])

    def test_matching_facts_verify(self):
        self.assertEqual(0, self.verify().returncode)

    def test_mismatches_are_refused(self):
        for flag, value in [("commit", "def456"), ("account", "222222222222"), ("region", "eu-west-1"),
                            ("root", "other"), ("environment", "prod"), ("terraform_version", "1.15.0"),
                            ("backend", "s3://acme-tf/orders/prod.tfstate")]:
            with self.subTest(flag=flag):
                result = self.verify(**{flag: value})

                self.assertEqual(1, result.returncode)
                self.assertIn(flag.replace("_", "-"), result.stderr)

    def test_modified_plan_is_refused(self):
        self.plan.write_bytes(b"tampered")

        result = self.verify()

        self.assertEqual(1, result.returncode)
        self.assertIn("checksum", result.stderr)


def load(name):
    return yaml.safe_load((WORKFLOWS / name).read_text(encoding="utf-8"))


def triggers(workflow):
    return workflow.get("on", workflow.get(True))


def steps_text(job):
    return "\n".join(str(s.get("run", "")) + " " + str(s.get("uses", "")) for s in job.get("steps", []))


class ChecksWorkflowTest(unittest.TestCase):
    def setUp(self):
        self.workflow = load("harness-checks.yml")
        self.text = (WORKFLOWS / "harness-checks.yml").read_text(encoding="utf-8")

    def test_runs_on_pull_requests_without_target_trigger(self):
        self.assertIn("pull_request", triggers(self.workflow))
        self.assertNotIn("pull_request_target", self.text)

    def test_never_gets_cloud_credentials(self):
        self.assertEqual({"contents": "read"}, self.workflow["permissions"])
        self.assertNotIn("id-token", self.text)
        self.assertNotIn("configure-aws-credentials", self.text)

    def test_runs_the_harness_check(self):
        self.assertIn("python harness/check.py .", steps_text(self.workflow["jobs"]["check"]))


class DeployWorkflowTest(unittest.TestCase):
    def setUp(self):
        self.workflow = load("terraform-deploy.yml")
        self.text = (WORKFLOWS / "terraform-deploy.yml").read_text(encoding="utf-8")
        self.plan = self.workflow["jobs"]["plan"]
        self.apply = self.workflow["jobs"]["apply"]

    def test_only_merged_main_commits_get_credentials(self):
        self.assertEqual({"push": {"branches": ["main"]}}, {k: v for k, v in triggers(self.workflow).items()
                                                            if k != "workflow_dispatch"})
        for job in (self.plan, self.apply):
            self.assertIn("refs/heads/main", job["if"])
        self.assertNotIn("pull_request", self.text)

    def test_least_permissions(self):
        self.assertEqual({"contents": "read"}, self.workflow["permissions"])
        for job in (self.plan, self.apply):
            self.assertEqual({"contents": "read", "id-token": "write"}, job["permissions"])

    def test_plan_and_apply_use_different_roles(self):
        self.assertIn("vars.AWS_PLAN_ROLE_ARN", json.dumps(self.plan))
        self.assertIn("vars.AWS_APPLY_ROLE_ARN", json.dumps(self.apply))
        self.assertNotIn("AWS_APPLY_ROLE_ARN", json.dumps(self.plan))

    def test_apply_waits_for_environment_and_is_serialized(self):
        self.assertEqual(["plan"], self.apply["needs"] if isinstance(self.apply["needs"], list) else [self.apply["needs"]])
        self.assertIn("environment", self.apply)
        concurrency = self.workflow["concurrency"]
        self.assertIn("state", concurrency["group"])
        self.assertFalse(concurrency["cancel-in-progress"])

    def test_apply_verifies_provenance_then_applies_the_saved_plan(self):
        steps = steps_text(self.apply)
        self.assertLess(steps.index("plan_provenance.py verify"), steps.index("apply -input=false tfplan"))

    def test_no_unsafe_flags(self):
        for flag in ("-auto-approve", "-lock=false", "-target", "-refresh=false"):
            self.assertNotIn(flag, self.text)

    def test_raw_plan_is_not_published(self):
        uploads = [s for s in self.plan["steps"] if "upload-artifact" in str(s.get("uses", ""))]
        self.assertEqual(1, len(uploads))
        self.assertLessEqual(int(uploads[0]["with"]["retention-days"]), 1)
        self.assertNotIn("plan.json", str(uploads[0]["with"]["path"]))
        self.assertIn("plan_summary.py", steps_text(self.plan))


if __name__ == "__main__":
    unittest.main()
