---
name: terraform-aws
description: "Use when writing or reviewing Terraform for AWS: module layout, naming, state backends and locking, IAM least privilege and confused-deputy conditions, KMS key policies, keeping secrets out of state, OIDC for CI, or GitHub Actions plan and apply pipelines. Not for creating a new application (creating-aws-projects) or installing repository checks (aws-iac-team-harness)."
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
- **Don't** run `terraform apply`, `destroy`, `state` commands, `-target` or `-auto-approve` from an agent session. Apply runs in CI from the approved saved plan. The `aws-iac-team-harness` skill installs the checks and the reference workflow.
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

## Cost questions

For prices, use the AWS Pricing MCP server (`awslabs.aws-pricing-mcp-server`). Its [README](https://github.com/awslabs/mcp/tree/main/src/aws-pricing-mcp-server) has the setup. Prices in this skill are dated examples, not quotes.

---

## Reference Loading Strategy

Load **only** the reference file that matches the user's question. Never bulk-load all three.

| User is asking about | Load |
|---------------------|------|
| Module structure, naming, state, backend buckets | `references/terraform-structure.md` |
| IAM policies, least privilege, role design, SCPs, Checkov checks, KMS, secrets in state, OIDC | `references/security-iam.md` |
| CI/CD, GitHub Actions, OIDC, pipelines, ephemeral envs, drift | `references/cicd-patterns.md` |

For infrastructure **reviews**: load `terraform-structure.md` and `security-iam.md`. Only add `cicd-patterns.md` if the review scope includes pipeline config.
