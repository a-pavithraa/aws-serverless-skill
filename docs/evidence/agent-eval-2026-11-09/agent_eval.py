"""Run one headless Claude Code session in a prepared folder and record its usage.

Usage: python agent_eval.py <workdir> <prompt-file> <out-prefix> [--model sonnet] [--max-turns 80]
Writes <out-prefix>.jsonl (stream) and <out-prefix>.json (summary: turns, tokens, cost, duration, skills, answer).
"""
import argparse
import json
import os
import subprocess
import time
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("workdir")
parser.add_argument("prompt_file")
parser.add_argument("out")
parser.add_argument("--model", default="sonnet")
parser.add_argument("--max-turns", type=int, default=80)
args = parser.parse_args()

empty = Path("D:/pills-ai/eval/empty")
empty.touch()
env = dict(os.environ, AWS_CONFIG_FILE=str(empty), AWS_SHARED_CREDENTIALS_FILE=str(empty))
for key in ("AWS_PROFILE", "AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN"):
    env.pop(key, None)

prompt = Path(args.prompt_file).read_text(encoding="utf-8")
command = ["claude", "-p", prompt, "--model", args.model, "--output-format", "stream-json", "--verbose",
           "--max-turns", str(args.max_turns), "--setting-sources", "project,local",
           "--allowedTools", "Skill", "Read", "Glob", "Grep", "Write", "Edit",
           "Bash(terraform fmt *)", "Bash(terraform init *)", "Bash(terraform validate*)", "Bash(terraform test*)",
           "Bash(terraform -chdir=*)", "Bash(cd *)", "Bash(ls *)", "Bash(cat *)",
           "Bash(python *profiles.py *)", "Bash(python *check_new_project.py *)", "Bash(python *apply_harness.py *)",
           "Bash(python *check.py *)", "Bash(python3 *apply_harness.py *)",
           "Bash(uv run --with copier==9.19.1 python *render.py *)",
           "--disallowedTools", "WebFetch", "WebSearch", "Agent", "PowerShell"]
start = time.time()
result = subprocess.run(command, cwd=args.workdir, capture_output=True, text=True, encoding="utf-8",
                        errors="replace", env=env, stdin=subprocess.DEVNULL, timeout=3600)
elapsed = round(time.time() - start)
Path(args.out + ".jsonl").write_text(result.stdout, encoding="utf-8")

summary = {"workdir": args.workdir, "seconds": elapsed, "skills": [], "tool_calls": {}, "answer": ""}
for line in result.stdout.splitlines():
    try:
        event = json.loads(line)
    except json.JSONDecodeError:
        continue
    if event.get("type") == "assistant":
        for part in event.get("message", {}).get("content", []):
            if part.get("type") == "tool_use":
                name = part.get("name")
                summary["tool_calls"][name] = summary["tool_calls"].get(name, 0) + 1
                if name == "Skill":
                    summary["skills"].append(part.get("input", {}).get("skill"))
    if event.get("type") == "result":
        summary.update(turns=event.get("num_turns"), cost_usd=event.get("total_cost_usd"),
                       usage=event.get("usage"), answer=event.get("result") or "", subtype=event.get("subtype"))
Path(args.out + ".json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
print(json.dumps({k: summary.get(k) for k in ("workdir", "seconds", "turns", "cost_usd", "skills", "subtype")}))
