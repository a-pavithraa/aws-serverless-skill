provider "aws" {
  region              = var.aws_region
  allowed_account_ids = var.allowed_account_id == "" ? null : [var.allowed_account_id]

  default_tags {
    tags = {
      Project     = var.project_name
      Environment = var.environment
      ManagedBy   = "terraform"
      Generator   = "landform/ecs-web"
    }
  }
}
