"""Render tests for templates/apigw-lambda.

Run with Copier available:
    uv run --no-project --with copier==9.19.1 python -m unittest discover -s tests/scripts -p test_template_render.py
"""

import hashlib
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
SKILL = REPO / "skills" / "creating-aws-projects"
TEMPLATE = SKILL / "templates" / "apigw-lambda"
RENDER = SKILL / "scripts" / "render.py"

try:
    import copier  # noqa: F401
except ImportError as missing:
    raise ImportError("Copier is required for these tests; see the module docstring") from missing

VALID = {
    "project_name": "orders-api",
    "aws_region": "us-east-1",
    "environment": "dev",
    "auth_mode": "iam",
    "log_retention_days": 14,
}


SQS_TEMPLATE = SKILL / "templates" / "sqs-lambda-worker"
SQS_VALID = {"project_name": "orders-worker", "aws_region": "us-east-1", "environment": "dev",
             "log_retention_days": 14}

ECS_TEMPLATE = SKILL / "templates" / "ecs-web"
ECS_VALID = {"project_name": "orders-web", "aws_region": "us-east-1", "environment": "dev",
             "log_retention_days": 14, "public_reason": "public storefront read API", "network_name": "shared-dev"}

SFN_TEMPLATE = SKILL / "templates" / "apigw-step-functions"
SFN_VALID = {"project_name": "orders-flow", "aws_region": "us-east-1", "environment": "dev",
             "log_retention_days": 14, "auth_mode": "iam"}

EC2_TEMPLATE = SKILL / "templates" / "alb-ec2"
EC2_VALID = {"project_name": "orders-vm", "aws_region": "us-east-1", "environment": "dev",
             "log_retention_days": 14, "plain_http_reason": "sandbox without a domain name",
             "network_name": "shared-dev"}

NET_TEMPLATE = SKILL / "templates" / "network"
NET_VALID = {"project_name": "shared-net", "aws_region": "us-east-1", "environment": "dev", "log_retention_days": 14}


def copier_copy(answers: dict, dest: Path, template: Path = TEMPLATE):
    data_file = dest.parent / f"{dest.name}-answers.json"
    data_file.write_text(json.dumps(answers), encoding="utf-8")
    return subprocess.run(
        [sys.executable, "-m", "copier", "copy", "--defaults", "--quiet",
         "--data-file", str(data_file), str(template), str(dest)],
        capture_output=True, text=True,
    )


def tree_digest(root: Path) -> dict:
    return {
        str(path.relative_to(root)).replace(os.sep, "/"): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.rglob("*")) if path.is_file()
    }


class Workdir(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="render-"))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)


class CopierValidationTest(Workdir):
    def assert_rejected(self, overrides, answer):
        dest = self.tmp / "out"

        result = copier_copy({**VALID, **overrides}, dest)

        self.assertNotEqual(0, result.returncode, result.stdout)
        self.assertIn(answer, result.stderr + result.stdout)
        self.assertFalse((dest / "infra").exists(), "a rejected render must not write the project")

    def test_valid_answers_render(self):
        result = copier_copy(VALID, self.tmp / "out")

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertTrue((self.tmp / "out" / "infra" / "main.tf").is_file())

    def test_public_api_without_reason_is_rejected(self):
        self.assert_rejected({"auth_mode": "none"}, "public_reason")

    def test_s3_backend_without_bucket_is_rejected(self):
        self.assert_rejected({"backend": "s3", "state_key": "orders/dev.tfstate"}, "state_bucket")

    def test_s3_backend_without_key_is_rejected(self):
        self.assert_rejected({"backend": "s3", "state_bucket": "acme-tfstate"}, "state_key")

    def test_invalid_project_name_is_rejected(self):
        self.assert_rejected({"project_name": "Orders_API"}, "project_name")

    def test_invalid_account_id_is_rejected(self):
        self.assert_rejected({"allowed_account_id": "1234"}, "allowed_account_id")

    def test_unsupported_retention_is_rejected(self):
        self.assert_rejected({"log_retention_days": 10}, "log_retention_days")

    def test_untested_runtime_is_rejected(self):
        self.assert_rejected({"runtime": "python3.14"}, "runtime")

    def test_untested_architecture_is_rejected(self):
        self.assert_rejected({"architecture": "x86_64"}, "architecture")


