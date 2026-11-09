import json
import re
import unittest
from datetime import date
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SKILLS = REPO / "skills"
README = (REPO / "README.md").read_text(encoding="utf-8")
SKILL_DIRS = sorted(p.parent for p in SKILLS.glob("*/SKILL.md"))
VERIFIED = re.compile(r"verified (\d{4}-\d{2}-\d{2})")


def frontmatter(skill_dir: Path) -> dict:
    text = (skill_dir / "SKILL.md").read_text(encoding="utf-8")
    block = text.split("---", 2)[1]
    return {m.group(1): m.group(2).strip().strip('"') for m in re.finditer(r"^(\w+): (.*)$", block, re.MULTILINE)}


class SkillListTest(unittest.TestCase):
    def test_marketplace_lists_every_skill(self):
        manifest = json.loads((REPO / ".claude-plugin" / "marketplace.json").read_text(encoding="utf-8"))
        listed = {Path(s).name for plugin in manifest["plugins"] for s in plugin["skills"]}

        self.assertEqual({d.name for d in SKILL_DIRS}, listed)

    def test_readme_names_every_skill(self):
        for skill in SKILL_DIRS:
            self.assertIn(f"`{skill.name}`", README, skill.name)


class SkillFileTest(unittest.TestCase):
    def test_name_matches_folder(self):
        for skill in SKILL_DIRS:
            self.assertEqual(skill.name, frontmatter(skill)["name"])

    def test_description_states_when_to_use(self):
        for skill in SKILL_DIRS:
            description = frontmatter(skill)["description"]
            with self.subTest(skill=skill.name):
                self.assertTrue(description.startswith("Use when"), description[:40])
                self.assertNotIn("—", description)
                self.assertLessEqual(len(description), 600)

    def test_named_scripts_exist(self):
        for skill in SKILL_DIRS:
            text = (skill / "SKILL.md").read_text(encoding="utf-8")
            for script in set(re.findall(r"scripts/([\w-]+\.py)", text)):
                with self.subTest(skill=skill.name, script=script):
                    self.assertTrue((skill / "scripts" / script).is_file())

    def test_no_hand_kept_line_counts(self):
        for skill in SKILL_DIRS:
            text = (skill / "SKILL.md").read_text(encoding="utf-8")
            self.assertIsNone(re.search(r"\(\d+ lines\)", text), skill.name)


class FactsTest(unittest.TestCase):
    def test_verified_dates_are_less_than_a_year_old(self):
        for path in SKILLS.rglob("*.md"):
            for found in VERIFIED.findall(path.read_text(encoding="utf-8")):
                with self.subTest(file=str(path.relative_to(REPO)), date=found):
                    self.assertLess((date.today() - date.fromisoformat(found)).days, 365)


class HarnessDocsTest(unittest.TestCase):
    HARNESS = SKILLS / "aws-iac-team-harness"

    def test_readme_names_every_check_and_script(self):
        for name in ["fmt", "validate", "tflint", "checkov", "terraform-test",
                     "check.py", "baseline.py", "apply_harness.py", "verify_deployment.py",
                     "plan_summary.py", "plan_provenance.py"]:
            self.assertIn(name, README, name)

    def test_skill_says_how_a_reviewer_records_a_tflint_false_positive(self):
        text = (REPO / "skills" / "aws-iac-team-harness" / "SKILL.md").read_text(encoding="utf-8")

        self.assertIn("# tflint-ignore: <rule>", text)
        self.assertIn("reviewer", text[text.index("# tflint-ignore: <rule>") - 600:text.index("# tflint-ignore: <rule>") + 600])

    def test_coverage_map_names_every_custom_check(self):
        coverage = (self.HARNESS / "references" / "coverage.md").read_text(encoding="utf-8")
        for policy in (self.HARNESS / "assets" / "project" / "harness" / "checkov").glob("*.yaml"):
            self.assertIn(policy.stem, coverage)


class PatternDocsTest(unittest.TestCase):
    CREATING = SKILLS / "creating-aws-projects"

    def test_every_template_has_a_pattern_row(self):
        patterns = (self.CREATING / "references" / "patterns.md").read_text(encoding="utf-8")
        for template in (self.CREATING / "templates").iterdir():
            self.assertIn(f"| `{template.name}` | template exists", patterns, template.name)

    def test_every_profile_points_at_a_template(self):
        for path in (self.CREATING / "profiles").glob("*.json"):
            profile = json.loads(path.read_text(encoding="utf-8"))
            self.assertTrue((self.CREATING / profile["template"] / "copier.yml").is_file(), path.name)


if __name__ == "__main__":
    unittest.main()
