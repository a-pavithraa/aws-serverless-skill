# Lambda Powertools Observability

## Overview

| Utility | Purpose | Output |
|---------|---------|--------|
| **Logger** | Structured JSON logging | CloudWatch Logs |
| **Tracer** | Distributed tracing | AWS X-Ray |
| **Metrics** | Custom metrics via EMF | CloudWatch Metrics |

---

## Complete Handler Pattern

Decorator order matters: metrics MUST be outermost.

```python
import os
from aws_lambda_powertools import Logger, Tracer, Metrics
from aws_lambda_powertools.metrics import MetricUnit
from aws_lambda_powertools.utilities.typing import LambdaContext

logger = Logger()
tracer = Tracer()
metrics = Metrics()

@metrics.log_metrics(capture_cold_start_metric=True)
@logger.inject_lambda_context(log_event=True)
@tracer.capture_lambda_handler
def handler(event: dict, context: LambdaContext) -> dict:
    logger.info("Processing request", extra={
        "order_id": event.get("order_id"),
        "customer_id": event.get("customer_id")
    })

    metrics.add_metric(name="OrdersProcessed", unit=MetricUnit.Count, value=1)
    metrics.add_dimension(name="Environment", value=os.environ.get("ENV", "dev"))

    try:
        result = process_order(event)
        metrics.add_metric(name="OrdersSucceeded", unit=MetricUnit.Count, value=1)
        return {"statusCode": 200, "body": result}

    except ValueError as e:
        logger.warning("Validation failed", extra={"error": str(e)})
        metrics.add_metric(name="OrdersFailed", unit=MetricUnit.Count, value=1)
        return {"statusCode": 400, "body": str(e)}


@tracer.capture_method
def process_order(event: dict) -> str:
    return "processed"
```

---

## Metrics: Why EMF Over CloudWatch API

Traditional `put_metric_data` is synchronous (adds latency), costs per API call, and needs retry logic.

EMF writes metrics to stdout as JSON. CloudWatch parses them asynchronously — zero latency impact, no additional API calls.

### High-Cardinality Trap

```python
@metrics.log_metrics
def handler(event, context):
    # DON'T: High-cardinality dimensions cause metric explosion
    # metrics.add_dimension(name="OrderId", value=event["order_id"])

    # DO: Use metadata for high-cardinality data (searchable in logs, not metrics)
    metrics.add_metadata(key="order_id", value=event["order_id"])

    metrics.add_metric(name="OrderProcessed", unit=MetricUnit.Count, value=1)
```

---

## Idempotency: Safe Retries

```python
from aws_lambda_powertools.utilities.idempotency import (
    IdempotencyConfig,
    DynamoDBPersistenceLayer,
    idempotent
)

persistence = DynamoDBPersistenceLayer(table_name="IdempotencyTable")
config = IdempotencyConfig(expires_after_seconds=3600)

@idempotent(config=config, persistence_store=persistence)
def handler(event, context):
    """
    If invoked twice with the same event, second invocation returns cached result.
    Protects against: Lambda retries on timeout, SQS redelivery, user double-clicks.
    """
    order_id = create_order(event)
    charge_customer(event["customer_id"], event["amount"])
    return {"order_id": order_id}
```

### Idempotency Table (Terraform)
```hcl
resource "aws_dynamodb_table" "idempotency" {
  name         = "${local.name_prefix}-idempotency"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "id"

  attribute {
    name = "id"
    type = "S"
  }

  ttl {
    attribute_name = "expiration"
    enabled        = true
  }
}
```

---

## Terraform: Lambda with Powertools

```hcl
locals {
  powertools_layer = "arn:aws:lambda:${data.aws_region.current.name}:017000801446:layer:AWSLambdaPowertoolsPythonV2:59"
}

resource "aws_lambda_function" "this" {
  function_name    = var.function_name
  handler          = var.handler
  runtime          = "python3.11"
  memory_size      = var.memory_size
  timeout          = var.timeout
  architectures    = ["arm64"]
  role             = aws_iam_role.lambda.arn
  filename         = data.archive_file.lambda.output_path
  source_code_hash = data.archive_file.lambda.output_base64sha256

  layers = [local.powertools_layer]

  environment {
    variables = {
      POWERTOOLS_SERVICE_NAME       = var.function_name
      POWERTOOLS_METRICS_NAMESPACE  = var.metrics_namespace
      POWERTOOLS_LOG_LEVEL          = var.environment == "prod" ? "INFO" : "DEBUG"
      POWERTOOLS_LOGGER_SAMPLE_RATE = "0.1"
      ENVIRONMENT                   = var.environment
    }
  }

  tracing_config {
    mode = "Active"
  }
}

resource "aws_cloudwatch_log_group" "lambda" {
  name              = "/aws/lambda/${var.function_name}"
  retention_in_days = var.environment == "prod" ? 30 : 7
}

resource "aws_iam_role_policy_attachment" "xray" {
  role       = aws_iam_role.lambda.name
  policy_arn = "arn:aws:iam::aws:policy/AWSXRayDaemonWriteAccess"
}
```
