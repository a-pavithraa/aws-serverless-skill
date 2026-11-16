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

# A task definition that only scheduled tasks run is not a service: this check does not look at it.
resource "aws_ecs_task_definition" "batch" {
  family                   = "${var.name}-batch"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = "256"
  memory                   = "512"
  container_definitions = jsonencode([{
    name                   = "batch"
    image                  = "public.ecr.aws/docker/library/python:3.13-slim"
    readonlyRootFilesystem = true
  }])
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
}