def run_render(*args):
    return subprocess.run([sys.executable, str(RENDER), *args], capture_output=True, text=True)


class RenderedProjectTest(Workdir):
    def render(self, name="out", answers=VALID):
        dest = self.tmp / name
        result = copier_copy(answers, dest)
        self.assertEqual(0, result.returncode, result.stderr)
        return dest

    def test_renders_are_identical_for_identical_answers(self):
        first = tree_digest(self.render("first"))
        second = tree_digest(self.render("second"))

        self.assertEqual(first, second)

    def test_answers_are_recorded(self):
        answers = (self.render() / ".copier-answers.yml").read_text(encoding="utf-8")

        self.assertIn("project_name: orders-api", answers)
        self.assertIn("auth_mode: iam", answers)

    def test_no_template_syntax_left(self):
        leftovers = [
            str(path) for path in self.render().rglob("*")
            if path.is_file() and re.search(r"\{\{|\{%|\[\[", path.read_text(encoding="utf-8", errors="ignore"))
        ]

        self.assertEqual([], leftovers)

    def test_tfvars_carry_answers(self):
        tfvars = (self.render() / "infra" / "envs" / "dev.tfvars").read_text(encoding="utf-8")

        self.assertRegex(tfvars, r'project_name\s+=\s+"orders-api"')
        self.assertRegex(tfvars, r'auth_mode\s+=\s+"iam"')

    def test_local_backend_has_no_backend_file(self):
        self.assertFalse((self.render() / "infra" / "backend.tf").exists())

    def test_s3_backend_file_uses_native_locking(self):
        dest = self.render(answers={**VALID, "backend": "s3", "state_bucket": "acme-tf", "state_key": "orders/dev.tfstate"})

        backend = (dest / "infra" / "backend.tf").read_text(encoding="utf-8")

        self.assertIn('bucket       = "acme-tf"', backend)
        self.assertIn("use_lockfile = true", backend)

    def test_readme_and_runbook_name_the_commands(self):
        dest = self.render()
        readme = (dest / "README.md").read_text(encoding="utf-8")
        runbook = (dest / "docs" / "runbook.md").read_text(encoding="utf-8")

        for command in ["python -m unittest discover -s app/tests", "terraform -chdir=infra test",
                        "-var-file=envs/dev.tfvars"]:
            self.assertIn(command, readme)
        for alarm in ["orders-api-dev-lambda-errors", "orders-api-dev-api-5xx"]:
            self.assertIn(alarm, runbook)

    def test_generated_app_tests_pass(self):
        dest = self.render()

        result = subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", "app/tests"],
                                cwd=dest, capture_output=True, text=True)

        self.assertEqual(0, result.returncode, result.stderr)


class PackageTest(Workdir):
    def test_package_contains_only_the_handler(self):
        dest = self.tmp / "out"
        self.assertEqual(0, copier_copy(VALID, dest).returncode)
        infra = dest / "infra"
        for command in (["init", "-backend=false", "-input=false"], ["test"]):
            result = subprocess.run(["terraform", f"-chdir={infra}", *command], capture_output=True, text=True)
            self.assertEqual(0, result.returncode, result.stdout + result.stderr)

        import zipfile
        with zipfile.ZipFile(infra / "build" / "lambda.zip") as package:
            self.assertEqual(["handler.py"], sorted(package.namelist()))


