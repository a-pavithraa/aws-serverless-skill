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

  logging_config {
    log_format = "JSON"
    log_group  = aws_cloudwatch_log_group.worker.name
  }

  tracing_config {
    mode = "Active"
  }
}
