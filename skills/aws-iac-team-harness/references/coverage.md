# Check coverage map

Requirement → the check that enforces it → stage → fixture or test that proves it fails. IDs were read from Checkov 3.4.3 and TFLint 0.65.0 + aws ruleset 0.50.0 output on a rendered `apigw-lambda` project (2026-11-08). Custom checks exist only where no upstream check covers the requirement.

Stages: **HCL** = `check.py` on source, no credentials (hook, PR CI). **Plan** = scan of `terraform show -json` in protected CI (Task 5). **Runtime** = `verify_deployment.py` against a deployed sandbox (Task 6).

| Requirement | Check | Stage | Proven by |
| --- | --- | --- | --- |
| Log groups have explicit retention | Checkov `CKV_AWS_66` | HCL | `test_checks.test_missing_retention_fails_with_fix` |
| Every Lambda function writes to a Terraform-managed log group (not an auto-created never-expiring one) | **`HARNESS_AWS_1`** (graph: function ↔ `aws_cloudwatch_log_group`) | HCL | fixture `lambda-without-log-group`; cross-file pass in `lambda-cross-file` |
| Every Lambda function has an alarm | **`HARNESS_AWS_2`** (graph: function ↔ `aws_cloudwatch_metric_alarm`) | HCL | `test_alarms_removed_in_another_file_fail_at_the_function` (finding lands in unchanged `main.tf`) |
| Alarm notifications can be published: the alarm topic does not use `alias/aws/sns` | **`HARNESS_AWS_3`** (graph: topic connected to an alarm, with the AWS managed key) | HCL | `test_alarm_topic_on_aws_managed_key_fails`; false-positive guard `test_managed_key_topic_without_alarm_passes`; found by the Task 6 sandbox deployment |
| Every dead-letter queue has an alarm: a queue that another `aws_sqs_queue` names in its `redrive_policy` | **`HARNESS_AWS_4`** (graph: queue ↔ queue without its own `redrive_policy`, ↔ `aws_cloudwatch_metric_alarm`) | HCL | fixture `dlq-without-alarm` (finding at the dead-letter queue only, not its source queue); cross-file pass and false-positive guard (a queue that is no dead-letter queue, and a source queue, need no alarm) in `queue-cross-file`; `test_dead_letter_queue_without_its_alarm_fails_at_the_queue` on a rendered `sqs-lambda-worker` |
| Every ECS service has an alarm that names it (`aws_ecs_service`, and `aws_ecs_express_gateway_service` for Express Mode) | **`HARNESS_AWS_5`** (graph: service ↔ `aws_cloudwatch_metric_alarm`) | HCL | fixture `ecs-service-without-alarm` (an alarm on the target group only fails); cross-file pass and false-positive guard (task definitions need none) in `ecs-service-cross-file`; `test_express_service_without_its_alarms_fails_at_the_service` on a rendered `ecs-web` |
| A service runs two instances unless one is a recorded decision | `ecs-web` `min_tasks` default 2, `alb-ec2` `min_instances` default 2; `single_task_reason` / `single_instance_reason` (≥ 10 characters) in Copier, Terraform variable validation and a tag | HCL | `test_template_render` `test_one_task_without_a_reason_is_rejected`, `test_one_instance_without_a_reason_is_rejected`; `plan.tftest.hcl` `single_task_needs_a_reason`, `single_instance_needs_a_reason` |
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
| More than one instance answers, and the instances agree (`repeat`, `expect_distinct`, `expect_same` in `.verify/probes.json`) | `verify_deployment.py verify`: `instances:<probe>`, `agree:<probe>` | Runtime | `test_verification.MultiInstanceProbeTest`. **Unit-tested with fakes only; not yet run against a sandbox account** |
| No request fails while a rollout runs; old and new both answer; the rollout ends on this checkout's source | `verify_deployment.py watch-rollout`: `rollout`, `rollout-probes`, `rollout-overlap` (reported), `rollout-result` | Runtime | `test_verification.WatchRolloutTest`. **Unit-tested with fakes only; not yet run against a sandbox account** |

## Why `HARNESS_AWS_4` and `HARNESS_AWS_5` are custom

Checked against Checkov 3.4.3 (`checkov --list --framework terraform` and its `checkov/terraform/checks` directory, verified 2026-11-15): the only check that names `aws_cloudwatch_metric_alarm` is `CKV_AWS_319` (alarm actions enabled); no check reads `redrive_policy` or names `aws_ecs_express_gateway_service`, and no check asks for an alarm on a queue or an ECS service.

What they do not cover, observed with Checkov 3.4.3 on 2026-11-15:

- **One reference only.** A graph connection follows one reference between two resources. An alarm that names the queue or service through a `local` does not count (observed: a `local.dlq_name` in the dimensions failed the check), so name the resource attribute in `dimensions`. Two-hop conditions (service → target group → alarm) combined with `and` passed a service whose target group had no alarm, so `HARNESS_AWS_5` does not accept a target-group alarm.
- **Inline `redrive_policy` only.** A dead-letter queue wired with a separate `aws_sqs_queue_redrive_policy` resource is not recognized: that resource names both queues, and the graph has no direction to tell them apart.
- **No direction between queues.** Two queues that reference each other for another reason (a tag, a `redrive_allow_policy` on a queue whose source uses `aws_sqs_queue_redrive_policy`) are treated as a dead-letter pair; the one without a `redrive_policy` needs an alarm or a reviewed skip.
- **A queue that is a dead-letter queue and also has its own `redrive_policy`** (a chain) is not checked.
- **Not whether the alarm is useful.** Any alarm that names the resource passes. The templates alarm on `ApproximateNumberOfMessagesVisible > 0` for a dead-letter queue and on `RunningTaskCount` below the minimum and CPU for a service.
- Resources with `count = 0` are still checked (observed on `ecs-web` before an image digest exists), which is the wanted result.

## Values Checkov cannot resolve

Checkov evaluates HCL with the values it can find. Without a var-file, `var.auth_mode == "iam" ? "AWS_IAM" : "NONE"` was evaluated as failing `CKV_AWS_309` (observed). `check.py` therefore runs Checkov once per environment file (`envs/`, `env/` or `environments/`, or `--var-file`) and reports **UNVERIFIED** when a root has none (`test_unresolved_variables_are_unverified`). Values unknown until apply (IDs, ARNs) are a plan-stage concern: plan JSON marks them in `after_unknown`, and the plan stage must treat them as unknown, not as absent.

## Pattern-specific skips

`infra/.checkov.yaml` in each template lists skipped checks, each with its reason (no DLQ on a synchronous API, no VPC, no CMK on logs, …). It is project-owned: changing it is a reviewed policy decision, and the protected-file rules (Task 4) treat it that way.

## Windows note

Checkov's `checkov.cmd` launcher runs the first `python` on PATH, not the interpreter Checkov was installed into. With uv or pipx installs that python usually lacks Checkov, and the scan fails ("File association not found for extension .py"). `check.py` reports that as UNVERIFIED. Fix the install (point the launcher at the tool environment's `python.exe`) or pass `--checkov` with a working launcher.
