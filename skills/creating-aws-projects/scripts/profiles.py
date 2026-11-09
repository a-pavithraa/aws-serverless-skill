#!/usr/bin/env python3
"""Check a runtime profile against the release gate in references/runtime-selection.md.

Usage:
    python profiles.py check <profile-id> [--today YYYY-MM-DD]
    python profiles.py resolve <pattern> <runtime> <architecture> <packaging> [--today YYYY-MM-DD]

Prints JSON. Exit codes: 0 PASS, 1 FAIL, 2 UNVERIFIED.
"""

import argparse
import json
import sys
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

PROFILES_DIR = Path(__file__).resolve().parents[1] / "profiles"
TEMPLATE_PACKAGING = {"apigw-lambda": "zip", "sqs-lambda-worker": "zip", "ecs-web": "container", "apigw-step-functions": "definition", "alb-ec2": "ami", "network": "module"}
RUNWAY_DAYS = 365
RECHECK_DAYS = 180
REQUIRED_FIELDS = [
    "id", "status", "pattern", "lambda_variant",
    "runtime.identifier", "runtime.os", "runtime.preview", "runtime.lifecycle",
    "runtime.source", "runtime.checked",
    "architecture", "packaging", "regions", "tools", "evidence",
]
EXIT_CODES = {"PASS": 0, "FAIL": 1, "UNVERIFIED": 2}


@dataclass
class Result:
    status: str
    reasons: list = field(default_factory=list)
    profile_id: str | None = None


def _lookup(profile, dotted):
    node = profile
    for key in dotted.split("."):
        if not isinstance(node, dict) or key not in node:
            return False, None
        node = node[key]
    return True, node


def _combine(profile_id, failures, unverified):
    if failures:
        return Result("FAIL", failures + unverified, profile_id)
    if unverified:
        return Result("UNVERIFIED", unverified, profile_id)
    return Result("PASS", [], profile_id)


def check_profile(profile: dict, today: date) -> Result:
    profile_id = profile.get("id")
    missing = [name for name in REQUIRED_FIELDS if not _lookup(profile, name)[0]]
    if missing:
        return Result("FAIL", [f"incomplete profile: missing {name}" for name in missing], profile_id)

    failures, unverified = [], []
    runtime = profile["runtime"]

    if runtime["preview"]:
        failures.append(f"{runtime['identifier']} is a preview runtime; previews are not default candidates")

    deprecation = runtime["lifecycle"].get("deprecation")
    if deprecation == "none":
        # A managed service such as Step Functions has no runtime versions to deprecate.
        if profile["architecture"] != "managed":
            failures.append(f"{runtime['identifier']} claims no deprecation, but only a managed profile has no runtime")
        elif not str(runtime["lifecycle"].get("reason", "")).strip():
            failures.append(f"{runtime['identifier']} claims no deprecation without a reason")
    elif deprecation is None:
        unverified.append(f"{runtime['identifier']} has no deprecation date recorded; confirm the lifecycle")
    else:
        days_left = (date.fromisoformat(deprecation) - today).days
        if days_left <= 0:
            failures.append(f"{runtime['identifier']} deprecated on {deprecation}")
        elif days_left < RUNWAY_DAYS:
            failures.append(
                f"{runtime['identifier']} deprecates on {deprecation}, inside the {RUNWAY_DAYS}-day runway"
            )

    checked = date.fromisoformat(runtime["checked"])
    if (today - checked).days > RECHECK_DAYS:
        unverified.append(
            f"lifecycle source last checked {runtime['checked']}; recheck {runtime['source']}"
        )

    if profile["status"] == "supported" and not profile["evidence"].get("sandbox"):
        failures.append("status is supported but evidence.sandbox is empty")

    return _combine(profile_id, failures, unverified)


def load_profiles(profiles_dir: Path):
    for path in sorted(Path(profiles_dir).glob("*.json")):
        yield json.loads(path.read_text(encoding="utf-8"))


def resolve(profiles_dir, pattern, runtime, architecture, packaging, today: date, *, region) -> Result:
    for profile in load_profiles(profiles_dir):
        if (
            profile.get("pattern") == pattern
            and _lookup(profile, "runtime.identifier")[1] == runtime
            and profile.get("architecture") == architecture
            and profile.get("packaging") == packaging
        ):
            if region not in profile.get("regions", []):
                return Result("UNVERIFIED", [f"{profile['id']} is tested in {', '.join(profile.get('regions', []))}, "
                                             f"not {region}"], profile["id"])
            return check_profile(profile, today)
    return Result(
        "UNVERIFIED",
        [f"no profile for {pattern} {runtime} {architecture} {packaging}; this combination is untested"],
    )


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--today", type=date.fromisoformat, default=date.today())
    sub = parser.add_subparsers(dest="command", required=True)
    check = sub.add_parser("check")
    check.add_argument("profile_id")
    res = sub.add_parser("resolve")
    for name in ["pattern", "runtime", "architecture", "packaging"]:
        res.add_argument(name)
    res.add_argument("--region", required=True)
    args = parser.parse_args(argv)

    if args.command == "check":
        path = PROFILES_DIR / f"{args.profile_id}.json"
        if not path.is_file():
            result = Result("UNVERIFIED", [f"unknown profile {args.profile_id}"])
        else:
            result = check_profile(json.loads(path.read_text(encoding="utf-8")), args.today)
    else:
        result = resolve(PROFILES_DIR, args.pattern, args.runtime, args.architecture, args.packaging, args.today,
                         region=args.region)

    print(json.dumps({"status": result.status, "profile_id": result.profile_id, "reasons": result.reasons}))
    return EXIT_CODES[result.status]


if __name__ == "__main__":
    sys.exit(main())
