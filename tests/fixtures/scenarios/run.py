#!/usr/bin/env python3
"""Run the RED/GREEN scenarios in tests/baseline-scenarios.md and write the answers for judging.

Usage:
    python3 run.py [--model sonnet] [--only 1,4] [--jobs 4] [--out report.md]

Each scenario's test prompt runs twice, each in a fresh headless session (claude -p) in an empty folder:
RED with no skills, GREEN with this repository's skills in .claude/skills. User-scope settings are not loaded
(--setting-sources project,local), so an installed copy of the old skills cannot answer in either run. The
session may only load skills and read files. The report holds each scenario's prompt, success criteria, both
answers and the skills each run loaded; a person (or a judge) marks each criterion against the answers.
"""

import argparse
import json
import re
import shutil
import subprocess
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
SKILLS = REPO / "skills"
SCENARIOS = REPO / "tests" / "baseline-scenarios.md"


def parse_scenarios(text: str) -> list[dict]:
    scenarios = []
    for block in re.split(r"^## Scenario ", text, flags=re.MULTILINE)[1:]:
        number, title = re.match(r"(\d+): (.+)", block).groups()
        skill = re.search(r"\*\*Skill:\*\* `([^`]+)`", block).group(1)
        prompt = re.search(r"### Test Prompt\s+```[^\n]*\n(.*?)\n```", block, re.DOTALL).group(1)
        criteria_text = re.split(r"^---$", block.split("### Success Criteria", 1)[1], flags=re.MULTILINE)[0]
        criteria = re.findall(r"^- \[ \] (.+)$", criteria_text, re.MULTILINE)
        scenarios.append({"id": number, "title": title.strip(), "skill": skill, "prompt": prompt, "criteria": criteria})
    return scenarios


def run_one(scenario: dict, arm: str, model: str, max_turns: int) -> dict:
    work = Path(tempfile.mkdtemp(prefix=f"scenario-{scenario['id']}-{arm}-"))
    try:
        if arm == "green":
            shutil.copytree(SKILLS, work / ".claude" / "skills")
        subprocess.run(["git", "init", "-q"], cwd=work, check=True)
        command = ["claude", "-p", scenario["prompt"], "--model", model, "--output-format", "stream-json", "--verbose",
                   "--max-turns", str(max_turns), "--setting-sources", "project,local",
                   "--allowedTools", "Skill", "Read", "Glob", "Grep",
                   "--disallowedTools", "Bash", "Edit", "Write", "NotebookEdit", "WebFetch", "WebSearch"]
        try:
            stream = subprocess.run(command, cwd=work, capture_output=True, text=True, encoding="utf-8",
                                    errors="replace", timeout=600, stdin=subprocess.DEVNULL).stdout
        except subprocess.TimeoutExpired as timeout:
            stream = timeout.stdout.decode() if isinstance(timeout.stdout, bytes) else (timeout.stdout or "")
        answer, loaded, cost = "", [], None
        for line in stream.splitlines():
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if event.get("type") == "assistant":
                for part in event.get("message", {}).get("content", []):
                    if part.get("type") == "tool_use" and part.get("name") == "Skill":
                        loaded.append(str(part.get("input", {}).get("skill", "")))
            if event.get("type") == "result":
                answer, cost = event.get("result") or "", event.get("total_cost_usd")
        return {"id": scenario["id"], "arm": arm, "answer": answer or "(no answer: the session ended without one)",
                "loaded": loaded, "cost_usd": cost}
    finally:
        shutil.rmtree(work, ignore_errors=True)


def report(scenarios: list[dict], results: list[dict], model: str) -> str:
    by_key = {(r["id"], r["arm"]): r for r in results}
    lines = [f"# Scenario runs ({model})", "",
             "RED: no skills. GREEN: this repository's skills available. Verdicts are added below each scenario.", ""]
    for s in scenarios:
        lines += [f"## Scenario {s['id']}: {s['title']}", "", f"Skill: `{s['skill']}`", "", "Prompt:", "", "```",
                  s["prompt"], "```", "", "Success criteria:", ""]
        lines += [f"{i}. {c}" for i, c in enumerate(s["criteria"], 1)] + [""]
        for arm in ("red", "green"):
            r = by_key.get((s["id"], arm))
            if not r:
                continue
            loaded = ", ".join(r["loaded"]) or "none"
            lines += [f"### {arm.upper()} (skills loaded: {loaded})", "", r["answer"].strip(), ""]
    cost = sum(r["cost_usd"] or 0 for r in results)
    lines += [f"Total cost: ${cost:.2f}", ""]
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--model", default="sonnet")
    parser.add_argument("--only", help="Comma-separated scenario numbers")
    parser.add_argument("--jobs", type=int, default=4)
    parser.add_argument("--max-turns", type=int, default=10)
    parser.add_argument("--out", default="report.md")
    args = parser.parse_args()
    scenarios = parse_scenarios(SCENARIOS.read_text(encoding="utf-8"))
    if args.only:
        wanted = set(args.only.split(","))
        scenarios = [s for s in scenarios if s["id"] in wanted]
    runs = [(s, arm) for s in scenarios for arm in ("red", "green")]
    with ThreadPoolExecutor(max_workers=args.jobs) as pool:
        results = list(pool.map(lambda run: run_one(*run, args.model, args.max_turns), runs))
    Path(args.out).write_text(report(scenarios, results, args.model), encoding="utf-8")
    for r in results:
        print(f"scenario {r['id']:>2} {r['arm']:5} loaded {', '.join(r['loaded']) or '-':40} answer {len(r['answer'])} chars")


if __name__ == "__main__":
    main()
