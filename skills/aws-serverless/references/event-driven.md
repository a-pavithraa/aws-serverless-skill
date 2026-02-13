# Event-Driven Architecture Patterns

## Lambda: Transform, Not Transport

Lambda adds cost, cold starts, and a code failure point on every invocation. When Lambda does nothing but move data between services — no parsing, enrichment, validation, or business logic — it is transport. Remove it.

### Transport (Anti-pattern)

```
SNS       → Lambda → SQS          # Lambda just calls sqs.send_message
EventBridge → Lambda → DynamoDB   # Lambda just calls dynamodb.put_item
API Gateway → Lambda → SQS        # Lambda just calls sqs.send_message
S3 event  → Lambda → SNS          # Lambda just calls sns.publish
```

### Transform (Correct use)

```
SQS             → Lambda → DynamoDB    # validate, apply business rules, write canonical form
Kinesis         → Lambda → S3          # aggregate, convert format, partition by date
DynamoDB Streams → Lambda → EventBridge # compute derived state, emit domain events
```

### Native Alternatives for Transport

| Instead of Lambda between… | Use |
|---|---|
| API Gateway → SQS | API Gateway direct integration (VTL) — see Storage-First below |
| EventBridge → DynamoDB / SQS / SNS | EventBridge Pipes with filter + input transformation |
| SNS → SQS | SNS → SQS subscription with filter policy |
| Step Functions state → AWS service | Step Functions SDK integrations (200+ services) |
| One queue → another queue | EventBridge Pipes: source filter → target |

EventBridge Pipes connect a source to a target with optional filtering and input transformation — no Lambda for the common case. Add Lambda only as the enrichment step when transformation requires actual code.

---

## Step Functions vs Single Lambda

