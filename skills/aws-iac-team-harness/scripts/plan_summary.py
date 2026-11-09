#!/usr/bin/env python3
"""Summarize `terraform show -json` output without printing any attribute values.

Usage:
    terraform show -json tfplan > plan.json
    python plan_summary.py plan.json [--json]

Prints each changed resource address with its action (create, update, replace, delete),
the attributes Terraform will only know after apply, and a destructive-change section.
Values are never printed: plan JSON can hold secrets, so publish this summary, not the plan.
"""

import argparse
import json
import sys
from pathlib import Path

STATEFUL_TYPES = {
    "aws_db_instance", "aws_rds_cluster", "aws_dynamodb_table", "aws_s3_bucket", "aws_efs_file_system",
    "aws_ecr_repository", "aws_elasticache_replication_group", "aws_kms_key", "aws_secretsmanager_secret",
    "aws_sqs_queue", "aws_opensearch_domain",
}


def action_of(actions):
    if actions in (["delete", "create"], ["create", "delete"]):
        return "replace"
    if len(actions) == 1 and actions[0] in ("create", "update", "delete"):
        return actions[0]
    return None


def contains_unknown(value):
    if value is True:
        return True
    if isinstance(value, dict):
        return any(contains_unknown(v) for v in value.values())
    if isinstance(value, list):
        return any(contains_unknown(v) for v in value)
    return False


def unknown_keys(after_unknown):
    if not isinstance(after_unknown, dict):
        return []
    return sorted(key for key, value in after_unknown.items() if contains_unknown(value))


def summarize(plan: dict):
    changes = []
    for rc in plan.get("resource_changes", []):
        if rc.get("mode") != "managed":
            continue
        action = action_of(rc["change"]["actions"])
        if action is None:
            continue
        changes.append({
            "address": rc["address"],
            "type": rc["type"],
            "action": action,
            "reason": rc.get("action_reason", ""),
            "known_after_apply": unknown_keys(rc["change"].get("after_unknown")),
        })
    counts = {}
    for change in changes:
        counts[change["action"]] = counts.get(change["action"], 0) + 1
    destructive = [c for c in changes if c["action"] in ("delete", "replace")]
    return {
        "counts": counts,
        "changes": changes,
        "destructive": [{"address": c["address"], "action": c["action"], "reason": c["reason"]} for c in destructive],
        "stateful_destructive": sorted(c["address"] for c in destructive if c["type"] in STATEFUL_TYPES),
    }


def markdown(summary):
    counts = ", ".join(f"{n} to {action}" for action, n in sorted(summary["counts"].items())) or "no changes"
    lines = [f"### Terraform plan: {counts}", ""]
    if summary["stateful_destructive"]:
        lines += ["**Stateful resources destroyed or replaced** (data loss unless intended):", ""]
        lines += [f"- `{address}`" for address in summary["stateful_destructive"]] + [""]
    if summary["changes"]:
        lines += ["| Address | Action | Known after apply |", "| --- | --- | --- |"]
        for c in summary["changes"]:
            lines.append(f"| `{c['address']}` | {c['action']} | {', '.join(c['known_after_apply'])} |")
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("plan_json", type=Path)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    summary = summarize(json.loads(args.plan_json.read_text(encoding="utf-8")))
    print(json.dumps(summary, indent=2) if args.json else markdown(summary))
    return 0


if __name__ == "__main__":
    sys.exit(main())
