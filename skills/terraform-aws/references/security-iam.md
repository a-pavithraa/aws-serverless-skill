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

## Combining Policy Documents

Compose multiple scoped policy documents into one without inline merging:

```hcl
data "aws_iam_policy_document" "lambda_combined" {
  source_policy_documents = [
    data.aws_iam_policy_document.lambda_logs.json,
    data.aws_iam_policy_document.dynamodb.json,
    data.aws_iam_policy_document.s3.json,
  ]
}
```

---

## IAM Access Analyzer

Enable per-account to continuously identify resources shared outside the account, unused roles/permissions, and excessive access.

```hcl
resource "aws_accessanalyzer_analyzer" "main" {
  analyzer_name = "${local.name_prefix}-analyzer"
  type          = "ACCOUNT"
}
```

---

## Dynamic Infrastructure Scanning

Static analysis alone is insufficient — run post-deployment scans:

| Tool | What it catches |
|------|----------------|
| Amazon Inspector | EC2, Lambda, container vulnerabilities |
| AWS Security Hub CSPM | Recurring configuration drift scans |
| Amazon GuardDuty | Threat detection, anomalous API calls |
| Amazon Detective | Incident investigation and root cause |

---

## Policy Enforcement with Sentinel (HCP Terraform)

Sentinel policies evaluate before `apply` — violations block deployment without manual intervention:

- Require tags on all resources
- Restrict instance types to an approved list
- Block destruction of production resources
