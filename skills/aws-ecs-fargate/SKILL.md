---
name: aws-ecs-fargate
description: "Use when writing or reviewing Terraform that deploys a container service to ECS Fargate: task definitions, secrets injected from Secrets Manager, image tags and ECR lifecycle, deployment rollback and alarms, a service behind a load balancer or in a VPC that a platform team owns, why a task does not start, or running more than one task. Not for a new service from a template (creating-aws-projects) or Lambda (aws-serverless)."
---

# ECS Fargate services in Terraform

This skill covers the application's Terraform root: cluster, task definition, service, ECR repository and log group. It assumes that the VPC, load balancer, target group, IAM roles and secrets may belong to a platform team, and that the application root only references them.

## Reference what the platform team owns

Start with the contract. Ask the platform team for:

- the execution and task role names;
- the secret name and the JSON keys it must hold;
- the VPC, the private subnets and the load balancer's security group;
- the target group, with its type, port and health check path;
- the deployer's grant.

Look up each item with a data source, and check it at plan time. Then a wrong ID fails the plan before anything changes, instead of failing a task at runtime.

```hcl
data "aws_iam_role" "execution" { name = local.execution_role_name } # plan fails if the role is missing

# Exists only for its postcondition, which tflint cannot see.
# tflint-ignore: terraform_unused_declarations
data "aws_subnet" "private" {
  for_each = toset(var.private_subnet_ids)
  id       = each.value
  lifecycle {
    postcondition {
      condition     = self.vpc_id == var.vpc_id
      error_message = "Subnet ${each.value} is not in ${var.vpc_id}."
    }
  }
}
```

- **Target group.** ECS registers the tasks through its service-linked role, so the deployer needs no Elastic Load Balancing permissions. Take the target group ARN as a variable, and make the `load_balancer` block dynamic, so the service can run before the target group exists.
- **Security groups.** Allow the container port in only from the load balancer's security group. Without VPC endpoints, the task needs outbound 443 to reach ECR, Secrets Manager and CloudWatch Logs. Some NAT instances accept traffic only from one source security group. A task without that group fails with "connection issue between the task and AWS Secrets Manager". That reads like an IAM problem, but it is the network: check egress first.
- **The deployer's grant.** Write down each AWS action the root needs, next to the root, and update it in the same change that adds a resource type. A platform team grants permissions from that list.

## Secrets

```hcl
secrets = [for name, key in local.secret_keys : {
  name      = name
  valueFrom = "${data.aws_secretsmanager_secret.app.arn}:${key}::" # <arn>:<json-key>:<version-stage>:<version-id>
}]
```

- One secret holding a JSON object, with one key for each variable. Keep the trailing `::`. Empty fields mean `AWSCURRENT`.
- The **execution role** reads the secret, not the task role. Its policy resource ends in `-??????`, the random suffix that Secrets Manager adds to the ARN.
- Set values with the CLI or the console, never through a Terraform resource. Terraform looks up the secret only by name or ARN.
- Put secret values only in `secrets`. Anyone with `ecs:DescribeTaskDefinition` can read `environment` values.
- **A rotated or updated secret does not reach running tasks.** Run a new deployment (`aws ecs update-service --force-new-deployment`) after every rotation, and put that step in the rotation runbook.
- A missing key, or a secret that the execution role cannot read, stops the task before the container starts. Only the task's stopped reason shows the cause. When you add a key to the task definition, put the value in the secret before you deploy.

