#!/usr/bin/env python3
"""Render a template into a new directory, after the runtime profile gate passes.

Usage:
    python render.py <pattern> <destination> --answers answers.json [--today YYYY-MM-DD]

Copier does the rendering and the answer validation. This script adds what Copier
does not: it refuses a destination that already exists, refuses an untested or
failing runtime profile, and leaves nothing behind when rendering fails.

Prints JSON on success. Exit codes: 0 rendered; 1 profile FAIL or render error;
2 profile UNVERIFIED; 3 destination exists.
"""

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from datetime import date
from pathlib import Path

import profiles

SKILL = Path(__file__).resolve().parents[1]


def template_revision():
    try:
        head = subprocess.run(["git", "-C", str(SKILL), "rev-parse", "HEAD"],
                              capture_output=True, text=True, check=True).stdout.strip()
        dirty = subprocess.run(["git", "-C", str(SKILL), "status", "--porcelain", "--", "."],
                               capture_output=True, text=True, check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"
    return f"{head}{'+uncommitted' if dirty else ''}"


def template_defaults(template: Path) -> dict:
    import yaml

    config = yaml.safe_load((template / "copier.yml").read_text(encoding="utf-8"))
    return {key: value.get("default") for key, value in config.items()
            if not key.startswith("_") and isinstance(value, dict)}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("pattern", choices=sorted(profiles.TEMPLATE_PACKAGING))
    parser.add_argument("destination", type=Path)
    parser.add_argument("--answers", type=Path, required=True)
    parser.add_argument("--today", type=date.fromisoformat, default=date.today())
    args = parser.parse_args(argv)

    destination = args.destination.resolve()
    if destination.exists():
        print(f"{destination} exists; render into a new directory", file=sys.stderr)
        return 3

    template = SKILL / "templates" / args.pattern
    answers = json.loads(args.answers.read_text(encoding="utf-8"))
    chosen = {**template_defaults(template), **answers}

    gate = profiles.resolve(SKILL / "profiles", args.pattern, chosen["runtime"], chosen["architecture"],
                            profiles.TEMPLATE_PACKAGING[args.pattern], args.today, region=chosen["aws_region"])
    if gate.status != "PASS":
        print(f"runtime profile {gate.status}: " + "; ".join(gate.reasons), file=sys.stderr)
        return profiles.EXIT_CODES[gate.status]

    import copier

    destination.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{destination.name}-", dir=destination.parent))
    try:
        copier.run_copy(str(template), str(staging / "project"), data=answers,
                        defaults=True, quiet=True, unsafe=False)
        (staging / "project").rename(destination)
    except Exception as error:
        print(f"render failed: {error}", file=sys.stderr)
        return 1
    finally:
        shutil.rmtree(staging, ignore_errors=True)

    print(json.dumps({
        "destination": str(destination),
        "pattern": args.pattern,
        "profile_id": gate.profile_id,
        "template_revision": template_revision(),
    }))
    return 0


if __name__ == "__main__":
    sys.exit(main())
