# Lambda Patterns Reference

## Cold Starts: The Real Problem

### Cold Start Happens Per Concurrent Execution

Cold start happens once **per concurrent execution slot**, not once globally. 100 simultaneous requests = up to 100 cold starts. Functions are terminated after ~45–60 minutes idle (can be earlier under resource pressure) — don't build logic that assumes a specific idle duration.

### Cold Start Mitigation

**Pre-warming** — only effective at very low concurrency; useless during burst traffic since the warm instances are outnumbered immediately. For predictable peaks, use scheduled Provisioned Concurrency instead — see Concurrency & Scaling section.

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

### ARM Graviton2: Cheapest Cold Start Win

One `architectures` field change. ~20% cheaper per GB-second, generally equal or faster cold starts. No code changes required for interpreted runtimes (Python, Node.js, Ruby). Compiled runtimes (Go, Rust) need a cross-compilation step.

```hcl
resource "aws_lambda_function" "api" {
  architectures = ["arm64"]  # Graviton2 — default is ["x86_64"]
  # Everything else unchanged
}
```

**Exception**: GraalVM native images built for x86 run slower on arm64 — rebuild for `linux/arm64` target or stay on x86 for GraalVM.

### Runtime Cold Start Characteristics

Absolute cold start numbers are too SDK-version and payload-sensitive to be reliable — use power tuning on your actual function. The relative ordering and behavioral characteristics below are stable:

| Tier | Runtimes | Behavior |
|---|---|---|
| Fastest | Rust, Go, .NET 8 NativeAOT | Compiled to native binary; no JIT; sub-100ms in practice |
| Interpreted | Python, Node.js, Ruby | Consistent; no JIT variance; scales with import size |
| JVM (mitigated) | Java + SnapStart, GraalVM native | Stable after snapshot restore; see SnapStart section |
| Slowest without mitigation | Java (JVM, no SnapStart) | 2–5 s+; OOM at 128 MB; C2 JIT rarely engages in Lambda's sandbox |

Key characteristics:
- **Rust**: Sub-50ms in optimized production functions; the limiting factor is SDK/dependency initialization, not the runtime itself
- **Go**: Native binary, stable from first invocation; managed runtime (no longer requires a custom runtime bootstrap)
- **.NET 8 NativeAOT**: Now in the fastest tier — a large regression from .NET 3.1/6 which had 500ms+ cold starts; requires `PublishAot=true` at build time
- **Python / Node.js / Ruby**: Cold start scales with the number and size of imports initialized at module level — keep the global scope lean
- **Java (JVM)**: Needs 1–3k warm invocations for C1 JIT; use SnapStart instead of trying to optimize JVM cold start manually
- **GraalVM native**: Stable warm performance comparable to Go; needs 256 MB+; perform worse on arm64 unless rebuilt for that target

### SnapStart (Java 11+, Python 3.12+, .NET 8+)

> *Source: [AWS Lambda SnapStart](https://docs.aws.amazon.com/lambda/latest/dg/snapstart.html) · verified 2026-02-19*

Snapshots the fully initialized execution environment after the init phase and restores it on cold start. Cuts Java cold start from 3–10 s to typically under 1 s — without provisioned concurrency costs.

```hcl
resource "aws_lambda_function" "api" {
  runtime    = "java21"
  publish    = true  # Required — SnapStart only works on published versions, not $LATEST

  snap_start {
    apply_on = "PublishedVersions"
  }
}

resource "aws_lambda_alias" "live" {
  name             = "live"
  function_name    = aws_lambda_function.api.function_name
  function_version = aws_lambda_function.api.version  # Point to published version
}

# Use the alias ARN in event source mappings and API Gateway integrations
```

**Caveats that cause subtle bugs:**
- Init code must not seed randomness or capture wall-clock time — the snapshot is replayed across many instances, so `new Random()` in a static initializer produces the same seed on every restore. Initialize random sources lazily inside the handler instead.
- Cannot combine with `provisioned_concurrent_executions` — they're mutually exclusive
- Event source mappings and API Gateway integrations must target the alias ARN, not the function ARN — `$LATEST` bypasses the snapshot

---

## Lambda Layers: Deployment Optimization, NOT Package Manager

Don't use layers to share business logic or application dependencies between functions. Layers have no semantic versioning, break local dev (they're not installed in your environment), blind vulnerability scanners, and have a hard limit of 5 per function.

