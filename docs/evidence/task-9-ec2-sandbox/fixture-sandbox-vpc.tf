# Sandbox network for template deployments: a VPC with an internet gateway and two public subnets.
# Use it when the account's default VPC is missing or has no internet gateway; pass the subnet_ids
# output to a template. Destroy it after the template's own resources are gone.
terraform {
  required_version = ">= 1.10.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = ">= 6.72.0, < 7.0.0"
    }
  }
}

variable "aws_region" {
  type    = string
  default = "us-east-1"
}

variable "allowed_account_id" {
  type = string
}

variable "zones" {
  type        = list(string)
  default     = ["us-east-1a", "us-east-1b"]
  description = "Two zones that offer the instance types the templates use (t4g, Fargate arm64)."
}

provider "aws" {
  region              = var.aws_region
  allowed_account_ids = [var.allowed_account_id]

  default_tags {
    tags = { Project = "lf-sandbox-net", Environment = "sandbox", ManagedBy = "terraform" }
  }
}

resource "aws_vpc" "sandbox" {
  cidr_block           = "10.42.0.0/16"
  enable_dns_hostnames = true
  tags                 = { Name = "lf-sandbox-net" }
}

resource "aws_internet_gateway" "sandbox" {
  vpc_id = aws_vpc.sandbox.id
}

resource "aws_subnet" "public" {
  count                   = length(var.zones)
  vpc_id                  = aws_vpc.sandbox.id
  availability_zone       = var.zones[count.index]
  cidr_block              = cidrsubnet(aws_vpc.sandbox.cidr_block, 8, count.index)
  map_public_ip_on_launch = true
  tags                    = { Name = "lf-sandbox-net-${var.zones[count.index]}" }
}

resource "aws_route_table" "public" {
  vpc_id = aws_vpc.sandbox.id

  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.sandbox.id
  }
}

resource "aws_route_table_association" "public" {
  count          = length(aws_subnet.public)
  subnet_id      = aws_subnet.public[count.index].id
  route_table_id = aws_route_table.public.id
}

output "subnet_ids" {
  value = aws_subnet.public[*].id
}
