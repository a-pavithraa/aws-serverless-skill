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

variable "function_timeout_seconds" {
  description = "Lambda timeout. The queue's visibility timeout is set from it."
  type        = number
  default     = 10

  validation {
    condition     = var.function_timeout_seconds >= 1 && var.function_timeout_seconds <= 900
    error_message = "function_timeout_seconds: 1-900."
  }
}

variable "lambda_memory_mb" {
  description = "Lambda memory in MB. CPU grows with memory."
  type        = number
  default     = 256
}

variable "max_receive_count" {
  type        = number
  default     = 3
  description = "Deliveries before SQS moves a message to the dead-letter queue."

  validation {
    condition     = var.max_receive_count >= 1 && var.max_receive_count <= 10
    error_message = "max_receive_count: 1-10."
  }
}

variable "batch_size" {
  description = "Messages each Lambda invocation receives from the queue."
  type        = number
  default     = 10

  validation {
    condition     = var.batch_size >= 1 && var.batch_size <= 10
    error_message = "batch_size: 1-10; larger batches need a batching window."
  }
}

variable "max_concurrency" {
  type        = number
  default     = 2
  description = "Upper bound on concurrent invocations from the queue."

  validation {
    condition     = var.max_concurrency >= 2 && var.max_concurrency <= 1000
    error_message = "max_concurrency: 2-1000, the range SQS event sources accept."
  }
}

variable "max_message_age_seconds" {
  type        = number
  default     = 300
  description = "The oldest-message alarm fires when a message waits longer than this."
}
