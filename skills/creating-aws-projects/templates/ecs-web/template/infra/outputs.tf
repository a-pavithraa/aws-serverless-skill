output "account_id" {
  description = "Account the resources are in. The verifier compares it with the expected account."
  value       = data.aws_caller_identity.current.account_id
}

output "region" {
  description = "Region the resources are in. The verifier compares it with the expected region."
  value       = var.aws_region
}

output "ecr_repository_url" {
  description = "Image repository. Push images here, then deploy them by digest."
  value       = aws_ecr_repository.app.repository_url
}

output "ecs_cluster_name" {
  description = "Name of the ECS cluster."
  value       = aws_ecs_cluster.this.name
}

output "ecs_service_name" {
  description = "Name of the Express Mode service; null until image_digest is set."
  value       = local.deploy_service ? local.service_name : null
}

output "image_digest" {
  description = "Image digest the service runs; null until image_digest is set."
  value       = local.deploy_service ? var.image_digest : null
}

output "service_url" {
  description = "HTTPS URL of the service; null until image_digest is set."
  value       = local.deploy_service ? "https://${trimprefix(aws_ecs_express_gateway_service.web[0].ingress_paths[0].endpoint, "https://")}" : null
}

output "log_group" {
  description = "Log group of the containers."
  value       = aws_cloudwatch_log_group.app.name
}

output "alarm_names" {
  description = "Names of the alarms this project creates. The verifier reports their states."
  value = concat([aws_cloudwatch_metric_alarm.http_5xx.alarm_name], aws_cloudwatch_metric_alarm.running_tasks[*].alarm_name,
  aws_cloudwatch_metric_alarm.cpu_high[*].alarm_name)
}

output "alarm_topic_arn" {
  description = "SNS topic the alarms notify. Subscribe someone, or no one is told."
  value       = aws_sns_topic.alarms.arn
}

output "secret_name" {
  description = "Secrets Manager secret that holds the app's secrets as JSON keys; null without secret_names. Set its value before the service starts."
  value       = length(aws_secretsmanager_secret.app) > 0 ? aws_secretsmanager_secret.app[0].name : null
}
