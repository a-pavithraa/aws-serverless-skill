variable "project_name" {
  description = "Lowercase project name, 3-32 characters. Names every resource as <project_name>-<environment>."
  type        = string

  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{1,30}[a-z0-9]$", var.project_name))
    error_message = "project_name: lowercase letters, digits and hyphens, 3-32 characters."
  }
}

variable "environment" {
  description = "Environment name, such as dev or prod: 2-16 lowercase letters and digits."
  type        = string

  validation {
    condition     = can(regex("^[a-z][a-z0-9]{1,15}$", var.environment))
    error_message = "environment: lowercase letters and digits, 2-16 characters."
  }

  validation {
    condition     = length("${var.project_name}-${var.environment}") <= 32
    error_message = "project_name and environment: <project_name>-<environment> names the load balancer and target group, which allow at most 32 characters."
  }
}

variable "aws_region" {
  description = "Region to deploy to. The runtime profile records the regions this template was tested in."
  type        = string
}

variable "allowed_account_id" {
  type        = string
  default     = ""
  description = "When set, the provider refuses to run against any other account."

  validation {
    condition     = var.allowed_account_id == "" || can(regex("^[0-9]{12}$", var.allowed_account_id))
    error_message = "allowed_account_id: empty or a 12-digit account ID."
  }
}

variable "log_retention_days" {
  description = "Days CloudWatch Logs keeps the log groups."
  type        = number

  validation {
    condition     = contains([1, 3, 5, 7, 14, 30, 60, 90, 120, 150, 180, 365, 400, 545, 731, 1096, 1827, 2192, 2557, 2922, 3288, 3653], var.log_retention_days)
    error_message = "log_retention_days: one of the values CloudWatch Logs accepts (1, 3, 5, 7, 14, 30, 60, 90, ...)."
  }
}

variable "alarm_email" {
  type        = string
  default     = ""
  description = "Subscribed to the alarm topic when set. The subscription must be confirmed from the email."
}

variable "ami_ssm_parameter" {
  type        = string
  default     = "/aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-arm64"
  description = "Public SSM parameter that names the newest AL2023 arm64 AMI. Each plan reads it; a new AMI replaces the instances."
}

variable "instance_type" {
  description = "Graviton (arm64) instance type; the AMI is arm64."
  type        = string
  default     = "t4g.micro"

  validation {
    condition     = can(regex("^(t4g|m7g|m8g|c7g|c8g|r7g|r8g)[.]", var.instance_type))
    error_message = "instance_type: a Graviton (arm64) type such as t4g.micro; the AMI is arm64."
  }
}

variable "min_instances" {
  description = "Fewest instances the group runs, and the number it starts with."
  type        = number
  default     = 2

  validation {
    condition     = var.min_instances >= 1
    error_message = "min_instances: at least 1."
  }
}

variable "max_instances" {
  description = "Most instances the group runs. A refresh needs one above min_instances to add before it removes."
  type        = number
  default     = 3

  validation {
    condition     = var.max_instances > var.min_instances && var.max_instances <= 20
    error_message = "max_instances: more than min_instances, so a refresh can add an instance before it removes one; at most 20."
  }
}

variable "certificate_arn" {
  type        = string
  default     = ""
  description = "ACM certificate for HTTPS. Empty serves plain HTTP on port 80."
}

variable "plain_http_reason" {
  type        = string
  default     = ""
  description = "Why the service may serve plain HTTP. Required when certificate_arn is empty."

  validation {
    condition     = var.certificate_arn != "" || length(trimspace(var.plain_http_reason)) >= 10
    error_message = "plain_http_reason: without certificate_arn the load balancer serves plain HTTP; give a reason of at least 10 characters."
  }
}

variable "subnet_ids" {
  type        = list(string)
  default     = []
  description = "Public subnets in at least two Availability Zones, in a VPC with an attached internet gateway. Give these or network_name; the default VPC is not used."
}

variable "network_name" {
  type        = string
  default     = ""
  description = "A network made with the network template (<project>-<environment>). Its public subnets come from SSM at plan time."

  validation {
    condition     = var.network_name == "" || length(var.subnet_ids) == 0
    error_message = "network_name: give network_name or subnet_ids, not both."
  }

  validation {
    condition     = var.network_name != "" || length(var.subnet_ids) >= 2
    error_message = "network_name: give network_name (a network made with the network template) or at least two public subnet_ids. The default VPC is not used."
  }

  validation {
    condition     = var.network_name == "" || can(regex("^[a-z][a-z0-9-]{1,48}$", var.network_name))
    error_message = "network_name: the network project's <project>-<environment>."
  }
}
