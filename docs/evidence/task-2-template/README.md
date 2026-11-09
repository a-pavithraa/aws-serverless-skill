# Task 2 evidence: reproducible `apigw-lambda` template

Date: 2026-11-08. Windows 11, Python 3.13.8 (uv), Copier 9.19.1, Terraform 1.14.4, providers aws 6.72.0 / archive 2.8.1 (resolved by `init`).

Command:

```
uv run --no-project --with copier==9.19.1 python -m unittest discover -s tests/scripts -p test_template_render.py
Ran 22 tests in 174.305s
OK
```

What the 22 tests establish:

- Copier rejects, non-interactively and without writing `infra/`: public route without a reason, s3 backend without bucket or key, bad project name, bad account ID, unsupported retention, untested runtime or architecture.
- Two renders with identical answers from the same checkout are byte-identical. The only machine-dependent content is `_src_path` in `.copier-answers.yml` (the template path on the rendering machine); it is the one documented transient field.
- `.copier-answers.yml` is written only because the template ships `{{_copier_conf.answers_file}}.jinja`; setting `_answers_file` alone did not create it (observed RED run).
- No `{{`, `{%` or `[[` remain in rendered files; tfvars carry the answers; the s3 backend uses `use_lockfile = true`; the local backend writes no `backend.tf`.
- README names the test, package and deploy commands; runbook names each alarm.
- The generated app's unit tests pass; `terraform init -backend=false` + `terraform test` (mocked) pass on the render, and the built `infra/build/lambda.zip` contains only `handler.py`.
- `render.py` refuses an existing destination (exit 3, contents unchanged), refuses a profile that fails the gate (exit 1, nothing created), and leaves no staging directory after a Copier validation failure.

Template revision for these runs: `1cf9fce+uncommitted` (the template is not committed yet; `render.py` prints the revision it rendered from).

Not established here: deployed behaviour, IAM correctness at runtime, ZIP identity against the deployed `CodeSha256` (Task 6).
