#!/usr/bin/env python3
"""Install this repository's skills for Claude Code or Codex. Safe to rerun.

Usage:
    python3 install.py            Claude Code: add the marketplace and install the plugin at user scope
    python3 install.py --codex    Codex: copy the skill folders into ~/.codex/skills (or $CODEX_HOME/skills)

Claude Code gets the plugin through the marketplace, so the skills work in every project and
update with the marketplace: the script turns on auto-update for it. Codex has no plugin
install, so the script copies the skill folders and replaces only folders it copied before.
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

if sys.version_info < (3, 10):
    sys.exit(f"ERROR: install.py needs Python 3.10 or later, and this is {sys.version.split()[0]}.")

HERE = Path(__file__).resolve().parent
MARKETPLACE = "aws-serverless-skill"
REPOSITORY = "a-pavithraa/aws-serverless-skill"
MARKER = ".installed-by-aws-serverless-skill"


def manifest():
    return json.loads((HERE / ".claude-plugin" / "marketplace.json").read_text(encoding="utf-8"))


def run(*command):
    return subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="replace")


def turn_on_auto_update():
    path = Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude") / "settings.json"
    try:
        settings = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    except json.JSONDecodeError:
        return f"skipped  auto-update: {path} is not valid JSON. Turn it on in /plugin > Marketplaces"
    entry = settings.setdefault("extraKnownMarketplaces", {}).setdefault(
        MARKETPLACE, {"source": {"source": "github", "repo": REPOSITORY}})
    if "autoUpdate" in entry:
        return f"kept     auto-update {'on' if entry['autoUpdate'] else 'off'}, as set in {path}"
    entry["autoUpdate"] = True
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(settings, indent=2) + "\n", encoding="utf-8")
    return f"set      auto-update on in {path}"


def install_for_claude(source):
    claude = shutil.which("claude")
    if not claude:
        sys.exit("ERROR: the claude command is not on PATH. Install Claude Code first: https://code.claude.com")
    lines = []
    if MARKETPLACE not in run(claude, "plugin", "marketplace", "list", "--json").stdout:
        added = run(claude, "plugin", "marketplace", "add", source)
        if added.returncode != 0:
            sys.exit(f"ERROR: could not add the marketplace:\n{added.stdout}{added.stderr}")
        lines.append(f"added    marketplace {MARKETPLACE}")
    else:
        run(claude, "plugin", "marketplace", "update", MARKETPLACE)
        lines.append(f"updated  marketplace {MARKETPLACE}")
    lines.append(turn_on_auto_update())
    for plugin in manifest()["plugins"]:
        result = run(claude, "plugin", "install", f"{plugin['name']}@{MARKETPLACE}")
        ok = result.returncode == 0
        lines.append(f"{'installed' if ok else 'FAILED':8} {plugin['name']}"
                     + ("" if ok else f": {(result.stdout + result.stderr).strip()}"))
    return lines


def install_for_codex():
    target = Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex") / "skills"
    lines = []
    for plugin in manifest()["plugins"]:
        for listed in plugin["skills"]:
            folder = (HERE / listed).resolve()
            destination = target / folder.name
            if destination.exists() and not (destination / MARKER).exists():
                lines.append(f"kept     {destination}: not installed by this script; delete it to replace it")
                continue
            if destination.exists():
                shutil.rmtree(destination)
            shutil.copytree(folder, destination, ignore=shutil.ignore_patterns("__pycache__", ".git"))
            (destination / MARKER).write_text(f"{plugin['name']}\n", encoding="utf-8")
            lines.append(f"copied   {folder.name}")
    return lines


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--codex", action="store_true", help="Copy the skills into Codex instead of Claude Code")
    parser.add_argument("--source", default=REPOSITORY,
                        help="Where Claude Code gets the marketplace: a GitHub owner/repo or a local clone")
    args = parser.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")
    for line in install_for_codex() if args.codex else install_for_claude(args.source):
        print(line)


if __name__ == "__main__":
    main()
