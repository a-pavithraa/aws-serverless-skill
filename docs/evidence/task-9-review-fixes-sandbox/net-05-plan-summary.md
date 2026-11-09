### Terraform plan: 19 to create

| Address | Action | Known after apply |
| --- | --- | --- |
| `aws_ssm_parameter.nat_mode` | create | arn, data_type, has_value_wo, id, insecure_value, key_id, tier, version |
| `aws_ssm_parameter.public_subnet_ids` | create | arn, data_type, has_value_wo, id, insecure_value, key_id, tier, value, version |
| `aws_ssm_parameter.vpc_id` | create | arn, data_type, has_value_wo, id, insecure_value, key_id, tier, value, version |
| `module.vpc.aws_cloudwatch_log_group.flow_log[0]` | create | arn, deletion_protection_enabled, id, log_group_class, name, name_prefix |
| `module.vpc.aws_default_network_acl.this[0]` | create | arn, default_network_acl_id, id, owner_id, vpc_id |
| `module.vpc.aws_default_route_table.default[0]` | create | arn, default_route_table_id, id, owner_id, route, vpc_id |
| `module.vpc.aws_default_security_group.this[0]` | create | arn, description, egress, id, ingress, name, name_prefix, owner_id, vpc_id |
| `module.vpc.aws_flow_log.this[0]` | create | arn, iam_role_arn, id, log_destination, log_format, vpc_id |
| `module.vpc.aws_iam_policy.vpc_flow_log_cloudwatch[0]` | create | arn, attachment_count, id, name, policy, policy_id |
| `module.vpc.aws_iam_role.vpc_flow_log_cloudwatch[0]` | create | arn, create_date, id, inline_policy, managed_policy_arns, name, unique_id |
| `module.vpc.aws_iam_role_policy_attachment.vpc_flow_log_cloudwatch[0]` | create | id, policy_arn, role |
| `module.vpc.aws_internet_gateway.this[0]` | create | arn, id, owner_id, vpc_id |
| `module.vpc.aws_route.public_internet_gateway[0]` | create | gateway_id, id, instance_id, instance_owner_id, network_interface_id, origin, route_table_id, state |
| `module.vpc.aws_route_table.public[0]` | create | arn, id, owner_id, propagating_vgws, route, vpc_id |
| `module.vpc.aws_route_table_association.public[0]` | create | id, route_table_id, subnet_id |
| `module.vpc.aws_route_table_association.public[1]` | create | id, route_table_id, subnet_id |
| `module.vpc.aws_subnet.public[0]` | create | arn, availability_zone_id, id, ipv6_cidr_block, ipv6_cidr_block_association_id, owner_id, private_dns_hostname_type_on_launch, vpc_id |
| `module.vpc.aws_subnet.public[1]` | create | arn, availability_zone_id, id, ipv6_cidr_block, ipv6_cidr_block_association_id, owner_id, private_dns_hostname_type_on_launch, vpc_id |
| `module.vpc.aws_vpc.this[0]` | create | arn, default_network_acl_id, default_route_table_id, default_security_group_id, dhcp_options_id, enable_network_address_usage_metrics, id, ipv6_association_id, ipv6_cidr_block, ipv6_cidr_block_network_border_group, main_route_table_id, owner_id |
