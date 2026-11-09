import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
INSTALL = REPO / "install.py"
SKILLS = sorted(p.parent.name for p in (REPO / "skills").glob("*/SKILL.md"))


class CodexInstallTest(unittest.TestCase):
    def setUp(self):
        self.home = Path(tempfile.mkdtemp(prefix="codex-home-"))
        self.env = {**os.environ, "CODEX_HOME": str(self.home)}

    def tearDown(self):
        shutil.rmtree(self.home, ignore_errors=True)

    def install(self):
        return subprocess.run([sys.executable, str(INSTALL), "--codex"], capture_output=True, text=True, env=self.env)

    def test_copies_every_skill(self):
        result = self.install()

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(SKILLS, sorted(p.name for p in (self.home / "skills").iterdir()))
        self.assertTrue((self.home / "skills" / "aws-iac-team-harness" / "scripts" / "check.py").is_file())

    def test_rerun_replaces_its_own_copies(self):
        self.install()
        stale = self.home / "skills" / "terraform-aws" / "stale.md"
        stale.write_text("old", encoding="utf-8")

        self.install()

        self.assertFalse(stale.exists())

    def test_keeps_a_folder_it_did_not_install(self):
        mine = self.home / "skills" / "terraform-aws"
        mine.mkdir(parents=True)
        (mine / "SKILL.md").write_text("my own", encoding="utf-8")

        result = self.install()

        self.assertEqual("my own", (mine / "SKILL.md").read_text(encoding="utf-8"))
        self.assertIn("kept", result.stdout)


if __name__ == "__main__":
    unittest.main()
