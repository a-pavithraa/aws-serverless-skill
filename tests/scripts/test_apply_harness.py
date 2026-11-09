import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
HARNESS = REPO / "skills" / "aws-iac-team-harness"
APPLY = HARNESS / "scripts" / "apply_harness.py"
FIXTURES = REPO / "tests" / "fixtures" / "checks"
sys.path.insert(0, str(REPO / "skills" / "creating-aws-projects" / "scripts"))

from check_new_project import TEMPLATE_SYNTAX, harness_installed  # noqa: E402

OWNED = ["harness/check.py", "harness/baseline.py", "harness/plan_summary.py", "harness/plan_provenance.py",
         "harness/verify_deployment.py", "harness/.tflint.hcl",
         "harness/checkov/HARNESS_AWS_1.yaml", "harness/checkov/HARNESS_AWS_2.yaml",
         "harness/checkov/HARNESS_AWS_3.yaml"]


def snapshot(root: Path):
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()}


class ApplyHarnessTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="apply-"))
        self.project = self.tmp / "project"
        shutil.copytree(FIXTURES / "lambda-cross-file", self.project / "infra")
        (self.project / "AGENTS.md").write_text("# Team notes\n\nUse feature branches.\n", encoding="utf-8")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def apply(self, *args):
        result = subprocess.run([sys.executable, str(APPLY), str(self.project), "--json", *args],
                                capture_output=True, text=True)
        self.assertIn(result.returncode, (0, 1), result.stderr)
        return result, json.loads(result.stdout)

    def actions(self, report):
        return {line["path"]: line["action"] for line in report["files"]}

    def test_fresh_install_adds_owned_files_and_lock(self):
        result, report = self.apply()

        self.assertEqual(0, result.returncode)
        for path in OWNED:
            self.assertTrue((self.project / path).is_file(), path)
            self.assertEqual("added", self.actions(report)[path])
        lock = json.loads((self.project / "harness" / "lock.json").read_text(encoding="utf-8"))
        self.assertEqual(set(OWNED) | {"AGENTS.md#harness"}, set(lock["files"]))

    def test_new_project_check_fails_without_the_harness(self):
        result = harness_installed(self.project)

        self.assertEqual("FAIL", result.status)
        self.assertIn("harness/check.py", result.detail)
        self.assertIn("apply_harness.py", result.fix)
        self.assertFalse((self.project / "harness").exists(), "the check must not install anything")

    def test_new_project_check_passes_once_installed(self):
        self.apply()

        self.assertEqual("PASS", harness_installed(self.project).status)

    def test_new_project_check_fails_on_an_edited_harness_file(self):
        self.apply()
        tflint = self.project / "harness" / ".tflint.hcl"
        tflint.write_text(tflint.read_text(encoding="utf-8") + "\n# team change\n", encoding="utf-8")

        result = harness_installed(self.project)

        self.assertEqual("FAIL", result.status)
        self.assertIn("harness/.tflint.hcl", result.detail)

    def test_installed_files_hold_no_template_syntax(self):
        self.apply("--workflows")

        flagged = [path.relative_to(self.project).as_posix() for path in self.project.rglob("*")
                   if path.is_file() and TEMPLATE_SYNTAX.search(path.read_text(encoding="utf-8", errors="ignore"))]

        self.assertEqual([], flagged, "check_new_project's template-syntax check would fail a fresh project")

    def test_workflows_only_on_request(self):
        self.apply()
        self.assertFalse((self.project / ".github").exists())

        _, report = self.apply("--workflows")

        for name in ("harness-checks.yml", "terraform-deploy.yml"):
            self.assertEqual("added", self.actions(report)[f".github/workflows/{name}"])

    def test_agents_md_keeps_team_content_and_gains_one_section(self):
        self.apply()
        self.apply()

        agents = (self.project / "AGENTS.md").read_text(encoding="utf-8")
        self.assertTrue(agents.startswith("# Team notes\n\nUse feature branches.\n"))
        self.assertEqual(1, agents.count("<!-- harness:begin -->"))
        self.assertIn("python harness/check.py .", agents)

    def test_repeat_install_changes_nothing(self):
        self.apply()
        before = snapshot(self.project)

        _, report = self.apply()

        self.assertEqual(before, snapshot(self.project))
        self.assertEqual({"up to date"}, set(self.actions(report).values()))

    def test_edited_owned_file_is_kept_and_reported(self):
        self.apply()
        tflint = self.project / "harness" / ".tflint.hcl"
        tflint.write_text(tflint.read_text(encoding="utf-8") + "\n# team change\n", encoding="utf-8")
        lock_before = (self.project / "harness" / "lock.json").read_bytes()

        result, report = self.apply()

        self.assertEqual(1, result.returncode)
        self.assertEqual("conflict", self.actions(report)["harness/.tflint.hcl"])
        self.assertIn("# team change", tflint.read_text(encoding="utf-8"))
        self.assertEqual(lock_before, (self.project / "harness" / "lock.json").read_bytes())

    def test_edited_agents_section_is_kept_and_reported(self):
        self.apply()
        agents = self.project / "AGENTS.md"
        agents.write_text(agents.read_text(encoding="utf-8").replace("harness/check.py", "harness/check.py --fast"),
                          encoding="utf-8")

        result, report = self.apply()

        self.assertEqual(1, result.returncode)
        self.assertEqual("conflict", self.actions(report)["AGENTS.md#harness"])
        self.assertIn("--fast", agents.read_text(encoding="utf-8"))

    def test_unowned_file_at_owned_path_is_not_overwritten(self):
        (self.project / "harness").mkdir()
        (self.project / "harness" / "check.py").write_text("print('team script')\n", encoding="utf-8")

        result, report = self.apply()

        self.assertEqual(1, result.returncode)
        self.assertEqual("conflict", self.actions(report)["harness/check.py"])
        self.assertEqual("print('team script')\n", (self.project / "harness" / "check.py").read_text(encoding="utf-8"))

    def test_older_release_file_is_updated(self):
        self.apply()
        lock_path = self.project / "harness" / "lock.json"
        old_text = "# older release\n"
        (self.project / "harness" / ".tflint.hcl").write_text(old_text, encoding="utf-8")
        lock = json.loads(lock_path.read_text(encoding="utf-8"))
        import hashlib
        lock["files"]["harness/.tflint.hcl"] = hashlib.sha256(old_text.encode()).hexdigest()
        lock_path.write_text(json.dumps(lock), encoding="utf-8")

        result, report = self.apply()

        self.assertEqual(0, result.returncode)
        self.assertEqual("updated", self.actions(report)["harness/.tflint.hcl"])
        self.assertEqual((HARNESS / "assets" / "project" / "harness" / ".tflint.hcl").read_bytes(),
                         (self.project / "harness" / ".tflint.hcl").read_bytes())

    def test_dry_run_writes_nothing(self):
        before = snapshot(self.project)

        _, report = self.apply("--dry-run")

        self.assertEqual(before, snapshot(self.project))
        self.assertEqual("added", self.actions(report)["harness/check.py"])

    def test_installed_check_uses_installed_config(self):
        self.apply()

        result = subprocess.run([sys.executable, str(self.project / "harness" / "check.py"), str(self.project),
                                 "--json", "--terraform", "no-such-terraform", "--checkov", "no-such-checkov"],
                                capture_output=True, text=True)

        report = json.loads(result.stdout)
        self.assertEqual(2, result.returncode)
        self.assertEqual(str((self.project / "harness").resolve()), report["harness_dir"])


if __name__ == "__main__":
    unittest.main()
