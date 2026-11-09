mock_provider "aws" {
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
}

variables {
  project_name       = "plan-test"
  environment        = "dev"
  aws_region         = "us-east-1"
  auth_mode          = "iam"
  log_retention_days = 14
}

run "iam_route_defaults" {
  command = plan

  assert {
    condition     = aws_apigatewayv2_route.hello.authorization_type == "AWS_IAM"
    error_message = "auth_mode = iam must put AWS_IAM on the route."
  }

  assert {
    condition     = aws_lambda_function.api.runtime == "python3.13" && aws_lambda_function.api.architectures == tolist(["arm64"])
    error_message = "The tested runtime profile is python3.13 on arm64."
  }

  assert {
    condition     = aws_lambda_function.api.tracing_config[0].mode == "Active"
    error_message = "Active tracing must be on."
  }

  assert {
    condition     = aws_lambda_function.api.logging_config[0].log_format == "JSON" && aws_lambda_function.api.logging_config[0].log_group == "/aws/lambda/plan-test-dev"
    error_message = "The function must log JSON to the Terraform-managed log group."
  }

  assert {
    condition     = aws_cloudwatch_log_group.lambda.retention_in_days == 14 && aws_cloudwatch_log_group.api_access.retention_in_days == 14
    error_message = "Every log group needs explicit retention."
  }

  assert {
    condition     = aws_lambda_function.api.publish && aws_lambda_permission.api.qualifier == "live"
    error_message = "The API must invoke a published version through the live alias."
  }

  assert {
    condition     = !contains(keys(aws_apigatewayv2_api.http.tags), "PublicReason")
    error_message = "An IAM-authorised API carries no PublicReason tag."
  }

  assert {
    condition     = length(aws_sns_topic_subscription.alarm_email) == 0
    error_message = "No email subscription without alarm_email."
  }
}

run "public_route_without_reason_is_rejected" {
  command = plan

  variables {
    auth_mode = "none"
  }

  expect_failures = [var.public_reason]
}

run "public_route_with_reason" {
  command = plan

  variables {
    auth_mode     = "none"
    public_reason = "Public health endpoint for the status page"
  }

  assert {
    condition     = aws_apigatewayv2_route.hello.authorization_type == "NONE"
    error_message = "auth_mode = none must leave the route unauthenticated."
  }

  assert {
    condition     = aws_apigatewayv2_api.http.tags["PublicReason"] == "Public health endpoint for the status page"
    error_message = "A public API records its reason as a tag."
  }
}

run "unsupported_retention_is_rejected" {
  command = plan

  variables {
    log_retention_days = 10
  }

  expect_failures = [var.log_retention_days]
}

run "timeout_above_api_limit_is_rejected" {
  command = plan

  variables {
    lambda_timeout_seconds = 30
  }

  expect_failures = [var.lambda_timeout_seconds]
}
