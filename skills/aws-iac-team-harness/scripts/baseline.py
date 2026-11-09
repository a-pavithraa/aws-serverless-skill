#!/usr/bin/env python3
"""Record legacy findings so existing code can adopt the harness while new code meets every rule.

Usage (people, not agents, run this):
    python baseline.py record <project> --owner TEAM --reason "why, with a ticket" --expires YYYY-MM-DD
    python baseline.py prune <project>

A baseline entry tolerates one finding: the same check ID on the same resource (or file,
for TFLint) in the same root. It never disables a rule. A new instance of a recorded rule,
or a finding that replaces a fixed one, still fails. Entries expire; an expired entry stops
tolerating its finding. `prune` drops entries whose finding is gone.

The file is harness/baseline.json. Review changes to it like code.
"""

import argparse
import json
import sys
from datetime import date
from pathlib import Path

BASELINE = Path("harness") / "baseline.json"
REQUIRED = ("id", "root", "resource", "owner", "reason", "expires")


class BaselineError(ValueError):
    pass


def base_root(root: str) -> str:
    return root.split(" [", 1)[0]


def identity(check_id, root, resource):
    return f"{check_id} {base_root(root)} {resource}"


def finding_identity(finding, root):
    return identity(finding["id"], root, finding.get("resource") or finding.get("file", ""))


def entry_identity(entry):
    return identity(entry["id"], entry["root"], entry["resource"])


def validate(entries):
    for entry in entries:
        missing = [key for key in REQUIRED if not str(entry.get(key, "")).strip()]
        if missing:
            raise BaselineError(f"baseline entry {entry.get('id')} {entry.get('resource')} lacks {', '.join(missing)}")
        try:
            date.fromisoformat(entry["expires"])
        except ValueError as error:
            raise BaselineError(f"baseline entry {entry_identity(entry)}: expires is not YYYY-MM-DD") from error
    return entries


def load(project: Path):
    path = project / BASELINE
    if not path.is_file():
        return []
    return validate(json.loads(path.read_text(encoding="utf-8")).get("findings", []))


def apply(results, entries, today: date):
    """Return results with tolerated findings removed, and the identities of entries nothing matched."""
    by_identity = {entry_identity(e): e for e in entries}
    matched, unverified_roots = set(), set()
    applied = []
    for result in results:
        if result.status == "UNVERIFIED":
            unverified_roots.add(base_root(result.root))
        if not result.findings:
            applied.append(result)
            continue
        kept, tolerated = [], 0
        for finding in result.findings:
            key = finding_identity(finding, result.root)
            entry = by_identity.get(key)
            if entry is None:
                kept.append(finding)
                continue
            matched.add(key)
            if date.fromisoformat(entry["expires"]) < today:
                kept.append({**finding, "fix": f"baseline entry expired on {entry['expires']} "
                                                f"(owner {entry['owner']}); fix it: {finding.get('fix', '')}"})
            else:
                tolerated += 1
        if kept:
            detail = f"{len(kept)} finding(s)" + (f", {tolerated} baselined" if tolerated else "")
            applied.append(type(result)(result.id, result.root, "FAIL", detail, result.fix, kept))
        else:
            applied.append(type(result)(result.id, result.root, "PASS", f"{tolerated} baselined", "", []))
    retired = sorted(key for key, e in by_identity.items()
                     if key not in matched and base_root(e["root"]) not in unverified_roots)
    return applied, retired


def write(project: Path, entries):
    path = project / BASELINE
    path.parent.mkdir(parents=True, exist_ok=True)
    entries = sorted(entries, key=entry_identity)
    path.write_text(json.dumps({"findings": entries}, indent=2) + "\n", encoding="utf-8", newline="\n")


def current_findings(project: Path):
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import check

    tools = {tool: check.resolve_tool(tool, None) for tool in ("terraform", "tflint", "checkov")}
    results = check.Checker(project, check.default_harness_dir(project), tools).run_all()
    incomplete = [f"{r.id} {r.root}: {r.detail}" for r in results
                  if r.status == "UNVERIFIED" and r.id in ("checkov", "tflint")]
    return results, incomplete


def record(project: Path, owner, reason, expires):
    results, incomplete = current_findings(project)
    if incomplete:
        print("cannot record a baseline from an incomplete scan:\n  " + "\n  ".join(incomplete), file=sys.stderr)
        return 2
    entries = {entry_identity(e): e for e in load(project)}
    added = 0
    for result in results:
        if result.id not in ("checkov", "tflint"):
            continue
        for finding in result.findings:
            entry = {"id": finding["id"], "root": base_root(result.root),
                     "resource": finding.get("resource") or finding.get("file", ""),
                     "owner": owner, "reason": reason, "expires": expires}
            if entry_identity(entry) not in entries:
                entries[entry_identity(entry)] = entry
                added += 1
    write(project, validate(list(entries.values())))
    print(f"recorded {added} new finding(s); {len(entries)} in {BASELINE.as_posix()}")
    return 0


def prune(project: Path):
    results, incomplete = current_findings(project)
    if incomplete:
        print("cannot prune from an incomplete scan:\n  " + "\n  ".join(incomplete), file=sys.stderr)
        return 2
    entries = load(project)
    _, retired = apply(results, entries, date.today())
    write(project, [e for e in entries if entry_identity(e) not in set(retired)])
    print(f"removed {len(retired)} entr{'y' if len(retired) == 1 else 'ies'} whose finding is gone")
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    rec = sub.add_parser("record")
    rec.add_argument("project", type=Path)
    rec.add_argument("--owner", required=True)
    rec.add_argument("--reason", required=True)
    rec.add_argument("--expires", required=True, type=lambda v: date.fromisoformat(v).isoformat())
    pr = sub.add_parser("prune")
    pr.add_argument("project", type=Path)
    args = parser.parse_args(argv)
    project = args.project.resolve()
    if args.command == "record":
        return record(project, args.owner, args.reason, args.expires)
    return prune(project)


if __name__ == "__main__":
    sys.exit(main())
