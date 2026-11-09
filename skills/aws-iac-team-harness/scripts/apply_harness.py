#!/usr/bin/env python3
"""Install or update the harness in a Terraform project.

Usage:
    python apply_harness.py <project> [--workflows] [--dry-run] [--json]

Writes the harness scripts and config under harness/ and one marked section of AGENTS.md.
--workflows also writes the reference GitHub Actions workflows; leave it off when the
project already deploys through another runner (Atlantis, HCP Terraform, ...). harness/lock.json records the SHA-256 of what was
written, so a rerun updates files nobody has edited since and reports the rest as
conflicts instead of overwriting them. User files (Terraform, app code, .checkov.yaml,
harness/baseline.json) are never touched.

Exit codes: 0 installed or up to date; 1 at least one conflict to resolve by hand.
"""

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

SKILL = Path(__file__).resolve().parents[1]
ASSETS = SKILL / "assets" / "project"
LOCK = Path("harness") / "lock.json"
SECTION_KEY = "AGENTS.md#harness"
BEGIN, END = "<!-- harness:begin -->", "<!-- harness:end -->"
SECTION_RE = re.compile(re.escape(BEGIN) + r"\n(.*?)" + re.escape(END), re.DOTALL)


def digest(text: str) -> str:
    return hashlib.sha256(text.replace("\r\n", "\n").encode("utf-8")).hexdigest()


SCRIPTS = ("check.py", "baseline.py", "plan_summary.py", "plan_provenance.py", "verify_deployment.py")


def owned_files(workflows: bool):
    files = {f"harness/{name}": SKILL / "scripts" / name for name in SCRIPTS}
    folders = ["harness"] + ([".github/workflows"] if workflows else [])
    for folder in folders:
        for path in sorted((ASSETS / folder).rglob("*")):
            if path.is_file():
                files[path.relative_to(ASSETS).as_posix()] = path
    return files


class Installer:
    def __init__(self, project: Path, dry_run: bool, workflows: bool):
        self.project, self.dry_run, self.workflows = project, dry_run, workflows
        lock_path = project / LOCK
        self.lock = json.loads(lock_path.read_text(encoding="utf-8")).get("files", {}) if lock_path.is_file() else {}
        self.locked = dict(self.lock)
        self.report = []

    def decide(self, key, present, wanted):
        if present is None:
            return "added"
        if digest(present) == digest(wanted):
            return "up to date"
        if self.lock.get(key) == digest(present):
            return "updated"
        return "conflict"

    def note(self, key, action, reason=""):
        self.report.append({"path": key, "action": action, "reason": reason})
        if action != "conflict":
            self.locked[key] = self.wanted_digest

    def write(self, path: Path, text: str):
        if not self.dry_run:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8", newline="\n")

    def own(self, relative: str, source: Path):
        target = self.project / relative
        wanted = source.read_text(encoding="utf-8").replace("\r\n", "\n")
        present = target.read_text(encoding="utf-8") if target.is_file() else None
        action = self.decide(relative, present, wanted)
        self.wanted_digest = digest(wanted)
        if action in ("added", "updated"):
            self.write(target, wanted)
        reason = ""
        if action == "conflict":
            reason = (f"edited since the harness wrote it; merge {source} by hand" if relative in self.lock
                      else f"not written by this harness; to take {source}, delete it and rerun")
        self.note(relative, action, reason)

    def own_section(self):
        target = self.project / "AGENTS.md"
        wanted = (ASSETS / "AGENTS.section.md").read_text(encoding="utf-8").replace("\r\n", "\n")
        text = target.read_text(encoding="utf-8").replace("\r\n", "\n") if target.is_file() else ""
        match = SECTION_RE.search(text)
        present = match.group(1) if match else None
        action = self.decide(SECTION_KEY, present, wanted)
        self.wanted_digest = digest(wanted)
        block = f"{BEGIN}\n{wanted}{END}"
        if action == "added":
            self.write(target, (text.rstrip("\n") + "\n\n" if text.strip() else "") + block + "\n")
        elif action == "updated":
            self.write(target, text[:match.start()] + block + text[match.end():])
        reason = "the harness section of AGENTS.md was edited; merge by hand" if action == "conflict" else ""
        self.note(SECTION_KEY, action, reason)

    def save_lock(self):
        if self.locked != self.lock:
            text = json.dumps({"files": dict(sorted(self.locked.items()))}, indent=2) + "\n"
            self.write(self.project / LOCK, text)

    def run(self):
        for relative, source in owned_files(self.workflows).items():
            self.own(relative, source)
        self.own_section()
        self.save_lock()
        return self.report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("project", type=Path)
    parser.add_argument("--workflows", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    project = args.project.resolve()
    if not project.is_dir():
        print(f"{project} is not a directory", file=sys.stderr)
        return 2
    report = Installer(project, args.dry_run, args.workflows).run()
    conflicts = [r for r in report if r["action"] == "conflict"]

    if args.json:
        print(json.dumps({"dry_run": args.dry_run, "files": report}, indent=2))
    else:
        for r in report:
            print(f"{r['action']:<11} {r['path']}" + (f"  ({r['reason']})" if r["reason"] else ""))
        print(f"harness install: {len(conflicts)} conflict(s)" + (" (dry run)" if args.dry_run else ""))
    return 1 if conflicts else 0


if __name__ == "__main__":
    sys.exit(main())
