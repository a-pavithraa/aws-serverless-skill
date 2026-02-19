# CI/CD Patterns for Serverless

## OIDC Authentication (No Access Keys)

**Never store AWS access keys in GitHub secrets.** Use OIDC instead.

### Terraform Setup for OIDC
```hcl
resource "aws_iam_openid_connect_provider" "github" {
  url = "https://token.actions.githubusercontent.com"

  client_id_list = ["sts.amazonaws.com"]

  thumbprint_list = ["6938fd4d98bab03faadb97b34396831e3780aea1"]
}

resource "aws_iam_role" "github_actions" {
  name = "github-actions-deploy"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Principal = {
        Federated = aws_iam_openid_connect_provider.github.arn
      }
      Action = "sts:AssumeRoleWithWebIdentity"
      Condition = {
        StringEquals = {
          "token.actions.githubusercontent.com:aud" = "sts.amazonaws.com"
        }
        StringLike = {
          "token.actions.githubusercontent.com:sub" = "repo:YOUR_ORG/YOUR_REPO:ref:refs/heads/main"
        }
      }
    }]
  })
}
```

### GitHub Actions Usage
```yaml
permissions:
  id-token: write
  contents: read

steps:
  - uses: aws-actions/configure-aws-credentials@v4
    with:
      role-to-assume: ${{ secrets.AWS_ROLE_ARN }}
      aws-region: us-east-1
```

---

## Lambda Versioning & Aliases

### Blue-Green Deployments with Aliases
```hcl
resource "aws_lambda_function" "api" {
  function_name = var.function_name
  publish       = true
}

resource "aws_lambda_alias" "live" {
  name             = "live"
  function_name    = aws_lambda_function.api.function_name
  function_version = aws_lambda_function.api.version

  # Optional: Traffic shifting for canary deploys
  # routing_config {
  #   additional_version_weights = {
  #     "${aws_lambda_function.api.version}" = 0.1
  #   }
  # }
}

# API Gateway points to alias, not $LATEST
resource "aws_apigatewayv2_integration" "lambda" {
  api_id           = aws_apigatewayv2_api.api.id
  integration_type = "AWS_PROXY"
  integration_uri  = aws_lambda_alias.live.invoke_arn
}
```

---

## Rollback Strategy

### Alias-Based Rollback

```hcl
resource "aws_lambda_alias" "live" {
  name             = "live"
  function_name    = aws_lambda_function.api.function_name
  function_version = aws_lambda_function.api.version
}

resource "aws_lambda_alias" "previous" {
  name             = "previous"
  function_name    = aws_lambda_function.api.function_name
  function_version = max(1, tonumber(aws_lambda_function.api.version) - 1)
}
```

### Manual Rollback
```bash
aws lambda update-alias \
  --function-name my-function \
  --name live \
  --function-version 5
```

---

## Container Image Deployment

For Lambda functions > 50MB or with complex dependencies:

```hcl
resource "aws_ecr_repository" "lambda" {
  name                 = var.function_name
  image_tag_mutability = "IMMUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }
}

resource "aws_lambda_function" "api" {
  function_name = var.function_name
  package_type  = "Image"
  image_uri     = "${aws_ecr_repository.lambda.repository_url}:${var.image_tag}"
  role          = aws_iam_role.lambda.arn
  timeout       = 30
  memory_size   = 512
}
```

---

## Terraform Pipeline Architecture

Plan-first, manually-applied, multi-environment GitHub Actions flow with per-branch state isolation.

### Environment Resolution

A composite action maps Git refs to environment config. This single source of truth drives backend key, tfvars, resource naming, and tagging.

