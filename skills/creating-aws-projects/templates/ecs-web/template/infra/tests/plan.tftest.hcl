mock_provider "aws" {
  override_during = plan

  mock_resource "aws_secretsmanager_secret" {
    defaults = {
      arn = "arn:aws:secretsmanager:us-east-1:123456789012:secret:plan-test-dev/app-AbCdEf"
    }
  }

  mock_data "aws_subnet" {
    defaults = {
      vpc_id = "vpc-0123456789abcdef0"
    }
  }

  mock_data "aws_caller_identity" {
    defaults = {
      account_id = "123456789012"
    }
  }

  mock_data "aws_iam_policy_document" {
    defaults = {
      json = "{\"Version\":\"2012-10-17\",\"Statement\":[]}"
    }
  }

  mock_resource "aws_ecr_repository" {
    defaults = {
      arn            = "arn:aws:ecr:us-east-1:123456789012:repository/plan-test-dev"
      repository_url = "123456789012.dkr.ecr.us-east-1.amazonaws.com/plan-test-dev"
    }
  }

  mock_resource "aws_iam_role" {
    defaults = {
      arn = "arn:aws:iam::123456789012:role/mock"
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
  subnet_ids         = ["subnet-0aaaaaaaaaaaaaaaa", "subnet-0bbbbbbbbbbbbbbbb"]
}

run "repository_only_without_a_digest" {
  command = plan

  assert {
    condition     = length(aws_ecs_express_gateway_service.web) == 0
    error_message = "Without image_digest the plan must create the repository only, so the first image can be pushed."
  }

  assert {
    condition     = aws_ecr_repository.app.image_tag_mutability == "IMMUTABLE"
    error_message = "Image tags must be immutable, so a tag always names the same digest."
  }

  assert {
    condition     = aws_ecr_repository.app.image_scanning_configuration[0].scan_on_push
    error_message = "Images must be scanned on push."
  }
}

run "service_runs_the_digest" {
  command = plan

  variables {
    image_digest = "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
  }

  assert {
    condition     = endswith(aws_ecs_express_gateway_service.web[0].primary_container[0].image, "@sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa")
    error_message = "The service must run the image by digest."
  }

  assert {
    condition     = aws_ecs_express_gateway_service.web[0].cpu_architecture == "ARM64"
    error_message = "The profile is arm64; the image is built for linux/arm64."
  }

  assert {
    condition     = aws_ecs_express_gateway_service.web[0].health_check_path == "/health"
    error_message = "The load balancer must check /health."
  }

  assert {
    condition     = aws_ecs_express_gateway_service.web[0].wait_for_steady_state
    error_message = "Apply must wait for a steady state, so a failed rollout fails the apply."
  }

  assert {
    condition     = aws_ecs_express_gateway_service.web[0].primary_container[0].aws_logs_configuration[0].log_group == "/ecs/plan-test-dev"
    error_message = "Container logs must go to the log group with the chosen retention."
  }

  assert {
    condition     = length(aws_cloudwatch_metric_alarm.running_tasks) == 1 && length(aws_cloudwatch_metric_alarm.cpu_high) == 1
    error_message = "A deployed service needs the running-task and CPU alarms."
  }
}

run "rejects_a_tag_instead_of_a_digest" {
  command = plan

  variables {
    image_digest = "latest"
  }

  expect_failures = [var.image_digest]
}

run "rejects_memory_fargate_does_not_accept" {
  command = plan

  variables {
    cpu    = 256
    memory = 4096
  }

  expect_failures = [var.memory]
}

run "rejects_min_tasks_above_max" {
  command = plan

  variables {
    min_tasks = 3
    max_tasks = 2
  }

  expect_failures = [var.max_tasks]
}

run "needs_a_network_or_subnets" {
  command = plan

  variables {
    subnet_ids = []
  }

  expect_failures = [var.network_name]
}

run "longest_names_fit_iam" {
  command = plan

  variables {
    project_name = "a-project-name-of-thirty-two-ch"
    environment  = "sixteencharsenvx"
  }

  assert {
    condition     = length(aws_iam_role.infrastructure.name) <= 64 && length(aws_iam_role.execution.name) <= 64 && length(aws_iam_role.task.name) <= 64
    error_message = "IAM role names allow at most 64 characters, for the longest project_name and environment."
  }
}

run "network_name_reads_the_public_subnets_from_ssm" {
  command = plan

  variables {
    network_name = "shared-dev"
    subnet_ids   = []
    image_digest = "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
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
    condition     = length(aws_ecs_express_gateway_service.web[0].network_configuration) == 1
    error_message = "The service must run in the network's subnets."
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

run "rejects_subnets_in_one_zone" {
  command = plan

  variables {
    image_digest = "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
  }

  override_data {
    target = data.aws_subnet.all["subnet-0bbbbbbbbbbbbbbbb"]
    values = {
      vpc_id            = "vpc-0123456789abcdef0"
      availability_zone = "us-east-1a"
    }
  }

  expect_failures = [aws_ecs_express_gateway_service.web]
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

run "no_secrets_by_default" {
  command = plan

  variables {
    image_digest = "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
  }

  assert {
    condition     = length(aws_secretsmanager_secret.app) == 0 && length(aws_ecs_express_gateway_service.web[0].primary_container[0].secret) == 0
    error_message = "Without secret_names the template creates no secret and injects none."
  }
}

run "secrets_come_from_secrets_manager" {
  command = plan

  variables {
    image_digest    = "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    secret_names    = ["DB_PASSWORD", "API_TOKEN"]
    app_environment = { FEATURE_FLAG = "on" }
  }

  assert {
    condition = (
      [for s in aws_ecs_express_gateway_service.web[0].primary_container[0].secret : "${s.name}=${s.value_from}"]
      == ["DB_PASSWORD=arn:aws:secretsmanager:us-east-1:123456789012:secret:plan-test-dev/app-AbCdEf:DB_PASSWORD::",
      "API_TOKEN=arn:aws:secretsmanager:us-east-1:123456789012:secret:plan-test-dev/app-AbCdEf:API_TOKEN::"]
    )
    error_message = "Each secret name must be injected from one JSON key of the project's secret, through the secret block."
  }

  assert {
    condition = alltrue([for e in aws_ecs_express_gateway_service.web[0].primary_container[0].environment :
    !contains(["DB_PASSWORD", "API_TOKEN"], e.name)])
    error_message = "A secret must never be a plain environment variable: anyone with ecs:DescribeTaskDefinition can read those."
  }

  assert {
    condition     = contains([for e in aws_ecs_express_gateway_service.web[0].primary_container[0].environment : "${e.name}=${e.value}"], "SECRET_NAMES=DB_PASSWORD,API_TOKEN") && contains([for e in aws_ecs_express_gateway_service.web[0].primary_container[0].environment : "${e.name}=${e.value}"], "FEATURE_FLAG=on")
    error_message = "The app gets SECRET_NAMES and the plain settings as environment variables."
  }

  assert {
    condition = contains(flatten([for st in data.aws_iam_policy_document.execution.statement : st.resources if contains(st.actions, "secretsmanager:GetSecretValue")]),
    "arn:aws:secretsmanager:us-east-1:123456789012:secret:plan-test-dev/app-AbCdEf")
    error_message = "The execution role may read the project's secret, and only it."
  }
}

run "rejects_a_secret_looking_plain_setting" {
  command = plan

  variables {
    app_environment = { DB_PASSWORD = "hunter2" }
  }

  expect_failures = [var.app_environment]
}

run "rejects_a_plain_setting_that_is_a_listed_secret" {
  command = plan

  variables {
    secret_names    = ["APP_CONFIG"]
    app_environment = { APP_CONFIG = "x" }
  }

  expect_failures = [var.app_environment]
}

run "rejects_a_secret_name_that_is_not_an_environment_variable_name" {
  command = plan

  variables {
    secret_names = ["db-password"]
  }

  expect_failures = [var.secret_names]
}
