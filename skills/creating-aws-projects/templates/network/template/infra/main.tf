data "aws_caller_identity" "current" {}

locals {
  name       = "${var.project_name}-${var.environment}"
  ssm_prefix = "/landform/network/${local.name}"
  private    = var.nat_mode != "none"
  # Changing a zone replaces its subnets and everything in them. The lookup only picks the first
  # zones for a new network; pin them in zones after the first apply (availability_zones output).
  azs = length(var.zones) > 0 ? var.zones : slice(sort(tolist(setintersection(
  data.aws_availability_zones.available.names, data.aws_ec2_instance_type_offerings.zones.locations))), 0, var.az_count)
}

data "aws_availability_zones" "available" {
  state = "available"

  filter {
    name   = "opt-in-status"
    values = ["opt-in-not-required"]
  }
}

data "aws_ec2_instance_type_offerings" "zones" {
  location_type = "availability-zone"

  filter {
    name   = "instance-type"
    values = [var.zone_instance_type]
  }
}

module "vpc" {
  # terraform-aws-modules/vpc/aws 6.7.3, pinned to the tag's commit: a registry version can be re-pointed.
  source = "git::https://github.com/terraform-aws-modules/terraform-aws-vpc.git?ref=b3abd6df2ecf052451a361ed55b8f06f8742a795"

  name = local.name
  cidr = var.cidr
  azs  = local.azs

  public_subnets  = [for i in range(var.az_count) : cidrsubnet(var.cidr, 24 - tonumber(split("/", var.cidr)[1]), i)]
  private_subnets = local.private ? [for i in range(var.az_count) : cidrsubnet(var.cidr, 24 - tonumber(split("/", var.cidr)[1]), i + 10)] : []

  # Instances in public subnets need a public address to reach package repositories without NAT.
  map_public_ip_on_launch = true
  enable_dns_hostnames    = true
  enable_dns_support      = true

  enable_nat_gateway     = local.private
  single_nat_gateway     = var.nat_mode == "single"
  one_nat_gateway_per_az = var.nat_mode == "per-az"

  manage_default_security_group  = true
  default_security_group_ingress = []
  default_security_group_egress  = []

  enable_flow_log                                 = true
  create_flow_log_cloudwatch_log_group            = true
  create_flow_log_cloudwatch_iam_role             = true
  flow_log_cloudwatch_log_group_retention_in_days = var.log_retention_days
  flow_log_max_aggregation_interval               = 600
}

# Services read these at plan time (network_name). The parameters are not secret.
resource "aws_ssm_parameter" "vpc_id" {
  name  = "${local.ssm_prefix}/vpc-id"
  type  = "String"
  value = module.vpc.vpc_id
}

resource "aws_ssm_parameter" "public_subnet_ids" {
  name  = "${local.ssm_prefix}/public-subnet-ids"
  type  = "StringList"
  value = join(",", module.vpc.public_subnets)
}

resource "aws_ssm_parameter" "private_subnet_ids" {
  count = local.private ? 1 : 0
  name  = "${local.ssm_prefix}/private-subnet-ids"
  type  = "StringList"
  value = join(",", module.vpc.private_subnets)
}

resource "aws_ssm_parameter" "nat_mode" {
  name  = "${local.ssm_prefix}/nat-mode"
  type  = "String"
  value = var.nat_mode
}
