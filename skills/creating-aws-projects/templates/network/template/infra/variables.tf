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

variable "cidr" {
  description = "VPC CIDR, /16 to /20. Each subnet is a /24 cut from it."
  type        = string
  default     = "10.42.0.0/16"

  validation {
    condition     = can(cidrhost(var.cidr, 0)) && tonumber(split("/", var.cidr)[1]) >= 16 && tonumber(split("/", var.cidr)[1]) <= 20
    error_message = "cidr: an IPv4 CIDR from /16 to /20."
  }
}

variable "az_count" {
  description = "Availability Zones to use, 2 or 3. Load balancers need two."
  type        = number
  default     = 2

  validation {
    condition     = var.az_count >= 2 && var.az_count <= 3
    error_message = "az_count: 2 or 3; load balancers need two zones."
  }
}

variable "nat_mode" {
  type        = string
  default     = "none"
  description = "none: public subnets only. single: private subnets and one NAT gateway. per-az: one NAT gateway per zone."

  validation {
    condition     = contains(["none", "single", "per-az"], var.nat_mode)
    error_message = "nat_mode: none, single or per-az."
  }
}

variable "zone_instance_type" {
  type        = string
  default     = "t4g.micro"
  description = "Only zones that offer this instance type get subnets."
}

variable "zones" {
  type        = list(string)
  default     = []
  description = "Availability Zones, pinned. Empty picks the first az_count zones that offer zone_instance_type; copy the availability_zones output here after the first apply."

  validation {
    condition     = length(var.zones) == 0 || length(var.zones) == var.az_count
    error_message = "zones: empty, or exactly az_count zones."
  }
}
