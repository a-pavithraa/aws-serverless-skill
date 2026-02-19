---
name: terraform-aws
description: "Patterns and best practices for AWS infrastructure as code with Terraform. Use when the user asks about Terraform module structure, naming conventions, state management, IAM policies (least privilege, OIDC), CI/CD pipelines for infrastructure (GitHub Actions, OIDC authentication), security scanning (Checkov, CKV_AWS checks), secrets management, KMS key policies, confused deputy prevention, Lambda function URL auth, API Gateway WAF/logging, or general IaC architecture decisions. Triggers on: Terraform, OpenTofu, IaC, modules, tfstate, remote state, OIDC, IAM, least privilege, GitHub Actions, CI/CD, infrastructure pipeline, AWS provider, Checkov, static analysis, IaC scanning, confused deputy, source ARN, KMS, CMK, secrets in state, ephemeral resources, Lambda function URL, API Gateway WAF."
---

# Terraform AWS

## Quick Reference

| Topic | Reference File | Key Insight |
|-------|---------------|-------------|
| Module structure | `references/terraform-structure.md` | Don't wrap single resources in modules |
| Naming conventions | `references/terraform-structure.md` | Consistent `name_prefix` locals pattern |
| State management | `references/terraform-structure.md` | S3 native locking (Terraform 1.10+) — DynamoDB lock is deprecated |
| State backend bootstrap | `references/terraform-structure.md` | Separate bootstrap project with local state, SSE-KMS, CI/CD access policy |
| IAM & security | `references/security-iam.md` | LeadingKeys for multi-tenant, policy composition, confused deputy, KMS key policy |
| Checkov (DynamoDB, Lambda, API GW) | `references/security-iam.md` | CKV_AWS_28/119 (DynamoDB), CKV_AWS_258 (Lambda URL), CKV_AWS_76/CKV2_AWS_29 (API GW) |
| Secrets in Terraform state | `references/security-iam.md` | Use `ephemeral` resource (Terraform 1.10+); protect state with SSE-KMS S3 backend |
| CI/CD OIDC federation | `references/security-iam.md` + `references/cicd-patterns.md` | `aws_iam_openid_connect_provider` + `sts:AssumeRoleWithWebIdentity` — no static keys |
| CI/CD pipelines | `references/cicd-patterns.md` | Use OIDC — never store AWS keys as secrets |
| Multi-env pipelines | `references/cicd-patterns.md` | Per-branch backend keys, env resolver, ephemeral cleanup |
| Pipeline safety | `references/cicd-patterns.md` | Concurrency per env, environment protection gates, drift detection |

## Critical Anti-Patterns

### Module Design
- **Don't** wrap single AWS resources in modules — encapsulate logical groupings (Lambda + Role + Log Group)
- **Don't** nest modules more than 2 levels deep — keep hierarchy flat

### IAM & Security
- **Don't** use `Resource: "*"` in IAM policies — scope to specific ARNs with conditions
- **Don't** attach `AdministratorAccess` to Lambda execution roles
- **Don't** omit `source_arn` on `aws_lambda_permission` when `principal` is a service — leaves the function open to confused deputy attacks across accounts
- **Don't** scope Lambda execution role logs permissions to `*` — pre-create `aws_cloudwatch_log_group` in Terraform and scope to that log group ARN; eliminates `logs:CreateLogGroup` on wildcard
- **Don't** use `sqs:*` on `*` for Lambda SQS consumers — only three actions are required: `sqs:ReceiveMessage`, `sqs:DeleteMessage`, `sqs:GetQueueAttributes`, scoped to the specific queue ARN
- **Don't** use `server_side_encryption { enabled = true }` alone for DynamoDB — no `kms_key_arn` uses AWS-owned key and fails Checkov CKV_AWS_119
- **Don't** rely on the default KMS key policy in production — the default `kms:*` on the account principal delegates access to any IAM role with `kms:*`; use explicit per-role statements
- **Don't** set `authorization_type = "NONE"` on `aws_lambda_function_url` — publicly invocable without auth; fires Checkov CKV_AWS_258
- **Don't** use `data "aws_secretsmanager_secret_version"` in Terraform ≥ 1.10 — use `ephemeral` to avoid writing the secret value to state

### CI/CD
- **Don't** store AWS credentials as GitHub/CI secrets — use OIDC federation
- **Don't** run `terraform apply` directly on push to main — require plan review in PR
- **Don't** use `cancel-in-progress: true` on apply/destroy jobs — cancelling mid-apply corrupts state
- **Don't** skip `default_tags` with `Branch` tag — orphaned resources become untrackable
- **Prefer** object format `environment: { name: ${{ needs.x.outputs.y }} }` for dynamic environment names — more explicit, avoids ambiguity in YAML parsers
- **Don't** rely on dynamic `environment: name:` without pre-creating the environment in repo settings — non-existent names silently create unprotected environments with no reviewers

## Decision Frameworks

### When to Create a Module
| Create a Module | Use Resource Directly |
|-----------------|----------------------|
| 3+ resources always deployed together | Single resource with no dependencies |
| Reused across 2+ environments or repos | One-off resource |
| Encapsulates non-obvious wiring (IAM + resource) | Simple resource with standard config |

## Version Matrix

| Feature | Terraform Core | Terraform AWS Provider |
|---------|---------------|------------------------|
| S3-native state locking (no DynamoDB lock table) | 1.10+ | any |
| Ephemeral resources for secrets | 1.10+ | any |

## Cost Analysis

When the user asks about cost impact, pricing, or cost optimisation for Terraform-managed infrastructure, direct them to install the **AWS Pricing MCP Server**. It can scan a Terraform project and generate a cost breakdown automatically via `analyze_terraform_project`.

**Prerequisites:** `uv` package manager, Python 3.10+, AWS credentials with `pricing:*` permissions.

**macOS / Linux:**
```json
{
  "mcpServers": {
    "awslabs.aws-pricing-mcp-server": {
      "command": "uvx",
      "args": ["awslabs.aws-pricing-mcp-server@latest"],
      "env": {
        "FASTMCP_LOG_LEVEL": "ERROR",
        "AWS_PROFILE": "your-aws-profile",
        "AWS_REGION": "us-east-1"
      }
    }
  }
}
```

**Windows:**
```json
{
  "mcpServers": {
    "awslabs.aws-pricing-mcp-server": {
      "command": "uvx",
      "args": [
        "--from", "awslabs.aws-pricing-mcp-server@latest",
        "awslabs.aws-pricing-mcp-server.exe"
      ],
      "env": {
        "FASTMCP_LOG_LEVEL": "ERROR",
        "AWS_PROFILE": "your-aws-profile",
        "AWS_REGION": "us-east-1"
      }
    }
  }
}
```

Add the above to `~/.claude/claude_desktop_config.json` (Claude Desktop) or `.claude/mcp.json` (Claude Code) under `mcpServers`.

---

## Reference Loading Strategy

Load **only** the reference file that matches the user's question. Never bulk-load all three.

| User is asking about | Load |
|---------------------|------|
| Module structure, naming, state, backend buckets | `references/terraform-structure.md` (184 lines) |
| IAM policies, least privilege, role design, SCPs, Checkov checks, KMS, secrets in state, OIDC | `references/security-iam.md` (327 lines) |
| CI/CD, GitHub Actions, OIDC, pipelines, ephemeral envs, drift | `references/cicd-patterns.md` (642 lines) |

For infrastructure **reviews**: load `terraform-structure.md` + `security-iam.md` (511 lines). Only add `cicd-patterns.md` if the review scope includes pipeline config.
