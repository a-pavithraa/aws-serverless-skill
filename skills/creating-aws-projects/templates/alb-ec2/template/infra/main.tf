locals {
  name      = "${var.project_name}-${var.environment}"
  app_port  = 8080
  https     = var.certificate_arn != ""
  app_dir   = "${path.module}/../app"
  app_files = [for f in fileset(local.app_dir, "**") : f if !startswith(f, "tests/") && !strcontains(f, "__pycache__")]
  subnet_ids = (length(var.subnet_ids) > 0 ? var.subnet_ids
  : split(",", nonsensitive(data.aws_ssm_parameter.public_subnets[0].value)))
  exposure_tags = local.https ? {} : { PlainHttpReason = var.plain_http_reason }
}

data "aws_caller_identity" "current" {}

data "aws_default_tags" "current" {}

# Every plan reads the newest AMI. When AWS publishes a new one, the plan shows a new launch
# template version and the apply starts a rolling instance refresh: that is how instances get patched.
data "aws_ssm_parameter" "ami" {
  name = var.ami_ssm_parameter
}

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

# The load balancer is internet-facing and the instances download packages at boot: both need an
# internet gateway attached to the VPC. Without one, apply waits for healthy instances until it times
# out. This read fails the plan instead, with "no matching EC2 Internet Gateway found".
data "aws_internet_gateway" "vpc" {
  filter {
    name   = "attachment.vpc-id"
    values = [data.aws_subnet.first.vpc_id]
  }

  filter {
    name   = "attachment.state"
    values = ["available"]
  }
}

resource "aws_cloudwatch_log_group" "app" {
  name              = "/ec2/${local.name}"
  retention_in_days = var.log_retention_days
}

resource "aws_security_group" "alb" {
  name        = "${local.name}-alb"
  description = "Load balancer for ${local.name}"
  vpc_id      = data.aws_subnet.first.vpc_id
}

resource "aws_vpc_security_group_ingress_rule" "alb_listener" {
  security_group_id = aws_security_group.alb.id
  description       = "Clients"
  cidr_ipv4         = "0.0.0.0/0"
  ip_protocol       = "tcp"
  from_port         = local.https ? 443 : 80
  to_port           = local.https ? 443 : 80
}

resource "aws_vpc_security_group_egress_rule" "alb_to_instances" {
  security_group_id            = aws_security_group.alb.id
  description                  = "Requests and health checks to the instances"
  referenced_security_group_id = aws_security_group.instances.id
  ip_protocol                  = "tcp"
  from_port                    = local.app_port
  to_port                      = local.app_port
}

resource "aws_security_group" "instances" {
  name        = "${local.name}-instances"
  description = "Instances of ${local.name}: the load balancer in, HTTPS out"
  vpc_id      = data.aws_subnet.first.vpc_id
}

resource "aws_vpc_security_group_ingress_rule" "instances_from_alb" {
  security_group_id            = aws_security_group.instances.id
  description                  = "Load balancer"
  referenced_security_group_id = aws_security_group.alb.id
  ip_protocol                  = "tcp"
  from_port                    = local.app_port
  to_port                      = local.app_port
}

# Boot installs packages from the AL2023 repositories and the CloudWatch agent sends logs: both over HTTPS.
resource "aws_vpc_security_group_egress_rule" "instances_https" {
  security_group_id = aws_security_group.instances.id
  description       = "Package repositories and CloudWatch Logs"
  cidr_ipv4         = "0.0.0.0/0"
  ip_protocol       = "tcp"
  from_port         = 443
  to_port           = 443
}

data "aws_iam_policy_document" "instances_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["ec2.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "instances" {
  name               = "${local.name}-instances"
  assume_role_policy = data.aws_iam_policy_document.instances_assume.json
}

data "aws_iam_policy_document" "instances" {
  statement {
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents", "logs:DescribeLogStreams"]
    resources = ["${aws_cloudwatch_log_group.app.arn}:*"]
  }
}

resource "aws_iam_role_policy" "instances" {
  name   = "write-app-logs"
  role   = aws_iam_role.instances.id
  policy = data.aws_iam_policy_document.instances.json
}

resource "aws_iam_instance_profile" "instances" {
  name = "${local.name}-instances"
  role = aws_iam_role.instances.name
}

