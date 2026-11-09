#!/usr/bin/env python3
"""Check a project rendered from a template in this skill.

Runs the shared harness checks (aws-iac-team-harness/scripts/check.py) and adds two
that only make sense right after rendering:

- template-syntax: no Copier/Jinja syntax ({{, {%, [[) left in project files; ${{ is allowed
- runtime-profile: the runtime/architecture recorded in .copier-answers.yml still
  passes the profile gate (scripts/profiles.py)

Usage:
    python check_new_project.py <project> [--json] [--today YYYY-MM-DD]

Exit codes as check.py: 0 all PASS, 1 any FAIL, 2 otherwise UNVERIFIED.
"""

import argparse
import json
import re
import sys
from datetime import date
from pathlib import Path

SKILL = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL.parent / "aws-iac-team-harness" / "scripts"))
sys.path.insert(0, str(SKILL / "scripts"))

import check  # noqa: E402
import profiles  # noqa: E402

# ${{ is a GitHub Actions expression in the harness workflows, not a Copier placeholder.
TEMPLATE_SYNTAX = re.compile(r"(?<!\$)\{\{|\{%|\[\[")
SKIP_DIRS = {".terraform", ".git", "build", "__pycache__"}


def read_answers(project: Path) -> dict:
    path = project / ".copier-answers.yml"
    if not path.is_file():
        return {}
    answers = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        match = re.match(r"^([A-Za-z_]\w*): ?(.*)$", line)
        if match:
            answers[match.group(1)] = match.group(2).strip().strip("'\"")
    return answers


def template_syntax(project: Path):
    leftovers = []
    for path in project.rglob("*"):
        parts = path.relative_to(project).parts
        if not path.is_file() or any(p in SKIP_DIRS for p in parts):
            continue
        if TEMPLATE_SYNTAX.search(path.read_text(encoding="utf-8", errors="ignore")):
            leftovers.append(path.relative_to(project).as_posix())
    if leftovers:
        return check.CheckResult("template-syntax", ".", "FAIL", ", ".join(leftovers),
                                 "render again with every answer supplied; do not hand-edit placeholders")
    return check.CheckResult("template-syntax", ".", "PASS")


def runtime_profile(project: Path, today: date):
    answers = read_answers(project)
    pattern = Path(answers.get("_src_path", "")).name
    if not answers or pattern not in profiles.TEMPLATE_PACKAGING:
        return check.CheckResult("runtime-profile", ".", "UNVERIFIED",
                                 "no .copier-answers.yml from a known template; cannot tell which profile applies")
    result = profiles.resolve(SKILL / "profiles", pattern, answers.get("runtime"), answers.get("architecture"),
                              profiles.TEMPLATE_PACKAGING[pattern], today, region=answers.get("aws_region"))
    return check.CheckResult("runtime-profile", ".", result.status,
                             result.profile_id or "; ".join(result.reasons),
                             "" if result.status == "PASS" else "; ".join(result.reasons))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("project", type=Path)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--today", type=date.fromisoformat, default=date.today())
    args = parser.parse_args(argv)

    project = args.project.resolve()
    tools = {tool: check.resolve_tool(tool, None) for tool in ("terraform", "tflint", "checkov")}
    results = [template_syntax(project), runtime_profile(project, args.today)]
    results += check.Checker(project, check.default_harness_dir(project), tools).run_all()
    report = check.report_dict(results)

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        check.print_human(report)
    return check.aggregate(results)[1]


if __name__ == "__main__":
    sys.exit(main())