**Correct use — deployment optimization** by separating rarely-changed dependencies from frequently-changed code:

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
**Async invocations are not immediately rejected due to throttling — they are queued and retried.**

When you invoke Lambda asynchronously (SNS, EventBridge, or `InvocationType: Event`):
1. Request goes to internal queue (always succeeds at intake)
2. Internal poller invokes function synchronously
3. If throttled, request returns to queue
4. **Retries continue for up to 6 hours** — but the event *will* fail if the retry window expires or maximum attempts are exhausted without a successful execution

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

### Scheduled Provisioned Concurrency for Predictable Peaks

Always-on PC is expensive. For predictable peaks (lunch rush, daily batch, market open), use Application Auto Scaling scheduled actions to activate PC only during the window.

**Sizing formula**: `concurrent_executions = avg_requests_per_second × avg_duration_seconds × 1.1` (10% buffer)

**Three non-obvious requirements:**

1. **Provision the entire synchronous call chain** — if your entry function calls three others synchronously, provisioning only the entry point does nothing; the unprovisioned callees cold-start and negate the benefit. Every function in the chain needs its own scheduled PC.

2. **Schedule 5–10 minutes before the peak** — Lambda needs time to prepare environments. Scheduling at the exact peak start means the first wave of requests still cold-starts.

3. **Scale-in requires both MinCapacity=0 AND MaxCapacity=0** — setting only MinCapacity=0 leaves MaxCapacity in place and doesn't fully release provisioned concurrency.

```hcl
resource "aws_lambda_alias" "live" {
  name             = "live"
  function_name    = aws_lambda_function.api.function_name
  function_version = aws_lambda_function.api.version
}

# Register the alias as a scalable target
resource "aws_appautoscaling_target" "lambda_pc" {
  service_namespace  = "lambda"
  resource_id        = "function:${aws_lambda_function.api.function_name}:${aws_lambda_alias.live.name}"
  scalable_dimension = "lambda:function:ProvisionedConcurrency"
  min_capacity       = 0
  max_capacity       = 250
}

# Scale OUT 10 minutes before peak
resource "aws_appautoscaling_scheduled_action" "scale_out" {
  name               = "scale-out"
  service_namespace  = aws_appautoscaling_target.lambda_pc.service_namespace
  resource_id        = aws_appautoscaling_target.lambda_pc.resource_id
  scalable_dimension = aws_appautoscaling_target.lambda_pc.scalable_dimension
  schedule           = "cron(50 11 * * ? *)"  # 11:50 UTC — peak starts at noon

  scalable_target_action {
    min_capacity = 250
    max_capacity = 250
  }
}

# Scale IN after peak — both min AND max must be 0 to fully release
resource "aws_appautoscaling_scheduled_action" "scale_in" {
  name               = "scale-in"
  service_namespace  = aws_appautoscaling_target.lambda_pc.service_namespace
  resource_id        = aws_appautoscaling_target.lambda_pc.resource_id
  scalable_dimension = aws_appautoscaling_target.lambda_pc.scalable_dimension
  schedule           = "cron(15 13 * * ? *)"

  scalable_target_action {
    min_capacity = 0
    max_capacity = 0  # Required — omitting this does not release PC
  }
}
```

---

## Memory Sizing: AWS Lambda Power Tuning

