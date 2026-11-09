resource "aws_iam_role" "fn" {
  name = var.name
  assume_role_policy = jsonencode({
    Version   = "2012-10-17"
    Statement = [{ Effect = "Allow", Action = "sts:AssumeRole", Principal = { Service = "lambda.amazonaws.com" } }]
  })
}

resource "aws_lambda_function" "worker" {
  function_name    = var.name
  role             = aws_iam_role.fn.arn
  runtime          = "python3.13"
  handler          = "main.handler"
  filename         = "worker.zip"
  source_code_hash = "unused"

  tracing_config {
    mode = "Active"
  }
}

resource "aws_cloudwatch_metric_alarm" "worker_errors" {
  alarm_name          = "${var.name}-errors"
  namespace           = "AWS/Lambda"
  metric_name         = "Errors"
  dimensions          = { FunctionName = aws_lambda_function.worker.function_name }
  statistic           = "Sum"
  period              = 60
  evaluation_periods  = 1
  threshold           = 0
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"
}
