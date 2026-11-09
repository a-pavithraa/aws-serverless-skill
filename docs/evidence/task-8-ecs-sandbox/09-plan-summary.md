### Terraform plan: 3 to create

| Address | Action | Known after apply |
| --- | --- | --- |
| `aws_cloudwatch_metric_alarm.cpu_high[0]` | create | arn, evaluate_low_sample_count_percentiles, id |
| `aws_cloudwatch_metric_alarm.running_tasks[0]` | create | arn, evaluate_low_sample_count_percentiles, id |
| `aws_ecs_express_gateway_service.web[0]` | create | current_deployment, ingress_paths, service_arn, service_revision_arn |