```yaml
# .github/actions/resolve-environment/action.yml
name: Resolve Terraform Environment
description: Maps git ref to environment, tfvars file, and backend state key

outputs:
  environment:
    description: Environment name (prod, qa, or sanitized branch name)
    value: ${{ steps.resolve.outputs.environment }}
  tfvars_file:
    description: Path to tfvars file
    value: ${{ steps.resolve.outputs.tfvars_file }}
  backend_key:
    description: S3 backend state key
    value: ${{ steps.resolve.outputs.backend_key }}
  is_ephemeral:
    description: Whether this is a short-lived branch environment
    value: ${{ steps.resolve.outputs.is_ephemeral }}
  protected_environment:
    description: GitHub Environment name for protection rules (empty for ephemeral)
    value: ${{ steps.resolve.outputs.protected_environment }}

runs:
  using: composite
  steps:
    - id: resolve
      shell: bash
      run: |
        REF="${{ github.event.ref || github.ref }}"
        REF_NAME="${REF#refs/heads/}"
        REF_NAME="${REF_NAME#refs/tags/}"

        if [[ "$REF" == refs/tags/release* ]]; then
          ENV="prod"
          TFVARS="environments/prod.tfvars"
          BACKEND_KEY="prod/terraform.tfstate"
          IS_EPHEMERAL="false"
          PROTECTED_ENV="production"
        elif [[ "$REF_NAME" == "main" ]]; then
          ENV="qa"
          TFVARS="environments/qa.tfvars"
          BACKEND_KEY="qa/terraform.tfstate"
          IS_EPHEMERAL="false"
          PROTECTED_ENV="qa"
        else
          # Sanitize branch name: lowercase, replace non-alphanum with dash, truncate
          SANITIZED=$(echo "$REF_NAME" | tr '[:upper:]' '[:lower:]' | sed 's/[^a-z0-9]/-/g' | cut -c1-20)
          # Append short hash to avoid collisions between branches with similar prefixes
          HASH=$(echo -n "$REF_NAME" | sha256sum | cut -c1-6)
          ENV="${SANITIZED}-${HASH}"
          TFVARS="environments/dev.tfvars"
          BACKEND_KEY="branches/${ENV}/terraform.tfstate"
          IS_EPHEMERAL="true"
          PROTECTED_ENV=""
        fi

        echo "environment=${ENV}" >> "$GITHUB_OUTPUT"
        echo "tfvars_file=${TFVARS}" >> "$GITHUB_OUTPUT"
        echo "backend_key=${BACKEND_KEY}" >> "$GITHUB_OUTPUT"
        echo "is_ephemeral=${IS_EPHEMERAL}" >> "$GITHUB_OUTPUT"
        echo "protected_environment=${PROTECTED_ENV}" >> "$GITHUB_OUTPUT"
```

### Per-Branch Backend State

Each branch gets its own state file via partial backend configuration. The HCL backend block defines the bucket and region; the `key` is injected at init time.

For regulated environments, use separate buckets per trust boundary (prod vs non-prod) and key paths within each bucket for branch isolation. See `terraform-structure.md` → "Separate Backends Per Environment" for the bucket strategy.

```hcl
# backend.tf — partial configuration (key omitted intentionally)
# The bucket itself may differ per trust tier (prod vs non-prod).
# The key is always injected dynamically per branch/environment.
terraform {
  backend "s3" {
    bucket = "myproject-terraform-state"
    region = "us-east-1"
    # key is provided via -backend-config at init time
  }
}
```

```bash
# CI init step — key comes from environment resolver
terraform init \
  -input=false \
  -reconfigure \
  -backend-config="key=${{ needs.resolve.outputs.backend_key }}"
```

> `-reconfigure` is needed in CI because each run may target a different backend key. It reinitializes the backend from scratch without attempting state migration. Always pair with `-input=false` to prevent interactive prompts.

### Resource Naming with Environment Suffix

Non-production resources include the environment name for identification. Production has no suffix.

```hcl
variable "environment" {
  type = string
}

locals {
  env_suffix  = var.environment == "prod" ? "" : "-${var.environment}"
  name_prefix = "myapp${local.env_suffix}"
}

resource "aws_lambda_function" "api" {
  function_name = "${local.name_prefix}-api"
  # prod: "myapp-api", branch: "myapp-feat-login-a1b2c3-api"
}

resource "aws_dynamodb_table" "main" {
  name = "${local.name_prefix}-orders"
  # prod: "myapp-orders", branch: "myapp-feat-login-a1b2c3-orders"
}
```

