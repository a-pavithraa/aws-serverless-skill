# Patterns

| Pattern | Status | Use when | Not when |
| --- | --- | --- | --- |
| `apigw-lambda` | template exists; profile `candidate` until sandbox evidence is recorded in the profile | Request/response HTTP API, short handlers (< 29 s), spiky or low traffic | Long-lived connections, a full web framework already in the codebase (evaluate Lambda Web Functions or ECS) |
| `ecs-web` | template exists; profile `candidate` until sandbox evidence is recorded in the profile | Container HTTP service, steady traffic, no authentication at the load balancer; ECS Express Mode owns the load balancer | Event-driven handlers; a WAF, load balancer access logs, own listener rules or a non-canary rollout (Express Mode allows none) |
| `sqs-lambda-worker` | template exists; profile `candidate` until sandbox evidence is recorded in the profile | Asynchronous work items that can be retried: partial batch responses, a dead-letter queue on the source queue, idempotency by message `id` | Strict ordering (needs a FIFO queue, not in this template); work longer than 15 minutes |
| `apigw-step-functions` | template exists; profile `candidate` until sandbox evidence is recorded in the profile | Multi-step workflow behind an API that answers within 25 s: synchronous Express workflow, execution status mapped to 200, 422, 504 or 500 | A single call (use `apigw-lambda`); work longer than 25 s or that needs exactly-once steps (needs an asynchronous Standard workflow, not in this template) |
| `network` | template exists; profile `candidate` until sandbox evidence is recorded in the profile | A VPC for `ecs-web` and `alb-ec2`, in its own Terraform root and state; publishes subnet IDs to SSM | An organization whose platform team already provides networks (pass their `subnet_ids`) |
| `alb-ec2` | template exists; profile `candidate` until sandbox evidence is recorded in the profile | Software that needs a VM: Auto Scaling group behind a load balancer, AL2023 AMI from SSM, rolling instance refresh | Anything that fits a container (use `ecs-web`) |

EKS is out of scope. A planned pattern has no template: say so rather than hand-writing one and calling it this pattern.

## apigw-lambda answers

| Answer | Values | Default | Notes |
| --- | --- | --- | --- |
| `project_name` | `^[a-z][a-z0-9-]{1,30}[a-z0-9]$` | — | Prefix of every resource name |
| `aws_region` | region | `us-east-1` | Must be in the profile's `regions` to count as tested |
| `environment` | `^[a-z][a-z0-9]{1,15}$` | `dev` | Names `infra/envs/<env>.tfvars` |
| `auth_mode` | `iam`, `none` | `iam` | `none` requires `public_reason` (≥ 10 chars); ask the user why the API is public |
| `runtime`, `architecture` | profile values only | `python3.13`, `arm64` | Other combinations have no profile: UNVERIFIED |
| `log_retention_days` | CloudWatch values | `14` | |
| `alarm_email` | email or empty | empty | Subscription needs confirmation from the inbox |
| `allowed_account_id` | 12 digits or empty | empty | Provider refuses other accounts when set; recommend setting it |
| `backend` | `local`, `s3` | `local` | `s3` needs `state_bucket`, `state_key`; the bucket must exist |

## network answers

`project_name`, `aws_region`, `environment`, `log_retention_days` (flow logs), `allowed_account_id` and `backend` work as in `apigw-lambda`. `runtime` is `none` and `architecture` is `managed`. The network adds these:

| Answer | Values | Default | Notes |
| --- | --- | --- | --- |
| `cidr` | IPv4 /16 to /20 | `10.42.0.0/16` | Subnets are /24s cut from it |
| `az_count` | 2 or 3 | `2` | Load balancers need two zones |
| `nat_mode` | `none`, `single`, `per-az` | `none` | `none` costs nothing; each NAT gateway costs about 32 USD a month plus data |
| `zone_instance_type` | an instance type | `t4g.micro` | Only zones that offer it get subnets |

`ecs-web` and `alb-ec2` take `network_name = "<project>-<environment>"` of a network made from this template.

