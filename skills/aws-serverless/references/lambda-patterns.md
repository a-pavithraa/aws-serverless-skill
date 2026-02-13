# Lambda Patterns Reference

## Cold Starts: The Real Problem

### Cold Start Happens Per Concurrent Execution
**Common misconception**: "It's only the first request, then the next million are fast."

**Reality**: Cold start happens once **for each concurrent execution**. If 10 requests arrive simultaneously, you get 10 cold starts.

```
Traffic pattern matters:
- Sequential requests (1 at a time) → 1 cold start total
- Burst of 100 concurrent requests → up to 100 cold starts
- Bursty traffic (food ordering at noon, Black Friday) → worst case
```

### Idle Timeout Behavior
AWS terminates idle functions after **45-60 minutes of inactivity**. However:
- Functions can be terminated earlier during high resource contention
- Higher memory functions (1536MB+) may be terminated earlier
- **Don't build business logic assuming specific idle timeouts**

### Cold Start Mitigation

**Pre-warming** (only effective at low concurrency):
```hcl
# Schedule Lambda to invoke itself before expected traffic spike
resource "aws_cloudwatch_event_rule" "warmup" {
  name                = "prewarm-api"
  schedule_expression = "cron(58 11 * * ? *)"  # 11:58 AM before lunch rush
}
```

**Provisioned Concurrency** (for critical paths):
```hcl
resource "aws_lambda_provisioned_concurrency_config" "api" {
  function_name                     = aws_lambda_function.api.function_name
  provisioned_concurrent_executions = 5
  qualifier                         = aws_lambda_alias.live.name
}
```

**Cost warning**: Provisioned concurrency has significant uptime costs:
- 128MB function: $1.40/month per unit
- 1GB function: $11.16/month per unit  
- 10GB function: $111.61/month per unit

---

## Lambda Layers: Deployment Optimization, NOT Package Manager

### Common Misconception
"Use Lambda Layers to share code between functions like NPM packages."

### Why Layers Are Poor Package Managers
1. **No semantic versioning** - only incremental version numbers
2. **Breaks local testing** - you still need dependencies locally
3. **Doesn't work with statically compiled languages**
4. **Breaks static analyzers** - vulnerability scanners can't see layer contents
5. **Max 5 layers per function**
6. **Doesn't integrate with npm/pip ecosystem**

### Correct Use: Deployment Optimization
Layers speed up deployments by separating rarely-changed dependencies from frequently-changed code:

```hcl
# Layer contains node_modules (changes rarely)
resource "aws_lambda_layer_version" "dependencies" {
  filename            = "dependencies.zip"
  layer_name          = "${local.name_prefix}-deps"
  compatible_runtimes = ["nodejs18.x"]
  
  # Only redeploy when package-lock.json changes
  source_code_hash = filebase64sha256("package-lock.json")
}

# Function contains only your code (changes often)
resource "aws_lambda_function" "api" {
  filename         = "function.zip"  # Small, just your code
  function_name    = "${local.name_prefix}-api"
  handler          = "index.handler"
  runtime          = "nodejs18.x"
  layers           = [aws_lambda_layer_version.dependencies.arn]
  source_code_hash = filebase64sha256("function.zip")
}
```

### Good Uses for Layers
- **Binary dependencies**: FFMPEG, ImageMagick, GeoIP databases
- **Custom runtimes**: LLRT, Bun
- **AWS-provided layers**: Lambda Powertools, AWS SDK extensions
- **Deployment optimization**: As described above

### Terraform Pattern for Layer-Based Deployment
```hcl
locals {
  deps_hash = filebase64sha256("${path.module}/package-lock.json")
}

# Check if dependencies changed
data "aws_lambda_layer_version" "existing" {
  layer_name = "${local.name_prefix}-deps"
  count      = can(data.aws_lambda_layer_version.existing[0]) ? 1 : 0
}

resource "aws_lambda_layer_version" "dependencies" {
  # Only create new version if hash changed
  filename            = data.archive_file.deps.output_path
  layer_name          = "${local.name_prefix}-deps"
  compatible_runtimes = ["python3.11"]
  source_code_hash    = local.deps_hash
}
```

---

## Timeouts: Context-Aware Strategy

### Key Timeout Limits
| Service | Max Timeout |
|---------|-------------|
| API Gateway integration | 29 seconds (hard limit) |
| Lambda maximum | 15 minutes |
| EventBridge API Destinations | 5 seconds |
| Step Functions external endpoint | 1 minute |

### The Problem with Fixed Timeouts
```python
# BAD: Fixed timeout doesn't account for cold start or earlier operations
response = requests.get(url, timeout=5)
```

### Context-Aware Timeout Pattern
```python
def handler(event, context):
    # Reserve 500ms for error handling/cleanup
    time_remaining = context.get_remaining_time_in_millis() - 500
    
    # If we've already used 3 seconds of a 6 second function
    # we only have 2.5 seconds left for this HTTP call
    timeout_seconds = time_remaining / 1000
    
    try:
        response = requests.get(url, timeout=timeout_seconds)
    except requests.Timeout:
        logger.error("Downstream timeout", extra={
            "time_allowed": timeout_seconds,
            "correlation_id": event.get("correlation_id")
        })
        return {
            "statusCode": 504,
            "body": json.dumps({
                "errorCode": 10021,
                "message": "Downstream service timeout",
                "requestId": context.aws_request_id
            })
        }
```

