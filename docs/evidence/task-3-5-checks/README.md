# Tasks 3 to 5: evidence for checks, installation and CI

Date: 2026-11-08. Windows 11. Terraform 1.14.4, TFLint 0.65.0 with the aws ruleset 0.50.0, Checkov 3.4.3, Copier 9.19.1, PyYAML from `uv`.

## Commands and results

Full suite, second run (`full-2.log`):

```
uv run --no-project --with copier==9.19.1 --with pyyaml python -m unittest discover -s tests/scripts -p "test_*.py" -v
Ran 111 tests in 808.922s
FAILED (failures=3)
```

The three failures had one cause: TFLint `--chdir` cannot make a path relative across Windows drives (repository on D:, temporary project on C:). `check.py` reported each one as UNVERIFIED, not PASS. The fix runs TFLint and Checkov with the root as the working directory. The three tests then pass:

```
python -m unittest ...test_clean_render_passes_every_check ...test_new_project_check_delegates_and_adds_template_checks ...test_baseline.IntegrationTest
Ran 3 tests in 190.337s
OK
```

## What the tests prove

- A clean render passes `app-tests`, `fmt`, `init`, `validate`, `tflint`, `checkov` and `terraform-test`.
- Seeded faults fail with the fix named: no log retention (`CKV_AWS_66`), an unauthenticated route (`CKV_AWS_309`), an unformatted file (`fmt`).
- Alarms removed in `observability.tf` fail at `aws_lambda_function.api` in `main.tf` (`HARNESS_AWS_2`). This is the cross-file case.
- A missing tool, a failed `init` and a root with no `envs/*.tfvars` give UNVERIFIED, never PASS.
- Baseline: recorded findings pass. A new instance of the same rule fails. A substituted finding fails, and so does an expired entry.
- Installer: a repeated install changes nothing. Edited owned files are reported as conflicts and kept. Workflows are installed only with `--workflows`.
- CI: the plan summary prints no attribute values. Each provenance mismatch is refused. The workflow properties are checked statically.

## Measured check time

`check_new_project.py` on one rendered root with a warm provider cache took 42.6 s. Checkov took about 20 s of that, and `terraform test` took most of the rest. A cold `init` with network problems took about 4 minutes before it failed, and the check reported it as UNVERIFIED.

## Environment findings

- The Terraform plugin cache is not safe for concurrent use. Parallel runs made `init` fail with "Failed to install provider". Run checks one at a time.
- On Windows, Checkov's `checkov.cmd` launcher uses the first `python` on PATH.

## Not verified

- The GitHub workflows have not run. No repository, environment or OIDC role exists for them (see `docs/decisions/deployment-runner.md`).
- actionlint did not run: the auto-mode classifier refused the Docker command.
- No agent-host hook adapters ship yet, because none has been tested.
