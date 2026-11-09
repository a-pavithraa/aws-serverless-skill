#!/usr/bin/env python3
"""Run the harness checks on a Terraform project and report PASS, FAIL or UNVERIFIED per check.

Usage:
    python check.py <project> [--json] [--changed PATH ...] [--harness-dir DIR]
                    [--var-file FILE ...] [--terraform BIN] [--tflint BIN] [--checkov BIN]

Checks, per Terraform root: fmt, init (-backend=false), validate, tflint, checkov
(once per environment file), terraform-test. Plus app-tests when <project>/app/tests exists.

Environment files: each --var-file is used for the root it is in. A root with none named uses
*.tfvars in its envs/, env/ or environments/ directory.

--changed limits the run to the roots containing those paths. A changed path outside every
root (a shared module, harness config) checks every root.

Findings recorded in harness/baseline.json (see baseline.py) are tolerated until they expire.

A missing tool, a failed init, a timeout, unparseable output, or values Checkov cannot
resolve is UNVERIFIED, never PASS.

Exit codes: 0 every check passed; 1 at least one FAIL; 2 no FAIL but something UNVERIFIED.
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import date
from pathlib import Path

import baseline

TIMEOUT_SECONDS = 600
SKIP_DIRS = {".terraform", ".git", "build", "tests", "node_modules", "__pycache__"}
EXIT_CODES = {"PASS": 0, "FAIL": 1, "UNVERIFIED": 2}

FIXES = {
    "CKV_AWS_66": "set retention_in_days on the aws_cloudwatch_log_group",
    "CKV_AWS_309": "set authorization_type (AWS_IAM, JWT or CUSTOM) on the route; a deliberately public route "
                   "needs a reviewed skip with its reason in .checkov.yaml",
    "CKV_AWS_364": "set source_arn (or source_account) on the aws_lambda_permission",
    "CKV_AWS_50": "add tracing_config { mode = \"Active\" } to the function",
    "CKV_AWS_76": "add access_log_settings to the API stage",
}


@dataclass
class CheckResult:
    id: str
    root: str
    status: str
    detail: str = ""
    fix: str = ""
    findings: list = field(default_factory=list)
    seconds: float = 0.0


def aggregate(results):
    if not results:
        return "UNVERIFIED", EXIT_CODES["UNVERIFIED"]
    found = {r.status for r in results}
    for status in ("FAIL", "UNVERIFIED"):
        if status in found:
            return status, EXIT_CODES[status]
    return "PASS", 0


def run(command, cwd=None):
    try:
        completed = subprocess.run(command, cwd=cwd, capture_output=True, text=True,
                                   encoding="utf-8", errors="replace", timeout=TIMEOUT_SECONDS)
    except FileNotFoundError:
        return None, f"{command[0]} not found"
    except subprocess.TimeoutExpired:
        return None, f"{' '.join(command)} timed out after {TIMEOUT_SECONDS}s"
    return completed, ""


def tail(text, lines=15):
    return "\n".join(text.strip().splitlines()[-lines:])


def find_roots(project: Path):
    roots = set()
    for tf in project.rglob("*.tf"):
        parts = tf.relative_to(project).parts[:-1]
        if any(p in SKIP_DIRS or p.startswith(".") or p == "modules" for p in parts):
            continue
        roots.add(tf.parent)
    return sorted(roots)


def affected_roots(project: Path, changed):
    roots = find_roots(project)
    if not changed:
        return roots
    selected = set()
    for path in changed:
        path = Path(path).resolve()
        owner = [r for r in roots if r.resolve() == path or r.resolve() in path.parents]
        if not owner:
            return roots
        selected.add(max(owner, key=lambda r: len(r.parts)))
    return sorted(selected)


def timed(function, *args):
    started = time.perf_counter()
    produced = function(*args)
    results = produced if isinstance(produced, list) else [produced]
    elapsed = round(time.perf_counter() - started, 2)
    for result in results:
        result.seconds = round(elapsed / len(results), 2) if results else elapsed
    return results


def resolve_tool(name, override):
    candidate = override or name
    return shutil.which(candidate)


def unverified(check_id, root, detail):
    return CheckResult(check_id, root, "UNVERIFIED", detail)


VAR_FILE_DIRS = ("envs", "env", "environments")


class Checker:
    def __init__(self, project: Path, harness_dir: Path, tools: dict, var_files=()):
        self.project = project
        self.harness_dir = harness_dir
        self.tools = tools
        self.var_files = [Path(f).resolve() for f in var_files]

    def environment_files(self, root):
        named = [f for f in self.var_files if root.resolve() in f.parents]
        if named:
            return sorted(named)
        return sorted(f for d in VAR_FILE_DIRS if (root / d).is_dir() for f in (root / d).glob("*.tfvars"))

    def rel(self, path: Path):
        return path.relative_to(self.project).as_posix() or "."

    def app_tests(self):
        tests = self.project / "app" / "tests"
        if not tests.is_dir():
            return []
        completed, error = run([sys.executable, "-m", "unittest", "discover", "-s", "app/tests"], cwd=self.project)
        if completed is None:
            return [unverified("app-tests", "app", error)]
        if completed.returncode != 0:
            return [CheckResult("app-tests", "app", "FAIL", tail(completed.stderr), "fix the failing unit tests")]
        return [CheckResult("app-tests", "app", "PASS", tail(completed.stderr, 3))]

    def root_checks(self, root: Path):
        name = self.rel(root)
        terraform = self.tools["terraform"]
        if not terraform:
            return [unverified(c, name, "terraform not found")
                    for c in ("fmt", "init", "validate", "tflint", "checkov", "terraform-test")]

        results = timed(self.fmt, terraform, root, name)
        [init] = timed(self.init, terraform, root, name)
        results.append(init)
        if init.status != "PASS":
            reason = f"init did not pass: {init.detail.splitlines()[0] if init.detail else ''}"
            results += [unverified(c, name, reason) for c in ("validate", "tflint", "terraform-test")]
            results += timed(self.checkov, root, name)
            return results
        results += timed(self.validate, terraform, root, name)
        results += timed(self.tflint, root, name)
        results += timed(self.checkov, root, name)
        results += timed(self.terraform_test, terraform, root, name)
        return results

    def fmt(self, terraform, root, name):
        completed, error = run([terraform, "fmt", "-check", "-recursive", "-list=true", "-no-color", str(root)])
        if completed is None:
            return unverified("fmt", name, error)
        if completed.returncode == 0:
            return CheckResult("fmt", name, "PASS")
        files = completed.stdout.strip() or completed.stderr.strip()
        return CheckResult("fmt", name, "FAIL", files, f"run terraform fmt -recursive {name}")

    def init(self, terraform, root, name):
        command = [terraform, f"-chdir={root}", "init", "-backend=false", "-input=false", "-no-color"]
        if (root / ".terraform.lock.hcl").is_file():
            command.append("-lockfile=readonly")
        completed, error = run(command)
        if completed is None:
            return unverified("init", name, error)
        if completed.returncode != 0:
            return unverified("init", name, tail(completed.stderr or completed.stdout))
        return CheckResult("init", name, "PASS")

    def validate(self, terraform, root, name):
        completed, error = run([terraform, f"-chdir={root}", "validate", "-json", "-no-color"])
        if completed is None:
            return unverified("validate", name, error)
        try:
            report = json.loads(completed.stdout)
        except json.JSONDecodeError:
            return unverified("validate", name, tail(completed.stdout + completed.stderr))
        if report.get("valid"):
            return CheckResult("validate", name, "PASS")
        findings = [{"id": "validate", "name": d.get("summary", ""), "detail": d.get("detail", ""),
                     "file": (d.get("range") or {}).get("filename", "")}
                    for d in report.get("diagnostics", []) if d.get("severity") == "error"]
        return CheckResult("validate", name, "FAIL", f"{len(findings)} error(s)", "fix the configuration errors",
                           findings)

    def tflint(self, root, name):
        tflint = self.tools["tflint"]
        if not tflint:
            return unverified("tflint", name, "tflint not found")
        config = str(self.harness_dir / ".tflint.hcl")
        completed, error = run([tflint, "--init", f"--config={config}"], cwd=root)
        if completed is None or completed.returncode != 0:
            return unverified("tflint", name, error or tail(completed.stderr or completed.stdout))
        completed, error = run([tflint, f"--config={config}", "--format=json", "--no-color"], cwd=root)
        if completed is None:
            return unverified("tflint", name, error)
        try:
            report = json.loads(completed.stdout)
        except json.JSONDecodeError:
            return unverified("tflint", name, tail(completed.stdout + completed.stderr))
        if report.get("errors"):
            return unverified("tflint", name, json.dumps(report["errors"])[:2000])
        findings = [{"id": i["rule"]["name"], "name": i["message"],
                     "file": (root / i["range"]["filename"]).relative_to(self.project).as_posix(),
                     "lines": [i["range"]["start"]["line"], i["range"]["end"]["line"]],
                     "fix": i["rule"].get("link", "")}
                    for i in report.get("issues", [])]
        if findings:
            return CheckResult("tflint", name, "FAIL", f"{len(findings)} issue(s)", "see each finding's rule link",
                               findings)
        return CheckResult("tflint", name, "PASS")

    def checkov(self, root, name):
        checkov = self.tools["checkov"]
        if not checkov:
            return [unverified("checkov", name, "checkov not found")]
        var_files = self.environment_files(root)
        if not var_files:
            searched = ", ".join(f"{d}/*.tfvars" for d in VAR_FILE_DIRS)
            return [unverified("checkov", name, f"no environment file ({searched}): values Checkov cannot resolve "
                                                "would be guessed; add one, or name it with --var-file")]
        results = []
        for var_file in var_files:
            check_id_root = f"{name} [{var_file.stem}]"
            command = [checkov, "-d", str(root), "--framework", "terraform", "--skip-download", "--quiet",
                       "-o", "json", "--skip-path", ".terraform",
                       "--external-checks-dir", str(self.harness_dir / "checkov"),
                       "--var-file", str(var_file)]
            if (root / ".checkov.yaml").is_file():
                command += ["--config-file", str(root / ".checkov.yaml")]
            # Checkov relativizes paths against the working directory and fails across Windows drives.
            completed, error = run(command, cwd=root)
            if completed is None:
                results.append(unverified("checkov", check_id_root, error))
                continue
            results.append(self.checkov_result(completed, root, check_id_root))
        return results

    def checkov_result(self, completed, root, name):
        try:
            report = json.loads(completed.stdout) if completed.stdout.strip() else None
        except json.JSONDecodeError:
            return unverified("checkov", name, tail(completed.stdout + completed.stderr))
        if isinstance(report, list):
            report = next((r for r in report if r.get("check_type") == "terraform"), None)
        if report is None:
            return unverified("checkov", name, "checkov produced no terraform report: " + tail(completed.stderr))
        summary = report.get("summary", {})
        if summary.get("parsing_errors"):
            return unverified("checkov", name, f"{summary['parsing_errors']} file(s) could not be parsed")
        failed = report.get("results", {}).get("failed_checks", [])
        findings = [{
            "id": f["check_id"],
            "name": f["check_name"],
            "resource": f["resource"],
            "file": (root / f["file_path"].lstrip("/\\")).relative_to(self.project).as_posix(),
            "lines": f.get("file_line_range"),
            "fix": FIXES.get(f["check_id"]) or f.get("guideline") or f["check_name"],
        } for f in failed]
        if findings:
            return CheckResult("checkov", name, "FAIL", f"{len(findings)} failed check(s)", "see each finding's fix",
                               findings)
        if not summary.get("passed"):
            return unverified("checkov", name, "checkov evaluated no checks")
        return CheckResult("checkov", name, "PASS", f"{summary['passed']} passed")

    def terraform_test(self, terraform, root, name):
        if not list((root / "tests").glob("*.tftest.hcl")):
            return unverified("terraform-test", name, "no tests/*.tftest.hcl in this root")
        completed, error = run([terraform, f"-chdir={root}", "test", "-no-color"])
        if completed is None:
            return unverified("terraform-test", name, error)
        if completed.returncode != 0:
            return CheckResult("terraform-test", name, "FAIL", tail(completed.stdout + completed.stderr),
                               "fix the failing run blocks")
        return CheckResult("terraform-test", name, "PASS", tail(completed.stdout, 1))

    def run_all(self, changed=None):
        results = timed(self.app_tests)
        roots = affected_roots(self.project, changed)
        if not roots:
            results.append(unverified("roots", ".", "no Terraform files found"))
        for root in roots:
            results += self.root_checks(root)
        return results


def default_harness_dir(project: Path):
    installed = project / "harness"
    if (installed / ".tflint.hcl").is_file():
        return installed
    return Path(__file__).resolve().parents[1] / "assets" / "project" / "harness"


def with_baseline(project: Path, results, today: date):
    try:
        entries = baseline.load(project)
    except (baseline.BaselineError, ValueError) as error:
        return results + [CheckResult("baseline", ".", "FAIL", str(error), "fix harness/baseline.json")], []
    return baseline.apply(results, entries, today)


def report_dict(results, retired=(), seconds=0.0, harness_dir=None):
    status, _ = aggregate(results)
    counts = {s: sum(r.status == s for r in results) for s in EXIT_CODES}
    return {
        "status": status,
        "seconds": float(seconds),
        "harness_dir": str(harness_dir) if harness_dir else None,
        "baseline_retired": list(retired),
        "summary": f"harness check: {status} (pass {counts['PASS']}, fail {counts['FAIL']}, "
                   f"unverified {counts['UNVERIFIED']})",
        "checks": [asdict(r) for r in results],
    }


def print_human(report):
    for c in report["checks"]:
        line = f"{c['status']:<10} {c['id']:<15} {c['root']}"
        if c["detail"] and c["status"] != "PASS":
            line += f"  {c['detail'].splitlines()[0]}"
        print(line)
        for f in c["findings"]:
            print(f"           - {f['id']} {f.get('resource') or f.get('file', '')}: {f.get('fix') or f['name']}")
    for identity in report.get("baseline_retired", []):
        print(f"           baseline entry no longer needed: {identity} (run baseline.py prune)")
    print(report["summary"])


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("project", type=Path)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--harness-dir", type=Path)
    parser.add_argument("--changed", nargs="*", type=Path, default=[])
    parser.add_argument("--var-file", action="append", type=Path, default=[], dest="var_files")
    for tool in ("terraform", "tflint", "checkov"):
        parser.add_argument(f"--{tool}")
    args = parser.parse_args(argv)

    project = args.project.resolve()
    tools = {tool: resolve_tool(tool, getattr(args, tool)) for tool in ("terraform", "tflint", "checkov")}
    harness_dir = (args.harness_dir or default_harness_dir(project)).resolve()
    started = time.perf_counter()
    results = Checker(project, harness_dir, tools, args.var_files).run_all(args.changed)
    results, retired = with_baseline(project, results, date.today())
    report = report_dict(results, retired, round(time.perf_counter() - started, 2), harness_dir)

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print_human(report)
    return aggregate(results)[1]


if __name__ == "__main__":
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    sys.exit(main())