> Tool: [aws-lambda-power-tuning](https://github.com/alexcasalboni/aws-lambda-power-tuning) — Alex Casalboni

Memory and CPU are linked: Lambda allocates CPU proportionally to memory. At **1769 MB = exactly 1 vCPU**. Below that, your function runs on a fraction of a core. Above 1769 MB you get more than 1 vCPU, but only multi-threaded code benefits.

**Before running the tool, classify the function:**

| Type | Signal | Memory expectation |
|---|---|---|
| I/O-bound | Mostly waiting on DynamoDB/HTTP/SQS | 128–512 MB; more memory won't reduce duration |
| CPU-bound | JSON parsing, image resizing, compression, crypto | More memory = faster = often cheaper (duration drops faster than price rises) |
| Memory-bound | Large in-memory datasets, caches | Size to fit working set; start at 512 MB |

Don't guess for CPU-bound functions — a function that drops from 3000 ms at 128 MB to 300 ms at 1769 MB costs 14% less despite 14× the memory price.

### Deploy Power Tuning (once per account/region)

```bash
# Deploy via SAR — takes ~2 minutes
aws serverlessrepo create-cloud-formation-change-set \
  --application-id arn:aws:serverlessrepo:us-east-1:451282441545:applications/aws-lambda-power-tuning \
  --semantic-version 4.3.6 \
  --stack-name lambda-power-tuning \
  --capabilities CAPABILITY_IAM \
  --region us-east-1

aws cloudformation execute-change-set \
  --change-set-name $(aws cloudformation describe-change-set \
    --stack-name lambda-power-tuning \
    --query 'ChangeSetId' --output text) \
  --stack-name lambda-power-tuning
```

### Run a Tuning Job

```bash
STATE_MACHINE_ARN=$(aws cloudformation describe-stacks \
  --stack-name lambda-power-tuning \
  --query "Stacks[0].Outputs[?OutputKey=='StateMachineARN'].OutputValue" \
  --output text)

aws stepfunctions start-execution \
  --state-machine-arn "$STATE_MACHINE_ARN" \
  --input '{
    "lambdaARN": "arn:aws:lambda:us-east-1:123456789012:function:my-function",
    "powerValues": [128, 256, 512, 1024, 1769, 3008],
    "num": 50,
    "payload": "<paste representative prod-like payload here>",
    "parallelInvocation": true,
    "strategy": "balanced"
  }'
```

**Parameter decisions:**

| Parameter | Guidance |
|---|---|
| `powerValues` | Always include 1769 (1 vCPU boundary) and 3008 (2 vCPU). Default sweep: `[128, 256, 512, 1024, 1769, 3008]` |
| `num` | 50 for stable p99 signal; 10 for a quick directional check |
| `payload` | Must be prod-representative — a tiny synthetic payload gives wrong results for memory-bound functions |
| `parallelInvocation` | `true` unless the function has side effects that can't safely run concurrently |
| `strategy` | `cost` for batch/async workers; `speed` for user-facing APIs; `balanced` as default |

### Interpret the Output

The execution output contains a `visualization` URL — open it. The interactive chart shows cost and duration at each memory setting. Look for:

- **Elbow point**: where adding memory stops reducing duration proportionally → optimal setting is just past this point
- **Cost inversion**: if the cost curve dips below the starting point at higher memory, you're in CPU-bound territory — higher memory is both faster and cheaper

### Apply the Result in Terraform

```hcl
resource "aws_lambda_function" "api" {
  memory_size = 1024  # From power tuning — was 128
  timeout     = 10
}
```

Re-run tuning after any significant code change — adding a new library, switching JSON parser, or changing algorithm can shift the optimal point by 2–4× memory.

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

### Lambda-to-Lambda: Synchronous Calls

**Lambda is not a stable interface.** Synchronous invocation couples the caller to the callee's function name, region, and account ID. Renaming a function, splitting it, going multi-region, or moving it to another account all require a coordinated caller deploy. For cross-service calls, put a stable interface in front: API Gateway or a Lambda Function URL behind a custom CloudFront domain.

**You pay twice.** The caller is billed for its full duration including idle time spent waiting for the callee. That idle time produces no compute value.

**Concurrency starvation under load.** Caller and callee each hold a concurrency slot simultaneously. Under a traffic spike, callers exhaust the account limit while waiting for a throttled callee — the entire chain stalls. Raising concurrency limits defers this, it doesn't prevent it.

**What to use instead depends on whether you need a response:**

| Scenario | Replace with |
|---|---|
| Don't need a response — offload work | Async invocation (`InvocationType="Event"`) — caller slot released immediately |
| Need a response — multi-step orchestration | Step Functions — see `event-driven.md` |
| Need a response — cross-service call | Stable HTTP interface (API Gateway or Function URL + CloudFront) |

```python
# Fire-and-forget: caller slot freed on 202, not on callee completion
lambda_client.invoke(
    FunctionName="downstream",
    InvocationType="Event",
    Payload=json.dumps(payload).encode(),
)
# Always pair with on_failure destination on the callee — see Async Invocations section
```

---

## Invocation Payload Limits

These are hard limits — no configuration changes them. The only escape is S3 offloading.

| Invocation type | Request limit | Response limit |
|---|---|---|
| Synchronous (`RequestResponse`) | 6 MB | 6 MB |
| Asynchronous (`Event`) | 1 MB | — |
| SQS message body | 256 KB | — |
| Kinesis record | 1 MB | — |
| EventBridge event | 256 KB | — |

> *Source: [AWS Lambda quotas](https://docs.aws.amazon.com/lambda/latest/dg/gettingstarted-limits.html) · verified 2026-02-19*

**The trap**: Direct async Lambda invocations accept up to 1 MB, but SNS, EventBridge, and SQS messages that *trigger* Lambda still have their own 256 KB limits. If you're passing large payloads event-to-event and only test synchronously, you won't hit this during dev — only in production under realistic data.

**S3 claim-check pattern** for oversized payloads:
```python
def invoke_async(function_name: str, payload: dict) -> None:
    body = json.dumps(payload).encode()
    if len(body) > 900_000:  # Stay under 1 MB async limit with margin
        key = f"invocation-payloads/{uuid.uuid4()}.json"
        s3.put_object(Bucket=PAYLOAD_BUCKET, Key=key, Body=body,
                      ServerSideEncryption="aws:kms")
        body = json.dumps({"s3_ref": {"bucket": PAYLOAD_BUCKET, "key": key}}).encode()
    lambda_client.invoke(
        FunctionName=function_name,
        InvocationType="Event",
        Payload=body,
    )
```
The callee checks for `s3_ref` and fetches from S3 before processing. Delete the S3 object after successful processing to avoid accumulation.

---

## Recursive Invocation Loops

A Lambda that triggers itself — directly or through an intermediary — creates an infinite loop that can burn through millions of invocations before anyone notices.

**Common triggers**:
- Lambda processes S3 events and writes output to the **same bucket and prefix** → triggers more events
- Lambda reads from SQS, fails, and **re-queues to the same queue** → retries loop forever
- Lambda publishes to SNS and **subscribes to the same topic** → fans back to itself

**AWS recursive loop detection (2023)**: Lambda detects and stops specific patterns — SQS → Lambda → SQS and SNS → Lambda → SNS — after 16 recursive calls (`RecursiveInvocationTooManyTimesException`). Direct Lambda → Lambda recursion and S3-triggered loops are **not detected**.

**Prevention**:

```hcl
# S3: always use separate buckets or prefix filters
resource "aws_s3_bucket_notification" "trigger" {
  bucket = aws_s3_bucket.input.id  # Input bucket only
  lambda_function {
    lambda_function_arn = aws_lambda_function.processor.arn
    events              = ["s3:ObjectCreated:*"]
    filter_prefix       = "raw/"      # Trigger only on raw/ prefix
  }
}
# Write output to output/ prefix — no notification configured there
```

**Emergency kill switch** — if you detect a runaway loop, set reserved concurrency to 0 immediately. This stops all invocations without deleting the function or its configuration:
```bash
aws lambda put-function-concurrency \
  --function-name my-runaway-function \
  --reserved-concurrent-executions 0
```