> Source: [When to use Step Functions vs. doing it all in a Lambda function](https://theburningmonk.com/2024/03/when-to-use-step-functions-vs-doing-it-all-in-a-lambda-function/) — Yan Cui

### Decision Flow

```
Does the workflow have human approval or wait-for-external-event steps?
  → Yes: Step Functions (Lambda billing during idle is wasteful)

Could execution exceed 15 minutes?
  → Yes: Step Functions Standard

Do you need per-step audit trails for compliance?
  → Yes: Step Functions

Is the workflow a straight sequence with no branching, retries, or waits?
  → Yes: Single Lambda (simpler, cheaper, faster to build)

Does cost or concurrency at very high scale matter?
  → Yes: Single Lambda (no per-transition cost, higher throughput ceiling)

Otherwise: Step Functions — the operational benefits outweigh the cost for
business-critical workflows.
```

Cost note: Step Functions Standard charges $25 per million state transitions on top of compute costs.

### Hybrid Pattern: Nest Express Inside Standard

> Source: [Combine Standard and Express Workflows for fun & profit](https://theburningmonk.com/2023/09/combine-standard-and-express-workflows-for-fun-profit/) — Yan Cui

```
Standard Workflow (outer)
  ├── Wait for payment confirmation  ← long wait, exactly-once critical
  ├── → Express Workflow (inner)     ← many rapid transitions, cost-sensitive
  │     ├── Validate
  │     ├── Enrich
  │     ├── Transform
  │     └── Route
  └── Send confirmation              ← back in Standard
```

### Hybrid Implementation Notes

- Use `arn:aws:states:::states:startExecution.sync:2` (`:2` suffix) to wait for child Express execution and propagate output
- Express has no console history — always configure `logging_configuration` to CloudWatch Logs
- Pass `AWS_STEP_FUNCTIONS_STARTED_BY_EXECUTION_ID` from parent to correlate logs
- Standard IAM role needs `states:StartExecution`, `states:DescribeExecution`, `states:StopExecution` on Express ARN

### Direct Service Integrations (Skip Lambda)

Step Functions integrates directly with 200+ AWS services. Only add Lambda when the response needs complex parsing or business logic.

| Use direct integration | Use Lambda |
|---|---|
| Simple API call with extractable response | Verbose response needing a parser (e.g. Textract) |
| Data extraction via JSONPath or intrinsic functions | Complex transformation logic |
| Calling DynamoDB, S3, SNS, SQS, EventBridge | Custom SDK libraries needed |

For distributed transactions, implement the saga pattern: every action gets an idempotent compensating action, orchestrated via Step Functions Catch/Retry.

---

## Storage-First Pattern (API Gateway → SQS)

> Source: [When to use a Lambda function, and when not?](https://jeromevdl.medium.com/when-to-use-a-lambda-function-and-when-not-9a225e6dd2dd) — Jérôme Van Der Linden

For high-criticality APIs where losing a message is unacceptable, skip Lambda between API Gateway and SQS.

```
Don't:  Client → API Gateway → Lambda → SQS  (failure point before storage)
Do:     Client → API Gateway → SQS (direct)
```

```hcl
resource "aws_api_gateway_integration" "sqs" {
  rest_api_id             = aws_api_gateway_rest_api.main.id
  resource_id             = aws_api_gateway_resource.orders.id
  http_method             = aws_api_gateway_method.post.http_method
  type                    = "AWS"
  integration_http_method = "POST"
  uri                     = "arn:aws:apigateway:${var.region}:sqs:path/${data.aws_caller_identity.current.account_id}/${aws_sqs_queue.orders.name}"

  request_parameters = {
    "integration.request.header.Content-Type" = "'application/x-www-form-urlencoded'"
  }

  request_templates = {
    "application/json" = "Action=SendMessage&MessageBody=$util.urlEncode($input.body)"
  }
}
```

---

## SQS + Lambda: Key Configuration

```hcl
resource "aws_sqs_queue" "main" {
  name                       = "${local.name_prefix}-queue"
  visibility_timeout_seconds = 300  # 6x Lambda timeout
  message_retention_seconds  = 1209600  # 14 days
  receive_wait_time_seconds  = 20  # Long polling

  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.dlq.arn
    maxReceiveCount     = 3
  })
}

resource "aws_lambda_event_source_mapping" "sqs" {
  event_source_arn = aws_sqs_queue.main.arn
  function_name    = aws_lambda_function.processor.arn
  batch_size       = 10

  scaling_config {
    maximum_concurrency = 50
  }

  function_response_types = ["ReportBatchItemFailures"]
}
```

### Partial Batch Failure Handling

```python
def handler(event, context):
    failed_ids = []

    for record in event['Records']:
        try:
            process_message(record)
        except Exception:
            logger.error(f"Failed: {record['messageId']}", exc_info=True)
            failed_ids.append(record['messageId'])

    return {
        'batchItemFailures': [
            {'itemIdentifier': id} for id in failed_ids
        ]
    }
```

Always pair queues with a DLQ alarm — see `monitoring.md` for alarm patterns.

---

## DynamoDB Streams

> Source: [DynamoDB Streams — What you need to know](https://www.alexdebrie.com/bites/dynamodb-streams/) — Alex DeBrie

### DynamoDB Streams vs Kinesis Data Streams

| | DynamoDB Streams | Kinesis Data Streams |
|--|---|---|
| **Max consumers** | **2** (hard limit) | Up to 20 with enhanced fan-out |
| **Cost to enable** | Free | Per-shard-hour charge |
| **Retention** | 24 hours (fixed) | Configurable (1–365 days) |
| **Duplicate records** | None within source region | Possible |

### Critical Gotchas

**1. Hard limit of 2 consumers per stream**
Lambda, KCL workers, EventBridge Pipes, and Global Tables each count. Exceeding 2 requires routing through Kinesis Data Streams.

**2. Errors block stream progress — unlike SQS**
Unhandled errors retry the shard until records expire (24 hours). Always implement `ReportBatchItemFailures` and idempotency.

**3. Cap concurrency when syncing to a relational database**
Set `reserved_concurrent_executions` on the Lambda consumer to prevent overwhelming the RDS connection pool.

**4. `stream_view_type` is immutable post-creation**
Cannot be changed without recreating the stream (risks data loss). Default to `NEW_AND_OLD_IMAGES`.

**5. TTL deletions are distinguishable**
TTL deletes emit `REMOVE` with `userIdentity.type = "Service"`. Filter these if your processor should only react to application-initiated deletes.

**6. Streams do not consume table RCU/WCU**

---

## Idempotency

For event-driven consumers, use Lambda Powertools idempotency — see `lambda-powertools.md`. Use `event_key_jmespath` to scope the idempotency key (e.g., `"body.order_id"`).

---

## Service Selection

```
Need ordering guarantee?
  → Yes: Kinesis or SQS FIFO
  → No: Continue

Multiple consumers need same event?
  → Yes: SNS fan-out or EventBridge
  → No: SQS

Need to react to DB changes?
  → Yes: DynamoDB Streams
  → No: Continue

Complex multi-step workflow?
  → No: Direct Lambda invocation or SQS
  → Yes: Step Functions — which type?
      Exactly-once + long-running (>5 min) + low frequency?
        → Standard Workflow
      High-throughput + many transitions + ≤5 min?
        → Express Workflow
      Both?
        → Hybrid: Standard outer + Express inner
```
