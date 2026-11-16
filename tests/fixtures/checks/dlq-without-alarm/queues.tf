resource "aws_sqs_queue" "dead_letter" {
  name                    = "${var.name}-dlq"
  sqs_managed_sse_enabled = true
}

resource "aws_sqs_queue" "orders" {
  name                    = "${var.name}-orders"
  sqs_managed_sse_enabled = true

  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.dead_letter.arn
    maxReceiveCount     = 3
  })
}

# Only the source queue has an alarm: nothing tells anyone that messages reached the dead-letter queue.
resource "aws_cloudwatch_metric_alarm" "oldest_message" {
  alarm_name          = "${var.name}-oldest-message-age"
  namespace           = "AWS/SQS"
  metric_name         = "ApproximateAgeOfOldestMessage"
  dimensions          = { QueueName = aws_sqs_queue.orders.name }
  statistic           = "Maximum"
  period              = 60
  evaluation_periods  = 5
  threshold           = 300
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"
}
