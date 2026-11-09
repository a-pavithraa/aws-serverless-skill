terraform {
  required_version = "~> 1.10"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = ">= 6.72.0, < 7.0.0"
    }
    archive = {
      source  = "hashicorp/archive"
      version = ">= 2.8.1, < 3.0.0"
    }
  }
}
