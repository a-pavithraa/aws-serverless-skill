### Terraform plan: 18 to delete

**Stateful resources destroyed or replaced** (data loss unless intended):

- `aws_kms_key.alarms`

| Address | Action | Known after apply |
| --- | --- | --- |
| `aws_apigatewayv2_api.http` | delete |  |
| `aws_apigatewayv2_integration.lambda` | delete |  |
| `aws_apigatewayv2_route.hello` | delete |  |
| `aws_apigatewayv2_stage.default` | delete |  |
| `aws_cloudwatch_dashboard.service` | delete |  |
| `aws_cloudwatch_log_group.api_access` | delete |  |
| `aws_cloudwatch_log_group.lambda` | delete |  |
| `aws_cloudwatch_metric_alarm.api_5xx` | delete |  |
| `aws_cloudwatch_metric_alarm.lambda_duration_p99` | delete |  |
| `aws_cloudwatch_metric_alarm.lambda_errors` | delete |  |
| `aws_cloudwatch_metric_alarm.lambda_throttles` | delete |  |
| `aws_iam_role.lambda` | delete |  |
| `aws_iam_role_policy.lambda` | delete |  |
| `aws_kms_key.alarms` | delete |  |
| `aws_lambda_alias.live` | delete |  |
| `aws_lambda_function.api` | delete |  |
| `aws_lambda_permission.api` | delete |  |
| `aws_sns_topic.alarms` | delete |  |
