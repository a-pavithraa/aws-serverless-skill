# Monitoring & Alerting Reference

## Monitoring Philosophy

**Alert on symptoms, not causes.** Users don't care if CPU is high—they care if requests are failing.

| Don't Alert On | Do Alert On |
|----------------|-------------|
| CPU > 80% | Error rate > 1% |
| Memory usage high | P99 latency > 3s |
| Queue depth increasing | DLQ has messages |
| Concurrent executions high | Throttling occurring |

---

## Lambda: Essential Metrics & Alarms

### Key CloudWatch Metrics

| Metric | What It Tells You | Alert Threshold |
|--------|------------------|-----------------|
| `Errors` | Function threw exception | > 0 for critical, > 1% for others |
| `Throttles` | Concurrency limit hit | > 0 (investigate immediately) |
| `Duration` | Execution time | > 80% of timeout |
| `ConcurrentExecutions` | Active instances | > 80% of reserved concurrency |
| `IteratorAge` (streams) | Processing lag | > 60000ms (1 minute behind) |

### Lambda Alarm Module
```hcl
variable "function_name" {
  type = string
}

variable "timeout_seconds" {
  type = number
}

variable "sns_topic_arn" {
  type = string
}

# Error rate alarm
resource "aws_cloudwatch_metric_alarm" "errors" {
  alarm_name          = "${var.function_name}-errors"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 2
  threshold           = 0
  treat_missing_data  = "notBreaching"
  
  metric_name = "Errors"
  namespace   = "AWS/Lambda"
  period      = 60
  statistic   = "Sum"
  
  dimensions = {
    FunctionName = var.function_name
  }
  
  alarm_actions = [var.sns_topic_arn]
  ok_actions    = [var.sns_topic_arn]
}

# Duration approaching timeout
resource "aws_cloudwatch_metric_alarm" "duration" {
  alarm_name          = "${var.function_name}-duration"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 3
  # Alert when P95 duration > 80% of timeout
  threshold           = var.timeout_seconds * 1000 * 0.8
  treat_missing_data  = "notBreaching"
  
  metric_name = "Duration"
  namespace   = "AWS/Lambda"
  period      = 300
  extended_statistic = "p95"
  
  dimensions = {
    FunctionName = var.function_name
  }
  
  alarm_actions = [var.sns_topic_arn]
}

# Throttling alarm (any throttle is bad)
resource "aws_cloudwatch_metric_alarm" "throttles" {
  alarm_name          = "${var.function_name}-throttles"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 1
  threshold           = 0
  treat_missing_data  = "notBreaching"
  
  metric_name = "Throttles"
  namespace   = "AWS/Lambda"
  period      = 60
  statistic   = "Sum"
  
  dimensions = {
    FunctionName = var.function_name
  }
  
  alarm_actions = [var.sns_topic_arn]
}
```

### Stream Processing: Iterator Age
```hcl
# For Kinesis or DynamoDB Streams
resource "aws_cloudwatch_metric_alarm" "iterator_age" {
  alarm_name          = "${var.function_name}-iterator-age"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 2
  threshold           = 60000  # 1 minute behind
  treat_missing_data  = "notBreaching"
  
  metric_name = "IteratorAge"
  namespace   = "AWS/Lambda"
  period      = 60
  statistic   = "Maximum"
  
  dimensions = {
    FunctionName = var.function_name
  }
  
  alarm_actions = [var.sns_topic_arn]
}
```

---

## DynamoDB: Essential Alarms

### Key Metrics

| Metric | What It Tells You | Alert When |
|--------|------------------|------------|
| `ThrottledRequests` | Capacity exceeded | > 0 |
| `SystemErrors` | DynamoDB internal error | > 0 |
| `UserErrors` | Your code issues (400s) | Depends on baseline |
| `ConsumedReadCapacityUnits` | Read usage | > 80% of provisioned |
| `ConsumedWriteCapacityUnits` | Write usage | > 80% of provisioned |

### DynamoDB Alarm Module
```hcl
variable "table_name" {
  type = string
}

variable "sns_topic_arn" {
  type = string
}

# Throttling (most important)
resource "aws_cloudwatch_metric_alarm" "throttles" {
  alarm_name          = "${var.table_name}-throttles"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 1
  threshold           = 0
  treat_missing_data  = "notBreaching"
  
  metric_name = "ThrottledRequests"
  namespace   = "AWS/DynamoDB"
  period      = 60
  statistic   = "Sum"
  
  dimensions = {
    TableName = var.table_name
  }
  
  alarm_actions = [var.sns_topic_arn]
}

# System errors (DynamoDB problem)
resource "aws_cloudwatch_metric_alarm" "system_errors" {
  alarm_name          = "${var.table_name}-system-errors"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 1
  threshold           = 0
  treat_missing_data  = "notBreaching"
  
  metric_name = "SystemErrors"
  namespace   = "AWS/DynamoDB"
  period      = 60
  statistic   = "Sum"
  
  dimensions = {
    TableName = var.table_name
  }
  
  alarm_actions = [var.sns_topic_arn]
}
```