### User-Facing API Timeout Recommendation
For user-facing APIs: **Set Lambda timeout to 3 seconds or less**

If you need longer operations:
```
Client → API Gateway → Lambda (returns immediately)
                           ↓
                     Start Step Function
                           ↓
                     Long-running workflow
                           ↓
                     Notify client (webhook/websocket)
```

---

## Async Invocations: Throttling Behavior

### Critical Insight
**Async invocations NEVER fail due to throttling.**

When you invoke Lambda asynchronously (SNS, EventBridge, or `InvocationType: Event`):
1. Request goes to internal queue (always succeeds)
2. Internal poller invokes function synchronously
3. If throttled, request returns to queue
4. **Retries continue for up to 6 hours**

### Implications
```python
# This WILL succeed even if function has 0 reserved concurrency
lambda_client.invoke(
    FunctionName='my-function',
    InvocationType='Event',  # Async
    Payload=json.dumps(event)
)
# Returns 202 Accepted, NOT throttling error
```

### When This Matters
- SNS → Lambda: Messages won't be lost due to throttling
- EventBridge → Lambda: Events retry for 6 hours
- Async Lambda-to-Lambda: Safe for fire-and-forget patterns

### Failure Handling: Use Destinations, Not Lambda DLQ

> Source: [Implementing error handling patterns](https://aws.amazon.com/blogs/compute/implementing-aws-lambda-error-handling-patterns/)

Lambda Destinations replace the legacy `dead_letter_config`:

| | Legacy DLQ (`dead_letter_config`) | Destinations (`destination_config`) |
|--|---|---|
| **Targets** | SQS, SNS only | SQS, SNS, Lambda, EventBridge |
| **Payload** | Original event only | Original event + error + stack trace + request/response metadata |
| **Invocation types** | Async only | Async + stream-based (event source mappings) |
| **Success routing** | Not supported | `on_success` routes to any target |

EventBridge is the preferred failure target — it can fan out to multiple consumers (alerting, auto-remediation, archival) without coupling the Lambda to specific downstream queues.

```hcl
resource "aws_lambda_function_event_invoke_config" "async" {
  function_name = aws_lambda_function.processor.function_name

  maximum_event_age_in_seconds = 3600
  maximum_retry_attempts       = 2

  destination_config {
    on_failure {
      destination = aws_sns_topic.async_failures.arn
    }
  }
}

# Stream-based invocations (SQS, Kinesis, DynamoDB Streams) also support on_failure destinations
resource "aws_lambda_event_source_mapping" "streams" {
  # ...
  destination_config {
    on_failure {
      destination = aws_sns_topic.stream_failures.arn
    }
  }
}
```

Note: SQS queue-level DLQs (via `redrive_policy`) are a separate concept and still correct for SQS message processing failures.

---

## Concurrency & Scaling

### Reserved vs Provisioned Concurrency
```hcl
# Reserved: Guarantees capacity, still has cold starts
resource "aws_lambda_function" "critical" {
  reserved_concurrent_executions = 100
}

# Provisioned: Pre-warmed, no cold starts, costs money
resource "aws_lambda_provisioned_concurrency_config" "critical" {
  provisioned_concurrent_executions = 10
  # Costs ~$111/month for 10GB memory
}
```

---

## Function Design Patterns

### Single-Purpose Functions
**Use when**: Functions have different dependencies, different scaling needs

```
✅ GET /users/{id}     → get-user function
✅ POST /users         → create-user function  
✅ DELETE /users/{id}  → delete-user function
```

### Lambdalith (Single Function, Multiple Routes)
**Use when**: All routes share dependencies, simpler deployment preferred

```python
# Using Lambda Powertools Event Handler
from aws_lambda_powertools.event_handler import APIGatewayRestResolver

app = APIGatewayRestResolver()

@app.get("/users/<user_id>")
def get_user(user_id: str):
    return {"user_id": user_id}

@app.post("/users")
def create_user():
    return {"status": "created"}

def handler(event, context):
    return app.resolve(event, context)
```

**Trade-offs**:
- ✅ Simpler deployment and local testing
- ✅ Potentially fewer cold starts at low traffic
- ❌ All routes penalized by heaviest dependency
- ❌ Scales slower (one function vs many)

### Lambda-to-Lambda: Avoid Synchronous Calls
```python
# BAD: Synchronous Lambda-to-Lambda
response = lambda_client.invoke(
    FunctionName='downstream',
    InvocationType='RequestResponse'  # Waits for response
)
# You're paying for BOTH functions to run

# BETTER: Use SQS, SNS, or Step Functions
sqs.send_message(QueueUrl=queue_url, MessageBody=json.dumps(payload))
```