class RenderScriptTest(Workdir):
    def answers_file(self, answers=VALID):
        path = self.tmp / "answers.json"
        path.write_text(json.dumps(answers), encoding="utf-8")
        return str(path)

    def test_renders_into_new_directory(self):
        dest = self.tmp / "new"

        result = run_render("apigw-lambda", str(dest), "--answers", self.answers_file(), "--today", "2026-11-08")

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertTrue((dest / "infra" / "main.tf").is_file())
        self.assertEqual("apigw-lambda.python3.13-arm64-zip", json.loads(result.stdout)["profile_id"])

    def test_refuses_existing_directory_without_touching_it(self):
        dest = self.tmp / "existing"
        dest.mkdir()
        (dest / "keep.txt").write_text("mine", encoding="utf-8")
        before = tree_digest(dest)

        result = run_render("apigw-lambda", str(dest), "--answers", self.answers_file(), "--today", "2026-11-08")

        self.assertEqual(3, result.returncode)
        self.assertIn("exists", result.stderr)
        self.assertEqual(before, tree_digest(dest))

    def test_refuses_profile_that_fails_the_gate(self):
        dest = self.tmp / "late"

        result = run_render("apigw-lambda", str(dest), "--answers", self.answers_file(), "--today", "2029-07-01")

        self.assertEqual(1, result.returncode)
        self.assertIn("deprecated", result.stderr)
        self.assertFalse(dest.exists())

    def test_refuses_a_region_the_profile_was_not_tested_in(self):
        dest = self.tmp / "elsewhere"

        result = run_render("apigw-lambda", str(dest), "--answers",
                            self.answers_file({**VALID, "aws_region": "eu-west-1"}), "--today", "2026-11-08")

        self.assertEqual(2, result.returncode, result.stderr)
        self.assertIn("eu-west-1", result.stderr)
        self.assertFalse(dest.exists())

    def test_invalid_answers_leave_nothing_behind(self):
        dest = self.tmp / "bad"

        result = run_render("apigw-lambda", str(dest), "--answers",
                            self.answers_file({**VALID, "auth_mode": "none"}), "--today", "2026-11-08")

        self.assertNotEqual(0, result.returncode)
        self.assertFalse(dest.exists())
        self.assertEqual(["answers.json"], [p.name for p in self.tmp.iterdir()])


class SqsWorkerTemplateTest(Workdir):
    def assert_rejected(self, overrides, answer):
        dest = self.tmp / "out"

        result = copier_copy({**SQS_VALID, **overrides}, dest, SQS_TEMPLATE)

        self.assertNotEqual(0, result.returncode, result.stdout)
        self.assertIn(answer, result.stderr + result.stdout)
        self.assertFalse((dest / "infra").exists())

    def test_valid_answers_render_with_app_tests_passing(self):
        dest = self.tmp / "out"

        self.assertEqual(0, copier_copy(SQS_VALID, dest, SQS_TEMPLATE).returncode)
        result = subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", "app/tests"],
                                cwd=dest, capture_output=True, text=True)

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertTrue((dest / ".verify" / "probes.json").is_file())

    def test_receive_count_outside_range_is_rejected(self):
        self.assert_rejected({"max_receive_count": 0}, "max_receive_count")

    def test_timeout_outside_range_is_rejected(self):
        self.assert_rejected({"function_timeout_seconds": 901}, "function_timeout_seconds")

    def test_batch_size_above_ten_is_rejected(self):
        self.assert_rejected({"batch_size": 11}, "batch_size")

    def test_concurrency_below_two_is_rejected(self):
        self.assert_rejected({"max_concurrency": 1}, "max_concurrency")

    def test_no_template_syntax_left(self):
        dest = self.tmp / "out"
        copier_copy(SQS_VALID, dest, SQS_TEMPLATE)

        leftovers = [str(p) for p in dest.rglob("*")
                     if p.is_file() and re.search(r"\{\{|\{%|\[\[", p.read_text(encoding="utf-8", errors="ignore"))]

        self.assertEqual([], leftovers)

    def test_render_script_accepts_the_pattern(self):
        answers = self.tmp / "answers.json"
        answers.write_text(json.dumps(SQS_VALID), encoding="utf-8")

        result = run_render("sqs-lambda-worker", str(self.tmp / "new"), "--answers", str(answers),
                            "--today", "2026-11-08")

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("sqs-lambda-worker.python3.13-arm64-zip", json.loads(result.stdout)["profile_id"])


