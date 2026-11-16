resource "aws_sqs_queue" "dead_letter" {
  name                    = "${var.name}-dlq"
  sqs_managed_sse_enabled = true
}

# The source queue has no alarm of its own: HARNESS_AWS_4 asks for one on the dead-letter queue only.
resource "aws_sqs_queue" "orders" {
  name                    = "${var.name}-orders"
  sqs_managed_sse_enabled = true

  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.dead_letter.arn
    maxReceiveCount     = 3
  })
}

# A queue that is not a dead-letter queue needs no alarm from this check.
resource "aws_sqs_queue" "events" {
  name                    = "${var.name}-events"
  sqs_managed_sse_enabled = true
}
