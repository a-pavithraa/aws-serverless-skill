#!/usr/bin/env python3
"""Bind a saved Terraform plan to what it was made from, and refuse to apply it anywhere else.

Usage:
    python plan_provenance.py write  <tfplan> <plan-meta.json> FACTS
    python plan_provenance.py verify <tfplan> <plan-meta.json> FACTS

FACTS: --commit --account --region --root --environment --terraform-version --backend

`write` runs after `terraform plan -out`; `verify` runs in the apply job with the facts
it observes (its own commit, `aws sts get-caller-identity` account, ...). Any mismatch, or a
plan file whose SHA-256 changed, exits 1 and names the field. Terraform itself refuses a
saved plan whose state has moved on ("Saved plan is stale"): then plan and approve again.
"""

import argparse
import hashlib
import json
import sys
from pathlib import Path

FACTS = ("commit", "account", "region", "root", "environment", "terraform_version", "backend")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("command", choices=["write", "verify"])
    parser.add_argument("plan", type=Path)
    parser.add_argument("meta", type=Path)
    for fact in FACTS:
        parser.add_argument(f"--{fact.replace('_', '-')}", required=True)
    args = parser.parse_args(argv)

    observed = {fact: getattr(args, fact) for fact in FACTS}
    if args.command == "write":
        args.meta.write_text(json.dumps({**observed, "plan_sha256": sha256(args.plan)}, indent=2) + "\n",
                             encoding="utf-8")
        print(f"plan bound to commit {args.commit}, account {args.account}, {args.region}, {args.root}")
        return 0

    recorded = json.loads(args.meta.read_text(encoding="utf-8"))
    problems = [f"{fact.replace('_', '-')}: plan made for {recorded.get(fact)!r}, applying to {observed[fact]!r}"
                for fact in FACTS if recorded.get(fact) != observed[fact]]
    if recorded.get("plan_sha256") != sha256(args.plan):
        problems.append("checksum: the plan file is not the one that was approved")
    if problems:
        print("refusing to apply:\n  " + "\n  ".join(problems), file=sys.stderr)
        return 1
    print("plan provenance verified")
    return 0


if __name__ == "__main__":
    sys.exit(main())
