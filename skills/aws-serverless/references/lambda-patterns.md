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
- **Go**: Native binary, stable from first invocation; managed runtime since 2023 (no longer requires custom runtime)
- **.NET 8 NativeAOT**: Now in the fastest tier — a large regression from .NET 3.1/6 which had 500ms+ cold starts; requires `PublishAot=true` at build time
- **Python / Node.js / Ruby**: Cold start scales with the number and size of imports initialized at module level — keep the global scope lean
- **Java (JVM)**: Needs 1–3k warm invocations for C1 JIT; use SnapStart instead of trying to optimize JVM cold start manually
- **GraalVM native**: Stable warm performance comparable to Go; needs 256 MB+; perform worse on arm64 unless rebuilt for that target

### SnapStart (Java Only)

> Launched November 2022. Java 11, 17, 21 only.

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

### Scheduled Provisioned Concurrency for Predictable Peaks

> Source: [Scheduling AWS Lambda Provisioned Concurrency for recurring peak usage](https://aws.amazon.com/blogs/compute/scheduling-aws-lambda-provisioned-concurrency-for-recurring-peak-usage/)

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

```json
{
  "power": 1024,
  "cost": 0.0000002083,
  "duration": 134.6,
  "stateMachine": {
    "executionCost": 0.00045,
    "visualization": "https://lambda-power-tuning.show/#..."
  }
}
```

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

> Source: [Are Lambda-to-Lambda calls really so bad?](https://theburningmonk.com/2020/07/are-lambda-to-lambda-calls-really-so-bad/) — Yan Cui

Two failure modes that are silent in dev and only surface at scale:

**Concurrency slot deadlock** — caller and callee each hold a slot simultaneously. Under load, callers exhaust the account limit waiting for callees that can never start:
```
Account concurrency limit: 1000
500 in-flight callers → 500 slots held, waiting
Callee throttled → callers time out → entire chain stalls
```
Adding concurrency doesn't fix this; it just raises the ceiling before the same deadlock. The fix is to not hold a slot across a service boundary.

**Retry amplification** — retries multiply, not add, across the chain:
```
Caller retries: 3  ×  Callee retries: 3  =  9 invocations per original request
Three layers deep:                           27 invocations
```
This shows up as unexplained cost spikes and DLQ floods during incidents, not during normal operation.

**The async pattern that avoids both** — fire-and-forget releases the caller slot immediately:
```python
lambda_client.invoke(
    FunctionName="downstream",
    InvocationType="Event",       # Returns 202, caller slot freed immediately
    Payload=json.dumps(payload).encode(),
)
# Always pair with on_failure destination on the callee — see Async Invocations section
```

**When synchronous calls are acceptable:**
- Both functions owned and deployed by the same team — function name coupling is a non-issue
- GraphQL resolvers: Apollo Server on Lambda requires synchronous sub-resolution
- Behind a Function URL + CloudFront: stable domain replaces raw function name coupling

For orchestrating multi-step workflows that need synchronous results, use Step Functions — see `event-driven.md`.

---

## Invocation Payload Limits

These are hard limits — no configuration changes them. The only escape is S3 offloading.

| Invocation type | Request limit | Response limit |
|---|---|---|
| Synchronous (`RequestResponse`) | 6 MB | 6 MB |
| Asynchronous (`Event`) | 256 KB | — |
| SQS message body | 256 KB | — |
| Kinesis record | 1 MB | — |
| EventBridge event | 256 KB | — |

**The trap**: Async invocations (SNS, EventBridge, SQS) all have a 256 KB limit. If you're passing large payloads event-to-event and only test synchronously, you won't hit this during dev — only in production under realistic data.

**S3 claim-check pattern** for oversized payloads:
```python
def invoke_async(function_name: str, payload: dict) -> None:
    body = json.dumps(payload).encode()
    if len(body) > 200_000:  # Stay under 256KB with margin
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