## apigw-step-functions answers

`project_name`, `aws_region`, `environment`, `auth_mode`, `public_reason`, `log_retention_days`, `alarm_email`, `allowed_account_id` and `backend` work as in `apigw-lambda`. `runtime` is `asl-jsonpath` and `architecture` is `managed`: Step Functions has no runtime. The workflow adds this:

| Answer | Values | Default | Notes |
| --- | --- | --- | --- |
| `workflow_timeout_seconds` | 1-25 | `10` | The workflow's `TimeoutSeconds`; it must end before API Gateway's 29 s integration timeout |

Prerequisite: the account's API Gateway CloudWatch role (`aws apigateway get-account` shows `cloudwatchRoleArn`). The template does not manage it.

## alb-ec2 answers

`project_name`, `aws_region`, `environment`, `runtime`, `architecture`, `log_retention_days`, `alarm_email`, `allowed_account_id` and `backend` work as in `apigw-lambda`. The service adds these:

| Answer | Values | Default | Notes |
| --- | --- | --- | --- |
| `instance_type` | a Graviton type (`t4g`, `m7g`, `c7g`, `r7g` and their `8g` successors) | `t4g.micro` | The AMI is arm64 |
| `min_instances`, `max_instances` | 1-20, max > min | `2`, `3` | A refresh adds one instance before it removes one |
| `certificate_arn` | ACM certificate ARN or empty | empty | Empty serves plain HTTP on port 80 |
| `plain_http_reason` | text, 10 characters or more | none | Required when `certificate_arn` is empty |
| `network_name` | a `network` project's `<project>-<environment>` | none | Required unless `subnet_ids` is given; the default VPC is not used |
| `subnet_ids` | comma-separated subnet IDs in two or more zones | empty | Only when there is no `network` project |

## ecs-web answers

`project_name`, `aws_region`, `environment`, `runtime`, `architecture`, `log_retention_days`, `alarm_email`, `allowed_account_id` and `backend` work as in `apigw-lambda`. The service adds these:

| Answer | Values | Default | Notes |
| --- | --- | --- | --- |
| `public_reason` | text, 10 characters or more | none | Required: the service has no authentication |
| `cpu` | `256`, `512`, `1024` | `256` | Fargate CPU units |
| `memory` | MiB that Fargate accepts for the CPU | `512` | 256 CPU: 512-2048; 512: 1024-4096; 1024: 2048-8192 |
| `min_tasks`, `max_tasks` | 1-20, min ≤ max | `1`, `2` | Scaled on average CPU 60 % |
| `network_name` | a `network` project's `<project>-<environment>` | none | Required unless `subnet_ids` is given; the default VPC is not used |
| `subnet_ids` | comma-separated subnet IDs in two or more zones | empty | Only when there is no `network` project |
| `secret_names` | comma-separated upper-case names, such as `DB_PASSWORD,API_TOKEN` | empty | One Secrets Manager secret, one JSON key per name, injected through the task's `secret` block; the value is set with the AWS CLI, never in Terraform |

The first deploy has two steps: the plan without `image_digest` creates the repository (and the secret, with `secret_names`), then the image is pushed and the plan with its digest creates the service. With `secret_names`, set the secret value between the two. The generated README has the commands.

## sqs-lambda-worker answers

`project_name`, `aws_region`, `environment`, `runtime`, `architecture`, `log_retention_days`, `alarm_email`, `allowed_account_id` and `backend` work as in `apigw-lambda`. The worker adds these:

| Answer | Values | Default | Notes |
| --- | --- | --- | --- |
| `function_timeout_seconds` | 1-900 | `10` | The queue's visibility timeout is six times this |
| `max_receive_count` | 1-10 | `3` | Deliveries before SQS moves a message to the dead-letter queue |
| `batch_size` | 1-10 | `10` | Larger batches need a batching window; not in this template |
| `max_concurrency` | 2-1000 | `2` | The event source's maximum concurrency; it also protects downstream systems |
