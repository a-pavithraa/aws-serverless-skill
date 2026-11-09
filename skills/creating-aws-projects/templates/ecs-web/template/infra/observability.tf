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



# The service writes one JSON line per request; this counts the ones with a 5xx status.
resource "aws_cloudwatch_log_metric_filter" "http_5xx" {
  name           = "${local.name}-http-5xx"
  log_group_name = aws_cloudwatch_log_group.app.name
  pattern        = "{ $.status >= 500 }"

  metric_transformation {
    name          = "Http5xx"
    namespace     = local.name
    value         = "1"
    default_value = "0"
  }
}

resource "aws_cloudwatch_metric_alarm" "http_5xx" {
  alarm_name          = "${local.name}-http-5xx"
  namespace           = local.name
  metric_name         = "Http5xx"
  statistic           = "Sum"
  period              = 60
  evaluation_periods  = 1
  threshold           = 0
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.alarms.arn]
  ok_actions          = [aws_sns_topic.alarms.arn]
}

# No data means no task reports metrics, which is as bad as zero running tasks.
resource "aws_cloudwatch_metric_alarm" "running_tasks" {
  count               = local.deploy_service ? 1 : 0
  alarm_name          = "${local.name}-running-tasks"
  namespace           = "ECS/ContainerInsights"
  metric_name         = "RunningTaskCount"
  dimensions          = { ClusterName = aws_ecs_cluster.this.name, ServiceName = local.service_name }
  statistic           = "Minimum"
  period              = 60
  evaluation_periods  = 3
  threshold           = var.min_tasks
  comparison_operator = "LessThanThreshold"
  treat_missing_data  = "breaching"
  alarm_actions       = [aws_sns_topic.alarms.arn]
  ok_actions          = [aws_sns_topic.alarms.arn]
}

resource "aws_cloudwatch_metric_alarm" "cpu_high" {
  count               = local.deploy_service ? 1 : 0
  alarm_name          = "${local.name}-cpu-high"
  namespace           = "AWS/ECS"
  metric_name         = "CPUUtilization"
  dimensions          = { ClusterName = aws_ecs_cluster.this.name, ServiceName = local.service_name }
  statistic           = "Average"
  period              = 60
  evaluation_periods  = 5
  threshold           = 85
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.alarms.arn]
  ok_actions          = [aws_sns_topic.alarms.arn]
}
