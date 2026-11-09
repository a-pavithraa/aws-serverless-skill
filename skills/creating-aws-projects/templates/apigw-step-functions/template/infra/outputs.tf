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
  value       = aws_api_gateway_stage.api.invoke_url
}

output "auth_mode" {
  description = "How callers authenticate: iam or none."
  value       = var.auth_mode
}

output "state_machine_arn" {
  description = "ARN of the Express state machine."
  value       = aws_sfn_state_machine.orders.arn
}

output "log_group" {
  description = "Log group of the workflow: every execution event, without input and output."
  value       = aws_cloudwatch_log_group.workflow.name
}

output "api_access_log_group" {
  description = "Log group with one JSON line per API request."
  value       = aws_cloudwatch_log_group.api_access.name
}

output "alarm_names" {
  description = "Names of the alarms this project creates. The verifier reports their states."
  value       = [aws_cloudwatch_metric_alarm.api_5xx.alarm_name, aws_cloudwatch_metric_alarm.executions_timed_out.alarm_name]
}

output "alarm_topic_arn" {
  description = "SNS topic the alarms notify. Subscribe someone, or no one is told."
  value       = aws_sns_topic.alarms.arn
}
