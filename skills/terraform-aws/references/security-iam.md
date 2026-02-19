# Security & IAM — Non-Obvious Patterns

## DynamoDB LeadingKeys Condition

Restrict writes to specific partition key prefixes — useful for multi-tenant isolation:

```hcl
data "aws_iam_policy_document" "dynamodb" {
  statement {
    effect = "Allow"
    actions = [
      "dynamodb:PutItem",
      "dynamodb:UpdateItem",
      "dynamodb:DeleteItem"
    ]
    resources = [aws_dynamodb_table.main.arn]

    condition {
      test     = "ForAllValues:StringLike"
      variable = "dynamodb:LeadingKeys"
      values   = ["TENANT#${var.tenant_id}#*"]
    }
  }
}
```

---

## Policy Enforcement with Sentinel (HCP Terraform)

Sentinel policies evaluate before `apply`. Three enforcement levels control what happens on violation:

| Level | Behaviour |
|-------|-----------|
| **Advisory** | Warning logged; run continues |
| **Soft-Mandatory** | Run blocked; designated override users can bypass |
| **Hard-Mandatory** | Run blocked; no override possible |

Soft-Mandatory is the practical starting point — it gates without permanently blocking teams that need an escape valve during rollout. Promote to Hard-Mandatory once a policy is stable and well understood.

---

## Static Analysis — IaC Scanning

In HCL mode, pick **one** tool — running both generates duplicate findings for the same resources under different check ID namespaces (`AVD-AWS-*` vs `CKV_AWS_*`). Plan-mode scanning is always Checkov.

| Scenario | Use Checkov | Use Trivy |
|----------|-------------|-----------|
| Lambda zip deployments (no containers) | ✓ HCL + plan mode | — marginal value |
| Lambda container image deployments | ✓ Plan mode | ✓ IaC + image scan (one tool) |
| Container image CVE scan | ✗ Not supported | ✓ Only option (`trivy image`) |
| Plan-mode scan (cross-resource graph) | ✓ Mature (`framework: terraform_plan`) | Supported but has a known limitation with `each`/`count` expressions |
| Secret detection in `.tf` files | Partial (IaC-specific hardcoded value checks) | ✓ `trivy fs --scanners secret,misconfig` |
| Custom policies | Python or YAML | Rego |
| Bridgecrew / Prisma Cloud integration | ✓ Native | ✗ |

Two scanning stages regardless of tool choice:

| Stage | Mode | Input | Catches |
|-------|------|-------|---------|
| PR / pre-plan | HCL | Raw `.tf` files | Per-resource misconfigs |
| Post-plan | Plan | `tfplan.json` | Cross-resource issues (only visible once the resource graph is resolved) |

### Trivy

