locals {
  name          = "${var.project_name}-${var.environment}"
  authorization = var.auth_mode == "iam" ? "AWS_IAM" : "NONE"
  exposure_tags = var.auth_mode == "none" ? { PublicReason = var.public_reason } : {}
  definition    = file("${path.module}/../workflow/definition.asl.json")
}

data "aws_caller_identity" "current" {}

resource "aws_cloudwatch_log_group" "workflow" {
  name              = "/aws/vendedlogs/states/${local.name}"
  retention_in_days = var.log_retention_days
}

resource "aws_cloudwatch_log_group" "api_access" {
  name              = "/aws/apigateway/${local.name}-access"
  retention_in_days = var.log_retention_days
}

data "aws_iam_policy_document" "workflow_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["states.amazonaws.com"]
    }
    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [data.aws_caller_identity.current.account_id]
    }
  }
}

resource "aws_iam_role" "workflow" {
  name               = "${local.name}-workflow"
  assume_role_policy = data.aws_iam_policy_document.workflow_assume.json
}

# Step Functions delivers logs through CloudWatch Logs log delivery, whose actions do not support
# resource-level permissions. The workflow itself calls no other service.
data "aws_iam_policy_document" "workflow" {
  statement {
    actions = [
      "logs:CreateLogDelivery", "logs:GetLogDelivery", "logs:UpdateLogDelivery", "logs:DeleteLogDelivery",
      "logs:ListLogDeliveries", "logs:PutResourcePolicy", "logs:DescribeResourcePolicies", "logs:DescribeLogGroups",
    ]
    resources = ["*"]
  }
  statement {
    actions   = ["xray:PutTraceSegments", "xray:PutTelemetryRecords", "xray:GetSamplingRules", "xray:GetSamplingTargets"]
    resources = ["*"]
  }
}

resource "aws_iam_role_policy" "workflow" {
  name   = "logs-and-traces"
  role   = aws_iam_role.workflow.id
  policy = data.aws_iam_policy_document.workflow.json
}

# Express: runs synchronously behind the API, at most 5 minutes; execution history is in the log group only.
# The log has every event but not the input and output, which hold the order and can hold customer
# data. The execution is named by the correlation ID, so each event's execution_arn carries it.
resource "aws_sfn_state_machine" "orders" {
  name       = local.name
  type       = "EXPRESS"
  role_arn   = aws_iam_role.workflow.arn
  definition = local.definition

  logging_configuration {
    log_destination        = "${aws_cloudwatch_log_group.workflow.arn}:*"
    include_execution_data = var.log_execution_data
    level                  = "ALL"
  }

  tracing_configuration {
    enabled = true
  }

  depends_on = [aws_iam_role_policy.workflow]
}

# No aws:SourceAccount condition here: API Gateway does not send it when it assumes an integration's
# credentials role, and the condition makes every request fail with "API Gateway does not have
# permission to assume the provided role" (seen in the sandbox).
data "aws_iam_policy_document" "api_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["apigateway.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "api" {
  name               = "${local.name}-api"
  assume_role_policy = data.aws_iam_policy_document.api_assume.json
}

data "aws_iam_policy_document" "api" {
  statement {
    actions   = ["states:StartSyncExecution"]
    resources = [aws_sfn_state_machine.orders.arn]
  }
}

resource "aws_iam_role_policy" "api" {
  name   = "start-sync-execution"
  role   = aws_iam_role.api.id
  policy = data.aws_iam_policy_document.api.json
}

resource "aws_api_gateway_rest_api" "orders" {
  name = local.name
  tags = local.exposure_tags

  endpoint_configuration {
    types = ["REGIONAL"]
  }

  lifecycle {
    create_before_destroy = true
  }
}

# Rejects a body that is not a JSON object with 400 before a workflow starts. The workflow decides
# what makes an order valid.
resource "aws_api_gateway_model" "order" {
  rest_api_id  = aws_api_gateway_rest_api.orders.id
  name         = "Order"
  content_type = "application/json"
  schema       = jsonencode({ "$schema" = "http://json-schema.org/draft-04/schema#", type = "object" })
}

resource "aws_api_gateway_request_validator" "body" {
  rest_api_id           = aws_api_gateway_rest_api.orders.id
  name                  = "body"
  validate_request_body = true
}

resource "aws_api_gateway_resource" "orders" {
  rest_api_id = aws_api_gateway_rest_api.orders.id
  parent_id   = aws_api_gateway_rest_api.orders.root_resource_id
  path_part   = "orders"
}

resource "aws_api_gateway_method" "post_orders" {
  rest_api_id   = aws_api_gateway_rest_api.orders.id
  resource_id   = aws_api_gateway_resource.orders.id
  http_method   = "POST"
  authorization = local.authorization

  request_validator_id = aws_api_gateway_request_validator.body.id
  request_models       = { "application/json" = aws_api_gateway_model.order.name }
}

