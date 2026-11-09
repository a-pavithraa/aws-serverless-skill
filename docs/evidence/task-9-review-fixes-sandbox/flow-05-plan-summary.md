### Terraform plan: 26 to create

| Address | Action | Known after apply |
| --- | --- | --- |
| `aws_api_gateway_deployment.orders` | create | created_date, id, rest_api_id, triggers |
| `aws_api_gateway_integration.start_sync` | create | cache_namespace, credentials, id, request_templates, resource_id, response_transfer_mode, rest_api_id |
| `aws_api_gateway_integration_response.execution` | create | id, resource_id, rest_api_id |
| `aws_api_gateway_integration_response.integration_error` | create | id, resource_id, rest_api_id |
| `aws_api_gateway_method.post_orders` | create | id, request_validator_id, resource_id, rest_api_id |
| `aws_api_gateway_method_response.post_orders["200"]` | create | id, resource_id, rest_api_id |
| `aws_api_gateway_method_response.post_orders["422"]` | create | id, resource_id, rest_api_id |
| `aws_api_gateway_method_response.post_orders["500"]` | create | id, resource_id, rest_api_id |
| `aws_api_gateway_method_response.post_orders["504"]` | create | id, resource_id, rest_api_id |
| `aws_api_gateway_method_settings.all` | create | id, rest_api_id, settings |
| `aws_api_gateway_model.order` | create | id, rest_api_id |
| `aws_api_gateway_request_validator.body` | create | id, rest_api_id |
| `aws_api_gateway_resource.orders` | create | id, parent_id, path, rest_api_id |
| `aws_api_gateway_rest_api.orders` | create | api_key_source, arn, binary_media_types, created_date, description, disable_execute_api_endpoint, endpoint_configuration, execution_arn, id, minimum_compression_size, policy, root_resource_id, security_policy |
| `aws_api_gateway_stage.api` | create | access_log_settings, arn, deployment_id, execution_arn, id, invoke_url, rest_api_id, web_acl_arn |
| `aws_cloudwatch_log_group.api_access` | create | arn, deletion_protection_enabled, id, log_group_class, name_prefix |
| `aws_cloudwatch_log_group.workflow` | create | arn, deletion_protection_enabled, id, log_group_class, name_prefix |
| `aws_cloudwatch_metric_alarm.api_5xx` | create | alarm_actions, arn, evaluate_low_sample_count_percentiles, id, ok_actions |
| `aws_cloudwatch_metric_alarm.executions_timed_out` | create | alarm_actions, arn, dimensions, evaluate_low_sample_count_percentiles, id, ok_actions |
| `aws_iam_role.api` | create | arn, create_date, id, inline_policy, managed_policy_arns, name_prefix, unique_id |
| `aws_iam_role.workflow` | create | arn, create_date, id, inline_policy, managed_policy_arns, name_prefix, unique_id |
| `aws_iam_role_policy.api` | create | id, name_prefix, policy, role |
| `aws_iam_role_policy.workflow` | create | id, name_prefix, role |
| `aws_kms_key.alarms` | create | arn, id, key_id, multi_region, rotation_period_in_days |
| `aws_sfn_state_machine.orders` | create | arn, creation_date, description, encryption_configuration, id, logging_configuration, name_prefix, revision_id, role_arn, state_machine_version_arn, status, version_description |
| `aws_sns_topic.alarms` | create | arn, beginning_archive_time, fifo_throughput_scope, id, kms_master_key_id, maximum_message_size, name_prefix, owner, policy, signature_version, tracing_config |