[Trivy](https://trivy.dev) (`trivy config`) is the actively maintained successor to tfsec — same underlying detection engine, broader ecosystem. `tfsec <dir>` maps directly to `trivy config <dir>`. Custom checks are written in Rego.

```bash
# With tfvars (resolves variable references in rule evaluation)
trivy config --tf-vars environments/prod.tfvars terraform/

# Plan JSON — same command, pass the file directly
trivy config tfplan.json

# IaC + secret detection in one pass (trivy fs, not trivy config)
trivy fs --scanners secret,misconfig --severity HIGH,CRITICAL terraform/
```

> `trivy config` does not run secret scanning. To detect hardcoded credentials alongside IaC misconfigs, use `trivy fs --scanners secret,misconfig`.

Minimal `trivy.yaml` at project root:

```yaml
severity:
  - HIGH
  - CRITICAL
misconfiguration:
  terraform:
    exclude-downloaded-modules: true  # skip .terraform/modules — third-party, not your code
```

### Checkov: DynamoDB

| Check ID | Non-obvious detail |
|----------|--------------------|
| `CKV_AWS_119` | `server_side_encryption { enabled = true }` with no `kms_key_arn` uses an AWS-owned key and **silently fails** this check. A customer-managed key is required. |

```hcl
resource "aws_kms_key" "dynamodb" {
  description             = "DynamoDB CMK"
  deletion_window_in_days = 7
  enable_key_rotation     = true
  tags                    = var.tags
}

resource "aws_dynamodb_table" "example" {
  # ...

  server_side_encryption {
    enabled     = true
    kms_key_arn = aws_kms_key.dynamodb.arn  # CKV_AWS_119 ✓
  }

  point_in_time_recovery {
    enabled = true  # CKV_AWS_28 ✓
  }

  deletion_protection_enabled = true  # No Checkov check — enforced by AWS Config + Security Hub DynamoDB.6

  tags = var.tags
}
```

> `CKV_AWS_165` (PITR for `aws_dynamodb_global_table`) always returns PASSED in Terraform — the Checkov source unconditionally returns PASSED because the field is not configurable at the global table resource level. Configure PITR on the underlying table resources instead.

### Checkov: Lambda

| Check ID | Non-obvious detail |
|----------|--------------------|
| `CKV_AWS_50` | Accepts both `"Active"` and `"PassThrough"`. PassThrough propagates trace headers but does not sample — traces only appear if the upstream caller initiates them. Prefer `"Active"`. |
| `CKV_AWS_258` | Covers `aws_lambda_function_url` only. Easy to overlook since Function URLs are a separate resource from the function itself. Fix: `authorization_type = "AWS_IAM"`. |

> **Log group pre-creation**: Pre-create `aws_cloudwatch_log_group "/aws/lambda/${var.function_name}"` in Terraform and scope execution role log permissions to that ARN. Eliminates `logs:CreateLogGroup` on `*` and enables `retention_in_days`. Without it, Lambda auto-creates on first invocation, requiring wildcard permissions.

### Checkov: API Gateway

| Check ID | Non-obvious detail |
|----------|--------------------|
| `CKV2_AWS_29` | Covers REST APIs (`aws_api_gateway_rest_api`) only. Teams switching to HTTP APIs (`aws_apigatewayv2_api`) lose this WAF check silently — the check simply does not fire. |

### CI Integration (GitHub Actions)

**Scenario A — Lambda zip deployments (no container images)**

Checkov only, two passes:

```yaml
# Pre-plan: HCL scan
- uses: bridgecrewio/checkov-action@v12
  with:
    directory: terraform/
    framework: terraform
    quiet: true
    soft_fail: false

# Post-plan: graph-aware scan
- name: Export plan to JSON
  run: terraform show -json tfplan > tfplan.json

- uses: bridgecrewio/checkov-action@v12
  with:
    file: terraform/tfplan.json
    framework: terraform_plan   # not "terraform" — plan mode uses a separate rule set
    quiet: true
    soft_fail: false
```

**Scenario B — Lambda container image deployments**

Trivy covers the container image and IaC scan. Checkov adds plan-mode graph checks.

```yaml
# Container image scan — OS-level CVEs; Checkov cannot do this
- uses: aquasecurity/trivy-action@0.30.0
  with:
    scan-type: image
    image-ref: ${{ env.IMAGE_URI }}
    severity: HIGH,CRITICAL
    exit-code: '1'
    format: sarif
    output: trivy-image.sarif

# IaC scan — reuse Trivy since it is already in the pipeline
- uses: aquasecurity/trivy-action@0.30.0
  with:
    scan-type: config
    scan-ref: terraform/
    severity: HIGH,CRITICAL
    exit-code: '1'

# Plan-mode: cross-resource graph checks
- name: Export plan to JSON
  run: terraform show -json tfplan > tfplan.json

- uses: bridgecrewio/checkov-action@v12
  with:
    file: terraform/tfplan.json
    framework: terraform_plan
    quiet: true
    soft_fail: false

- uses: github/codeql-action/upload-sarif@v3
  if: always()
  with:
    sarif_file: trivy-image.sarif
```

> SARIF upload surfaces container scan findings as code scanning alerts in GitHub's Security tab — inline on PRs rather than buried in build logs.

> Trivy supports plan JSON (`trivy config tfplan.json`) but has a confirmed limitation: resources using `each` or `count` expressions may produce incomplete results because the plan JSON omits attribute-level reference information for those constructs. Use Checkov for plan-mode scanning.

For centralized policy management across repos, see [AWS Prescriptive Guidance: Centralized Custom Checkov Scanning](https://docs.aws.amazon.com/prescriptive-guidance/latest/patterns/centralized-custom-checkov-scanning.html) — store custom policies and reusable workflows in a central repo; individual repos reference the shared workflow.

---

## Secrets in Terraform State

**Ephemeral resources (Terraform ≥ 1.10)** are not persisted to state or plan files — use them for any secret read:

```hcl
# data block — secret_string written to tfstate in plaintext
data "aws_secretsmanager_secret_version" "db" {
  secret_id = aws_secretsmanager_secret.db.id
}

# ephemeral block — not persisted to state or plan file
ephemeral "aws_secretsmanager_secret_version" "db" {
  secret_id = aws_secretsmanager_secret.db.id
}
```

> `use_lockfile = true` on the S3 backend (Terraform ≥ 1.10) replaces the deprecated `dynamodb_table` attribute for state locking.

---

## KMS Key Policy: Default IAM Delegation

When you create a KMS CMK, the default key policy includes:

```json
{
  "Sid": "Enable IAM User Permissions",
  "Effect": "Allow",
  "Principal": { "AWS": "arn:aws:iam::ACCOUNT_ID:root" },
  "Action": "kms:*",
  "Resource": "*"
}
```

This delegates full key access to IAM — meaning **any IAM principal in the account that holds a policy granting `kms:*` or `kms:Decrypt` can use the key**, even if you didn't intend them to. IAM policies cannot *override* a key policy Allow; they can only add permissions on top of it.

The safe pattern is to remove the broad delegation statement and add explicit statements per service and role:

```hcl
resource "aws_kms_key" "lambda_env" {
  description         = "Lambda environment variable encryption"
  enable_key_rotation = true

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        # Emergency break-glass only — restrict in production
        Sid       = "RootAccess"
        Effect    = "Allow"
        Principal = { AWS = "arn:aws:iam::${data.aws_caller_identity.current.account_id}:root" }
        Action    = "kms:*"
        Resource  = "*"
      },
      {
        Sid       = "LambdaDecrypt"
        Effect    = "Allow"
        Principal = { AWS = aws_iam_role.lambda_exec.arn }
        Action    = ["kms:Decrypt", "kms:GenerateDataKey"]
        Resource  = "*"
      },
      {
        # Restrict grants to AWS service use only — prevents manual grant abuse
        Sid       = "LambdaGrant"
        Effect    = "Allow"
        Principal = { AWS = aws_iam_role.lambda_exec.arn }
        Action    = ["kms:CreateGrant", "kms:ListGrants", "kms:RevokeGrant"]
        Resource  = "*"
        Condition = { Bool = { "kms:GrantIsForAWSResource" = "true" } }
      }
    ]
  })
}
```

---

## SQS → Lambda: Event Source Mapping Permissions

The Lambda event source mapping polls SQS using the **function's execution role**, not a separate polling role. The execution role needs exactly three actions, scoped to the specific queue:

```hcl
statement {
  actions = [
    "sqs:ReceiveMessage",      # Poll for messages
    "sqs:DeleteMessage",       # Delete after successful processing
    "sqs:GetQueueAttributes",  # Read queue metadata (batch size, visibility timeout)
  ]
  resources = [aws_sqs_queue.input.arn]
}
```

**For KMS-encrypted queues**, add `kms:Decrypt` on the queue's CMK:

```hcl
statement {
  actions   = ["kms:Decrypt"]
  resources = [aws_kms_key.sqs.arn]
}
```

> These are the exact three actions in the `AWSLambdaSQSQueueExecutionRole` AWS managed policy (verified from AWS managed policy reference). The managed policy scopes to `*` — always replace with the specific queue ARN in custom policies.
