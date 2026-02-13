# AWS Serverless & Terraform — Knowledge Base

A Claude Code skill library for AWS serverless and infrastructure-as-code patterns. Contains non-obvious gotchas, and decision frameworks — not introductory content any model already knows.

## Installation

### Claude Code (Plugin Marketplace)

```bash
/plugin marketplace add a-pavithraa/aws-serverless-skill
/plugin enable a-pavithraa/aws-serverless-skill
```

### Claude Code (Manual)

```bash
git clone https://github.com/a-pavithraa/aws-serverless-skill.git

cp -r aws-serverless-skill/skills/* ~/.claude/skills/
```

### Codex (Manual)

```bash
git clone https://github.com/a-pavithraa/aws-serverless-skill.git

mkdir -p ~/.codex/skills
cp -r aws-serverless-skill/skills/* ~/.codex/skills/
```

## Usage

### Claude Code

Skills are automatically discovered and loaded when relevant:

```
You: "How should I structure my Terraform backend for multiple environments?"
Claude: [Automatically loads terraform-aws skill]

You: "Design a DynamoDB table for a multi-tenant SaaS app"
Claude: [Automatically loads aws-dynamodb skill]
```

### Codex

Skills must be explicitly invoked:

```
using $terraform-aws set up a multi-environment CI/CD pipeline
using $aws-dynamodb design a single-table schema for orders and inventory
using $aws-serverless implement an SQS-triggered Lambda with DLQ
```

## Skills

### `terraform-aws`

Patterns for AWS infrastructure with Terraform.

| Reference | Contents |
|-----------|----------|
| `references/terraform-structure.md` | Module design, state management, S3 backend bootstrap (KMS, bucket policy, migration), environment isolation strategy |
| `references/security-iam.md` | Non-obvious IAM patterns: DynamoDB LeadingKeys, policy document composition, IAM Access Analyzer |
| `references/cicd-patterns.md` | Multi-environment GitHub Actions pipeline, environment resolver, per-branch backend keys, resource naming, default_tags, pipeline quality gates, ephemeral environment cleanup, drift detection |

**Triggers on:** Terraform, IaC, modules, tfstate, remote state, OIDC, IAM, GitHub Actions, CI/CD, infrastructure pipeline, AWS provider

---

### `aws-dynamodb`

Data modeling patterns for Amazon DynamoDB.

| Reference | Contents |
|-----------|----------|
| `references/dynamodb-patterns.md` | Single-table design, access pattern modeling, GSI patterns, multi-attribute composite keys (provider v6.29.0+), one-to-many relationships, cost optimization |

**Triggers on:** DynamoDB, single-table design, GSI, partition key, sort key, access patterns, filter expressions, composite keys

---

### `aws-serverless`

Patterns for Lambda, API Gateway, and event-driven architecture on AWS.

| Reference | Contents |
|-----------|----------|
| `references/lambda-patterns.md` | Cold starts, concurrency, memory tuning, Lambda Layers |
| `references/lambda-powertools.md` | AWS Lambda Powertools — structured logging, tracing, metrics |
| `references/api-gateway.md` | API Gateway v2 (HTTP API), authorizers, integrations |
| `references/event-driven.md` | SQS, SNS, EventBridge patterns, DLQs |
| `references/monitoring.md` | CloudWatch, X-Ray, alerting patterns |

**Triggers on:** Lambda, API Gateway, SQS, SNS, EventBridge, cold start, concurrency, Powertools, serverless

---

## Design Principles

- **No common knowledge.** Every section must contain something a model won't produce correctly unprompted.
- **Load selectively.** Skills load only the reference file relevant to the question — never bulk-load all references.
- **Cite sources.** Non-obvious patterns link to official docs, GitHub issues, or PRs that verify the claim.

## Credits

- DynamoDB modeling patterns: [Alex DeBrie](https://www.alexdebrie.com/) — author of [The DynamoDB Book](https://www.dynamodbbook.com/)
- Serverless / Lambda patterns: [Yan Cui (theburningmonk)](https://theburningmonk.com/)

## Prerequisites

- Claude Code CLI or Codex CLI
- AWS account with appropriate IAM permissions
