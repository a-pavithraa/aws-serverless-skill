mock_provider "aws" {
  override_during = plan

  mock_data "aws_caller_identity" {
    defaults = {
      account_id = "123456789012"
    }
  }

  mock_data "aws_availability_zones" {
    defaults = {
      names = ["us-east-1a", "us-east-1b", "us-east-1c", "us-east-1e"]
    }
  }

  mock_data "aws_ec2_instance_type_offerings" {
    defaults = {
      locations = ["us-east-1a", "us-east-1b", "us-east-1c"]
    }
  }

  mock_data "aws_iam_policy_document" {
    defaults = {
      json = "{\"Version\":\"2012-10-17\",\"Statement\":[]}"
    }
  }

  mock_resource "aws_iam_role" {
    defaults = {
      arn = "arn:aws:iam::123456789012:role/mock"
    }
  }

  mock_resource "aws_cloudwatch_log_group" {
    defaults = {
      arn = "arn:aws:logs:us-east-1:123456789012:log-group:mock"
    }
  }

  mock_resource "aws_vpc" {
    defaults = {
      id  = "vpc-0123456789abcdef0"
      arn = "arn:aws:ec2:us-east-1:123456789012:vpc/vpc-0123456789abcdef0"
    }
  }
}

variables {
  project_name       = "plan-test"
  environment        = "dev"
  aws_region         = "us-east-1"
  log_retention_days = 14
}

run "public_only_by_default" {
  command = plan

  assert {
    condition     = join(",", local.azs) == "us-east-1a,us-east-1b"
    error_message = "Subnets go in the first zones that offer zone_instance_type; us-east-1e does not."
  }

  assert {
    condition     = length(module.vpc.natgw_ids) == 0 && length(aws_ssm_parameter.private_subnet_ids) == 0
    error_message = "nat_mode none must create no NAT gateway and publish no private subnets."
  }

  assert {
    condition     = aws_ssm_parameter.public_subnet_ids.name == "/landform/network/plan-test-dev/public-subnet-ids" && aws_ssm_parameter.public_subnet_ids.type == "StringList"
    error_message = "Services find the public subnets at /landform/network/<name>/public-subnet-ids."
  }

  assert {
    condition     = aws_ssm_parameter.nat_mode.value == "none"
    error_message = "The NAT mode is published so services can tell public-only networks apart."
  }
}

run "pinned_zones_win" {
  command = plan

  variables {
    zones = ["us-east-1c", "us-east-1a"]
  }

  assert {
    condition     = join(",", local.azs) == "us-east-1c,us-east-1a"
    error_message = "Pinned zones must be used as given, so a change in AWS's zone list never moves subnets."
  }
}

run "single_nat_gateway" {
  command = plan

  variables {
    nat_mode = "single"
  }

  assert {
    condition     = length(aws_ssm_parameter.private_subnet_ids) == 1
    error_message = "nat_mode single must publish the private subnets."
  }
}

run "rejects_one_zone" {
  command = plan

  variables {
    az_count = 1
  }

  expect_failures = [var.az_count]
}

run "rejects_a_cidr_too_small_for_its_subnets" {
  command = plan

  variables {
    cidr = "10.42.0.0/24"
  }

  expect_failures = [var.cidr]
}
