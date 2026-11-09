output "account_id" {
  description = "Account the resources are in. The verifier compares it with the expected account."
  value       = data.aws_caller_identity.current.account_id
}

output "region" {
  description = "Region the resources are in. The verifier compares it with the expected region."
  value       = var.aws_region
}

output "api_url" {
  description = "Base URL of the API stage."
  value       = aws_apigatewayv2_stage.default.invoke_url
}

output "auth_mode" {
  description = "How callers authenticate: iam or none."
  value       = var.auth_mode
}

output "function_name" {
  description = "Name of the Lambda function."
  value       = aws_lambda_function.api.function_name
}

output "function_alias" {
  description = "Lambda alias that the trigger invokes."
  value       = aws_lambda_alias.live.name
}

output "function_version" {
  description = "Published Lambda version the alias points at."
  value       = aws_lambda_function.api.version
}

output "lambda_log_group" {
  description = "Log group of the Lambda function."
  value       = aws_cloudwatch_log_group.lambda.name
}

output "alarm_names" {
  description = "Names of the alarms this project creates. The verifier reports their states."
  value = [
    aws_cloudwatch_metric_alarm.lambda_errors.alarm_name,
    aws_cloudwatch_metric_alarm.lambda_throttles.alarm_name,
    aws_cloudwatch_metric_alarm.lambda_duration_p99.alarm_name,
    aws_cloudwatch_metric_alarm.api_5xx.alarm_name,
  ]
}

output "alarm_topic_arn" {
  description = "SNS topic the alarms notify. Subscribe someone, or no one is told."
  value       = aws_sns_topic.alarms.arn
}

output "artifact_path" {
  description = "Local path of the Lambda package that Terraform built. The verifier compares its hash with the deployed code."
  value       = data.archive_file.lambda.output_path
}
