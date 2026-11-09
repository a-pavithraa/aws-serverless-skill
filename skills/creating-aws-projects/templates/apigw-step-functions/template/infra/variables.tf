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

variable "auth_mode" {
  type        = string
  description = "iam: callers sign requests with SigV4. none: the route is public."

  validation {
    condition     = contains(["iam", "none"], var.auth_mode)
    error_message = "auth_mode: iam or none."
  }
}

variable "public_reason" {
  type        = string
  default     = ""
  description = "Why the API is public. Required when auth_mode is none; recorded as a tag."

  validation {
    condition     = var.auth_mode != "none" || length(trimspace(var.public_reason)) >= 10
    error_message = "public_reason: auth_mode = \"none\" needs a reason of at least 10 characters."
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

variable "throttle_rate_limit" {
  description = "Steady requests per second the API accepts before it answers 429."
  type        = number
  default     = 50
}

variable "throttle_burst_limit" {
  description = "Requests the API accepts at once before it answers 429."
  type        = number
  default     = 100
}

variable "log_execution_data" {
  type        = bool
  default     = false
  description = "Log each execution's input and output (the order). Turn on only to debug, for a short time: the order can hold customer data, and the log keeps it for log_retention_days."
}
