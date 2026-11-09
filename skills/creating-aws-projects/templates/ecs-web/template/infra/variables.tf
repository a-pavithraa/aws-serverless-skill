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

variable "image_digest" {
  type        = string
  default     = ""
  description = "Digest of the image in this project's repository. Empty creates the repository only; push an image, then plan with its digest."

  validation {
    condition     = var.image_digest == "" || can(regex("^sha256:[0-9a-f]{64}$", var.image_digest))
    error_message = "image_digest: empty or sha256:<64 hex>. Deploy by digest, not by tag."
  }
}

variable "cpu" {
  description = "Fargate CPU units for each task: 256, 512 or 1024."
  type        = number
  default     = 256

  validation {
    condition     = contains([256, 512, 1024], var.cpu)
    error_message = "cpu: 256, 512 or 1024."
  }
}

variable "memory" {
  description = "Fargate memory for each task in MiB. The allowed values depend on cpu."
  type        = number
  default     = 512

  validation {
    condition = (
      (var.cpu == 256 && contains([512, 1024, 2048], var.memory)) ||
      (var.cpu == 512 && var.memory >= 1024 && var.memory <= 4096 && var.memory % 1024 == 0) ||
      (var.cpu == 1024 && var.memory >= 2048 && var.memory <= 8192 && var.memory % 1024 == 0)
    )
    error_message = "memory: not a size Fargate accepts for this cpu."
  }
}

variable "min_tasks" {
  description = "Fewest tasks the service runs."
  type        = number
  default     = 1

  validation {
    condition     = var.min_tasks >= 1
    error_message = "min_tasks: at least 1."
  }
}

variable "max_tasks" {
  description = "Most tasks the service scales out to, at most 20."
  type        = number
  default     = 2

  validation {
    condition     = var.max_tasks >= var.min_tasks && var.max_tasks <= 20
    error_message = "max_tasks: between min_tasks and 20."
  }
}

variable "subnet_ids" {
  type        = list(string)
  default     = []
  description = "At least two subnets: public ones give an internet-facing load balancer, private ones an internal one. Give these or network_name; the default VPC is not used."
}

variable "security_group_ids" {
  type        = list(string)
  default     = []
  description = "Extra security groups for the tasks. Each one is another way in, so add only what you need."
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
    error_message = "network_name: give network_name (a network made with the network template) or at least two subnet_ids. The default VPC is not used."
  }

  validation {
    condition     = var.network_name == "" || can(regex("^[a-z][a-z0-9-]{1,48}$", var.network_name))
    error_message = "network_name: the network project's <project>-<environment>."
  }
}

variable "secret_names" {
  description = "Environment variable names the app reads as secrets, such as DB_PASSWORD. Each is one JSON key of the project's Secrets Manager secret. Empty creates no secret."
  type        = list(string)
  default     = []

  validation {
    condition     = alltrue([for n in var.secret_names : can(regex("^[A-Z_][A-Z0-9_]*$", n))]) && length(distinct(var.secret_names)) == length(var.secret_names)
    error_message = "secret_names: distinct environment variable names in upper case, such as DB_PASSWORD."
  }

  validation {
    condition     = !contains(var.secret_names, "SECRET_NAMES")
    error_message = "secret_names: SECRET_NAMES is set by the template."
  }
}

variable "app_environment" {
  description = "Plain settings for the app, as environment variables. Anyone with ecs:DescribeTaskDefinition can read them, so they must not hold secrets: put those in secret_names."
  type        = map(string)
  default     = {}

  validation {
    condition     = length(setintersection(keys(var.app_environment), var.secret_names)) == 0
    error_message = "app_environment: a name in secret_names comes from Secrets Manager; do not also set it here."
  }

  validation {
    condition     = alltrue([for k in keys(var.app_environment) : !can(regex("(?i)(PASSWORD|PASSWD|SECRET|TOKEN|CREDENTIAL|PRIVATE_KEY|API_KEY)", k))])
    error_message = "app_environment: a name that looks like a secret (PASSWORD, SECRET, TOKEN, CREDENTIAL, PRIVATE_KEY, API_KEY) goes in secret_names, not here."
  }
}

variable "secret_recovery_days" {
  description = "Days Secrets Manager keeps the secret after destroy, so it can be restored. Creating the project again under the same name fails until then."
  type        = number
  default     = 7

  validation {
    condition     = var.secret_recovery_days >= 7 && var.secret_recovery_days <= 30
    error_message = "secret_recovery_days: 7 to 30."
  }
}
