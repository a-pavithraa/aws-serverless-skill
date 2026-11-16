# Terraform Structure & Best Practices

## Module Design

### Don't Wrap Single Resources
```hcl
# BAD: Thin wrapper around one resource
module "s3_bucket" {
  source = "./modules/s3"
  name   = "my-bucket"
}

# GOOD: Use resource directly
resource "aws_s3_bucket" "main" {
  bucket = "my-bucket"
}
```

### Encapsulate Logical Groupings
```hcl
# GOOD: Groups related resources
module "api" {
  source = "./modules/lambda-api"
  # Creates: Lambda, API Gateway, IAM roles, CloudWatch logs
}
```

### Keep Inheritance Flat
- Maximum 1-2 levels of nested modules
- Modules should compose, not tunnel through each other

---

## State Management

### Remote State with S3 (Terraform 1.10+)

S3 native locking replaces the legacy DynamoDB lock table (deprecated in Terraform 1.11+).

```hcl
terraform {
  backend "s3" {
    bucket       = "mycompany-terraform-state"
    key          = "project/environment/terraform.tfstate"
    region       = "us-east-1"
    encrypt      = true
    use_lockfile = true
  }
}
```

Requirements:
- S3 bucket versioning must be enabled
- IAM permissions: `s3:GetObject`, `s3:PutObject`, `s3:DeleteObject` on lock file
- Terraform version >= 1.10.0

### Separate Backends Per Environment

Choose bucket strategy based on isolation requirements — not a blanket rule.

| Approach | Isolation | Access Control | Best For |
|----------|-----------|----------------|----------|
| Separate buckets per tier (prod / non-prod) | Strong — IAM policies scope access per bucket | Easy — separate policies per bucket | Regulated environments, multi-team, SOC2/PCI |
| Single bucket, per-env key paths | Logical — any principal with bucket access sees all state | Prefix-based S3 policies (coarser) | Single team, ephemeral branch envs, fast iteration |
| Terraform workspaces | Weak — same bucket, same key prefix | Hardest to restrict per-env | Not recommended for environment isolation |

**Recommended hybrid**: separate buckets at hard trust boundaries (prod vs non-prod), key paths within a bucket for soft boundaries (feature branches, dev/qa within non-prod). See `cicd-patterns.md` → "Per-Branch Backend State" for the key-path pattern.

## Environments and ownership

### One root, two files per environment

When every environment has the same resources, keep one root and give each environment a backend file and a variables file:

```text
infra/app/
  *.tf                      # no environment-specific value
  env/dev.s3.tfbackend      # key = "app/dev/terraform.tfstate"
  env/dev.tfvars            # environment, aws_account_id, IDs and names
```

```bash
terraform init -reconfigure -backend-config=env/dev.s3.tfbackend
terraform plan -var-file=env/dev.tfvars -out=dev.tfplan
```

- Set `allowed_account_ids = [var.aws_account_id]` on the provider. Then dev's variables with prod credentials fail before anything is planned.
- Use a directory per environment only when the environments have different resources.
- `terraform.tfvars`, `terraform.tfvars.json`, `*.auto.tfvars` and `*.auto.tfvars.json` load in **every** environment. A generated file with one of those names (for example, a user list exported from the identity provider) is applied to prod with dev's values. Name it `env/<env>.<name>.tfvars.json` and pass it with `-var-file`.
- To convert a root whose key is written in the `backend` block and whose values are in `terraform.tfvars`: put the existing key, unchanged, in `env/dev.s3.tfbackend`, and move the values to `env/dev.tfvars`. With the same key, `init -reconfigure` finds the existing state and nothing moves.

