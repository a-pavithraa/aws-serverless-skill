# Check coverage map

Requirement → the check that enforces it → stage → fixture or test that proves it fails. IDs were read from Checkov 3.4.3 and TFLint 0.65.0 + aws ruleset 0.50.0 output on a rendered `apigw-lambda` project (2026-11-08). Custom checks exist only where no upstream check covers the requirement.

Stages: **HCL** = `check.py` on source, no credentials (hook, PR CI). **Plan** = scan of `terraform show -json` in protected CI (Task 5). **Runtime** = `verify_deployment.py` against a deployed sandbox (Task 6).

| Requirement | Check | Stage | Proven by |
| --- | --- | --- | --- |
| Log groups have explicit retention | Checkov `CKV_AWS_66` | HCL | `test_checks.test_missing_retention_fails_with_fix` |
| Every Lambda function writes to a Terraform-managed log group (not an auto-created never-expiring one) | **`HARNESS_AWS_1`** (graph: function ↔ `aws_cloudwatch_log_group`) | HCL | fixture `lambda-without-log-group`; cross-file pass in `lambda-cross-file` |
| Every Lambda function has an alarm | **`HARNESS_AWS_2`** (graph: function ↔ `aws_cloudwatch_metric_alarm`) | HCL | `test_alarms_removed_in_another_file_fail_at_the_function` (finding lands in unchanged `main.tf`) |
| Alarm notifications can be published: the alarm topic does not use `alias/aws/sns` | **`HARNESS_AWS_3`** (graph: topic connected to an alarm, with the AWS managed key) | HCL | `test_alarm_topic_on_aws_managed_key_fails`; false-positive guard `test_managed_key_topic_without_alarm_passes`; found by the Task 6 sandbox deployment |
| Routes are authenticated, or publicly exposed by a reviewed decision | Checkov `CKV_AWS_309`; Terraform variable validation needs `public_reason` | HCL | `test_unauthenticated_route_fails`; `plan.tftest.hcl` `public_route_without_reason_is_rejected` |
| Invoke permission scoped to the API | Checkov `CKV_AWS_364` | HCL | upstream check; no harness fixture yet |
| Function not publicly invokable | Checkov `CKV_AWS_301` | HCL | upstream |
| Active tracing | Checkov `CKV_AWS_50` | HCL | upstream |
| API access logging | Checkov `CKV_AWS_76` | HCL | upstream |
| No IAM wildcards on restrictable actions; no admin/escalation | Checkov `CKV_AWS_1/49/62/63/107–111/356`, `CKV2_AWS_40` | HCL | upstream |
| Alarm actions enabled | Checkov `CKV_AWS_319` | HCL | upstream |
| SNS encrypted | Checkov `CKV_AWS_26` | HCL | upstream |
| Runtime not deprecated | TFLint `aws_lambda_function_deprecated_runtime`, Checkov `CKV_AWS_363`; release gate `profiles.py` | HCL | `test_profiles` |
| Formatting, validity | `terraform fmt -check`, `terraform validate` | HCL | `test_unformatted_file_fails` |
| Pattern configuration (auth wiring, alias, retention values) | mocked `terraform test` in the template | HCL | `infra/tests/plan.tftest.hcl` |
| Stateful deletes / replacements surfaced before apply | plan summary in CI | Plan | Task 5 |
| Deployed code is this checkout's package; authorized 200, unauthorized 403; request found in logs | `verify_deployment.py` | Runtime | Task 6 |

## Values Checkov cannot resolve

Checkov evaluates HCL with the values it can find. Without a var-file, `var.auth_mode == "iam" ? "AWS_IAM" : "NONE"` was evaluated as failing `CKV_AWS_309` (observed). `check.py` therefore runs Checkov once per environment file (`envs/`, `env/` or `environments/`, or `--var-file`) and reports **UNVERIFIED** when a root has none (`test_unresolved_variables_are_unverified`). Values unknown until apply (IDs, ARNs) are a plan-stage concern: plan JSON marks them in `after_unknown`, and the plan stage must treat them as unknown, not as absent.

## Pattern-specific skips

`infra/.checkov.yaml` in each template lists skipped checks, each with its reason (no DLQ on a synchronous API, no VPC, no CMK on logs, …). It is project-owned: changing it is a reviewed policy decision, and the protected-file rules (Task 4) treat it that way.

## Windows note

Checkov's `checkov.cmd` launcher runs the first `python` on PATH, not the interpreter Checkov was installed into. With uv or pipx installs that python usually lacks Checkov, and the scan fails ("File association not found for extension .py"). `check.py` reports that as UNVERIFIED. Fix the install (point the launcher at the tool environment's `python.exe`) or pass `--checkov` with a working launcher.
