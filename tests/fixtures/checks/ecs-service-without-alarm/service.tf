resource "aws_ecs_cluster" "this" {
  name = var.name

  setting {
    name  = "containerInsights"
    value = "enabled"
  }
}

resource "aws_ecs_task_definition" "web" {
  family                   = var.name
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = "256"
  memory                   = "512"
  container_definitions = jsonencode([{
    name                   = "web"
    image                  = "public.ecr.aws/docker/library/python:3.13-slim"
    readonlyRootFilesystem = true
  }])
}

resource "aws_lb_target_group" "web" {
  name        = var.name
  port        = 8080
  protocol    = "HTTP"
  target_type = "ip"
  vpc_id      = "vpc-0123456789abcdef0"
}

resource "aws_ecs_service" "web" {
  name             = var.name
  cluster          = aws_ecs_cluster.this.id
  task_definition  = aws_ecs_task_definition.web.arn
  desired_count    = 2
  launch_type      = "FARGATE"
  platform_version = "LATEST"

  network_configuration {
    subnets = ["subnet-0aaaaaaaaaaaaaaaa", "subnet-0bbbbbbbbbbbbbbbb"]
  }

  load_balancer {
    target_group_arn = aws_lb_target_group.web.arn
    container_name   = "web"
    container_port   = 8080
  }
}

# The only alarm watches the target group. HARNESS_AWS_5 follows one reference, so it does not count
# for the service: the fix is an alarm with ServiceName = aws_ecs_service.web.name.
resource "aws_cloudwatch_metric_alarm" "target_5xx" {
  alarm_name          = "${var.name}-target-5xx"
  namespace           = "AWS/ApplicationELB"
  metric_name         = "HTTPCode_Target_5XX_Count"
  dimensions          = { TargetGroup = aws_lb_target_group.web.arn_suffix }
  statistic           = "Sum"
  period              = 60
  evaluation_periods  = 1
  threshold           = 0
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"
}