> *Source: [Variable definition files](https://developer.hashicorp.com/terraform/language/values/variables) · verified 2026-11-16*

### Stop temporary settings from reaching prod

Proof-of-concept switches (a database container in the task, a borrowed security group, a repository shared with dev) stay as variables. Fail the plan when one is set in prod. A `check` block only warns, so use a validation (Terraform 1.9+ lets it read other variables):

```hcl
variable "db_sidecar" {
  type    = bool
  default = false

  validation {
    condition     = !(var.db_sidecar && var.environment == "prod")
    error_message = "The database sidecar loses its data on every deployment. Prod needs a real database."
  }
}
```

The guard stops a mistake. It does not create what prod needs instead, so list each switch with what replaces it and who provides it.

Test each guard with `terraform test`: `command = plan`, `environment = "prod"`, and `expect_failures = [var.db_sidecar]`. Under a `mock_provider`, give `mock_data` defaults that pass the provider's ARN checks and the data sources' postconditions. The mocked provider otherwise returns random strings, the plan stops on those checks, and the test reports an unexpected error instead of the guard.

```hcl
mock_provider "aws" {
  mock_data "aws_iam_role" {
    defaults = { arn = "arn:aws:iam::123456789012:role/mock" }
  }
  mock_data "aws_subnet" {
    defaults = { vpc_id = "vpc-0123456789abcdef0" } # the VPC the postcondition expects
  }
}
```

### One owner per resource

A rule like "apply only with `-target`" means that a resource has two owners: Terraform, and a person who edits it in the console. CI cannot apply such a root, and each targeted apply skips everything else.

1. Run one plan without `-target`, and list every resource that shows a change.
2. Choose one owner for each:
   - **Terraform owns it.** The console edit moves into the code in a pull request, and the console stops editing it.
   - **The console owns it.** Add a `removed` block with `destroy = false`, which takes it out of state without deleting it. Read its ID with a data source when other resources need it.
3. The plan without `-target` is then empty, and CI can apply the root.

```hcl
removed {
  from = aws_connect_contact_flow.this["ivr"]
  lifecycle {
    destroy = false
  }
}
```

Use `removed` rather than `ignore_changes` for a resource that a person owns. With `ignore_changes`, the resource stays in state, so a change that forces replacement, or a `destroy`, still acts on it. `ignore_changes` on the edited attribute is only a transition step, while the console edits move into code.

Split a root by owner and by rate of change, not by resource type. For example, users generated from an identity provider change every week, and flows change with releases. A user sync then does not wait on unfinished flow work.

> *Source: [`removed` block](https://developer.hashicorp.com/terraform/language/block/removed) · verified 2026-11-16*

### CloudTrail Integration

Enable CloudTrail on the state bucket to attribute every state change to a specific identity:

```hcl
resource "aws_cloudtrail" "state_audit" {
  name                          = "${local.name_prefix}-state-trail"
  s3_bucket_name                = aws_s3_bucket.cloudtrail.id
  include_global_service_events = true

  event_selector {
    read_write_type           = "All"
    include_management_events = true

    data_resource {
      type   = "AWS::S3::Object"
      values = ["${aws_s3_bucket.terraform_state.arn}/"]
    }
  }
}
```

Combined with S3 versioning, CloudTrail lets you answer: "Who applied this change and when?"

### State Backend Bootstrap

The state bucket, KMS key, and access policies must exist before any Terraform project can use them. This is a chicken-and-egg: you need infrastructure to store state, but you'd normally use Terraform (which needs state) to create infrastructure.

**Solution: a separate bootstrap project with local state.**

```
infra-bootstrap/          # separate directory (or repo for multi-team)
  main.tf                 # S3 bucket, KMS key, bucket policy
  outputs.tf              # bucket name, KMS ARN for downstream projects
  terraform.tfstate       # local state — committed or stored securely
  terraform.tfstate.backup
```

```hcl
# infra-bootstrap/main.tf
# No backend block — Terraform defaults to local state.
# After first apply, add an S3 backend block and run `terraform init -migrate-state`.

provider "aws" {
  region = "us-east-1"
}

data "aws_caller_identity" "current" {}

resource "aws_kms_key" "terraform_state" {
  description             = "Encrypts Terraform state files"
  deletion_window_in_days = 30
  enable_key_rotation     = true
}

resource "aws_kms_alias" "terraform_state" {
  name          = "alias/terraform-state"
  target_key_id = aws_kms_key.terraform_state.key_id
}

resource "aws_s3_bucket" "terraform_state" {
  bucket = "myorg-terraform-state-${data.aws_caller_identity.current.account_id}"

  lifecycle {
    prevent_destroy = true
  }
}

resource "aws_s3_bucket_versioning" "terraform_state" {
  bucket = aws_s3_bucket.terraform_state.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "terraform_state" {
  bucket = aws_s3_bucket.terraform_state.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm     = "aws:kms"
      kms_master_key_id = aws_kms_key.terraform_state.arn
    }
    bucket_key_enabled = true
  }
}

resource "aws_s3_bucket_public_access_block" "terraform_state" {
  bucket                  = aws_s3_bucket.terraform_state.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_policy" "terraform_state" {
  bucket = aws_s3_bucket.terraform_state.id
  policy = data.aws_iam_policy_document.bucket_policy.json
}

data "aws_iam_policy_document" "bucket_policy" {
  statement {
    sid       = "DenyNonTLS"
    effect    = "Deny"
    actions   = ["s3:*"]
    resources = [
      aws_s3_bucket.terraform_state.arn,
      "${aws_s3_bucket.terraform_state.arn}/*",
    ]
    principals {
      type        = "*"
      identifiers = ["*"]
    }
    condition {
      test     = "Bool"
      variable = "aws:SecureTransport"
      values   = ["false"]
    }
  }

  statement {
    sid       = "DenyNonKMSEncryptedUploads"
    effect    = "Deny"
    actions   = ["s3:PutObject"]
    resources = ["${aws_s3_bucket.terraform_state.arn}/*"]
    principals {
      type        = "*"
      identifiers = ["*"]
    }
    condition {
      test     = "StringNotEquals"
      variable = "s3:x-amz-server-side-encryption"
      values   = ["aws:kms"]
    }
  }
}
```

> **Why SSE-KMS over SSE-S3?** SSE-S3 (AES-256) is the S3 default and sufficient for basic encryption. SSE-KMS adds: separate key management and rotation, CloudTrail logging of key usage, and IAM policies that restrict who can decrypt state. Use SSE-KMS for state buckets — state files contain sensitive resource attributes in plaintext.
>
> `bucket_key_enabled = true` reduces KMS API costs by caching a bucket-level key instead of calling KMS per-object.

#### CI/CD Role Access Policy

Grant the CI/CD pipeline role (e.g., the OIDC-federated GitHub Actions role) the minimum permissions for state operations:

```hcl
# infra-bootstrap/cicd-policy.tf
data "aws_iam_policy_document" "terraform_cicd" {
  statement {
    sid    = "S3StateAccess"
    effect = "Allow"
    actions = [
      "s3:GetObject",
      "s3:PutObject",
      "s3:DeleteObject",  # required for S3 native lock file cleanup
      "s3:ListBucket",
    ]
    resources = [
      aws_s3_bucket.terraform_state.arn,
      "${aws_s3_bucket.terraform_state.arn}/*",
    ]
  }

  statement {
    sid    = "KMSStateEncryption"
    effect = "Allow"
    actions = [
      "kms:Encrypt",
      "kms:Decrypt",
      "kms:GenerateDataKey",
      "kms:DescribeKey",
    ]
    resources = [aws_kms_key.terraform_state.arn]
  }
}

resource "aws_iam_policy" "terraform_cicd" {
  name   = "terraform-state-cicd-access"
  policy = data.aws_iam_policy_document.terraform_cicd.json
}
```

Attach this policy to the GitHub Actions OIDC role (see `cicd-patterns.md` → "OIDC Authentication").

#### Downstream Project Backend Config

Projects reference the bootstrap outputs:

```hcl
# Any downstream project — backend.tf
terraform {
  backend "s3" {
    bucket         = "myorg-terraform-state-123456789012"
    region         = "us-east-1"
    encrypt        = true
    kms_key_id     = "alias/terraform-state"
    use_lockfile   = true
    # key is injected via -backend-config in CI (see cicd-patterns.md)
  }
}
```

> **Critical gotcha:** `encrypt = true` without `kms_key_id` sends an explicit `AES256` header on PutObject, which **overrides** the bucket's default KMS encryption policy. Even if the bucket is configured for SSE-KMS, state files end up SSE-S3. The `DenyNonKMSEncryptedUploads` bucket policy above catches this misconfiguration by rejecting non-KMS uploads. Always set both `encrypt = true` **and** `kms_key_id` together.
>
> `kms_key_id` accepts a key ARN, key ID, or alias (prefixed with `alias/`).
>
> — [gruntwork-io/terragrunt#2293](https://github.com/gruntwork-io/terragrunt/issues/2293) documents this exact SSE-S3/SSE-KMS override behavior.

#### Bootstrap Lifecycle

| Step | When | Command |
|------|------|---------|
| 1. Create (local state) | Once per account/tier | `terraform init && terraform apply` |
| 2. Migrate to S3 | After step 1 succeeds | Add `backend "s3"` block → `terraform init -migrate-state` |
| 3. Add CI/CD role | New repo/pipeline needs access | Add policy attachment, re-apply |
| 4. Key rotation | Automatic | No action (`enable_key_rotation = true`) |

After step 2, the local `terraform.tfstate` is empty — the bootstrap project manages itself via S3.

> — [nozaq/terraform-aws-remote-state-s3-backend](https://github.com/nozaq/terraform-aws-remote-state-s3-backend) for a full-featured module implementing this pattern.

---

## Coding Standards

### Use Attachment Resources
```hcl
# BAD: Embedded security group rules
resource "aws_security_group" "lambda" {
  ingress {
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = ["10.0.0.0/8"]
  }
}

# GOOD: Separate attachment resources
resource "aws_security_group" "lambda" {
  name = "lambda-sg"
}

resource "aws_security_group_rule" "https" {
  type              = "ingress"
  from_port         = 443
  to_port           = 443
  protocol          = "tcp"
  cidr_blocks       = ["10.0.0.0/8"]
  security_group_id = aws_security_group.lambda.id
}
```

### Use Default Tags

Apply tags to all resources via `default_tags` in the provider — not resource-by-resource.

AWS-recommended tag taxonomy:

| Tag | Purpose |
|-----|---------|
| `Name` | Human-readable resource name |
| `AppId` | Application identifier |
| `AppRole` | Technical function (webserver, database, queue) |
| `AppPurpose` | Business purpose (payment processor, frontend ui) |
| `Environment` | dev, test, prod |
| `Project` | Project name |
| `CostCenter` | Billing / cost allocation |

```hcl
provider "aws" {
  region = var.region

  default_tags {
    tags = {
      AppId       = var.app_id
      AppRole     = var.app_role
      AppPurpose  = var.app_purpose
      Environment = var.environment
      Project     = var.project
      CostCenter  = var.cost_center
      ManagedBy   = "terraform"
    }
  }
}
```