> *Source: [ECS secrets from Secrets Manager](https://docs.aws.amazon.com/AmazonECS/latest/developerguide/secrets-envvar-secrets-manager.html) · verified 2026-11-15*

## Images

- Tag each image with the commit SHA, in an `IMMUTABLE` repository, and pass the tag in as a variable whose validation rejects `latest`.
- ECS resolves the tag to a digest when it deploys (`versionConsistency`, on by default), and every later task in that deployment starts from that digest. A replacement task, a scale-out or a rollback therefore needs that exact image to still exist.
- **The lifecycle policy must not expire an image that a service still runs.** `imageCountMoreThan N` with `tagStatus = "any"` on a repository that several environments share lets frequent dev pushes, and throwaway builds, delete the image that production runs. Expire untagged images, and expire release images by age or by a tag prefix per environment. Or give each account its own repository, and copy the image to it on promotion.
- Build once, and deploy that digest to every environment.

> *Source: [ECS rolling deployments](https://docs.aws.amazon.com/AmazonECS/latest/developerguide/deployment-type-ecs.html) · verified 2026-11-15*

## Deployments

```hcl
deployment_minimum_healthy_percent = 100
deployment_maximum_percent         = 200

deployment_circuit_breaker {
  enable   = true
  rollback = true
}

alarms {
  enable      = true
  rollback    = true
  alarm_names = [aws_cloudwatch_metric_alarm.target_5xx.alarm_name]
}
```

- The circuit breaker sees only tasks that do not reach RUNNING or that fail health checks. A release that starts and then answers 5xx passes it. The `alarms` block fails the deployment and rolls it back when a named alarm goes to ALARM after the deployment.
- If an alarm is already in ALARM when a deployment starts, ECS does not watch alarms for that deployment. ECS polls `DescribeAlarms`, and a throttled poll can miss an alarm, so keep the circuit breaker on as well.
- An `alarms` block needs the alarms to exist, which needs `cloudwatch:PutMetricAlarm` in the deployer's grant. Until the platform team grants it, put the alarms and a `dynamic "alarms"` block behind one switch that defaults to off, so the plan stays clean.

### The rollback alarm

AWS recommends `HTTPCode_ELB_5XX_Count` for the rollback alarm. It counts the 502s and 504s that the load balancer answers itself when a new task hangs or crashes. `HTTPCode_Target_5XX_Count` counts only what the application answers, so it misses those.

- `HTTPCode_ELB_5XX_Count` exists only with the `LoadBalancer` dimension. On a load balancer that other services share, it counts their errors, and it would roll back your deployment for them. Alarm on the target group's `HTTPCode_Target_5XX_Count` only there. Make "the load balancer serves only this service" a variable with no default, so each environment states it.
- Alarm on a share, not a count: errors × 100 / `RequestCount` in metric math, with both sides from the same dimensions, and 0 below a minimum request count. During a deployment the old tasks still answer, and their successes dilute a fixed count of the new task's errors. A share also stays meaningful at quiet times.
- Treat missing data as not breaching, so a quiet period does not block every deployment.

```hcl
metric_query {
  id          = "share"
  expression  = "IF(requests >= ${var.http_5xx_min_requests}, 100 * errors / requests, 0)"
  return_data = true
}
```

### Deploy only when the image changed

Every new image tag registers a new task definition and replaces the running tasks. If CI tags the image with the commit SHA of every merge, a change to a queue or an alarm also replaces the tasks. That signs users out while sessions are in memory, and empties a sidecar database. Reuse the tag that the environment runs (`terraform output`) when nothing that goes into the image changed since that commit (`git diff --name-only <deployed> HEAD -- <build inputs>`). Run those pushes one at a time (one `concurrency` group): otherwise an infrastructure-only push can read the old tag while an application push is still deploying, and roll the application back.

> *Sources: [Alarm-based rollback](https://docs.aws.amazon.com/AmazonECS/latest/developerguide/deployment-alarm-failure.html) · verified 2026-11-21; [ALB CloudWatch metrics](https://docs.aws.amazon.com/elasticloadbalancing/latest/application/load-balancer-cloudwatch-metrics.html) · verified 2026-11-21*
- `health_check_grace_period_seconds` covers slow starts (JVM start, migrations). Set it from a measured start time.
- With `wait_for_steady_state = false`, the apply succeeds as soon as ECS accepts the new task definition. If the circuit breaker then rolls back, the apply still showed success, and the old revision is running. After the apply, run `aws ecs wait services-stable`, then check that the service's primary deployment has `rolloutState = COMPLETED` on the new task definition. With `true`, a task that stops at once, for example because a secret key is missing, makes the apply wait until its timeout.

> *Sources: [Circuit breaker](https://docs.aws.amazon.com/AmazonECS/latest/developerguide/deployment-circuit-breaker.html) · verified 2026-11-15; [Alarm-based rollback](https://docs.aws.amazon.com/AmazonECS/latest/developerguide/deployment-alarm-failure.html) · verified 2026-11-15*

## Logs and alarms

- Create `/ecs/<service>` in Terraform with `retention_in_days`, and leave out `awslogs-create-group`. Then the execution role needs no `logs:CreateLogGroup`, and the logs expire.
- Alarm, with an SNS topic that someone receives, on:
  - the 5xx share (see [The rollback alarm](#the-rollback-alarm));
  - `HealthyHostCount` for the target group: below 1 as critical, and below the desired count as a warning once it is above 1. `RunningTaskCount` exists only with Container Insights;
  - for every queue the service consumes, the DLQ depth, and the main queue's `ApproximateAgeOfOldestMessage`. A stuck consumer leaves messages ageing in the main queue, not in the DLQ.
- A service that scales to 0 on a schedule must not have alarms that treat missing data as breaching, such as no healthy targets. Every night would look like an outage.
- Send ECS events to the same topic with EventBridge. They are free, and catch what no metric alarm does:
  - `ECS Task State Change` with `lastStatus = STOPPED`, `group = service:<name>`, and `stopCode` `EssentialContainerExited` or `TaskFailedToStart`. Leave out `ServiceSchedulerInitiated`, so a normal deployment sends nothing. An `input_transformer` that sends only the task ARN, `stopCode` and `stoppedReason` keeps the message short;
  - `ECS Deployment State Change` with `eventName = SERVICE_DEPLOYMENT_FAILED`. ECS sends it only for services with the circuit breaker on.
- A topic encrypted with the AWS managed key `aws/sns` takes no messages from CloudWatch alarms or EventBridge, and nothing reports the failure. Its key policy cannot be changed to allow them. Where a platform team owns the topic, ask for a customer managed key whose policy allows `cloudwatch.amazonaws.com` and `events.amazonaws.com`.
- The `awslogs` driver has defaulted to `non-blocking` mode with a 10 MB buffer since 2025-06-25. When the buffer is full, log lines are lost. Set `mode` on purpose.
- For metrics, traces and log routing beyond this, including Container Insights levels, custom metrics from several tasks, masking regulated data in logs, whether to add a sidecar (CloudWatch agent, OpenTelemetry collector, FireLens), how to wire it, and sending telemetry to Grafana or another OTLP backend, read [`references/observability.md`](references/observability.md). Most services need no sidecar.

## When a task does not start

```bash
aws ecs list-tasks --cluster <cluster> --desired-status STOPPED
aws ecs describe-tasks --cluster <cluster> --tasks <arn> --query "tasks[].[stoppedReason,containers[].reason]"
```

| Stopped reason | Cause |
| --- | --- |
| `ResourceInitializationError` naming Secrets Manager | A missing key or value, no `GetSecretValue` on the execution role, or no route to Secrets Manager |
| `CannotPullContainerError` | The tag or digest is not in ECR (check the lifecycle policy), or no route to ECR |
| Running, then deregistered | The target group health check fails. Read the container log for the startup error, and check the health check path and the grace period |

## Before `desired_count` goes above 1

Check each item. Each one breaks quietly when a second task starts:

1. **Sessions in memory.** Users are signed out at random. Move sessions to a shared store. ALB stickiness is a stopgap: use `app_cookie` on the application's session cookie, not `lb_cookie`, whose fixed lifetime can end while the session is still alive.
2. **Scheduled jobs with no lock.** Each task runs each job. Add a lock (for example ShedLock, or a database advisory lock), or move the job to a scheduled task.
3. **Sidecar databases or caches.** Each task gets its own copy, and the data splits between them.
4. **Queue consumers.** These are fine with several tasks when processing is idempotent.

With one task, the service runs in one Availability Zone at a time, and every deployment replaces it.

With several tasks:

- `stopTimeout` (30 s by default on Fargate, at most 120 s) must be longer than the application's own shutdown wait, for example a scheduler that finishes its running job. Otherwise ECS kills the job halfway through every deployment.
- To see one bad task, use Container Insights with enhanced observability, which adds task and container metrics. Application metrics should carry no task dimension (`references/observability.md`).
- Size the healthy-target and missing-telemetry alarms from `desired_count`, not from a number written into the alarm.

## Review checklist

Report each item as PASS, FAIL or NOT APPLICABLE:

1. Platform-owned inputs are data sources with checks, and the root creates nothing that the platform team owns.
2. Secrets use `valueFrom` with a JSON key, the values are set outside Terraform, and the rotation runbook includes a new deployment.
3. Image tags are immutable and are not `latest`, and the lifecycle policy cannot expire an image that any environment runs.
4. Circuit breaker with rollback, an `alarms` block on a 5xx share that includes the load balancer's own 5xx when the load balancer is not shared, and a post-apply check that the new revision completed.
5. The log group is created in Terraform with retention, and the `awslogs` `mode` is set on purpose. Alarms use target-group dimensions on a shared load balancer, and notify a topic that CloudWatch and EventBridge can publish to. Task stops and failed deployments reach the same topic.
6. Each sidecar is justified by `references/observability.md` (step 5 or 6, or a backend other than CloudWatch), and is non-essential with its own memory and logs. The rollback alarm stays in CloudWatch. Traces of regulated data are redacted.
7. The task security group allows ingress only from the load balancer's group.
8. If `desired_count` can be above 1, the four items above are handled.
9. The provider sets `allowed_account_ids`, and each environment has its own state key.
10. Builds and applies run in CI from a reviewed plan, with an OIDC role (`terraform-aws`), not from a laptop.
