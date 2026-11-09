# Decision: template reuse for `apigw-lambda`

Date: 2026-11-08. Plan: `aws-harness-research/aws-harness-plan.md`, Task 0.

## Decision

Keep and adapt the untracked draft at `skills/creating-aws-projects/templates/apigw-lambda/`. Do not adopt the Serverless Land example or oisbase as the base. Copy no code from either; both are recorded as references only, so no third-party attribution is needed in the template.

Render with Copier invoked directly (no `landform` wrapper). Direct `aws_*` resources stay: the composition is 14 resources, and `terraform-aws-modules/lambda` would add its local packaging script for a dependency-free handler. Revisit when a pattern needs packaged dependencies.

## Acceptance contract used for the comparison

From plan §1 (`apigw-lambda` row) and §3: explicit API type and authentication, handler, package path, scoped IAM, structured logs with correlation, explicit retention, alarms with deliberate missing-data handling, dashboard and runbook, mocked configuration tests, and deployment evidence (authorized response, unauthorized rejection, artifact identity, correlated logs).

## Candidates

| | Draft (this repo) | Serverless Land `apigw-http-api-lambda-terraform` | oisbase |
| --- | --- | --- | --- |
| Revision | untracked working tree, 2026-11-08 | `aws-samples/serverless-patterns@23b5a9e` (2026-11-06) | `NipulM/oisbase@89a7b47` (2026-03-07) |
| License | repo's own | MIT-0 (LICENSE file; GitHub API reports NOASSERTION) | MIT |
| Form | Copier template, Terraform + Python app | single Terraform root + `src/` | Go CLI rendering Go templates into its own modules, wired through SSM parameters |
| Executed here | rendered and checked in Task 2/3 | **executed:** `terraform init -backend=false` + `validate` → "Success! The configuration is valid." (Terraform 1.14.4) | **desk only:** files read at the pinned revision; not built or run |

Requirement-by-requirement (evidence: `D`=desk read of the source at the revision above, `E`=executed):

| Requirement | Draft | Serverless Land | oisbase |
| --- | --- | --- | --- |
| Explicit auth decision | `auth_mode` iam/none, public requires a reason (D) | none; `$default` route, no authorizer (D) | none in the HTTP API template; CORS `*` (D) |
| Scoped invoke permission | `source_arn` to `GET /hello` on alias (D) | `/*/*` (D) | via OpenAPI body + SSM-resolved ARN (D) |
| Scoped execution role | own log group + X-Ray only (D) | `AWSLambdaBasicExecutionRole` (any log group) (D) | separate IAM template, not inspected in detail (D) |
| Explicit retention | both log groups (D) | both, variable default 7 (D) | Lambda variable; API fixed 14 (D) |
| Structured logs / correlation | JSON log format, correlation header echoed (D) | access log JSON only (D) | access log JSON only (D) |
| Tracing | Active (D) | not set (D) | not set (D) |
| Alarms, dashboard | 4 alarms, SNS, dashboard (D) | none (D) | none (D) |
| Artifact identity | ZIP + `source_code_hash`, published version + alias (D) | ZIP via S3 + `source_code_hash` (D) | `ignore_changes = [s3_bucket, s3_key]`: deployed code is changed outside Terraform (D) |
| Unsafe defaults | none known | `profile = "default"` in provider, `force_destroy = true` on bucket, fixed role name `serverless_lambda` collides across stacks (D) | none of those seen in the inspected files (D) |
| Mocked tests | `infra/tests/plan.tftest.hcl` (D) | none (D) | none in repo tree (D) |
| Non-interactive generation | Copier `--data-file` (to be tested Task 2) | n/a | prompts in `internal/prompts/questions.go`; non-interactive mode not established (D) |

Adaptation cost, estimated from the reads: Serverless Land would need every row above except retention and packaging, i.e. a rewrite of `main.tf`; oisbase would need a fork of its Go templates plus acceptance of its SSM-parameter wiring and out-of-band code deploys. Neither is a measured repair count; that comparison (Task 7) uses repeated agent runs.

## Draft inventory

Status meanings: **implemented** = present in files; **unverified** = present but not yet run; **missing** = not present.

| Area | Status | Notes / task |
| --- | --- | --- |
| Copier config with choices | implemented, unverified | cross-field validation for `public_reason`, `state_*` missing → Task 1/2 |
| Recorded answers file | unverified | `_answers_file` set but no `{{ _copier_conf.answers_file }}.jinja`; Copier may not write it → Task 2 |
| Handler + unit tests | implemented, unverified | stdlib only, no dependencies |
| Packaging | implemented, unverified | `archive_file` ZIP; ZIP determinism vs. deployed `CodeSha256` → Task 6 |
| IAM / API | implemented, unverified | |
| Observability | implemented, unverified | runbook missing; notification delivery not exercised → Task 6 |
| Mocked plan tests | implemented, unverified | → Task 2/3 |
| Checkov skip list with reasons | implemented, unverified | → Task 3 coverage map |
| Generated README / build instructions | missing | → Task 2 |
| Runtime profile record | missing | → Task 1 |
| `.verify/probes.json` | implemented | consumer (`verify_deployment.py`) missing → Task 6 |
| CI workflow | missing | belongs to the harness assets, not the template → Task 5 |

## Files to retain and change

Retain: everything under `templates/apigw-lambda/`. Change: `copier.yml` (validators, answers file), add `README.md.jinja` and `docs/runbook.md.jinja`. Nothing from the draft is deleted.
