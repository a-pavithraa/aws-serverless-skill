output "account_id" {
  description = "Account the resources are in. The verifier compares it with the expected account."
  value       = data.aws_caller_identity.current.account_id
}

output "region" {
  description = "Region the resources are in. The verifier compares it with the expected region."
  value       = var.aws_region
}

output "function_name" {
  description = "Name of the Lambda function."
  value       = aws_lambda_function.worker.function_name
}

output "function_alias" {
  description = "Lambda alias that the trigger invokes."
  value       = aws_lambda_alias.live.name
}

output "function_version" {
  description = "Published Lambda version the alias points at."
  value       = aws_lambda_function.worker.version
}

output "lambda_log_group" {
  description = "Log group of the Lambda function."
  value       = aws_cloudwatch_log_group.lambda.name
}

output "queue_url" {
  description = "Queue that producers send orders to."
  value       = aws_sqs_queue.orders.id
}

output "dead_letter_queue_url" {
  description = "Queue that receives a message after max_receive_count failed receives."
  value       = aws_sqs_queue.dead_letter.id
}

output "max_receive_count" {
  description = "Receives before a message moves to the dead-letter queue."
  value       = var.max_receive_count
}

output "visibility_timeout_seconds" {
  description = "How long a received message stays hidden: six times the function timeout."
  value       = aws_sqs_queue.orders.visibility_timeout_seconds
}

output "idempotency_table" {
  description = "DynamoDB table that records processed messages, so a redelivered message is not processed twice."
  value       = aws_dynamodb_table.idempotency.name
}

output "alarm_names" {
  description = "Names of the alarms this project creates. The verifier reports their states."
  value = [
    aws_cloudwatch_metric_alarm.lambda_errors.alarm_name,
    aws_cloudwatch_metric_alarm.dead_letter_messages.alarm_name,
    aws_cloudwatch_metric_alarm.oldest_message_age.alarm_name,
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
