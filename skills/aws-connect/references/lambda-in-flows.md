# Lambda functions invoked from a flow

## Limits

| Limit | Value |
| --- | --- |
| Synchronous timeout in the block | 8 seconds maximum (60 seconds for asynchronous mode) |
| Retries | On an error or a throttle, Connect retries up to 3 times within the timeout, then takes the Error branch |
| A chain of functions in one contact | 20 seconds in total |
| Response size | Less than 64 KB of UTF-8 data |
| `STRING_MAP` response | A flat object of string keys and values, with values of only alphanumeric characters, dash and underscore. A flow cannot reference an array |
| `JSON` response | Any valid JSON, including nested objects |

> *Sources: [Invoke Lambda function block](https://docs.aws.amazon.com/connect/latest/adminguide/invoke-lambda-function-block.html) · verified 2026-11-15; [Grant Connect access to Lambda functions](https://docs.aws.amazon.com/connect/latest/adminguide/connect-lambda-functions.html) · verified 2026-11-15*

A retry inside the 8 seconds runs the handler again. So writes the handler makes must be idempotent, for example an upsert keyed by contact ID with a counter incremented in SQL, not read and written back.

## Wiring in Terraform

```hcl
resource "aws_lambda_permission" "connect" {
  statement_id  = "AllowConnectInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.verify.function_name
  principal     = "connect.amazonaws.com"
  source_arn    = local.instance_arn # arn:<partition>:connect:<region>:<account>:instance/<id>
}

resource "aws_connect_lambda_function_association" "verify" {
  instance_id  = var.instance_id
  function_arn = aws_lambda_function.verify.arn
}

resource "aws_connect_contact_flow_module" "verification" {
  # ...
  depends_on = [aws_connect_lambda_function_association.verify]
}
```

The console adds the permission when you add a function there. Terraform does not, so both resources are needed.

In the flow block, set `ResponseValidation = { ResponseType = "STRING_MAP" }` for a status reply, and `InvocationTimeLimitSeconds` to the value you sized the function against.

## Timeouts

Budget from the outside in:

1. Block timeout: 8 seconds.
2. Function timeout: about 6 seconds. The gap covers invocation overhead.
3. Inside the function: connect timeout and statement timeout (for example 2 seconds each), and an SDK timeout on every AWS call.

Do slow setup (secret fetch, TLS handshake, connection pool) in the INIT phase, at module scope. In Node.js ESM, use a top-level `await`. INIT has its own budget and does not count against the invocation timeout. Catch an INIT failure, and retry it once in the handler. Otherwise a transient failure at INIT breaks every invocation in that execution environment.

## What the function returns and logs

The return value goes into contact attributes, then into the contact record (kept 24 months from contact start), into flow logs, and to the agent's screen. So:

- Return status codes only. Fetch patient or customer data in the agent application, by contact ID.
- Do not log the event. Log the outcome and the shape of the input (`dobLength`, `parsed: false`), not the values.
- Return the same failure status for "no such caller", "wrong answer" and "too many attempts". Then a caller cannot use the IVR to find out which records exist.

> *Source: [Amazon Connect feature specifications](https://docs.aws.amazon.com/connect/latest/adminguide/feature-limits.html) (contact records) · verified 2026-11-15*

## Metrics from the status

One JSON log line per invocation with a `reason` field, and one `aws_cloudwatch_log_metric_filter` per value, give a count for each outcome with no code change. Before you rely on the metrics, test the pattern against a real log line: `aws logs test-metric-filter --filter-pattern '{ $.reason = "OK" }' --log-event-messages '<copied line>'`. In the default text log format, the runtime puts a timestamp, request ID and level in front of the JSON. In the JSON log format (`logging_config { log_format = "JSON" }`), a string argument to `console.log` stays a string in `message`. Each of these changes what the pattern has to match.

> *Source: [Node.js Lambda logging](https://docs.aws.amazon.com/lambda/latest/dg/nodejs-logging.html) · verified 2026-11-15*

Alarm on the failure status (database or runtime errors that the handler caught), on Lambda `Errors` (INIT failures and timeouts only, because the handler never throws), and on `Throttles`. Set `treat_missing_data = "notBreaching"`, because a contact center has no traffic outside business hours.

## Databases

- Each warm execution environment holds its own connection. Without RDS Proxy, `reserved_concurrent_executions` caps the connections the function can open. Size it against `max_connections`, minus what other applications on the database use.
- Give the function its own database user with only the grants it needs, its own secret, and its own execution role. A role or credential borrowed from another application gives this function that application's access.
- Verify TLS against the RDS CA bundle with `rejectUnauthorized: true`, and connect to the RDS endpoint name. A vanity CNAME fails the hostname check. Ship the CA bundle next to the bundled code.
- Add an `error` listener to a `pg` pool. Without one, an idle connection that the server drops crashes the process.

## Packaging

If Terraform zips a build directory with `data "archive_file"`, a source change that was not rebuilt makes no Terraform diff and ships nothing. Build in CI, then plan from that build. With esbuild, bundling CommonJS `pg` into ESM needs a `createRequire` banner, or the function fails at INIT with `Dynamic require of "events" is not supported`.
