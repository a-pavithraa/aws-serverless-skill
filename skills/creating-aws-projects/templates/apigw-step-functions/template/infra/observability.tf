# The AWS managed key alias/aws/sns does not let CloudWatch use it: alarms on a topic
# encrypted with it fail with "does not have authorization to access the SNS topic encryption key".
# In a key policy, Resource "*" means this key.
resource "aws_kms_key" "alarms" {
  description             = "Encrypts the ${local.name} alarm topic"
  enable_key_rotation     = true
  deletion_window_in_days = 7
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid       = "AccountAdministersKey"
        Effect    = "Allow"
        Principal = { AWS = "arn:aws:iam::${data.aws_caller_identity.current.account_id}:root" }
        Action    = "kms:*"
        Resource  = "*"
      },
      {
        Sid       = "CloudWatchAlarmsPublish"
        Effect    = "Allow"
        Principal = { Service = "cloudwatch.amazonaws.com" }
        Action    = ["kms:Decrypt", "kms:GenerateDataKey*"]
        Resource  = "*"
        Condition = { StringEquals = { "aws:SourceAccount" = data.aws_caller_identity.current.account_id } }
      },
    ]
  })
}

resource "aws_sns_topic" "alarms" {
  name              = "${local.name}-alarms"
  kms_master_key_id = aws_kms_key.alarms.arn
}

resource "aws_sns_topic_subscription" "alarm_email" {
  count     = var.alarm_email == "" ? 0 : 1
  topic_arn = aws_sns_topic.alarms.arn
  protocol  = "email"
  endpoint  = var.alarm_email
}




resource "aws_cloudwatch_metric_alarm" "api_5xx" {
  alarm_name          = "${local.name}-api-5xx"
  namespace           = "AWS/ApiGateway"
  metric_name         = "5XXError"
  dimensions          = { ApiName = aws_api_gateway_rest_api.orders.name, Stage = aws_api_gateway_stage.api.stage_name }
  statistic           = "Sum"
  period              = 60
  evaluation_periods  = 1
  threshold           = 0
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.alarms.arn]
  ok_actions          = [aws_sns_topic.alarms.arn]
}

# A rejected order fails its execution on purpose and answers 422, so ExecutionsFailed is not alarmed;
# a failure that is not a rejection answers 500 and trips api-5xx.
resource "aws_cloudwatch_metric_alarm" "executions_timed_out" {
  alarm_name          = "${local.name}-executions-timed-out"
  namespace           = "AWS/States"
  metric_name         = "ExecutionsTimedOut"
  dimensions          = { StateMachineArn = aws_sfn_state_machine.orders.arn }
  statistic           = "Sum"
  period              = 60
  evaluation_periods  = 1
  threshold           = 0
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.alarms.arn]
  ok_actions          = [aws_sns_topic.alarms.arn]
}
