### Terraform plan: 16 to create

| Address | Action | Known after apply |
| --- | --- | --- |
| `aws_cloudwatch_dashboard.service` | create | dashboard_arn, id |
| `aws_cloudwatch_log_group.lambda` | create | arn, deletion_protection_enabled, id, log_group_class, name_prefix |
| `aws_cloudwatch_metric_alarm.dead_letter_messages` | create | alarm_actions, arn, evaluate_low_sample_count_percentiles, id, ok_actions |
| `aws_cloudwatch_metric_alarm.lambda_errors` | create | alarm_actions, arn, evaluate_low_sample_count_percentiles, id, ok_actions |
| `aws_cloudwatch_metric_alarm.oldest_message_age` | create | alarm_actions, arn, evaluate_low_sample_count_percentiles, id, ok_actions |
| `aws_dynamodb_table.idempotency` | create | arn, global_secondary_index, global_table_witness, id, point_in_time_recovery, read_capacity, server_side_encryption, stream_arn, stream_label, stream_view_type, warm_throughput, write_capacity |
| `aws_iam_role.lambda` | create | arn, create_date, id, inline_policy, managed_policy_arns, name_prefix, unique_id |
| `aws_iam_role_policy.lambda` | create | id, name_prefix, policy, role |
| `aws_kms_key.alarms` | create | arn, id, key_id, multi_region, rotation_period_in_days |
| `aws_lambda_alias.live` | create | arn, function_version, id, invoke_arn |
| `aws_lambda_event_source_mapping.orders` | create | amazon_managed_kafka_event_source_config, arn, event_source_arn, function_arn, function_name, id, last_modified, last_processing_result, maximum_record_age_in_seconds, maximum_retry_attempts, parallelization_factor, self_managed_kafka_event_source_config, state, state_transition_reason, uuid |
| `aws_lambda_function.worker` | create | arn, code_sha256, ephemeral_storage, id, invoke_arn, last_modified, qualified_arn, qualified_invoke_arn, response_streaming_invoke_arn, role, signing_job_arn, signing_profile_version_arn, source_code_size, version |
| `aws_sns_topic.alarms` | create | arn, beginning_archive_time, fifo_throughput_scope, id, kms_master_key_id, maximum_message_size, name_prefix, owner, policy, signature_version, tracing_config |
| `aws_sqs_queue.dead_letter` | create | arn, deduplication_scope, fifo_throughput_limit, id, name_prefix, policy, redrive_allow_policy, redrive_policy, url |
| `aws_sqs_queue.orders` | create | arn, deduplication_scope, fifo_throughput_limit, id, name_prefix, policy, redrive_allow_policy, redrive_policy, url |
| `aws_sqs_queue_redrive_allow_policy.dead_letter` | create | id, queue_url, redrive_allow_policy |
