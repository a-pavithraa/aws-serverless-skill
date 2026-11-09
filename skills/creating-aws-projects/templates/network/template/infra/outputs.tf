output "account_id" {
  description = "Account the resources are in. The verifier compares it with the expected account."
  value       = data.aws_caller_identity.current.account_id
}

output "region" {
  description = "Region the resources are in. The verifier compares it with the expected region."
  value       = var.aws_region
}

output "network_name" {
  description = "Name that consumers set as network_name: <project_name>-<environment>."
  value       = local.name
}

output "vpc_id" {
  description = "ID of the VPC."
  value       = module.vpc.vpc_id
}

output "public_subnet_ids" {
  description = "Public subnet IDs, one for each Availability Zone."
  value       = module.vpc.public_subnets
}

output "private_subnet_ids" {
  description = "Private subnet IDs; empty when nat_mode is none."
  value       = module.vpc.private_subnets
}

output "availability_zones" {
  description = "Availability Zones the subnets are in."
  value       = local.azs
}

output "ssm_prefix" {
  description = "SSM path under which the network publishes its IDs for consumers."
  value       = local.ssm_prefix
}