class EcsWebTemplateTest(Workdir):
    def assert_rejected(self, overrides, answer):
        dest = self.tmp / "out"

        result = copier_copy({**ECS_VALID, **overrides}, dest, ECS_TEMPLATE)

        self.assertNotEqual(0, result.returncode, result.stdout)
        self.assertIn(answer, result.stderr + result.stdout)
        self.assertFalse((dest / "infra").exists())

    def test_valid_answers_render_with_app_tests_passing(self):
        dest = self.tmp / "out"

        self.assertEqual(0, copier_copy(ECS_VALID, dest, ECS_TEMPLATE).returncode)
        result = subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", "app/tests"],
                                cwd=dest, capture_output=True, text=True)

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertTrue((dest / "Dockerfile").is_file())
        self.assertIn('"expect_source_hash": true', (dest / ".verify" / "probes.json").read_text(encoding="utf-8"))

    def test_secret_names_render_into_tfvars_and_the_probe(self):
        dest = self.tmp / "out"

        result = copier_copy({**ECS_VALID, "secret_names": "DB_PASSWORD,API_TOKEN"}, dest, ECS_TEMPLATE)

        self.assertEqual(0, result.returncode, result.stderr)
        tfvars = (dest / "infra" / "envs" / "dev.tfvars").read_text(encoding="utf-8")
        self.assertIn('secret_names       = ["DB_PASSWORD", "API_TOKEN"]', tfvars)
        probe = json.loads((dest / ".verify" / "probes.json").read_text(encoding="utf-8"))["probes"][0]
        self.assertEqual({"secrets_loaded": ["DB_PASSWORD", "API_TOKEN"]}, probe["expect_json"])

    def test_lower_case_secret_name_is_rejected(self):
        self.assert_rejected({"secret_names": "db-password"}, "secret_names")

    def test_build_tag_changes_with_the_dockerfile_and_a_failed_push_stops(self):
        dest = self.tmp / "out"
        copier_copy(ECS_VALID, dest, ECS_TEMPLATE)

        script = (dest / "build_image.sh").read_text(encoding="utf-8")
        readme = (dest / "README.md").read_text(encoding="utf-8")

        self.assertIn("set -euo pipefail", script)
        self.assertIn("TAG=${SOURCE:0:12}-${BASE:0:8}", script)
        self.assertIn('-t "$REPO:$TAG" --push . >&2', script)
        self.assertIn("imageTag=$TAG", script)
        self.assertIn("DIGEST=$(bash build_image.sh)", readme)

    def test_public_endpoint_without_reason_is_rejected(self):
        self.assert_rejected({"public_reason": ""}, "public_reason")

    def test_memory_that_fargate_rejects_for_the_cpu_is_rejected(self):
        self.assert_rejected({"cpu": 256, "memory": 4096}, "memory")

    def test_min_tasks_above_max_is_rejected(self):
        self.assert_rejected({"min_tasks": 3, "max_tasks": 2}, "max_tasks")

    def test_no_network_and_no_subnets_is_rejected(self):
        self.assert_rejected({"network_name": ""}, "subnet_ids")

    def test_subnet_ids_render_into_the_tfvars(self):
        dest = self.tmp / "out"

        result = copier_copy({**ECS_VALID, "network_name": "", "subnet_ids": "subnet-0aaa1111,subnet-0bbb2222"},
                             dest, ECS_TEMPLATE)

        self.assertEqual(0, result.returncode, result.stderr)
        tfvars = (dest / "infra" / "envs" / "dev.tfvars").read_text(encoding="utf-8")
        self.assertIn('subnet_ids         = ["subnet-0aaa1111", "subnet-0bbb2222"]', tfvars)
        self.assertIn('network_name       = ""', tfvars)

    def test_no_template_syntax_left(self):
        dest = self.tmp / "out"
        copier_copy(ECS_VALID, dest, ECS_TEMPLATE)

        leftovers = [str(p) for p in dest.rglob("*")
                     if p.is_file() and re.search(r"\{\{|\{%|\[\[", p.read_text(encoding="utf-8", errors="ignore"))]

        self.assertEqual([], leftovers)

    def test_render_script_accepts_the_pattern(self):
        answers = self.tmp / "answers.json"
        answers.write_text(json.dumps(ECS_VALID), encoding="utf-8")

        result = run_render("ecs-web", str(self.tmp / "new"), "--answers", str(answers), "--today", "2026-11-09")

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("ecs-web.python3.13-arm64-container", json.loads(result.stdout)["profile_id"])


