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

  mock_data "aws_ssm_parameter" {
    defaults = {
      value = "arn:aws:lambda:us-east-1:017000801446:layer:AWSLambdaPowertoolsPythonV3-python313-arm64:1"
    }
  }

  mock_resource "aws_sqs_queue" {
    defaults = {
      arn = "arn:aws:sqs:us-east-1:123456789012:mock-queue"
    }
  }
}

variables {
  project_name       = "plan-test"
  environment        = "dev"
  aws_region         = "us-east-1"
  log_retention_days = 14
}

run "worker_defaults" {
  command = plan

  assert {
    condition     = aws_sqs_queue.orders.visibility_timeout_seconds >= 6 * aws_lambda_function.worker.timeout
    error_message = "The queue's visibility timeout must be at least six times the function timeout."
  }

  assert {
    condition     = jsondecode(aws_sqs_queue.orders.redrive_policy).maxReceiveCount == 3 && jsondecode(aws_sqs_queue.orders.redrive_policy).deadLetterTargetArn == aws_sqs_queue.dead_letter.arn
    error_message = "Messages must move to the dead-letter queue after max_receive_count deliveries."
  }

  assert {
    condition     = contains(aws_lambda_event_source_mapping.orders.function_response_types, "ReportBatchItemFailures")
    error_message = "The event source must report partial batch failures, or one bad message retries the whole batch."
  }

  assert {
    condition     = aws_lambda_event_source_mapping.orders.scaling_config[0].maximum_concurrency == 2
    error_message = "The event source caps concurrency at max_concurrency."
  }

  assert {
    condition     = length(aws_lambda_function.worker.dead_letter_config) == 0
    error_message = "A function dead_letter_config does not apply to SQS event sources; use the queue's redrive policy."
  }

  assert {
    condition     = aws_lambda_function.worker.runtime == "python3.13" && aws_lambda_function.worker.architectures == tolist(["arm64"])
    error_message = "The tested runtime profile is python3.13 on arm64."
  }

  assert {
    condition     = aws_lambda_function.worker.tracing_config[0].mode == "Active" && aws_lambda_function.worker.logging_config[0].log_format == "JSON"
    error_message = "Active tracing and JSON logs must be on."
  }

  assert {
    condition     = aws_sqs_queue.orders.sqs_managed_sse_enabled && aws_sqs_queue.dead_letter.sqs_managed_sse_enabled
    error_message = "Both queues are encrypted at rest."
  }

  assert {
    condition     = aws_dynamodb_table.idempotency.ttl[0].enabled && aws_dynamodb_table.idempotency.ttl[0].attribute_name == "expiration"
    error_message = "Idempotency records expire through the table's TTL on the expiration attribute."
  }
}

run "longer_timeout_raises_visibility" {
  command = plan

  variables {
    function_timeout_seconds = 120
  }

  assert {
    condition     = aws_sqs_queue.orders.visibility_timeout_seconds == 720
    error_message = "Visibility timeout follows the function timeout."
  }
}

run "timeout_above_lambda_limit_is_rejected" {
  command = plan

  variables {
    function_timeout_seconds = 901
  }

  expect_failures = [var.function_timeout_seconds]
}

run "zero_receive_count_is_rejected" {
  command = plan

  variables {
    max_receive_count = 0
  }

  expect_failures = [var.max_receive_count]
}

run "concurrency_below_two_is_rejected" {
  command = plan

  variables {
    max_concurrency = 1
  }

  expect_failures = [var.max_concurrency]
}