# The workflow input is {"correlation_id": ..., "order": <request body>}. A caller's
# x-correlation-id is used only when it is 1-64 letters, digits or hyphens, so it cannot break the
# JSON and is a valid execution name.
resource "aws_api_gateway_integration" "start_sync" {
  rest_api_id             = aws_api_gateway_rest_api.orders.id
  resource_id             = aws_api_gateway_resource.orders.id
  http_method             = aws_api_gateway_method.post_orders.http_method
  type                    = "AWS"
  integration_http_method = "POST"
  uri                     = "arn:aws:apigateway:${var.aws_region}:states:action/StartSyncExecution"
  credentials             = aws_iam_role.api.arn
  passthrough_behavior    = "NEVER"
  timeout_milliseconds    = 29000

  request_templates = {
    "application/json" = <<-EOT
      #set($cid = $input.params('x-correlation-id'))
      #if(!$cid.matches('^[A-Za-z0-9-]{1,64}$'))
      #set($cid = $context.requestId)
      #end
      #set($order = $util.escapeJavaScript($input.json('$')).replaceAll("\\'", "'"))
      {
        "stateMachineArn": "${aws_sfn_state_machine.orders.arn}",
        "name": "$cid",
        "input": "{\"correlation_id\": \"$cid\", \"order\": $order}"
      }
    EOT
  }
}

resource "aws_api_gateway_method_response" "post_orders" {
  for_each    = toset(["200", "422", "500", "504"])
  rest_api_id = aws_api_gateway_rest_api.orders.id
  resource_id = aws_api_gateway_resource.orders.id
  http_method = aws_api_gateway_method.post_orders.http_method
  status_code = each.key

  response_parameters = {
    "method.response.header.x-correlation-id" = true
    "method.response.header.x-trace-id"       = true
  }
}

# StartSyncExecution answers 200 for every finished execution. The template maps the
# execution status to the HTTP status: SUCCEEDED 200, OrderRejected 422, TIMED_OUT 504, other failures 500.
resource "aws_api_gateway_integration_response" "execution" {
  rest_api_id = aws_api_gateway_rest_api.orders.id
  resource_id = aws_api_gateway_resource.orders.id
  http_method = aws_api_gateway_method.post_orders.http_method
  status_code = aws_api_gateway_method_response.post_orders["200"].status_code

  response_templates = {
    "application/json" = <<-EOT
      #set($r = $input.path('$'))
      #set($in = $util.parseJson($r.input))
      #set($context.responseOverride.header.x-correlation-id = $in.correlation_id)
      #set($context.responseOverride.header.x-trace-id = $context.xrayTraceId)
      #if($r.status == "SUCCEEDED")
      $r.output
      #elseif($r.status == "TIMED_OUT")
      #set($context.responseOverride.status = 504)
      {"error": "WorkflowTimedOut", "execution_arn": "$r.executionArn"}
      #elseif($r.error == "OrderRejected")
      #set($context.responseOverride.status = 422)
      {"error": "OrderRejected", "cause": "$util.escapeJavaScript($r.cause)", "execution_arn": "$r.executionArn"}
      #else
      #set($context.responseOverride.status = 500)
      {"error": "WorkflowFailed", "execution_arn": "$r.executionArn"}
      #end
    EOT
  }

  depends_on = [aws_api_gateway_integration.start_sync]
}

resource "aws_api_gateway_integration_response" "integration_error" {
  rest_api_id       = aws_api_gateway_rest_api.orders.id
  resource_id       = aws_api_gateway_resource.orders.id
  http_method       = aws_api_gateway_method.post_orders.http_method
  status_code       = aws_api_gateway_method_response.post_orders["500"].status_code
  selection_pattern = "[45]\\d{2}"

  response_templates = {
    "application/json" = "{\"error\": \"StartExecutionFailed\"}"
  }

  depends_on = [aws_api_gateway_integration.start_sync]
}

resource "aws_api_gateway_deployment" "orders" {
  rest_api_id = aws_api_gateway_rest_api.orders.id

  triggers = {
    redeployment = sha1(jsonencode([
      aws_api_gateway_resource.orders, aws_api_gateway_method.post_orders, aws_api_gateway_integration.start_sync,
      aws_api_gateway_model.order, aws_api_gateway_request_validator.body,
      aws_api_gateway_integration_response.execution, aws_api_gateway_integration_response.integration_error,
      aws_api_gateway_method_response.post_orders,
    ]))
  }

  lifecycle {
    create_before_destroy = true
  }
}

# Access logging needs the account-level API Gateway CloudWatch role (aws apigateway get-account).
# This project does not manage that role: it is shared by every REST API in the account and region.
resource "aws_api_gateway_stage" "api" {
  rest_api_id          = aws_api_gateway_rest_api.orders.id
  deployment_id        = aws_api_gateway_deployment.orders.id
  stage_name           = var.environment
  xray_tracing_enabled = true

  access_log_settings {
    destination_arn = aws_cloudwatch_log_group.api_access.arn
    format = jsonencode({
      requestId         = "$context.requestId"
      resourcePath      = "$context.resourcePath"
      status            = "$context.status"
      latencyMs         = "$context.responseLatency"
      integrationStatus = "$context.integration.status"
      integrationError  = "$context.integration.error"
      xrayTraceId       = "$context.xrayTraceId"
      sourceIp          = "$context.identity.sourceIp"
    })
  }
}

resource "aws_api_gateway_method_settings" "all" {
  rest_api_id = aws_api_gateway_rest_api.orders.id
  stage_name  = aws_api_gateway_stage.api.stage_name
  method_path = "*/*"

  settings {
    metrics_enabled        = true
    logging_level          = "ERROR"
    throttling_rate_limit  = var.throttle_rate_limit
    throttling_burst_limit = var.throttle_burst_limit
  }
}