---

## API Gateway: Essential Alarms

### Key Metrics

| Metric | Alert When |
|--------|------------|
| `5XXError` | > 1% of requests |
| `4XXError` | > 10% (depends on API) |
| `Latency` | P95 > 3 seconds |
| `IntegrationLatency` | P95 > 2 seconds |
| `Count` | Drop > 50% (anomaly) |

### API Gateway Alarm Module
```hcl
variable "api_name" {
  type = string
}

variable "api_stage" {
  type = string
}

variable "sns_topic_arn" {
  type = string
}

# 5XX errors (your backend is broken)
resource "aws_cloudwatch_metric_alarm" "api_5xx" {
  alarm_name          = "${var.api_name}-5xx-errors"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 2
  threshold           = 1  # 1% error rate
  treat_missing_data  = "notBreaching"
  
  metric_query {
    id          = "error_rate"
    expression  = "(errors / requests) * 100"
    label       = "Error Rate"
    return_data = true
  }
  
  metric_query {
    id = "errors"
    metric {
      metric_name = "5XXError"
      namespace   = "AWS/ApiGateway"
      period      = 300
      stat        = "Sum"
      dimensions = {
        ApiName = var.api_name
        Stage   = var.api_stage
      }
    }
  }
  
  metric_query {
    id = "requests"
    metric {
      metric_name = "Count"
      namespace   = "AWS/ApiGateway"
      period      = 300
      stat        = "Sum"
      dimensions = {
        ApiName = var.api_name
        Stage   = var.api_stage
      }
    }
  }
  
  alarm_actions = [var.sns_topic_arn]
}

# Latency alarm
resource "aws_cloudwatch_metric_alarm" "api_latency" {
  alarm_name          = "${var.api_name}-latency"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 3
  threshold           = 3000  # 3 seconds
  treat_missing_data  = "notBreaching"
  
  metric_name        = "Latency"
  namespace          = "AWS/ApiGateway"
  period             = 300
  extended_statistic = "p95"
  
  dimensions = {
    ApiName = var.api_name
    Stage   = var.api_stage
  }
  
  alarm_actions = [var.sns_topic_arn]
}
```

---

## SQS: DLQ Monitoring (Most Important)

**If messages are in the DLQ, something is broken.**

```hcl
variable "dlq_name" {
  type = string
}

variable "sns_topic_arn" {
  type = string
}

# Any message in DLQ is a problem
resource "aws_cloudwatch_metric_alarm" "dlq_messages" {
  alarm_name          = "${var.dlq_name}-has-messages"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 1
  threshold           = 0
  treat_missing_data  = "notBreaching"
  
  metric_name = "ApproximateNumberOfMessagesVisible"
  namespace   = "AWS/SQS"
  period      = 60
  statistic   = "Sum"
  
  dimensions = {
    QueueName = var.dlq_name
  }
  
  alarm_actions = [var.sns_topic_arn]
}
```

---

## Composite Alarms: Reduce Alert Fatigue

Combine related alarms to reduce noise:

```hcl
# Only alert if BOTH Lambda errors AND DLQ has messages
resource "aws_cloudwatch_composite_alarm" "processing_failure" {
  alarm_name = "${local.name_prefix}-processing-failure"
  
  alarm_rule = "ALARM(${aws_cloudwatch_metric_alarm.lambda_errors.alarm_name}) AND ALARM(${aws_cloudwatch_metric_alarm.dlq_messages.alarm_name})"
  
  alarm_actions = [var.pagerduty_topic_arn]
  ok_actions    = [var.pagerduty_topic_arn]
}
```

---

## Complete Monitoring Stack

```hcl
module "monitoring" {
  source = "./modules/monitoring"
  
  for_each = {
    "order-api"    = { function_name = aws_lambda_function.order_api.function_name, timeout = 6 }
    "payment-api"  = { function_name = aws_lambda_function.payment_api.function_name, timeout = 10 }
    "notification" = { function_name = aws_lambda_function.notification.function_name, timeout = 30 }
  }
  
  function_name   = each.value.function_name
  timeout_seconds = each.value.timeout
  sns_topic_arn   = aws_sns_topic.alerts.arn
}

# DLQ alarms
module "dlq_monitoring" {
  source = "./modules/dlq-alarm"
  
  for_each = {
    "orders-dlq"   = aws_sqs_queue.orders_dlq.name
    "payments-dlq" = aws_sqs_queue.payments_dlq.name
  }
  
  dlq_name      = each.value
  sns_topic_arn = aws_sns_topic.alerts.arn
}

# SNS topic for alerts
resource "aws_sns_topic" "alerts" {
  name = "${local.name_prefix}-alerts"
}

# Email subscription (replace with PagerDuty/Slack in production)
resource "aws_sns_topic_subscription" "email" {
  topic_arn = aws_sns_topic.alerts.arn
  protocol  = "email"
  endpoint  = "oncall@example.com"
}
```
