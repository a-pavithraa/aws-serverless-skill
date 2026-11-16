# Decision: two instances from the first deploy

Date: 2026-11-15.

## Why

A review of a real codebase (a container web app on ECS behind a load balancer, with SQS event queues) found:

- The service was pinned to one task "because state is in memory", but its deployment used minimum healthy 100 % and maximum 200 %, so every deploy ran two tasks together. The single-task assumption was written down and never tested; in-app timers, limits and caches doubled during each rollout.
- The stack had dead-letter queues with no alarm on them, and no alarm on the service. The harness checked that every Lambda function has an alarm, and nothing else.
- Our own `ecs-web` template defaulted to `min_tasks = 1`, so a project made from it met two tasks first in a production rollout. The verifier checked that every task ran the expected image but sent each probe once, so it never showed that more than one task answered or that the tasks agreed.

Principle: a service always runs at least two instances at some moment (a rollout or a scale-out). The templates and checks exercise two from the first deploy, and running one is a recorded decision.

## Decision

| Change | Where | Proven by |
| --- | --- | --- |
| `ecs-web` defaults to `min_tasks = 2`, `max_tasks = 4`. `min_tasks = 1` needs `single_task_reason` (≥ 10 characters); `alb-ec2` `min_instances = 1` needs `single_instance_reason`. Same three places as `public_reason`: Copier validator, Terraform variable validation, `plan.tftest.hcl`; the reason is a tag, and README and runbook say that a rollout still runs old and new together | templates | `test_template_render`, `plan.tftest.hcl` |
| `GET /hello` returns `instance`: the ECS task ID (task metadata endpoint v4) or the EC2 instance ID (IMDSv2), else the hostname; never fails the request | `ecs-web`, `alb-ec2` `app/server.py` | the apps' own `app/tests` |
| Probes may repeat and assert `expect_distinct` (at least N values of a key) and `expect_same` (keys equal in every response). Two or more running and one answering is FAIL; one running is UNVERIFIED, reported | `verify_deployment.py verify` | `test_verification.MultiInstanceProbeTest` |
| `watch-rollout` probes while a rollout runs, fails on any failed request, lists the instances and source hashes that answered, and fails a rollout that ends on other source | `verify_deployment.py watch-rollout` | `test_verification.WatchRolloutTest` |
| `HARNESS_AWS_4`: a dead-letter queue needs an alarm. `HARNESS_AWS_5`: an ECS service (`aws_ecs_service`, `aws_ecs_express_gateway_service`) needs an alarm that names it. Checkov 3.4.3 has no check for either | `harness/checkov/` | `test_checks`; `references/coverage.md` lists what they miss |
| The `ecs-web` alarms name `aws_ecs_express_gateway_service.web[0].service_name` instead of a local, so `HARNESS_AWS_5` can follow the reference | `ecs-web` `infra/observability.tf` | `test_checks.TemplateChecksTest` |

A single instance is reported as UNVERIFIED rather than required, so that a project with a recorded `single_task_reason` can still exit 0. The decision is in Terraform and reviewed there; the verifier says what it could not show.

## Not done

- **Sandbox evidence.** The `instance` field, the repeated probes and `watch-rollout` are unit-tested with fakes only. None has run against a sandbox account, and the profiles stay `candidate`. A sandbox run must show two task IDs answering, a rollout watched from start to end with both source hashes, and a broken image failing `rollout-result`.
- **`terraform-deploy.yml`** does not run `watch-rollout`. Running it needs boto3 and ECS, Auto Scaling and load balancer read permissions in the apply job, and a real run to show it works; `references/deployment-workflows.md` shows how.
- **Checks that follow more than one reference.** `HARNESS_AWS_5` does not accept an alarm on the service's target group, and `HARNESS_AWS_4` does not recognize `aws_sqs_queue_redrive_policy`: Checkov's graph conditions follow one reference without direction (tried and observed, see `coverage.md`).
- **Whether the code tolerates two copies.** The checks show that two instances run and agree on what they return. They cannot show that in-memory state is safe to duplicate; the README and runbook say where to look.
