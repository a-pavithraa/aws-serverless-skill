output "account_id" {
  description = "Account the resources are in. The verifier compares it with the expected account."
  value       = data.aws_caller_identity.current.account_id
}

output "region" {
  description = "Region the resources are in. The verifier compares it with the expected region."
  value       = var.aws_region
}

output "service_url" {
  description = "URL of the load balancer: https with a certificate, else http."
  value       = "${local.https ? "https" : "http"}://${aws_lb.web.dns_name}"
}

output "asg_name" {
  description = "Name of the Auto Scaling group."
  value       = aws_autoscaling_group.web.name
}

output "ami_id" {
  description = "AMI in the current launch template version."
  value       = aws_launch_template.web.image_id
}

output "launch_template_id" {
  description = "ID of the launch template. A manual instance refresh names it."
  value       = aws_launch_template.web.id
}

output "launch_template_version" {
  description = "Newest launch template version. Every instance must run it after a refresh."
  value       = aws_launch_template.web.latest_version
}

output "target_group_arn" {
  description = "Target group the instances register in."
  value       = aws_lb_target_group.web.arn
}

output "log_group" {
  description = "Log group of the service on the instances: one stream per instance."
  value       = aws_cloudwatch_log_group.app.name
}

output "alarm_names" {
  description = "Names of the alarms this project creates. The verifier reports their states."
  value = [aws_cloudwatch_metric_alarm.target_5xx.alarm_name, aws_cloudwatch_metric_alarm.unhealthy_hosts.alarm_name,
  aws_cloudwatch_metric_alarm.healthy_hosts.alarm_name]
}

output "alarm_topic_arn" {
  description = "SNS topic the alarms notify. Subscribe someone, or no one is told."
  value       = aws_sns_topic.alarms.arn
}
