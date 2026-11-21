# Observability and sidecars on Fargate

## Decide whether you need a sidecar

Work down this list, and stop at the first step that answers the question you have:

1. **Alarms on what the load balancer and queues already publish** (see SKILL.md). No sidecar, no code change.
2. **Container Insights** (`setting { name = "containerInsights" }` on the cluster). Task CPU, memory and `RunningTaskCount`. No sidecar.
   - The values are `disabled`, `enabled` and `enhanced`. `enhanced` adds task and container metrics, which AWS recommends, and which is how you find one bad task among several. A cluster without the setting takes the account's `containerInsights` setting, so set it on the cluster on purpose.
   - Its metrics are billed as custom metrics, and `enhanced` publishes more of them, per task and per container. `RunningTaskCount` is not billed since 2026-10-01. A common choice is `enhanced` in prod and `disabled` in dev.
3. **Log metric filters** on the application's own log lines (for example, a count of `ERROR`). No sidecar.
4. **Custom metrics from code.** Use a metrics library that calls `PutMetricData` directly (for example, Micrometer's CloudWatch registry), with `cloudwatch:PutMetricData` on the task role. No sidecar. See [Custom metrics with several tasks](#custom-metrics-with-several-tasks).
5. **Traces, or "which downstream call is slow".** This step needs a sidecar: CloudWatch Application Signals, or an OpenTelemetry collector.
6. **Logs to a destination other than CloudWatch, or filtered before storage.** This step needs a FireLens (Fluent Bit) sidecar.

On a service with one task, a sidecar marked `essential = true` adds a new way to stop the application. Add one only for steps 5 and 6.

These steps assume CloudWatch stores the telemetry. For Grafana (LGTM or Grafana Cloud) or another OTLP backend, read [A backend other than CloudWatch](#a-backend-other-than-cloudwatch).

Two shortcuts that do not work as expected:

- **EMF printed to stdout.** AWS documents agent-free extraction of embedded metric format only for Lambda. For containers, the documented paths are the CloudWatch agent, or the CloudWatch OTLP endpoint (which AWS recommends). Test a metric in a real task before you depend on stdout EMF through `awslogs`.
- **A plain OpenTelemetry exporter pointed at AWS.** The CloudWatch OTLP endpoints (`https://xray.<region>.amazonaws.com/v1/traces`, `https://monitoring.<region>.amazonaws.com/v1/metrics`, `https://logs.<region>.amazonaws.com/v1/logs`) take HTTP only, not gRPC. They accept SigV4-signed requests, which AWS recommends, or a long-lived API key as a bearer token. Most exporters built into an application, such as Spring Boot's, cannot sign with SigV4, and a bearer token is a long-lived secret in every task. Use a collector with the `sigv4auth` extension, or the ADOT agent, which sign with the task role.

> *Sources: [EMF with the CloudWatch agent](https://docs.aws.amazon.com/AmazonCloudWatch/latest/monitoring/CloudWatch_Embedded_Metric_Format_Generation_CloudWatch_Agent.html) · verified 2026-11-16; [CloudWatch OTLP endpoints](https://docs.aws.amazon.com/AmazonCloudWatch/latest/monitoring/CloudWatch-OTLPEndpoint.html) · verified 2026-11-21; [Container Insights](https://docs.aws.amazon.com/AmazonECS/latest/developerguide/cloudwatch-container-insights.html) · verified 2026-11-21; [ClusterSetting](https://docs.aws.amazon.com/AmazonECS/latest/APIReference/API_ClusterSetting.html) · verified 2026-11-21*

Do not add the X-Ray daemon as a sidecar, or the X-Ray SDK to new code. Both have been in maintenance mode since 2026-02-25. Use OpenTelemetry.

> *Source: [X-Ray SDK and daemon timeline](https://docs.aws.amazon.com/xray/latest/devguide/xray-sdk-daemon-timeline.html) · verified 2026-11-16*

## Custom metrics with several tasks

When every task publishes to the same metric, CloudWatch combines their data points in each period:

- **No task dimension.** Each distinct set of dimensions is a separate billed metric, and every deployment starts new task IDs. A task-ID dimension adds a new set of metrics with each deployment. Use Container Insights with enhanced observability for the per-task view.
- **Statistics.** Sum for counters. Maximum for pool waits, heap and job durations. For an average latency, divide the timer's sum by its count in metric math: the Average statistic weights a quiet task like a busy one.
- **Percentiles.** Percentiles computed inside each task cannot be combined. Use the load balancer's `TargetResponseTime` percentiles, which cover all targets.
- **A task that stops publishing.** Alarm on the `SampleCount` of a gauge over 5 minutes, below about 5 × `desired_count` minus a margin. A task's publishes do not line up with the minute, so a 1-minute count flaps.
- **Publish an allow-list.** A metrics library registers many meters by default (JVM, HTTP per route, connection pools), and each tag set is a billed metric. Deny by default, and publish only what an alarm, a dashboard or a known question needs. Tag only with fixed values: route templates, outcomes, job names, AWS service names. Never with user, patient or request IDs.
- **Dev in windows.** Custom metrics are billed for the hours in which they are published. A switch that turns publishing on in dev only while someone checks it costs only those hours.

## The `awslogs` driver loses logs by default

Since 2025-06-25, a container without `mode` in its `logConfiguration` uses `non-blocking` mode, with a `max-buffer-size` of `10m`. When the buffer is full, new log lines are lost. `blocking` mode keeps every line, but a write to stdout then waits when CloudWatch Logs is slow, and the application can hang and fail its health check.

The `defaultLogDriverMode` account setting changes the default for every container in a Region that does not set `mode`, so a task definition without `mode` can behave differently in two accounts. Choose a mode on purpose, and write it in the task definition:

```hcl
logConfiguration = {
  logDriver = "awslogs"
  options = {
    "awslogs-group"         = aws_cloudwatch_log_group.app.name
    "awslogs-region"        = var.aws_region
    "awslogs-stream-prefix" = "app"
    "mode"                  = "non-blocking"
    "max-buffer-size"       = "25m" # size it from the log rate in a burst
  }
}
```

Put records that must not be lost (an audit trail, for example) in a database, not only in logs.

> *Source: [ECS task definition parameters, logConfiguration](https://docs.aws.amazon.com/AmazonECS/latest/developerguide/task_definition_parameters.html) · verified 2026-11-21*

## Adding a sidecar

### Application Signals (traces and service metrics for Java, Python, .NET, Node.js)

Fargate supports only the sidecar layout. The daemon layout does not run on Fargate. The task uses `awsvpc`.

| Container | `essential` | Role |
| --- | --- | --- |
| `init` (the ADOT auto-instrumentation image) | `false` | Copies the agent into a shared volume, then exits |
| `ecs-cwagent` (CloudWatch agent) | `false` | Receives telemetry and sends it to CloudWatch |
| the application | `true` | `dependsOn = [{ containerName = "init", condition = "SUCCESS" }]`, mounts the shared volume, loads the agent with `JAVA_TOOL_OPTIONS` (or the language's equivalent) |

- `COMPLETE` and `SUCCESS` cannot be set on an essential container. If you mark `init` essential, the task definition is rejected, or the task stops when `init` exits.
- The agent's configuration goes in an SSM parameter, injected through `secrets` as `CW_CONFIG_CONTENT`. Fargate has no host file to mount.
- The **task role** needs `CloudWatchAgentServerPolicy`, plus whatever the application already needs.
- Application Signals needs a one-time enablement in each account. The first enablement creates `AWSServiceRoleForCloudWatchApplicationSignals`. Where a platform team owns the account, ask them for it.
- The Java agent must be version 1.32.2 or later. Check that the agent release supports the application's Java version.

> *Sources: [Application Signals on ECS](https://docs.aws.amazon.com/AmazonCloudWatch/latest/monitoring/CloudWatch-Application-Signals-Enable-ECSMain.html) · verified 2026-11-16; [ECS sidecar layout](https://docs.aws.amazon.com/AmazonCloudWatch/latest/monitoring/CloudWatch-Application-Signals-ECS-Sidecar.html) · verified 2026-11-16*

### Rules for any sidecar

- **Start and stop order.** Shutdown reverses `dependsOn`. Make the application depend on the collector (`condition = "START"`), so the collector starts first and stops last, after the application flushes its telemetry. `HEALTHY` needs a container health check, and most collector images have no shell for a `CMD-SHELL` check.
- **Memory.** Without a container-level `memory`, a JVM sizes its heap from the whole task's memory, and the sidecar's use then pushes the task into an out-of-memory stop. Give the application container `memory = task_memory - sidecar_memory`, and give the sidecar its own `memory`.
- **Its own logs.** Give the sidecar a `logConfiguration` with its own stream prefix. A non-essential collector that crashes stops sending telemetry without stopping the task, so alarm on missing data, not only on bad values.
- **Network.** The sidecar needs outbound 443 to the CloudWatch, X-Ray and Logs endpoints, through the same NAT or VPC endpoints as the application.
- **Image.** Pull from `public.ecr.aws` or a private ECR copy, pinned to a version, not `latest`.
- **One instrumentation.** A tracing library in the code and an auto-instrumentation agent both create spans for the same calls. Use one of them.

> *Source: [ContainerDependency](https://docs.aws.amazon.com/AmazonECS/latest/APIReference/API_ContainerDependency.html) · verified 2026-11-16*

### FireLens

- Use it only to send logs somewhere other than CloudWatch, to several places, or to filter or redact before storage.
- When a plugin's `Mem_Buf_Limit` is exceeded, Fluent Bit pauses the input and new records are lost. For production volume, use filesystem buffering.
- Do not allow inbound traffic on port 24224 in the task's security group.

> *Source: [FireLens buffer limits](https://docs.aws.amazon.com/AmazonECS/latest/developerguide/firelens-docker-buffer-limit.html) · verified 2026-11-16*

## A backend other than CloudWatch

For Grafana (Loki, Tempo and Mimir, or Grafana Cloud) or another OTLP vendor:

- **Dashboards only.** If people want Grafana dashboards but no new store, keep CloudWatch as the store and add Grafana with the CloudWatch data source. No sidecar, and no second copy of regulated data.
- **Where the collector runs.** Fargate does not support the `DAEMON` scheduling strategy. Run the collector (Grafana Alloy or an OpenTelemetry Collector) as a sidecar in each task, or as a gateway service that the tasks send to. A gateway is worth it once many services report, or for tail sampling, which needs every span of a trace at the same collector.
- **Direct export works, but use a collector for regulated data.** These backends take OTLP over HTTP with a token in a header, not SigV4, so the application can export without a collector. A collector keeps the redaction rules and the backend token in one container instead of in each application, and it buffers through a backend outage.
- **Keep the rollback alarm in CloudWatch.** The service's `alarms` block reads only CloudWatch alarms, and works only with the rolling update (`ECS`) deployment controller. A Grafana alert cannot stop or roll back a deployment.
- **Keep `awslogs` on the application container, with short retention.** A missing secret key, a failed migration or a JVM out-of-memory stop happens before the agent and the collector run, and a crashed non-essential collector drops telemetry without stopping the task. Send the full logs over OTLP through the same collector, instead of adding a FireLens sidecar. Loki takes OTLP logs at `/otlp`. Before Loki 3.0 it rejects them unless `allow_structured_metadata` is `true`.
- **Regulated data leaving AWS.** A SaaS backend needs the vendor's BAA (or what your compliance program requires), and outbound access through the network owner's NAT. A self-hosted backend's object storage holds the same data as the database and needs the same controls.

> *Sources: [ECS service parameters, `schedulingStrategy`](https://docs.aws.amazon.com/AmazonECS/latest/developerguide/service_definition_parameters.html) · verified 2026-11-16; [Alarm-based rollback](https://docs.aws.amazon.com/AmazonECS/latest/developerguide/deployment-alarm-failure.html) · verified 2026-11-16; [Loki OTLP ingestion](https://grafana.com/docs/loki/latest/send-data/otel/) · verified 2026-11-16; [Grafana Cloud OTLP endpoint](https://grafana.com/docs/grafana-cloud/send-data/otlp/send-data-otlp/) · verified 2026-11-16*

## Telemetry and regulated data

Traces and their attributes are a second copy of what the application handles, with their own retention and their own readers. Before you turn tracing on for an application that handles PHI or other regulated data:

- Check that the tracing service is on the compliance program's eligible-services list.
- Drop or redact URL query strings, exception messages and request bodies in the agent or collector configuration.
- Keep the agent's SQL statement sanitizer on. Do not capture bind parameters.
- Set retention on the trace and span log groups.
- Give access to trace data only to people who may read the underlying records.

### A backstop for regulated data in logs

The rule is that application logs hold no regulated data. A CloudWatch Logs data protection policy on the log group catches what slips through. It is a backstop, not a replacement for the rule: it misses free-text names, and flags lines that hold none.

- **There is no audit-only mode.** The policy needs an `Audit` statement and a `Deidentify` statement, and their data identifiers must match exactly. So a policy masks every match from its first apply, for anyone without `logs:Unmask`.
- **Findings are counted** in the `AWS/Logs` metric `LogEventsWithFindings`, one per log event that has a match. Alarm on it, but only after a trial.
- **Choose only the identifiers that fit the logs.** Loose ones, such as the full-name identifier, flag many lines that hold no regulated data. Test data in dev shows only that the policy is wired up: write one made-up line, and check that it is masked and counted. The false-positive rate shows only on real data. In prod, run the policy for a week with the alarm off, have someone who may read the records review the findings with `logs:Unmask`, and drop the identifiers that match mostly by mistake. Then turn the alarm on.
- **The deployer needs** `logs:PutDataProtectionPolicy`, `GetDataProtectionPolicy` and `DeleteDataProtectionPolicy` on the log group. Scanning is billed per GB, so read the log group's `IncomingBytes` first.

> *Sources: [Mask sensitive log data](https://docs.aws.amazon.com/AmazonCloudWatch/latest/logs/mask-sensitive-log-data-start.html) · verified 2026-11-21; [Audit findings](https://docs.aws.amazon.com/AmazonCloudWatch/latest/logs/mask-sensitive-log-data-audit-findings.html) · verified 2026-11-21*
