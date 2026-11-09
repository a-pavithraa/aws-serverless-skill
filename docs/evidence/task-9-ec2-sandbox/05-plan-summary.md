### Terraform plan: 20 to create

| Address | Action | Known after apply |
| --- | --- | --- |
| `aws_autoscaling_group.web` | create | arn, availability_zone_distribution, availability_zones, capacity_reservation_specification, default_cooldown, id, instance_lifecycle_policy, launch_template, load_balancers, mixed_instances_policy, name_prefix, predicted_capacity, service_linked_role_arn, target_group_arns, traffic_source, warm_pool_size |
| `aws_cloudwatch_log_group.app` | create | arn, deletion_protection_enabled, id, log_group_class, name_prefix |
| `aws_cloudwatch_metric_alarm.healthy_hosts` | create | alarm_actions, arn, dimensions, evaluate_low_sample_count_percentiles, id, ok_actions |
| `aws_cloudwatch_metric_alarm.target_5xx` | create | alarm_actions, arn, dimensions, evaluate_low_sample_count_percentiles, id, ok_actions |
| `aws_cloudwatch_metric_alarm.unhealthy_hosts` | create | alarm_actions, arn, dimensions, evaluate_low_sample_count_percentiles, id, ok_actions |
| `aws_iam_instance_profile.instances` | create | arn, create_date, id, name_prefix, unique_id |
| `aws_iam_role.instances` | create | arn, create_date, id, inline_policy, managed_policy_arns, name_prefix, unique_id |
| `aws_iam_role_policy.instances` | create | id, name_prefix, policy, role |
| `aws_kms_key.alarms` | create | arn, id, key_id, multi_region, rotation_period_in_days |
| `aws_launch_template.web` | create | arn, block_device_mappings, default_version, iam_instance_profile, id, latest_version, metadata_options, name_prefix, vpc_security_group_ids |
| `aws_lb.web` | create | arn, arn_suffix, dns_name, enable_prefix_for_ipv6_source_nat, enforce_security_group_inbound_rules_on_private_link_traffic, id, internal, ip_address_type, name_prefix, secondary_ips_auto_assigned_per_subnet, security_groups, subnet_mapping, vpc_id, zone_id |
| `aws_lb_listener.web` | create | arn, default_action, id, load_balancer_arn, mutual_authentication, routing_http_request_x_amzn_mtls_clientcert_header_name, routing_http_request_x_amzn_mtls_clientcert_issuer_header_name, routing_http_request_x_amzn_mtls_clientcert_leaf_header_name, routing_http_request_x_amzn_mtls_clientcert_serial_number_header_name, routing_http_request_x_amzn_mtls_clientcert_subject_header_name, routing_http_request_x_amzn_mtls_clientcert_validity_header_name, routing_http_request_x_amzn_tls_cipher_suite_header_name, routing_http_request_x_amzn_tls_version_header_name, routing_http_response_access_control_allow_credentials_header_value, routing_http_response_access_control_allow_headers_header_value, routing_http_response_access_control_allow_methods_header_value, routing_http_response_access_control_allow_origin_header_value, routing_http_response_access_control_expose_headers_header_value, routing_http_response_access_control_max_age_header_value, routing_http_response_content_security_policy_header_value, routing_http_response_server_enabled, routing_http_response_strict_transport_security_header_value, routing_http_response_x_content_type_options_header_value, routing_http_response_x_frame_options_header_value, ssl_policy, tcp_idle_timeout_seconds |
| `aws_lb_target_group.web` | create | arn, arn_suffix, connection_termination, health_check, id, ip_address_type, load_balancer_arns, load_balancing_algorithm_type, load_balancing_anomaly_mitigation, load_balancing_cross_zone_enabled, name_prefix, preserve_client_ip, protocol_version, stickiness, target_failover, target_group_health, target_health_state |
| `aws_security_group.alb` | create | arn, egress, id, ingress, name_prefix, owner_id |
| `aws_security_group.instances` | create | arn, egress, id, ingress, name_prefix, owner_id |
| `aws_sns_topic.alarms` | create | arn, beginning_archive_time, fifo_throughput_scope, id, kms_master_key_id, maximum_message_size, name_prefix, owner, policy, signature_version, tracing_config |
| `aws_vpc_security_group_egress_rule.alb_to_instances` | create | arn, id, referenced_security_group_id, security_group_id, security_group_rule_id |
| `aws_vpc_security_group_egress_rule.instances_https` | create | arn, id, security_group_id, security_group_rule_id |
| `aws_vpc_security_group_ingress_rule.alb_listener` | create | arn, id, security_group_id, security_group_rule_id |
| `aws_vpc_security_group_ingress_rule.instances_from_alb` | create | arn, id, referenced_security_group_id, security_group_id, security_group_rule_id |
