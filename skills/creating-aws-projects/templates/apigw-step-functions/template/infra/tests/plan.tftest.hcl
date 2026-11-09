mock_provider "aws" {
  override_during = plan

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

  mock_resource "aws_sfn_state_machine" {
    defaults = {
      arn = "arn:aws:states:us-east-1:123456789012:stateMachine:plan-test-dev"
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

variables {
  project_name       = "plan-test"
  environment        = "dev"
  aws_region         = "us-east-1"
  auth_mode          = "iam"
  log_retention_days = 14
}

run "sync_express_workflow" {
  command = plan

  assert {
    condition     = aws_sfn_state_machine.orders.type == "EXPRESS"
    error_message = "StartSyncExecution runs Express workflows only."
  }

  assert {
    condition     = jsondecode(aws_sfn_state_machine.orders.definition).TimeoutSeconds < 29
    error_message = "The workflow must time out before API Gateway's 29 s integration timeout."
  }

  assert {
    condition     = aws_sfn_state_machine.orders.logging_configuration[0].level == "ALL" && !aws_sfn_state_machine.orders.logging_configuration[0].include_execution_data
    error_message = "Express workflows keep no history, so every event is logged; but not the order body, which can hold customer data."
  }

  assert {
    condition     = strcontains(aws_api_gateway_integration.start_sync.request_templates["application/json"], "\"name\": \"$cid\"")
    error_message = "The execution is named by the correlation ID, so every log event's execution_arn carries it without logging the input."
  }

  assert {
    condition     = endswith(aws_api_gateway_integration.start_sync.uri, ":states:action/StartSyncExecution")
    error_message = "The API must wait for the execution with StartSyncExecution."
  }

  assert {
    condition     = aws_api_gateway_method.post_orders.authorization == "AWS_IAM"
    error_message = "auth_mode iam must require SigV4."
  }

  assert {
    condition     = length(regexall("responseOverride.status = 504", aws_api_gateway_integration_response.execution.response_templates["application/json"])) == 1
    error_message = "A timed-out execution must answer 504, not 200."
  }

  assert {
    condition     = length(regexall("responseOverride.status = 422", aws_api_gateway_integration_response.execution.response_templates["application/json"])) == 1
    error_message = "A rejected order must answer 422, not 200."
  }
}

run "public_api_needs_a_reason" {
  command = plan

  variables {
    auth_mode = "none"
  }

  expect_failures = [var.public_reason]
}

run "public_api_with_a_reason" {
  command = plan

  variables {
    auth_mode     = "none"
    public_reason = "status page reads only public data"
  }

  assert {
    condition     = aws_api_gateway_method.post_orders.authorization == "NONE" && aws_api_gateway_rest_api.orders.tags["PublicReason"] == "status page reads only public data"
    error_message = "A public API records why it is public."
  }
}
