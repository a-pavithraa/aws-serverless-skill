### Terraform plan: 18 to create

| Address | Action | Known after apply |
| --- | --- | --- |
| `aws_apigatewayv2_api.http` | create | api_endpoint, arn, execution_arn, id, ip_address_type |
| `aws_apigatewayv2_integration.lambda` | create | api_id, id, integration_response_selection_expression, integration_uri |
| `aws_apigatewayv2_route.hello` | create | api_id, id, target |
| `aws_apigatewayv2_stage.default` | create | access_log_settings, api_id, arn, default_route_settings, deployment_id, execution_arn, id, invoke_url |
| `aws_cloudwatch_dashboard.service` | create | dashboard_arn, dashboard_body, id |
| `aws_cloudwatch_log_group.api_access` | create | arn, deletion_protection_enabled, id, log_group_class, name_prefix |
| `aws_cloudwatch_log_group.lambda` | create | arn, deletion_protection_enabled, id, log_group_class, name_prefix |
| `aws_cloudwatch_metric_alarm.api_5xx` | create | alarm_actions, arn, dimensions, evaluate_low_sample_count_percentiles, id, ok_actions |
| `aws_cloudwatch_metric_alarm.lambda_duration_p99` | create | alarm_actions, arn, evaluate_low_sample_count_percentiles, id, ok_actions |
| `aws_cloudwatch_metric_alarm.lambda_errors` | create | alarm_actions, arn, evaluate_low_sample_count_percentiles, id, ok_actions |
| `aws_cloudwatch_metric_alarm.lambda_throttles` | create | alarm_actions, arn, evaluate_low_sample_count_percentiles, id, ok_actions |
| `aws_iam_role.lambda` | create | arn, create_date, id, inline_policy, managed_policy_arns, name_prefix, unique_id |
| `aws_iam_role_policy.lambda` | create | id, name_prefix, policy, role |
| `aws_kms_key.alarms` | create | arn, id, key_id, multi_region, rotation_period_in_days |
| `aws_lambda_alias.live` | create | arn, function_version, id, invoke_arn |
| `aws_lambda_function.api` | create | arn, code_sha256, ephemeral_storage, id, invoke_arn, last_modified, qualified_arn, qualified_invoke_arn, response_streaming_invoke_arn, role, signing_job_arn, signing_profile_version_arn, source_code_size, version |
| `aws_lambda_permission.api` | create | id, source_arn, statement_id_prefix |
| `aws_sns_topic.alarms` | create | arn, beginning_archive_time, fifo_throughput_scope, id, kms_master_key_id, maximum_message_size, name_prefix, owner, policy, signature_version, tracing_config |