class StepFunctionsTemplateTest(Workdir):
    def assert_rejected(self, overrides, answer):
        dest = self.tmp / "out"

        result = copier_copy({**SFN_VALID, **overrides}, dest, SFN_TEMPLATE)

        self.assertNotEqual(0, result.returncode, result.stdout)
        self.assertIn(answer, result.stderr + result.stdout)
        self.assertFalse((dest / "infra").exists())

    def test_definition_is_json_with_the_chosen_timeout(self):
        dest = self.tmp / "out"

        self.assertEqual(0, copier_copy({**SFN_VALID, "workflow_timeout_seconds": 12}, dest, SFN_TEMPLATE).returncode)
        definition = json.loads((dest / "workflow" / "definition.asl.json").read_text(encoding="utf-8"))

        self.assertEqual(12, definition["TimeoutSeconds"])
        self.assertEqual(17, definition["States"]["Slow"]["Seconds"])

    def test_timeout_at_or_past_the_api_limit_is_rejected(self):
        self.assert_rejected({"workflow_timeout_seconds": 26}, "workflow_timeout_seconds")

    def test_public_api_without_reason_is_rejected(self):
        self.assert_rejected({"auth_mode": "none"}, "public_reason")

    def test_readme_names_the_status_mapping_and_prerequisite(self):
        dest = self.tmp / "out"
        copier_copy(SFN_VALID, dest, SFN_TEMPLATE)

        readme = (dest / "README.md").read_text(encoding="utf-8")

        for text in ("422", "504", "aws apigateway get-account", "StartSyncExecution"):
            self.assertIn(text, readme)

    def test_no_template_syntax_left(self):
        dest = self.tmp / "out"
        copier_copy(SFN_VALID, dest, SFN_TEMPLATE)

        leftovers = [str(p) for p in dest.rglob("*")
                     if p.is_file() and re.search(r"(?<!\$)\{\{|\{%|\[\[", p.read_text(encoding="utf-8", errors="ignore"))]

        self.assertEqual([], leftovers)

    def test_render_script_accepts_the_pattern(self):
        answers = self.tmp / "answers.json"
        answers.write_text(json.dumps(SFN_VALID), encoding="utf-8")

        result = run_render("apigw-step-functions", str(self.tmp / "new"), "--answers", str(answers),
                            "--today", "2026-11-09")

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("apigw-step-functions.asl-jsonpath-managed-definition",
                         json.loads(result.stdout)["profile_id"])


class AlbEc2TemplateTest(Workdir):
    def assert_rejected(self, overrides, answer):
        dest = self.tmp / "out"

        result = copier_copy({**EC2_VALID, **overrides}, dest, EC2_TEMPLATE)

        self.assertNotEqual(0, result.returncode, result.stdout)
        self.assertIn(answer, result.stderr + result.stdout)
        self.assertFalse((dest / "infra").exists())

    def test_valid_answers_render_with_app_tests_passing(self):
        dest = self.tmp / "out"

        self.assertEqual(0, copier_copy(EC2_VALID, dest, EC2_TEMPLATE).returncode)
        result = subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", "app/tests"],
                                cwd=dest, capture_output=True, text=True)

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertTrue((dest / "infra" / "templates" / "user_data.yaml.tftpl").is_file())

    def test_plain_http_without_reason_is_rejected(self):
        self.assert_rejected({"plain_http_reason": ""}, "plain_http_reason")

    def test_x86_instance_type_is_rejected(self):
        self.assert_rejected({"instance_type": "t3.micro"}, "instance_type")

    def test_max_not_above_min_is_rejected(self):
        self.assert_rejected({"min_instances": 2, "max_instances": 2}, "max_instances")

    def test_name_too_long_for_the_load_balancer_is_rejected(self):
        self.assert_rejected({"project_name": "a-project-name-of-thirty-chars"}, "32 characters")

    def test_no_network_and_no_subnets_is_rejected(self):
        self.assert_rejected({"network_name": ""}, "subnet_ids")

    def test_subnet_ids_render_into_the_tfvars(self):
        dest = self.tmp / "out"

        result = copier_copy({**EC2_VALID, "network_name": "", "subnet_ids": "subnet-0aaa1111,subnet-0bbb2222"},
                             dest, EC2_TEMPLATE)

        self.assertEqual(0, result.returncode, result.stderr)
        tfvars = (dest / "infra" / "envs" / "dev.tfvars").read_text(encoding="utf-8")
        self.assertIn('subnet_ids         = ["subnet-0aaa1111", "subnet-0bbb2222"]', tfvars)
        self.assertIn('network_name       = ""', tfvars)

    def test_no_template_syntax_left(self):
        dest = self.tmp / "out"
        copier_copy(EC2_VALID, dest, EC2_TEMPLATE)

        leftovers = [str(p) for p in dest.rglob("*")
                     if p.is_file() and re.search(r"(?<![$%])\{\{|\{%|\[\[", p.read_text(encoding="utf-8", errors="ignore"))]

        self.assertEqual([], leftovers)

    def test_render_script_accepts_the_pattern(self):
        answers = self.tmp / "answers.json"
        answers.write_text(json.dumps(EC2_VALID), encoding="utf-8")

        result = run_render("alb-ec2", str(self.tmp / "new"), "--answers", str(answers), "--today", "2026-11-09")

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("alb-ec2.python3.13-arm64-ami", json.loads(result.stdout)["profile_id"])