### Environment Tagging

Tag every resource with the source branch/environment. This enables cleanup of orphaned resources if a branch is deleted before `terraform destroy` runs.

```hcl
# provider.tf
variable "environment" {
  type = string
}

variable "branch_name" {
  type    = string
  default = ""
}

provider "aws" {
  region = var.region

  default_tags {
    tags = {
      ManagedBy   = "terraform"
      Environment = var.environment
      Branch      = var.branch_name
      Project     = "myapp"
    }
  }
}
```

> `default_tags` (AWS provider v3.38.0+) propagates to all resources that support tags without repeating them per resource. Resource-level `tags` override defaults if keys overlap.
>
> **Caveats:**
> - `aws_autoscaling_group` is explicitly excluded — use `tag {}` blocks directly on that resource.
> - Never pass the same tag key via both `default_tags` and a resource/module `tags` variable — causes perpetual plan diffs ([hashicorp/terraform-provider-aws#18311](https://github.com/hashicorp/terraform-provider-aws/issues/18311)).
> - Never use computed values (`timestamp()`, `formatdate()`) in `default_tags` — use static strings only.
> - Use `tags_all` (not `tags`) in outputs/references that need the full merged tag set.

Pass branch name from CI:

```bash
terraform plan \
  -var="environment=${{ needs.resolve.outputs.environment }}" \
  -var="branch_name=${{ github.ref_name }}" \
  -var-file="${{ needs.resolve.outputs.tfvars_file }}" \
  -out=tfplan
```

---

## Pipeline Quality Gates

### Linting & Security Checks (Before Plan)

Run formatting, linting, and security scanning before `terraform plan`. These are fast, read-only, and catch issues early.

```yaml
jobs:
  lint-and-security:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - uses: hashicorp/setup-terraform@v3

      - name: Format check
        run: terraform fmt -check -recursive -diff
        # Exit code 0 = formatted, non-zero = needs formatting.
        # -diff shows what would change. -recursive checks nested dirs.

      - uses: terraform-linters/setup-tflint@v6
        with:
          github_token: ${{ secrets.GITHUB_TOKEN }}

      - name: TFLint init
        run: tflint --init
        working-directory: terraform/

      - name: TFLint
        run: tflint --format compact --recursive
        working-directory: terraform/

      - uses: bridgecrewio/checkov-action@v12
        with:
          directory: terraform/
          framework: terraform
          quiet: true        # only show failures
          soft_fail: false   # block the pipeline on failures
```

> For Lambda container image deployments, replace the Checkov HCL step with `trivy-action` (image + config scan) and keep Checkov for plan-mode only. See `security-iam.md` → "CI Integration" for the container scenario pipeline.

---

## Pipeline Safety Controls

### Concurrency per Environment

Prevent parallel applies or destroys against the same Terraform state. Uses the `needs` context to key on the resolved environment.

```yaml
jobs:
  terraform-plan:
    # ...plan job that outputs environment name...
    outputs:
      tf_environment: ${{ steps.resolve.outputs.environment }}

  terraform-apply:
    needs: terraform-plan
    concurrency:
      group: terraform-${{ needs.terraform-plan.outputs.tf_environment }}
      cancel-in-progress: false  # never cancel an in-progress apply
    steps:
      # ...
```

> Concurrency keys support `needs` context. `cancel-in-progress: false` is critical — cancelling a running `terraform apply` can leave state locked or resources half-created.

### Environment Protection for Apply

Use GitHub Environments with required reviewers to gate infrastructure mutations. The environment name must use the **object format** when set dynamically from a previous job's output.

```yaml
jobs:
  terraform-apply:
    needs: terraform-plan
    if: needs.terraform-plan.outputs.has_changes == 'true'
    # Object format is the explicit, unambiguous choice for dynamic environment names.
    # Both string and object forms accept expressions; prefer object form for clarity.
    environment:
      name: ${{ needs.terraform-plan.outputs.protected_environment }}
    concurrency:
      group: terraform-${{ needs.terraform-plan.outputs.tf_environment }}
      cancel-in-progress: false
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      # ... init, download plan artifact, apply ...
```

Configure required reviewers in GitHub repo Settings → Environments → select environment → Required reviewers (up to 6; only 1 needs to approve).

### Destroy Controls

Restrict `terraform destroy` to specific actors and require explicit confirmation.

```yaml
  terraform-destroy:
    needs: terraform-plan
    if: >-
      github.event_name == 'workflow_dispatch' &&
      github.event.inputs.action == 'destroy' &&
      github.event.inputs.confirm_destroy == 'DESTROY'
    environment:
      name: ${{ needs.terraform-plan.outputs.protected_environment }}
    runs-on: ubuntu-latest
    steps:
      - name: Verify actor
        run: |
          ALLOWED_ACTORS="admin-user,lead-engineer"
          if [[ ! ",$ALLOWED_ACTORS," == *",${{ github.actor }},"* ]]; then
            echo "::error::Actor ${{ github.actor }} is not authorized for destroy"
            exit 1
          fi

      - uses: actions/checkout@v4
      # ... init with correct backend key, then terraform destroy ...
```

---

## Ephemeral Environment Cleanup

### Branch Deletion Trigger

When a branch is deleted, automatically destroy its ephemeral infrastructure.

```yaml
# .github/workflows/terraform-cleanup.yml
name: Terraform Cleanup

on:
  delete:
    # Triggers when any branch or tag is deleted.
    # Workflow runs from the DEFAULT branch (the deleted branch's code is gone).
    # github.event.ref = deleted ref name, github.event.ref_type = "branch" or "tag"

jobs:
  resolve:
    if: github.event.ref_type == 'branch'
    runs-on: ubuntu-latest
    outputs:
      environment: ${{ steps.resolve.outputs.environment }}
      backend_key: ${{ steps.resolve.outputs.backend_key }}
      is_ephemeral: ${{ steps.resolve.outputs.is_ephemeral }}
    steps:
      - uses: actions/checkout@v4
      - uses: ./.github/actions/resolve-environment
        id: resolve

  cleanup:
    needs: resolve
    if: needs.resolve.outputs.is_ephemeral == 'true'
    runs-on: ubuntu-latest
    concurrency:
      group: terraform-${{ needs.resolve.outputs.environment }}
      cancel-in-progress: false
    steps:
      - uses: actions/checkout@v4

      - uses: aws-actions/configure-aws-credentials@v4
        with:
          role-to-assume: ${{ secrets.AWS_ROLE_ARN }}
          aws-region: us-east-1

      - uses: hashicorp/setup-terraform@v3

      - name: Init with branch backend key
        run: |
          terraform init \
            -input=false \
            -reconfigure \
            -backend-config="key=${{ needs.resolve.outputs.backend_key }}"
        working-directory: terraform/

      - name: Destroy
        run: terraform destroy -auto-approve -var-file="environments/dev.tfvars" -var="environment=${{ needs.resolve.outputs.environment }}"
        working-directory: terraform/
```

> The `delete` event runs the workflow **from the default branch**, not the deleted branch. `github.event.ref` contains the deleted ref name. The workflow file must exist on the default branch.
>
> — [GitHub: Events that trigger workflows — delete](https://docs.github.com/en/actions/writing-workflows/choosing-when-your-workflow-runs/events-that-trigger-workflows#delete)

### Tag-Based Orphan Cleanup

If a branch is deleted before the cleanup workflow runs (or cleanup fails), use the `Branch` tag to find and destroy orphaned resources.

```bash
#!/usr/bin/env bash
# scripts/cleanup-orphaned-resources.sh
# Finds AWS resources tagged with a branch that no longer exists in the remote.

set -euo pipefail

REMOTE_BRANCHES=$(git ls-remote --heads origin | awk '{print $2}' | sed 's|refs/heads/||')

TAGGED_BRANCHES=$(
  aws resourcegroupstaggingapi get-resources \
    --tag-filters Key=ManagedBy,Values=terraform Key=Project,Values=myapp \
    --query "ResourceTagMappingList[].Tags[?Key=='Branch'].Value" \
    --output text | sort -u
)

for BRANCH in $TAGGED_BRANCHES; do
  if ! echo "$REMOTE_BRANCHES" | grep -qx "$BRANCH"; then
    echo "Orphaned branch found: $BRANCH"
    echo "Resources:"
    aws resourcegroupstaggingapi get-resources \
      --tag-filters Key=Branch,Values="$BRANCH" Key=ManagedBy,Values=terraform \
      --query "ResourceTagMappingList[].ResourceARN" \
      --output text
    echo "---"
    echo "Run terraform destroy for this environment, or delete resources manually."
  fi
done
```

> `get-resources` uses AND logic across tag filters, OR logic across values within a filter.

To automate fully, pair with a scheduled workflow that runs the cleanup script and triggers `terraform destroy` for each orphaned environment:

```yaml
# .github/workflows/orphan-cleanup.yml
name: Orphan Environment Cleanup
on:
  schedule:
    - cron: '0 3 * * 1'  # Weekly Monday 3 AM UTC
  workflow_dispatch:

jobs:
  find-orphans:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0

      - uses: aws-actions/configure-aws-credentials@v4
        with:
          role-to-assume: ${{ secrets.AWS_ROLE_ARN }}
          aws-region: us-east-1

      - name: Find orphaned branch environments
        run: bash scripts/cleanup-orphaned-resources.sh
```

---

## Drift Detection

Run a read-only plan on a schedule to catch out-of-band changes (console edits, manual CLI changes).

```yaml
# .github/workflows/drift-detection.yml
name: Terraform Drift Detection
on:
  schedule:
    - cron: '0 6 * * *'  # Daily 6 AM UTC
  workflow_dispatch:

jobs:
  detect-drift:
    runs-on: ubuntu-latest
    strategy:
      matrix:
        environment: [prod, qa]
        include:
          - environment: prod
            tfvars: environments/prod.tfvars
            backend_key: prod/terraform.tfstate
          - environment: qa
            tfvars: environments/qa.tfvars
            backend_key: qa/terraform.tfstate
    steps:
      - uses: actions/checkout@v4

      - uses: aws-actions/configure-aws-credentials@v4
        with:
          role-to-assume: ${{ secrets.AWS_ROLE_ARN }}
          aws-region: us-east-1

      - uses: hashicorp/setup-terraform@v3

      - name: Init
        run: |
          terraform init \
            -input=false \
            -reconfigure \
            -backend-config="key=${{ matrix.backend_key }}"
        working-directory: terraform/

      - name: Detect drift
        id: plan
        run: |
          set +e
          terraform plan -detailed-exitcode -var-file="${{ matrix.tfvars }}" -input=false
          EXIT_CODE=$?
          set -e
          if [ $EXIT_CODE -eq 2 ]; then
            echo "drift_detected=true" >> "$GITHUB_OUTPUT"
          elif [ $EXIT_CODE -eq 0 ]; then
            echo "drift_detected=false" >> "$GITHUB_OUTPUT"
          else
            exit $EXIT_CODE
          fi
        working-directory: terraform/

      - name: Alert on drift
        if: steps.plan.outputs.drift_detected == 'true'
        run: |
          echo "::warning::Drift detected in ${{ matrix.environment }}"
          # Add Slack/email notification here
```

> `terraform plan -detailed-exitcode` returns: 0 = no changes, 1 = error, 2 = changes detected. This is a read-only operation — no state modifications.
