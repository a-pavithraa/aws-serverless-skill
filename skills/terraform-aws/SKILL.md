---
name: terraform-aws
description: "Patterns and best practices for AWS infrastructure as code with Terraform. Use when the user asks about Terraform module structure, naming conventions, state management, IAM policies (least privilege, OIDC), CI/CD pipelines for infrastructure (GitHub Actions, OIDC authentication), or general IaC architecture decisions. Triggers on: Terraform, OpenTofu, IaC, modules, tfstate, remote state, OIDC, IAM, least privilege, GitHub Actions, CI/CD, infrastructure pipeline, AWS provider."
---

# Terraform AWS

## Quick Reference

| Topic | Reference File | Key Insight |
|-------|---------------|-------------|
| Module structure | `references/terraform-structure.md` | Don't wrap single resources in modules |
| Naming conventions | `references/terraform-structure.md` | Consistent `name_prefix` locals pattern |
| State management | `references/terraform-structure.md` | S3 native locking (Terraform 1.10+) — DynamoDB lock is deprecated |
| State backend bootstrap | `references/terraform-structure.md` | Separate bootstrap project with local state, SSE-KMS, CI/CD access policy |
| IAM & security | `references/security-iam.md` | LeadingKeys for multi-tenant, policy composition |
| CI/CD pipelines | `references/cicd-patterns.md` | Use OIDC — never store AWS keys as secrets |
| Multi-env pipelines | `references/cicd-patterns.md` | Per-branch backend keys, env resolver, ephemeral cleanup |
| Pipeline safety | `references/cicd-patterns.md` | Concurrency per env, environment protection gates, drift detection |

## Critical Anti-Patterns

### Module Design
- **Don't** wrap single AWS resources in modules — encapsulate logical groupings (Lambda + Role + Log Group)
- **Don't** nest modules more than 2 levels deep — keep hierarchy flat

### IAM
- **Don't** use `Resource: "*"` in IAM policies — scope to specific ARNs with conditions
- **Don't** attach `AdministratorAccess` to Lambda execution roles

### CI/CD
- **Don't** store AWS credentials as GitHub/CI secrets — use OIDC federation
- **Don't** run `terraform apply` directly on push to main — require plan review in PR
- **Don't** use `cancel-in-progress: true` on apply/destroy jobs — cancelling mid-apply corrupts state
- **Don't** skip `default_tags` with `Branch` tag — orphaned resources become untrackable
- **Don't** use shorthand `environment: ${{ needs.x.outputs.y }}` — must use object format `environment: name:`
- **Don't** rely on dynamic `environment: name:` without pre-creating the environment in repo settings — non-existent names silently create unprotected environments with no reviewers

## Decision Frameworks

### When to Create a Module
| Create a Module | Use Resource Directly |
|-----------------|----------------------|
| 3+ resources always deployed together | Single resource with no dependencies |
| Reused across 2+ environments or repos | One-off resource |
| Encapsulates non-obvious wiring (IAM + resource) | Simple resource with standard config |

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
| IAM policies, least privilege, role design, SCPs | `references/security-iam.md` (147 lines) |
| CI/CD, GitHub Actions, OIDC, pipelines, ephemeral envs, drift | `references/cicd-patterns.md` (642 lines) |

For infrastructure **reviews**: load `terraform-structure.md` + `security-iam.md` (331 lines). Only add `cicd-patterns.md` if the review scope includes pipeline config.
