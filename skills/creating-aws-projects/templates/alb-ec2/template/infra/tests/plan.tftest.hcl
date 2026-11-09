mock_provider "aws" {
  override_during = plan

  mock_data "aws_caller_identity" {
    defaults = {
      account_id = "123456789012"
    }
  }

  mock_data "aws_default_tags" {
    defaults = {
      tags = { Project = "plan-test", Environment = "dev" }
    }
  }

  mock_data "aws_internet_gateway" {
    defaults = {
      id = "igw-0123456789abcdef0"
    }
  }

  mock_data "aws_iam_policy_document" {
    defaults = {
      json = "{\"Version\":\"2012-10-17\",\"Statement\":[]}"
    }
  }

  mock_data "aws_ssm_parameter" {
    defaults = {
      value = "ami-0123456789abcdef0"
    }
  }

  mock_data "aws_subnet" {
    defaults = {
      vpc_id = "vpc-0123456789abcdef0"
    }
  }

  mock_resource "aws_cloudwatch_log_group" {
    defaults = {
      arn = "arn:aws:logs:us-east-1:123456789012:log-group:mock"
    }
  }

  mock_resource "aws_iam_role" {
    defaults = {
      arn = "arn:aws:iam::123456789012:role/mock"
    }
  }

  mock_resource "aws_iam_instance_profile" {
    defaults = {
      arn = "arn:aws:iam::123456789012:instance-profile/mock"
    }
  }

  mock_resource "aws_launch_template" {
    defaults = {
      id             = "lt-0123456789abcdef0"
      latest_version = 1
    }
  }

  mock_resource "aws_lb" {
    defaults = {
      arn        = "arn:aws:elasticloadbalancing:us-east-1:123456789012:loadbalancer/app/mock/0123456789abcdef"
      arn_suffix = "app/mock/0123456789abcdef"
    }
  }

  mock_resource "aws_lb_target_group" {
    defaults = {
      arn        = "arn:aws:elasticloadbalancing:us-east-1:123456789012:targetgroup/mock/0123456789abcdef"
      arn_suffix = "targetgroup/mock/0123456789abcdef"
    }
  }

  mock_resource "aws_sns_topic" {
    defaults = {
      arn = "arn:aws:sns:us-east-1:123456789012:mock-alarms"
    }
  }

  mock_resource "aws_kms_key" {
    defaults = {
      arn = "arn:aws:kms:us-east-1:123456789012:key/00000000-0000-0000-0000-000000000000"
    }
  }
}

override_data {
  target = data.aws_subnet.all["subnet-0aaaaaaaaaaaaaaaa"]
  values = {
    vpc_id            = "vpc-0123456789abcdef0"
    availability_zone = "us-east-1a"
  }
}

override_data {
  target = data.aws_subnet.all["subnet-0bbbbbbbbbbbbbbbb"]
  values = {
    vpc_id            = "vpc-0123456789abcdef0"
    availability_zone = "us-east-1b"
  }
}

variables {
  project_name       = "plan-test"
  environment        = "dev"
  aws_region         = "us-east-1"
  log_retention_days = 14
  plain_http_reason  = "plan test without a domain"
  subnet_ids         = ["subnet-0aaaaaaaaaaaaaaaa", "subnet-0bbbbbbbbbbbbbbbb"]
}