resource "aws_launch_template" "web" {
  name                   = local.name
  image_id               = nonsensitive(data.aws_ssm_parameter.ami.value)
  instance_type          = var.instance_type
  update_default_version = true
  ebs_optimized          = true

  user_data = base64encode(templatefile("${path.module}/templates/user_data.yaml.tftpl", {
    files     = { for f in local.app_files : f => filebase64("${local.app_dir}/${f}") }
    log_group = aws_cloudwatch_log_group.app.name
  }))

  iam_instance_profile {
    arn = aws_iam_instance_profile.instances.arn
  }

  # A subnet may not assign public addresses by default; without one, boot cannot reach the
  # package repositories. With a network interface block, the security group must be set here.
  network_interfaces {
    associate_public_ip_address = true
    security_groups             = [aws_security_group.instances.id]
    delete_on_termination       = true
  }

  metadata_options {
    http_tokens                 = "required"
    http_put_response_hop_limit = 1
    http_endpoint               = "enabled"
  }

  monitoring {
    enabled = true
  }

  block_device_mappings {
    device_name = "/dev/xvda"
    ebs {
      volume_size           = 8
      volume_type           = "gp3"
      encrypted             = true
      delete_on_termination = true
    }
  }

  tag_specifications {
    resource_type = "instance"
    tags          = merge(data.aws_default_tags.current.tags, { Name = local.name })
  }

  tag_specifications {
    resource_type = "volume"
    tags          = data.aws_default_tags.current.tags
  }
}

resource "aws_lb" "web" {
  name                       = local.name
  load_balancer_type         = "application"
  security_groups            = [aws_security_group.alb.id]
  subnets                    = local.subnet_ids
  drop_invalid_header_fields = true
  tags                       = local.exposure_tags

  depends_on = [data.aws_internet_gateway.vpc]

  lifecycle {
    precondition {
      condition     = length(distinct([for s in data.aws_subnet.all : s.availability_zone])) >= 2
      error_message = "The subnets must be in at least two Availability Zones: the load balancer needs two, and one zone is a single point of failure."
    }
  }
}

resource "aws_lb_target_group" "web" {
  name                 = local.name
  port                 = local.app_port
  protocol             = "HTTP"
  vpc_id               = data.aws_subnet.first.vpc_id
  deregistration_delay = 30

  health_check {
    path                = "/health"
    matcher             = "200"
    interval            = 15
    healthy_threshold   = 2
    unhealthy_threshold = 2
  }
}

resource "aws_lb_listener" "web" {
  load_balancer_arn = aws_lb.web.arn
  port              = local.https ? 443 : 80
  protocol          = local.https ? "HTTPS" : "HTTP"
  ssl_policy        = local.https ? "ELBSecurityPolicy-TLS13-1-2-2021-06" : null
  certificate_arn   = local.https ? var.certificate_arn : null

  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.web.arn
  }
}

resource "aws_autoscaling_group" "web" {
  name                      = "${local.name}-web"
  min_size                  = var.min_instances
  max_size                  = var.max_instances
  desired_capacity          = var.min_instances
  vpc_zone_identifier       = local.subnet_ids
  target_group_arns         = [aws_lb_target_group.web.arn]
  health_check_type         = "ELB"
  health_check_grace_period = 300
  wait_for_elb_capacity     = var.min_instances

  launch_template {
    id      = aws_launch_template.web.id
    version = aws_launch_template.web.latest_version
  }

  # A new launch template version (new AMI or new app/ code) replaces instances one at a time,
  # adding a new one before removing an old one. Without the alarm, a refresh whose new instances
  # never become healthy does not fail: the group keeps replacing them and the refresh waits for
  # warm-up for hours (seen in the sandbox). With it, the refresh fails and rolls back.
  instance_refresh {
    strategy = "Rolling"
    preferences {
      min_healthy_percentage = 100
      max_healthy_percentage = 200
      instance_warmup        = 300
      auto_rollback          = true

      alarm_specification {
        alarms = [aws_cloudwatch_metric_alarm.unhealthy_hosts.alarm_name]
      }
    }
  }

  dynamic "tag" {
    for_each = data.aws_default_tags.current.tags
    content {
      key                 = tag.key
      value               = tag.value
      propagate_at_launch = false
    }
  }
}