class NetworkTemplateTest(Workdir):
    def assert_rejected(self, overrides, answer):
        dest = self.tmp / "out"

        result = copier_copy({**NET_VALID, **overrides}, dest, NET_TEMPLATE)

        self.assertNotEqual(0, result.returncode, result.stdout)
        self.assertIn(answer, result.stderr + result.stdout)
        self.assertFalse((dest / "infra").exists())

    def test_readme_names_the_ssm_parameters_services_read(self):
        dest = self.tmp / "out"

        self.assertEqual(0, copier_copy(NET_VALID, dest, NET_TEMPLATE).returncode)
        readme = (dest / "README.md").read_text(encoding="utf-8")

        self.assertIn("/landform/network/shared-net-dev/public-subnet-ids", readme)
        self.assertIn('network_name = "shared-net-dev"', readme)

    def test_one_zone_is_rejected(self):
        self.assert_rejected({"az_count": 1}, "az_count")

    def test_cidr_smaller_than_a_twenty_is_rejected(self):
        self.assert_rejected({"cidr": "10.0.0.0/24"}, "cidr")

    def test_render_script_accepts_the_pattern(self):
        answers = self.tmp / "answers.json"
        answers.write_text(json.dumps(NET_VALID), encoding="utf-8")

        result = run_render("network", str(self.tmp / "new"), "--answers", str(answers), "--today", "2026-11-09")

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("network.none-managed-module", json.loads(result.stdout)["profile_id"])


if __name__ == "__main__":
    unittest.main()


class TerraformConventionsTest(unittest.TestCase):
    """terraform-best-practices conventions that fmt, validate and tflint do not enforce."""

    def blocks(self, kind):
        for path in sorted((SKILL / "templates").glob("*/template/infra/*.tf*")):
            text = path.read_text(encoding="utf-8")
            for match in re.finditer(rf'^{kind} "([\w-]+)" {{\n(.*?)^}}', text, re.MULTILINE | re.DOTALL):
                yield f"{path.parent.parent.parent.name}: {kind} {match.group(1)}", match.group(2)

    def test_every_variable_has_a_description(self):
        missing = [name for name, body in self.blocks("variable") if not re.search(r"^  description\s*=", body, re.MULTILINE)]

        self.assertEqual([], missing)

    def test_every_output_has_a_description(self):
        missing = [name for name, body in self.blocks("output") if not re.search(r"^  description\s*=", body, re.MULTILINE)]

        self.assertEqual([], missing)

    def test_every_readme_says_to_commit_the_lock_file(self):
        for path in sorted((SKILL / "templates").glob("*/template/README.md.jinja")):
            with self.subTest(template=path.parent.parent.name):
                self.assertIn("Commit `infra/.terraform.lock.hcl`", path.read_text(encoding="utf-8"))

    def test_vpc_templates_list_what_they_only_refer_to(self):
        for name in ("ecs-web", "alb-ec2"):
            with self.subTest(template=name):
                readme = (SKILL / "templates" / name / "template" / "README.md.jinja").read_text(encoding="utf-8")
                self.assertIn("## What this project uses but does not own", readme)

    def test_terraform_version_is_bounded_to_one_major_version(self):
        for path in sorted((SKILL / "templates").glob("*/template/infra/versions.tf*")):
            with self.subTest(template=path.parent.parent.parent.name):
                self.assertIn('required_version = "~> 1.10"', path.read_text(encoding="utf-8"))

