locals {
  name           = "${var.project_name}-${var.environment}"
  service_name   = "${local.name}-web"
  deploy_service = var.image_digest != ""
  container_port = 8080
  environment    = merge(var.app_environment, length(var.secret_names) > 0 ? { SECRET_NAMES = join(",", var.secret_names) } : {})
  subnet_ids     = length(var.subnet_ids) > 0 ? var.subnet_ids : split(",", nonsensitive(data.aws_ssm_parameter.public_subnets[0].value))
}

data "aws_caller_identity" "current" {}

# A network from the network template publishes its subnets here.
data "aws_ssm_parameter" "public_subnets" {
  count = var.network_name != "" ? 1 : 0
  name  = "/landform/network/${var.network_name}/public-subnet-ids"
}

data "aws_subnet" "first" {
  id = local.subnet_ids[0]
}

# Subnets from two VPCs, or all in one zone, otherwise fail inside AWS, late in the apply.
data "aws_subnet" "all" {
  for_each = toset(local.subnet_ids)
  id       = each.value

  lifecycle {
    postcondition {
      condition     = self.vpc_id == data.aws_subnet.first.vpc_id
      error_message = "Subnet ${each.value} is not in the VPC of ${local.subnet_ids[0]}: every subnet must be in one VPC."
    }
  }
}

resource "aws_ecr_repository" "app" {
  name                 = local.name
  image_tag_mutability = "IMMUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }

  encryption_configuration {
    encryption_type = "KMS"
  }
}

resource "aws_ecr_lifecycle_policy" "app" {
  repository = aws_ecr_repository.app.name
  policy = jsonencode({
    rules = [{
      rulePriority = 1
      description  = "Keep the 20 newest images"
      selection    = { tagStatus = "any", countType = "imageCountMoreThan", countNumber = 20 }
      action       = { type = "expire" }
    }]
  })
}

resource "aws_ecs_cluster" "this" {
  name = local.name

  setting {
    name  = "containerInsights"
    value = "enabled"
  }
}

resource "aws_cloudwatch_log_group" "app" {
  name              = "/ecs/${local.name}"
  retention_in_days = var.log_retention_days
}

data "aws_iam_policy_document" "tasks_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["ecs-tasks.amazonaws.com"]
    }
    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [data.aws_caller_identity.current.account_id]
    }
  }
}

resource "aws_iam_role" "execution" {
  name               = "${local.name}-execution"
  assume_role_policy = data.aws_iam_policy_document.tasks_assume.json
}

# Scoped to this repository and log group instead of AmazonECSTaskExecutionRolePolicy, which allows every
# repository and log group in the account. GetAuthorizationToken has no resource-level permissions.
# The app's secrets: one secret, one JSON key per name in secret_names. Terraform creates it without
# a value, so the value never enters the state; set it with put-secret-value (README).
resource "aws_secretsmanager_secret" "app" {
  count = length(var.secret_names) > 0 ? 1 : 0

  name                    = "${local.name}/app"
  description             = "Secrets of ${local.name}: JSON keys ${join(", ", var.secret_names)}"
  recovery_window_in_days = var.secret_recovery_days
}

data "aws_iam_policy_document" "execution" {
  statement {
    actions   = ["ecr:GetAuthorizationToken"]
    resources = ["*"]
  }

  # ECS reads the secret when it starts a task. The AWS managed key aws/secretsmanager needs no KMS grant.
  dynamic "statement" {
    for_each = aws_secretsmanager_secret.app
    content {
      actions   = ["secretsmanager:GetSecretValue"]
      resources = [statement.value.arn]
    }
  }
  statement {
    actions   = ["ecr:BatchCheckLayerAvailability", "ecr:BatchGetImage", "ecr:GetDownloadUrlForLayer"]
    resources = [aws_ecr_repository.app.arn]
  }
  statement {
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["${aws_cloudwatch_log_group.app.arn}:*"]
  }
}

resource "aws_iam_role_policy" "execution" {
  name   = "pull-image-and-write-logs"
  role   = aws_iam_role.execution.id
  policy = data.aws_iam_policy_document.execution.json
}

# The application calls no AWS API. Add statements here when it does.
resource "aws_iam_role" "task" {
  name               = "${local.name}-task"
  assume_role_policy = data.aws_iam_policy_document.tasks_assume.json
}

data "aws_iam_policy_document" "infrastructure_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["ecs.amazonaws.com"]
    }
    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [data.aws_caller_identity.current.account_id]
    }
  }
}

# Express Mode uses this role to create and delete the load balancer, target groups, security groups,
# certificate and scaling policy. Changing the role replaces the service.
resource "aws_iam_role" "infrastructure" {
  name               = "${local.name}-express"
  assume_role_policy = data.aws_iam_policy_document.infrastructure_assume.json
}

resource "aws_iam_role_policy_attachment" "infrastructure" {
  role       = aws_iam_role.infrastructure.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSInfrastructureRoleforExpressGatewayServices"
}

resource "aws_ecs_express_gateway_service" "web" {
  count = local.deploy_service ? 1 : 0

  service_name            = local.service_name
  cluster                 = aws_ecs_cluster.this.name
  execution_role_arn      = aws_iam_role.execution.arn
  infrastructure_role_arn = aws_iam_role.infrastructure.arn
  task_role_arn           = aws_iam_role.task.arn
  cpu                     = tostring(var.cpu)
  memory                  = tostring(var.memory)
  cpu_architecture        = "ARM64"
  health_check_path       = "/health"
  wait_for_steady_state   = true

  primary_container {
    image          = "${aws_ecr_repository.app.repository_url}@${var.image_digest}"
    container_port = local.container_port

    dynamic "environment" {
      for_each = local.environment
      content {
        name  = environment.key
        value = environment.value
      }
    }

    # Values from the secret block, never from environment: anyone with ecs:DescribeTaskDefinition
    # can read environment values. <secret ARN>:<JSON key>:: reads the current version.
    dynamic "secret" {
      for_each = var.secret_names
      content {
        name       = secret.value
        value_from = "${aws_secretsmanager_secret.app[0].arn}:${secret.value}::"
      }
    }

    aws_logs_configuration {
      log_group         = aws_cloudwatch_log_group.app.name
      log_stream_prefix = "web"
    }
  }

  network_configuration {
    subnets         = local.subnet_ids
    security_groups = var.security_group_ids
  }

  scaling_target {
    auto_scaling_metric       = "AVERAGE_CPU"
    auto_scaling_target_value = 60
    min_task_count            = var.min_tasks
    max_task_count            = var.max_tasks
  }

  # Without these, destroy can remove the role policies first and leave the service stuck in DRAINING.
  depends_on = [aws_iam_role_policy_attachment.infrastructure, aws_iam_role_policy.execution]

  lifecycle {
    precondition {
      condition     = length(distinct([for s in data.aws_subnet.all : s.availability_zone])) >= 2
      error_message = "The subnets must be in at least two Availability Zones: the load balancer needs two, and one zone is a single point of failure."
    }
  }
}