run "fleet_defaults" {
  command = plan

  assert {
    condition     = aws_launch_template.web.image_id == "ami-0123456789abcdef0"
    error_message = "The launch template must use the AMI that the SSM parameter names."
  }

  assert {
    condition     = aws_launch_template.web.metadata_options[0].http_tokens == "required"
    error_message = "Instances must require IMDSv2."
  }

  assert {
    condition     = aws_launch_template.web.block_device_mappings[0].ebs[0].encrypted == "true"
    error_message = "The root volume must be encrypted."
  }

  assert {
    condition     = aws_autoscaling_group.web.health_check_type == "ELB" && aws_autoscaling_group.web.min_size == 2
    error_message = "The group must replace instances that fail the load balancer health check, with two or more running."
  }

  assert {
    condition     = aws_autoscaling_group.web.instance_refresh[0].preferences[0].min_healthy_percentage == 100 && aws_autoscaling_group.web.instance_refresh[0].preferences[0].auto_rollback
    error_message = "A refresh must add before it removes, and roll back when new instances stay unhealthy."
  }

  assert {
    condition     = contains(aws_autoscaling_group.web.instance_refresh[0].preferences[0].alarm_specification[0].alarms, "plan-test-dev-unhealthy-hosts")
    error_message = "A refresh whose new instances stay unhealthy only fails, and rolls back, when it watches the unhealthy-hosts alarm (seen in the sandbox: it waited 40 minutes)."
  }

  assert {
    condition     = aws_lb_target_group.web.health_check[0].path == "/health"
    error_message = "The target group must check /health."
  }

  assert {
    condition     = aws_lb_listener.web.protocol == "HTTP" && aws_lb.web.tags["PlainHttpReason"] == "plan test without a domain"
    error_message = "Without a certificate the listener is HTTP, and the load balancer records why."
  }

  assert {
    condition     = aws_launch_template.web.network_interfaces[0].associate_public_ip_address == "true" && aws_launch_template.web.vpc_security_group_ids == null
    error_message = "Instances need a public address to reach the package repositories, whatever the subnet's default; the security group goes on the interface."
  }

  assert {
    condition     = strcontains(base64decode(aws_launch_template.web.user_data), "/opt/app/server.py") && !strcontains(base64decode(aws_launch_template.web.user_data), "/opt/app/tests/")
    error_message = "User data must install app/ without its tests."
  }
}

run "https_with_a_certificate" {
  command = plan

  variables {
    certificate_arn   = "arn:aws:acm:us-east-1:123456789012:certificate/00000000-0000-0000-0000-000000000000"
    plain_http_reason = ""
  }

  assert {
    condition     = aws_lb_listener.web.protocol == "HTTPS" && aws_lb_listener.web.port == 443
    error_message = "With a certificate the listener is HTTPS on 443."
  }
}

run "plain_http_needs_a_reason" {
  command = plan

  variables {
    plain_http_reason = ""
  }

  expect_failures = [var.plain_http_reason]
}

run "rejects_an_x86_instance_type" {
  command = plan

  variables {
    instance_type = "t3.micro"
  }

  expect_failures = [var.instance_type]
}

run "network_name_reads_the_public_subnets_from_ssm" {
  command = plan

  variables {
    network_name = "shared-dev"
    subnet_ids   = []
  }

  override_data {
    target = data.aws_ssm_parameter.public_subnets[0]
    values = {
      value = "subnet-0aaaaaaaaaaaaaaaa,subnet-0bbbbbbbbbbbbbbbb"
    }
  }

  assert {
    condition     = join(",", local.subnet_ids) == "subnet-0aaaaaaaaaaaaaaaa,subnet-0bbbbbbbbbbbbbbbb"
    error_message = "network_name must take the subnets from /landform/network/<name>/public-subnet-ids."
  }

  assert {
    condition     = join(",", aws_autoscaling_group.web.vpc_zone_identifier) == "subnet-0aaaaaaaaaaaaaaaa,subnet-0bbbbbbbbbbbbbbbb"
    error_message = "The instances must run in the network's subnets."
  }
}

run "rejects_both_subnet_ids_and_network_name" {
  command = plan

  variables {
    network_name = "shared-dev"
    subnet_ids   = ["subnet-0aaaaaaaaaaaaaaaa", "subnet-0bbbbbbbbbbbbbbbb"]
  }

  expect_failures = [var.network_name]
}

run "needs_a_network_or_subnets" {
  command = plan

  variables {
    subnet_ids = []
  }

  expect_failures = [var.network_name]
}

run "rejects_a_name_too_long_for_the_load_balancer" {
  command = plan

  variables {
    project_name = "a-project-name-of-thirty-chars"
  }

  expect_failures = [var.environment]
}

run "rejects_subnets_in_one_zone" {
  command = plan

  override_data {
    target = data.aws_subnet.all["subnet-0bbbbbbbbbbbbbbbb"]
    values = {
      vpc_id            = "vpc-0123456789abcdef0"
      availability_zone = "us-east-1a"
    }
  }

  expect_failures = [aws_lb.web]
}

run "rejects_subnets_from_two_vpcs" {
  command = plan

  override_data {
    target = data.aws_subnet.all["subnet-0bbbbbbbbbbbbbbbb"]
    values = {
      vpc_id            = "vpc-0fedcba9876543210"
      availability_zone = "us-east-1b"
    }
  }

  expect_failures = [data.aws_subnet.all]
}
