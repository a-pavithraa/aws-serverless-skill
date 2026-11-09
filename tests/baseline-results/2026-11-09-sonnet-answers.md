# Scenario runs (sonnet)

RED: no skills. GREEN: this repository's skills available. Verdicts are added below each scenario.

## Scenario 1: Terraform State Encryption — SSE-S3 vs SSE-KMS

Skill: `terraform-aws`

Prompt:

```
I've set up my Terraform S3 backend with `encrypt = true` and configured my bucket's default encryption to use a KMS key. Is this correct?

terraform {
  backend "s3" {
    bucket   = "myorg-terraform-state"
    key      = "prod/terraform.tfstate"
    region   = "us-east-1"
    encrypt  = true
  }
}
```

Success criteria:

1. Identifies that `encrypt = true` alone uses SSE-S3 (AES-256), not SSE-KMS
2. Explains that this overrides the bucket's KMS default encryption
3. Provides corrected config with both `encrypt = true` and `kms_key_id`
4. Does NOT say "this configuration is correct"

### RED (skills loaded: none)

Partly. `encrypt = true` encrypts the state, but probably not with your KMS key.

**The gap:** With `encrypt = true` and no `kms_key_id`, Terraform sends an explicit `AES256` (SSE-S3) encryption header on every state write. An explicit header on the request overrides the bucket's default encryption. So your state is likely encrypted with S3-managed keys, not your KMS key, even though the bucket default says KMS. You can confirm with `aws s3api head-object --bucket myorg-terraform-state --key prod/terraform.tfstate`. Check whether `ServerSideEncryption` shows `AES256` or `aws:kms`.

**Fix:** Name the key in the backend:

```hcl
terraform {
  backend "s3" {
    bucket       = "myorg-terraform-state"
    key          = "prod/terraform.tfstate"
    region       = "us-east-1"
    encrypt      = true
    kms_key_id   = "arn:aws:kms:us-east-1:111122223333:key/xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
    use_lockfile = true
  }
}
```

After the change, run `terraform init -reconfigure` and apply or refresh so the state is rewritten. Existing versions stay under the old encryption.

**Also check:**
- **KMS permissions:** Every principal that runs Terraform needs `kms:GenerateDataKey` and `kms:Decrypt` on the key, as well as the S3 permissions. The key policy must allow them too.
- **Locking:** You have none configured. On Terraform 1.10 or later, `use_lockfile = true` uses S3-native locking (shown above). On older versions, use `dynamodb_table`, which is deprecated in newer releases. The lock's IAM principal also needs `s3:PutObject` and `s3:DeleteObject` on the `.tflock` object.
- **Bucket hardening:**
  - Turn on versioning, so you can recover from a bad state write.
  - Turn on Block Public Access.
  - Add a bucket policy that denies non-TLS requests (`aws:SecureTransport = false`).
  - Consider enabling S3 Bucket Keys to reduce KMS request costs.

### GREEN (skills loaded: terraform-aws)

Not quite. Your setup is incomplete, and it probably doesn't do what you expect.

**The problem**

With `encrypt = true` and no `kms_key_id`, the backend sends an explicit `AES256` (SSE-S3) header on every `PutObject`. That header overrides the bucket's default KMS encryption. Your state files are most likely being stored with SSE-S3, not your KMS key. The bucket config looks right, but it never gets applied to state uploads.

**The fix**

Set both `encrypt` and `kms_key_id`:

```hcl
terraform {
  backend "s3" {
    bucket       = "myorg-terraform-state"
    key          = "prod/terraform.tfstate"
    region       = "us-east-1"
    encrypt      = true
    kms_key_id   = "alias/terraform-state"   # key ARN, key ID, or alias/ name
    use_lockfile = true
  }
}
```

**Related changes**

1. **Check what you have now.** Run `aws s3api head-object --bucket myorg-terraform-state --key prod/terraform.tfstate` and look at `ServerSideEncryption`. If it says `AES256`, you're affected. After you change the backend, the next state write re-encrypts the object with KMS.
2. **Add a bucket policy as a guardrail.** A statement that denies `s3:PutObject` unless `s3:x-amz-server-side-encryption` equals `aws:kms` makes this misconfiguration fail loudly instead of silently.
3. **Add `use_lockfile = true`.** You have no locking configured. On Terraform 1.10 or later, S3-native locking works, and the DynamoDB lock table is deprecated.
4. **Grant KMS permissions to every principal that runs Terraform.** That means your CI role and any humans. They need `kms:Encrypt`, `kms:Decrypt`, `kms:GenerateDataKey` and `kms:DescribeKey` on that key. Also check that the key policy doesn't rely only on the default account-wide `kms:*` statement.
5. **Set `bucket_key_enabled = true`** on the bucket's encryption rule. It reduces KMS API calls and cost.

## Scenario 2: Terraform Backend Environment Isolation Strategy

Skill: `terraform-aws`

Prompt:

```
We have prod, staging, and 10+ feature branch environments. What's the best way to isolate Terraform state between them? Should I use Terraform workspaces?
```

Success criteria:

1. Does NOT recommend workspaces for environment isolation
2. Distinguishes between hard trust boundaries (separate buckets) and soft boundaries (key paths)
3. Recommends hybrid: separate bucket for prod, key paths for feature branches
4. Explains IAM access control implications of each approach

### RED (skills loaded: none)

**Short answer:** don't use workspaces for prod vs. staging. For feature branches, a separate state key per environment works better than workspaces, and workspaces are only acceptable there if the environments are identical and short-lived.

## Why not workspaces for prod/staging

- **Same backend, same credentials.** All workspaces share one backend config. In S3 they sit in the same bucket under `env:/<name>/`. A feature-branch engineer's credentials can therefore reach prod state, and IAM can't cleanly separate them.
- **Hidden context.** `terraform apply` depends on which workspace is selected, and nothing in the code shows that. Running `apply` in the wrong workspace is a common cause of incidents.
- **Poor fit for differing config.** Prod and staging usually differ in account, region, sizing, and sometimes module versions. Workspaces push you into `terraform.workspace` conditionals scattered through the code.
- HashiCorp's own docs say workspaces are not suitable for strong isolation between deployment environments.

## Recommended layout

**1. Prod and staging: separate backends, ideally separate AWS accounts**

```
envs/
  prod/      backend.tf  main.tf  terraform.tfvars   # bucket in prod account
  staging/   backend.tf  main.tf  terraform.tfvars   # bucket in staging account
modules/
  app/       # shared, versioned code
```

Each environment is a thin root module that calls shared modules with its own variables. Each has its own state bucket and lock table, with IAM scoped per account. A mistake in staging then can't touch prod state.

**2. Feature branches: one state key per branch, same root module**

Pass the key at init time, from CI:

```bash
terraform init \
  -backend-config="bucket=mycompany-tf-state-dev" \
  -backend-config="key=features/${BRANCH_SLUG}/terraform.tfstate"
terraform apply -var="env_name=${BRANCH_SLUG}"
```

- Put all feature environments in a dev or sandbox account with its own state bucket, separate from prod and staging.
- Use `env_name` to prefix or suffix resource names so they don't collide.
- Have CI destroy the environment and delete the state key when the branch merges or closes. With 10+ branches, orphaned environments are the real cost risk, so add a TTL tag and a reaper job.

Workspaces would also work for this tier. `terraform workspace new $BRANCH` is less setup than backend-config juggling, and the blast-radius concern is smaller in a sandbox account. The cost is the same hidden-context risk, so if you use them, have CI select the workspace and don't let people do it by hand.

## Other practices

- **Backend:** S3 with versioning and encryption. Use `use_lockfile = true` for native S3 locking on current Terraform, or DynamoDB locking on older versions.
- **Keep state small.** Split by lifecycle, for example network, data, and app stacks, so a feature branch doesn't need to plan the whole world.
- **Pin module versions** per environment so you can promote changes from feature to staging to prod deliberately.
- **Terragrunt or Terraform Stacks** reduce the boilerplate if the per-environment directories get repetitive. Don't adopt them just for this.

## Summary

| Tier | Isolation |
|---|---|
| prod | Own account, own backend |
| staging | Own account, own backend |
| feature branches | Shared dev account, one state key per branch, auto-destroyed |

I can sketch the `backend.tf` and CI snippet for this if you tell me your CI system. If you'd like me to look at your existing Terraform layout, I can do that too.

### GREEN (skills loaded: terraform-aws)

**Don't use workspaces for this.** Use a separate state file per environment, with a different backend key for each. Split prod from non-prod at the bucket level.

## Why not workspaces
- All workspaces share one backend config: the same bucket, the same credentials and the same code path. Prod and a feature branch differ only by a name that a stray `terraform workspace select` can change.
- You can't scope IAM per environment. Workspace state lives under `env:/<workspace>/<key>` in one bucket, so the policies are awkward prefix rules.
- The active workspace is hidden state. It's easy to run apply against prod while thinking you're on a feature environment.
- Workspaces also don't suit environments that need different providers, accounts or backends.

## Recommended layout
| Boundary | Isolation |
|---|---|
| **Prod** | Its own state bucket, ideally in its own AWS account, with its own KMS key. Only the prod CI role can touch it. |
| **Staging and feature branches** | A shared non-prod bucket with one key per environment, for example `myapp/staging/terraform.tfstate` and `myapp/feature-<branch>/terraform.tfstate`. |

Separate buckets give you real IAM isolation at the trust boundary that matters, which is prod. Key paths within non-prod are cheap and fast to create, so they suit 10+ short-lived branch environments.

## Implementation
Use a partial backend config in code, and pass the key when you run `init`.

```hcl
# backend.tf
terraform {
  backend "s3" {
    bucket       = "myorg-terraform-state-<account-id>"
    region       = "us-east-1"
    encrypt      = true
    kms_key_id   = "alias/terraform-state"   # set together with encrypt
    use_lockfile = true                      # S3-native locking, Terraform 1.10+
    # key supplied at init
  }
}
```

```bash
terraform init -reconfigure -input=false \
  -backend-config="key=myapp/feature-${BRANCH_SLUG}/terraform.tfstate"
```

- **One resolver:** have a single CI step map git ref to environment, tfvars file and backend key. Prod and staging get fixed keys. Feature branches get a key derived from the sanitized branch name.
- **Locking:** `use_lockfile = true` replaces the DynamoDB lock table. It needs bucket versioning and `s3:DeleteObject` on the lock file.
- **KMS:** set `kms_key_id` whenever `encrypt = true`. Otherwise Terraform sends an `AES256` header that overrides your bucket's default KMS encryption. A bucket policy that denies non-KMS uploads will catch this.
- **Tags:** put `Environment` and `Branch` in provider `default_tags` so orphaned resources can be traced.
- **CI:** use OIDC roles per tier, so the prod role is the only principal that can read the prod bucket. Set concurrency per environment, and don't use `cancel-in-progress` on apply jobs.
- **Cleanup:** destroy a feature environment (init with its key, then destroy) when the branch is deleted. Do this from CI, not by hand.
- **Audit:** turn on CloudTrail data events on the state buckets, so you can see who changed which state.

## Alternatives
- **Separate root directories per environment:** use these if prod and staging differ structurally. Share code through modules.
- **Terragrunt:** it can generate the backend key per directory if you want less boilerplate.
- **One AWS account per tier:** this is the strongest isolation, and it also limits blast radius for the resources themselves.

I can look at your repo and draft the `backend.tf`, the ref-to-environment resolver and the CI wiring if you'd like.

## Scenario 3: Terraform Bootstrap — Chicken-and-Egg

Skill: `terraform-aws`

Prompt:

```
I want to use Terraform to create my S3 state bucket and KMS key. How do I handle the fact that Terraform needs a state bucket to run, but I'm trying to create the state bucket with Terraform?
```

Success criteria:

1. Explains the local-state-first approach (no backend block = local default)
2. Describes `terraform init -migrate-state` as the migration step
3. Mentions `prevent_destroy = true` on the state bucket
4. Does NOT suggest `-target` as the solution

### RED (skills loaded: none)

This is the Terraform bootstrap problem. There are two common solutions, and I'd start with the first.

## Option 1: Bootstrap with local state, then migrate (most common)

Use a small separate config that creates the bucket and key, then move its state into the bucket it created.

**`bootstrap/main.tf`**
```hcl
terraform {
  required_providers {
    aws = { source = "hashicorp/aws", version = "~> 5.0" }
  }
  # Step 1: no backend block, so state is local
}

provider "aws" {
  region = "us-east-1"
}

resource "aws_kms_key" "tfstate" {
  description             = "Terraform state encryption"
  enable_key_rotation     = true
  deletion_window_in_days = 30
}

resource "aws_kms_alias" "tfstate" {
  name          = "alias/tfstate"
  target_key_id = aws_kms_key.tfstate.key_id
}

resource "aws_s3_bucket" "tfstate" {
  bucket = "my-org-tfstate-123456789012"

  lifecycle {
    prevent_destroy = true
  }
}

resource "aws_s3_bucket_versioning" "tfstate" {
  bucket = aws_s3_bucket.tfstate.id
  versioning_configuration { status = "Enabled" }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "tfstate" {
  bucket = aws_s3_bucket.tfstate.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm     = "aws:kms"
      kms_master_key_id = aws_kms_key.tfstate.arn
    }
    bucket_key_enabled = true
  }
}

resource "aws_s3_bucket_public_access_block" "tfstate" {
  bucket                  = aws_s3_bucket.tfstate.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}
```

**Steps:**
1. Run `terraform init && terraform apply`. State is local at this point.
2. Add a backend block to the same config:
   ```hcl
   terraform {
     backend "s3" {
       bucket       = "my-org-tfstate-123456789012"
       key          = "bootstrap/terraform.tfstate"
       region       = "us-east-1"
       encrypt      = true
       kms_key_id   = "alias/tfstate"
       use_lockfile = true   # native S3 locking, Terraform >= 1.10
     }
   }
   ```
3. Run `terraform init -migrate-state` and answer `yes`. The local state is copied into S3.
4. Delete the local `terraform.tfstate*` files.

Your other projects then use the same backend with different `key` values.

## Option 2: Keep bootstrap state local or out of Terraform

- **Commit nothing, keep it local.** The bootstrap config rarely changes. Some teams leave its state local and accept the risk. Losing it means you `terraform import` the bucket and key.
- **Create it with the CLI or CloudFormation.** One CloudFormation stack or a few `aws` CLI commands creates the bucket and key. The tradeoff is that they're no longer managed in Terraform.

## Practical tips

- **Locking:** On Terraform 1.10 or later, `use_lockfile = true` handles locking in S3, so you don't need a DynamoDB table. Older versions need a `dynamodb_table`.
- **Protect the bucket:** Keep `prevent_destroy` on it, and enable versioning so you can recover a bad state file.
- **Key policy:** Make sure the roles that run Terraform have `kms:Encrypt`, `kms:Decrypt` and `kms:GenerateDataKey` on the key, and S3 access on the bucket.
- **Backend values:** Backend blocks can't use variables. Use `-backend-config` flags or a `backend.hcl` file if you want to parameterize them.
- **Bucket names:** They're globally unique, so including the account ID is a good habit.

I can scaffold the `bootstrap/` directory in this repo if you'd like.

### GREEN (skills loaded: terraform-aws)

Use a separate bootstrap project that starts on local state. It creates the bucket and key, then migrates its own state into that bucket.

## The pattern

1. **Make a separate directory**, e.g. `infra-bootstrap/`. It has no `backend` block, so Terraform uses local state.
2. **Define the bucket and key** in it:
   - A KMS key with `enable_key_rotation = true`, plus an alias.
   - An S3 bucket with `prevent_destroy = true`, versioning enabled, SSE-KMS with `bucket_key_enabled = true`, and a public access block.
   - A bucket policy that denies non-TLS requests and denies uploads that aren't KMS-encrypted.
3. **Run `terraform init && terraform apply` once**, from a human session with admin-ish credentials. Don't have an agent do this.
4. **Optionally migrate the bootstrap project itself.** Add a `backend "s3"` block to it and run `terraform init -migrate-state`. After that the bootstrap project manages itself through S3.
5. **Point every other project at the bucket** with a backend like this:

```hcl
terraform {
  backend "s3" {
    bucket       = "myorg-terraform-state-123456789012"
    region       = "us-east-1"
    encrypt      = true
    kms_key_id   = "alias/terraform-state"
    use_lockfile = true
    # key supplied per project/env via -backend-config
  }
}
```

## Things to get right

- **Set `encrypt = true` and `kms_key_id` together.** With `encrypt` alone, Terraform sends an `AES256` header that overrides the bucket's KMS default, so your state ends up SSE-S3. The `DenyNonKMSEncryptedUploads` policy statement catches this.
- **Locking needs no DynamoDB table.** Use `use_lockfile = true` (Terraform ≥ 1.10). It requires bucket versioning, and the CI role needs `s3:DeleteObject` on the lock file.
- **Lock down the KMS key policy.** The default policy delegates to anything in the account with `kms:*`. In production, write explicit statements: admins manage the key, and only the CI/CD role and humans who need it get `Encrypt`, `Decrypt`, `GenerateDataKey` and `DescribeKey`.
- **Give CI a least-privilege policy.** Grant `s3:Get/Put/DeleteObject` and `s3:ListBucket` on the state bucket, plus the KMS actions above on the key. Attach it to your OIDC-federated role rather than using static keys.
- **If you stay on local state, treat it as a secret.** The `terraform.tfstate` file holds sensitive attributes. If the bootstrap project never migrates, store it securely. It rarely changes, so this is manageable.
- **Optionally enable CloudTrail data events** on the state bucket, so you can tell who changed state and when.
- **Avoid `terraform destroy` on the bootstrap project.** `prevent_destroy` protects the bucket, but losing the key would make every state file unreadable. Keep `deletion_window_in_days = 30`.

If you want, I can write the full `infra-bootstrap/` files here (`main.tf`, `outputs.tf`, the CI policy and the key policy) for your account and naming. If you give me a prefix and region, I'll use them.

## Scenario 4: DynamoDB Filter Expression Cost Misconception

Skill: `aws-dynamodb`

Prompt:

```
I have a DynamoDB table with millions of items. I'm querying with a filter expression to return only 10 matching items out of 1000. Does the filter expression reduce my read cost?
```

Success criteria:

1. Clearly states filter expressions do NOT reduce read (RCU) costs
2. Explains DynamoDB reads all items in a Query/Scan before applying filter
3. Recommends redesigning the data model to avoid runtime filters
4. Does NOT confirm filter expressions reduce cost

### RED (skills loaded: none)

**No.** A filter expression is applied *after* DynamoDB reads the data, so it doesn't reduce read cost.

**How it works**
- A `Query` or `Scan` reads up to 1 MB of items per call. DynamoDB then applies the filter and returns only the matches.
- Read capacity is charged on the data **read** (the size of everything evaluated), not on what's returned.
- So if you evaluate 1000 items and the filter keeps 10, you pay for all 1000. You save only on network transfer and client-side processing.
- Filtering also doesn't skip pagination. A page can come back with few or zero results while `LastEvaluatedKey` is still set, so you have to keep paging.

**How to actually cut cost**
1. **Use the key condition.** Put the selective attribute in the partition key or sort key, so `Query` reads only the matching range. This is the main fix.
2. **Add a GSI.** If you filter on a non-key attribute often, make it the key of a Global Secondary Index. Then the 10 items come from a targeted `Query` instead of a filter over 1000.
3. **Use a sparse index.** If the matching items share a rare attribute, index only items that have it. The index stays small.
4. **Reshape the sort key.** Composite sort keys like `STATUS#2026-11-09` let you use `begins_with` or `between` in the key condition.
5. **Use a projection.** Projecting fewer attributes reduces returned bytes, but not consumed read capacity on the base table. On a GSI or LSI, a leaner projection does reduce the item size read.

**Avoid `Scan` for this.** On a table with millions of items, a `Scan` with a filter reads the whole table. You pay for every item and it's slow.

If you share the table's key schema and the attributes you filter on, I can suggest a specific key or GSI design.

### GREEN (skills loaded: none)

No. A filter expression doesn't reduce your read cost.

DynamoDB applies the filter after it reads the items. You're billed read capacity on the size of everything the query or scan evaluated, not on what comes back. If the key condition matches 1000 items, you pay to read all 1000 even though only 10 are returned. Each 4 KB read takes 1 RCU if strongly consistent, or 0.5 RCU if eventually consistent. The filter only saves network transfer and client-side processing.

- **Pagination:** each call evaluates at most 1 MB of data before the filter runs. A page can return few or zero items and still have a `LastEvaluatedKey` you need to follow.
- **`Scan`:** if you're using `Scan` on the millions-item table, you pay for the entire table, because the filter doesn't narrow what gets read.

To reduce the cost, make the database find those 10 items by key instead of filtering them out:

1. **Put the filtered attribute in the sort key.** If you always filter on something like `status` or a date range, make it part of the sort key so a `KeyConditionExpression` (`begins_with`, `BETWEEN`, and so on) reads only the matching range.
2. **Add a GSI keyed on the filter attribute.** Query the index directly so you read only matching items.
3. **Use a sparse index.** If the 10 matches are the ones that have a particular attribute, such as `needs_review`, project only those items into a GSI by setting the attribute only on them. The index then contains almost nothing else.
4. **Use a composite sort key.** For example, `STATUS#2026-11-09` lets you filter on several attributes at once.
5. **Use projections.** If you can't restructure, a `ProjectionExpression` doesn't cut RCUs either, because they're based on the full item size. A GSI that projects only the needed attributes does shrink the read size.

The right fix depends on your access pattern. If you tell me the table's keys and what you're filtering on, I can suggest a specific key or index design.

## Scenario 5: DynamoDB GSI — Synthetic Key vs Multi-Attribute Composite Key

Skill: `aws-dynamodb`

Prompt:

```
I need a GSI on my DynamoDB table where I can query by region AND tournament_id together. I was planning to create a synthetic key by concatenating them: "REGION#us-east#TOURNAMENT#abc123". Is this the right approach?
```

Success criteria:

1. Recommends multi-attribute composite keys for new GSIs
2. Mentions Terraform AWS provider v6.29.0+ requirement
3. Shows `hash_key = ["attr1", "attr2"]` list syntax
4. Explains when synthetic keys are still appropriate
5. Does NOT just confirm synthetic key concatenation as the only option

### RED (skills loaded: none)

Yes, that's a standard pattern, but you may not need it. It depends on how you query.

**If you always query with both values (equality on each):** DynamoDB now supports multi-attribute GSI keys, with up to 4 attributes in the partition key and 4 in the sort key. You define the GSI partition key as `[region, tournament_id]` and skip the synthetic attribute. You don't need to concatenate or parse anything, and you don't need to keep a derived attribute in sync on writes. You do have to supply all partition key attributes with equality on every query. Check that your SDK and IaC tooling version supports it.

**If you also want "all tournaments in a region":** Use `region` as the GSI partition key and `tournament_id` as the sort key. One index then serves both queries: region alone, or region plus tournament. The synthetic key can't do the region-only query, because you can't prefix-match a partition key.

**If your tooling doesn't support multi-attribute keys, or you want the classic approach:** Your concatenated key is fine as the GSI partition key. Some details:
- **Prefixes:** `REGION#`/`TOURNAMENT#` only help if the GSI is overloaded with several entity types, as in single-table design. For a dedicated index, `us-east#abc123` is enough.
- **Delimiter:** Use one that can't appear in the values.
- **Backfill:** Existing items need the new attribute written before they appear in the index.
- **Updates:** Any code path that changes `region` or `tournament_id` must also update the synthetic attribute.
- **Typing:** The attribute is a string, so you lose native types.

**Whichever you choose, check for hot partitions.** `region + tournament_id` as the partition key puts every item for a big tournament in one partition. That's fine at modest volume. If a single tournament can see heavy write or read traffic (about 1,000 WCU or 3,000 RCU per partition), add a shard suffix such as `abc123#0..N` and query all shards. If you use `region` alone as the partition key, the same problem is worse, because there are only a handful of regions.

**My recommendation:** If you only ever query region plus tournament, use a multi-attribute GSI key. If you need region-level queries too, use `region` as the partition key and `tournament_id` as the sort key, and shard if the volume is high. Use the concatenated key only if tooling forces it.

What query patterns and write volume do you expect per tournament? That would settle whether sharding matters.

### GREEN (skills loaded: aws-dynamodb)

Concatenating works, but it's no longer the best approach. DynamoDB now supports **multi-attribute composite keys** on GSIs (GA Nov 2025). That lets you index `region` and `tournament_id` directly, with no synthetic string.

**Why it beats `REGION#us-east#TOURNAMENT#abc123`:**
- **No backfill.** Your items already have `region` and `tournament_id`, so you can add the GSI without a scan-and-update job to write a new concatenated attribute.
- **No drift.** You don't have to keep a derived attribute in sync on every write. That includes the case where `region` changes.
- **No string parsing.** Attributes keep their native types, so numbers sort numerically and you don't need to zero-pad.

**Terraform** (needs AWS provider v6.29.0 or later):

```hcl
attribute {
  name = "region"
  type = "S"
}

attribute {
  name = "tournament_id"
  type = "S"
}

global_secondary_index {
  name            = "RegionTournamentIndex"
  hash_key        = ["region", "tournament_id"]
  # range_key = [...]  # add if you need ordering within a tournament, e.g. ["round", "match_id"]
  projection_type = "ALL"   # or KEYS_ONLY / INCLUDE, depending on what the query returns
}
```

**Query.** Every partition-key attribute is required, with equality only:

```python
table.query(
    IndexName="RegionTournamentIndex",
    KeyConditionExpression="#r = :r AND tournament_id = :t",
    ExpressionAttributeNames={"#r": "region"},
    ExpressionAttributeValues={":r": "us-east", ":t": "abc123"},
)
```

**Things to know:**
- You can't query by `region` alone on this index. If you also need "all tournaments in a region", that needs a separate GSI.
- If you add sort-key attributes, they're queried left to right with no gaps, and an inequality is only allowed on the last one you use.
- `region` is a DynamoDB reserved word, so use an expression attribute name as shown.
- **When to keep the synthetic key:** if the GSI is overloaded across several entity types in a single-table design and you rely on `begins_with()`, or your provider version is older than 6.29.0.
- **Hot partition check:** if one region and tournament pair gets heavy traffic, that GSI partition could be hot. That's worth thinking through for large tournaments.

If you tell me whether you need any ordering within a tournament, I can pick the sort key. I can also add the GSI to your Terraform. I haven't looked at your table definition yet.

## Scenario 6: DynamoDB Schema-First Design Anti-Pattern

Skill: `aws-dynamodb`

Prompt:

```
I'm building a multi-tenant SaaS app with Users, Organizations, Projects, and Tasks. Help me design the DynamoDB tables — I'm thinking one table per entity.
```

Success criteria:

1. **STOPS** before suggesting a schema
2. Asks for access patterns before designing table structure
3. Does NOT default to one-table-per-entity
4. Explains that DynamoDB schema follows queries, not the other way around

### RED (skills loaded: none)

One table per entity is the relational habit. DynamoDB has no joins, so "show a project with its tasks" or "list a user's orgs" would turn into several round trips or scans. I'd model around your access patterns in one table, with items grouped by tenant.

## Assumed access patterns
Correct me if these are wrong, because the design follows from them.
1. Get an org, a project, or a task by ID.
2. List the projects in an org.
3. List the tasks in a project.
4. List the members of an org.
5. List the orgs a user belongs to.
6. Look up a user by email (for login).
7. List the tasks assigned to a user, sorted by due date.

## Table: `App` (on-demand billing)

| Entity | PK | SK | GSI1PK / GSI1SK |
|---|---|---|---|
| Org | `ORG#<orgId>` | `#META` | |
| Membership | `ORG#<orgId>` | `MEMBER#<userId>` | `USER#<userId>` / `ORG#<orgId>` |
| Project | `ORG#<orgId>` | `PROJ#<projectId>` | |
| Task | `ORG#<orgId>#PROJ#<projectId>` | `TASK#<taskId>` | `ASSIGNEE#<orgId>#<userId>` / `DUE#<date>#<taskId>` |
| User | `USER#<userId>` | `#PROFILE` | `EMAIL#<email>` / `#PROFILE` |

How each pattern is served:
- **1:** `GetItem` on the PK and SK.
- **2:** Query `PK=ORG#o`, `begins_with(SK, "PROJ#")`.
- **3:** Query `PK=ORG#o#PROJ#p`.
- **4:** Query `PK=ORG#o`, `begins_with(SK, "MEMBER#")`.
- **5:** Query GSI1 with `GSI1PK=USER#u`.
- **6:** Query GSI1 with `GSI1PK=EMAIL#x`.
- **7:** Query GSI1 with `GSI1PK=ASSIGNEE#o#u`. Only assigned tasks carry these attributes, so the index is sparse and cheap.

The email and membership items use the same GSI, with different key prefixes. That keeps you to one index for now.

## Design decisions
- **Tasks get their own partition per project.** If tasks lived under `ORG#o`, one large tenant would concentrate all its traffic on a single partition. Splitting by project spreads the load and keeps task listing a simple query.
- **Use sortable IDs such as ULIDs.** Tasks then list in creation order without an extra index.
- **Users are global, and membership is the join.** A user can belong to many orgs, so the membership item holds the role and links both directions. Store denormalized display fields (name, avatar) on it if you list members often. Update them when the user's profile changes.
- **Tenant isolation:**
  - Take `orgId` from the verified auth token, never from the request body.
  - Because every key starts with the org, you can add IAM `dynamodb:LeadingKeys` conditions if you ever need hard isolation.
  - For a few very large or regulated tenants, you can move them to a dedicated table later without changing the key shape.
- **Enable PITR and TTL** (for things like invites and sessions), and use `TransactWriteItems` when you create an org together with its owner membership.

## When separate tables would be right
- Entities with very different retention, backup or encryption needs.
- A strict data-isolation requirement per tenant.
- A team that would find a single-table layout too hard to maintain.

None of these look like they apply to your four entities, but tell me if one does.

## Questions that could change the design
- Do you need to search or filter tasks by status, label or text? Status can be handled with another GSI, but text search belongs in OpenSearch.
- Do you need "all my tasks across orgs"? The ASSIGNEE key above is scoped per org. Dropping the org from it would give a global view.
- How big do you expect the largest tenant to get?

I can turn this into a CloudFormation, CDK or SAM template, or write the data-access layer in your language, if you'd like.

### GREEN (skills loaded: aws-dynamodb)

I'd push back on one table per entity. Here's why, and a design to replace it.

## Why not one table per entity

DynamoDB has no joins. With four tables, "show an org's projects and their tasks" becomes several round trips that you stitch together in code. You also lose cross-entity transactions, which you'd want for membership, email uniqueness, and task counters. Multiple tables make sense when the data is independent or owned by different teams, and none of that applies here. Your entities are all hierarchical and tenant-scoped, so I'd use a **single table**.

## Assumed access patterns

I haven't seen your real ones, so please correct these. The whole design depends on them.

1. Get a user by id, and by email (login).
2. Get an org, list its members, and list a user's orgs.
3. List the projects in an org, and get one project.
4. List the tasks in a project, and filter them by status.
5. Get one task.
6. Show "my tasks" for a user within an org, by status and due date.

## Table layout

Table `app` has keys `PK` and `SK`, on-demand billing, and one GSI.

| Entity | PK | SK | Notes |
|---|---|---|---|
| User | `USER#<userId>` | `PROFILE` | |
| Email lock | `EMAIL#<email>` | `EMAIL#<email>` | No data. It's written in the same transaction as the user, with `attribute_not_exists(PK)`, to enforce unique emails. It also gives you a lookup by email. |
| Org | `ORG#<orgId>` | `META` | |
| Membership | `ORG#<orgId>` | `MEMBER#<userId>` | Carries a `role` attribute. This is the link item for the many-to-many between users and orgs. |
| Project | `ORG#<orgId>` | `PROJECT#<projectId>` | Keeping it in the org partition makes "list projects" a `begins_with` query. |
| Task | `ORG#<orgId>#PROJECT#<projectId>` | `TASK#<ulid>` | Tasks get their own partition per project, so one big org doesn't pile every task into a single partition. ULIDs make tasks sort by creation time. |

Querying `PK=ORG#x` returns the org, all its members, and all its projects in one call. Each pattern then maps like this:

- **Pattern 1 (user by id or email):** `GetItem` on the user or the email-lock item.
- **Pattern 2 (org, members):** `GetItem` for the org, or query `MEMBER#` in the org partition for its members.
- **Pattern 3 (projects):** query `PROJECT#` in the org partition.
- **Pattern 4 (tasks in a project):** query `TASK#` in the project partition.
- **Pattern 5 (one task):** `GetItem` with the task's `PK` and `SK`.

**GSI `ByUser`** serves "orgs for a user" (pattern 2) and uses multi-attribute keys, so there's no hand-built string concatenation:
- Membership items set `memberUserId` and `orgId`.
- The index has hash key `memberUserId` and range key `orgId`.
- It's sparse, because only membership items carry those attributes.

**GSI `TasksByAssignee`** serves pattern 6:
- The hash key is `[orgId, assigneeId]` and the range key is `[status, dueDate, taskId]`.
- It's sparse, so unassigned tasks never appear in it.
- Remember to alias `status` in expressions, since it's a reserved word.

Both indexes need Terraform AWS provider v6.29.0 or later.

## Decisions to make deliberately

- **Task status:** I'd keep status as an attribute and rely on the `TasksByAssignee` index for filtered views. That index only covers per-assignee queries. If "all open tasks in a project" is a hot query, filtering would read every task in the partition. In that case, put the status in the sort key (`TASK#OPEN#<ulid>`) and accept a delete-and-put on each status change.
- **Counters:** if you show task counts per project, store a count on the project item. Update it with `TransactWriteItems` alongside the task put, instead of counting at read time.
- **Tenant isolation:** every key starts with `ORG#<orgId>`, except user and email items. That lets you restrict an IAM role with `dynamodb:LeadingKeys` as defense in depth. Even so, always take `orgId` from the verified auth token, never from the request body.
- **Projections:** use `INCLUDE` or `KEYS_ONLY` on the GSIs where you can. Every base-table write is replicated to each index.
- **Table settings:** turn on point-in-time recovery and encryption. Only turn on Streams if you have a consumer, because the stream view type can't be changed after creation.

## Questions

1. Can a user belong to many orgs? I assumed yes.
2. How large can an org get (tasks per project, projects per org)? That decides whether the sort-key status variant is worth it.
3. Do you need cross-org views, such as "all my tasks in every org"? Pattern 6 is scoped to one org.
4. Do you need search, comments, or audit history? Those would add entities, and DynamoDB isn't good at free-text search.

Once you confirm or correct the access patterns, I can write the Terraform for the table and its indexes, plus example queries.

## Scenario 7: Lambda Layers as Dependency Manager Anti-Pattern

Skill: `aws-serverless`

Prompt:

```
I have 5 Lambda functions that all use the same 3 Python libraries (boto3, requests, pydantic). I want to avoid bundling them in each function. Should I put them in a Lambda Layer?
```

Success criteria:

1. Warns that Layers add cold start latency and (since Aug 2025) billed INIT cost via layer mounting and initialization
2. Does NOT unconditionally recommend Layers for shared application libraries
3. Warns about at least one additional Layer misuse drawback: breaks local dev, blinds vulnerability scanners, or 5-layer hard limit
4. Distinguishes valid Layer use cases (binaries, custom runtimes, Powertools) from package manager misuse
5. Does NOT frame the question as simply a package size optimization problem

### RED (skills loaded: none)

Yes, a layer fits this case, with a few caveats.

**Why it works**
- The 5 functions share the same dependencies, so a layer removes the duplication. You build and version the dependencies once.
- Function deployment packages get smaller, so code-only deploys are faster.

**Things to know**
- **boto3 is already in the Python runtime.** You can leave it out of the layer. The catch is that the bundled version changes as AWS updates the runtime. If you need a specific version, include it in the layer.
- **Build for Lambda's platform, not your machine.** pydantic v2 depends on compiled code (`pydantic-core`). You're on Windows, so a plain `pip install` will give you the wrong binaries. Target Linux and match the function architecture (x86_64 or arm64):
  ```
  pip install requests pydantic -t python/ --platform manylinux2014_x86_64 --only-binary=:all: --python-version 3.12 --implementation cp
  ```
  Use `manylinux2014_aarch64` if the functions run on arm64. Zip the result with `python/` at the top level.
- **Layers are immutable and versioned.** Each function points at a specific layer version. Updating the dependencies means publishing a new version and updating each function to use it. SAM, CDK, and Serverless can do that in one deploy.
- **Limits:**
  - A function can use at most 5 layers.
  - The function code and all its layers must total 250 MB unzipped.
- **A layer doesn't speed up cold starts.** The libraries still get loaded. It only helps with packaging and maintenance.

**When to skip it**
- The functions need different versions of these libraries.
- You'd rather have each function self-contained, so one dependency bump can't affect all five at once.
- The dependencies grow beyond the size limit. In that case, use container images.

For 5 functions on identical dependencies, I'd use a layer. If you tell me which IaC tool you use (SAM, CDK, Terraform, and so on), I can show how to define and attach it.

### GREEN (skills loaded: aws-serverless)

**A single layer is reasonable here, but it's optional, and the benefit is smaller than it looks.**

**Drop boto3 from your packaging first.** The Python runtime already includes it. You only need to bundle it if you must pin a specific version. That leaves requests and pydantic.

**Why a layer can work:**
- It is the "deployment optimization" case: stable dependencies in the layer, only your code in the function zip. Deploys are smaller and faster.
- Using one layer for all five functions keeps things simple.

**Why it's not a free win:**
- **Cold starts.** Each layer is mounted during INIT, and INIT has been billed since August 2025. One layer is cheap, but it isn't free. It also doesn't avoid the cost of importing the libraries.
- **No semantic versioning.** Layer versions are just integers. Pin each function to an explicit layer version ARN, and don't let all five float on the latest.
- **Local dev and scanners.** The layer isn't in your local environment, so you need a `requirements.txt` for tests. Vulnerability scanners that inspect function packages may also miss it.
- **pydantic is compiled** (`pydantic-core`). Build the layer for the right platform and architecture. For example, with pip use `--platform manylinux2014_aarch64 --only-binary=:all:` for arm64, and match the Python version.
- **Limits.** A function can have at most 5 layers, and the unzipped function plus layers must stay under 250 MB.

**My recommendation:**
- If the five functions deploy together from one repo, you gain little from sharing. Bundling `requests` and `pydantic` into each zip is simpler and has no layer-version coordination. The packages are small.
- If dependencies change rarely and you want fast code-only deploys, use one layer with these settings:
  - Build it from a pinned lockfile.
  - Set `compatible_runtimes` and `compatible_architectures`.
  - Pin each function to a specific layer version.
  - Keep your own business logic out of it.

Here's a Terraform sketch:

```hcl
resource "aws_lambda_layer_version" "python_deps" {
  layer_name               = "${local.name_prefix}-python-deps"
  filename                 = "layer.zip"            # contains python/lib/python3.13/site-packages/...
  source_code_hash         = filebase64sha256("layer.zip")
  compatible_runtimes      = ["python3.13"]
  compatible_architectures = ["arm64"]
}

resource "aws_lambda_function" "fn" {
  # ...
  layers = [aws_lambda_layer_version.python_deps.arn]  # ARN includes the version
}
```

Tell me whether the functions deploy together and which architecture you target. I can then help with the build script or the Terraform.

## Scenario 8: SQS Lambda Trigger — Missing DLQ and Error Handling

Skill: `aws-serverless`

Prompt:

```
Set up a Lambda function triggered by an SQS queue to process order events. Here's my Terraform:

resource "aws_sqs_queue" "orders" {
  name = "orders"
}

resource "aws_lambda_event_source_mapping" "sqs_trigger" {
  event_source_arn = aws_sqs_queue.orders.arn
  function_name    = aws_lambda_function.processor.arn
  batch_size       = 10
}
```

Success criteria:

1. Flags missing DLQ as a critical gap
2. Mentions visibility timeout must be ≥ 6× Lambda timeout
3. Recommends `function_response_types = ["ReportBatchItemFailures"]` for partial batch success
4. Does NOT say the configuration looks correct

### RED (skills loaded: none)

I couldn't write the files because the Write tool is disabled in this session. Below is the complete setup to copy in yourself. Your snippet had no `aws_lambda_function`, no IAM role, and no dead-letter queue, so I added those.

**`main.tf`**
```hcl
terraform {
  required_providers {
    aws     = { source = "hashicorp/aws", version = "~> 5.0" }
    archive = { source = "hashicorp/archive", version = "~> 2.0" }
  }
}

locals {
  function_timeout = 30
}

# ---------- Queues ----------
resource "aws_sqs_queue" "orders_dlq" {
  name                      = "orders-dlq"
  message_retention_seconds = 1209600 # 14 days
  sqs_managed_sse_enabled   = true
}

resource "aws_sqs_queue" "orders" {
  name = "orders"

  # AWS recommends >= 6x the function timeout so in-flight batches aren't redelivered mid-processing
  visibility_timeout_seconds = local.function_timeout * 6
  sqs_managed_sse_enabled    = true

  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.orders_dlq.arn
    maxReceiveCount     = 5
  })
}

# ---------- IAM ----------
data "aws_iam_policy_document" "assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "processor" {
  name               = "orders-processor"
  assume_role_policy = data.aws_iam_policy_document.assume.json
}

resource "aws_iam_role_policy_attachment" "logs" {
  role       = aws_iam_role.processor.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

# Least-privilege SQS access, scoped to this queue
data "aws_iam_policy_document" "sqs_read" {
  statement {
    actions   = ["sqs:ReceiveMessage", "sqs:DeleteMessage", "sqs:GetQueueAttributes"]
    resources = [aws_sqs_queue.orders.arn]
  }
}

resource "aws_iam_role_policy" "sqs_read" {
  name   = "sqs-read"
  role   = aws_iam_role.processor.id
  policy = data.aws_iam_policy_document.sqs_read.json
}

# ---------- Lambda ----------
data "archive_file" "processor" {
  type        = "zip"
  source_file = "${path.module}/src/handler.py"
  output_path = "${path.module}/build/processor.zip"
}

resource "aws_cloudwatch_log_group" "processor" {
  name              = "/aws/lambda/orders-processor"
  retention_in_days = 14
}

resource "aws_lambda_function" "processor" {
  function_name    = "orders-processor"
  role             = aws_iam_role.processor.arn
  runtime          = "python3.13"
  handler          = "handler.handler"
  filename         = data.archive_file.processor.output_path
  source_code_hash = data.archive_file.processor.output_base64sha256
  timeout          = local.function_timeout
  memory_size      = 256

  depends_on = [aws_cloudwatch_log_group.processor, aws_iam_role_policy_attachment.logs]
}

# ---------- Trigger ----------
resource "aws_lambda_event_source_mapping" "sqs_trigger" {
  event_source_arn = aws_sqs_queue.orders.arn
  function_name    = aws_lambda_function.processor.arn
  batch_size       = 10

  maximum_batching_window_in_seconds = 5
  function_response_types            = ["ReportBatchItemFailures"]

  scaling_config {
    maximum_concurrency = 10
  }

  depends_on = [aws_iam_role_policy.sqs_read]
}
```

**`src/handler.py`**
```python
import json
import logging

logger = logging.getLogger()
logger.setLevel(logging.INFO)


def process_order(order: dict) -> None:
    # TODO: real business logic. Must be idempotent: SQS standard queues are at-least-once.
    logger.info("Processing order %s", order.get("orderId"))


def handler(event, context):
    failures = []
    for record in event["Records"]:
        try:
            process_order(json.loads(record["body"]))
        except Exception:
            logger.exception("Failed message %s", record["messageId"])
            failures.append({"itemIdentifier": record["messageId"]})
    # Only these messages are retried; after maxReceiveCount they go to the DLQ
    return {"batchItemFailures": failures}
```

**What I added beyond your snippet**
- **Missing resources:** your mapping referenced `aws_lambda_function.processor`, which wasn't defined. I added it, plus an execution role with CloudWatch Logs access and SQS read permissions scoped to the `orders` queue.
- **Dead-letter queue:** after 5 failed receives, a message goes to `orders-dlq` instead of retrying forever.
- **Visibility timeout:** I set it to 6× the function timeout (180s). The SQS default of 30s would equal the function timeout, so messages could be redelivered while still being processed.
- **Partial batch failures:** `ReportBatchItemFailures` is set on the mapping and the handler returns `batchItemFailures`. Without it, one bad order makes the whole batch of 10 retry, so the other nine get processed twice.
- **Concurrency cap:** `maximum_concurrency = 10` stops a backlog from using up your account's Lambda concurrency or overwhelming downstream systems. Adjust it to fit your workload.
- **Batching window:** `maximum_batching_window_in_seconds = 5` lets small batches fill up, which is cheaper at low volume. Remove it if you need minimum latency.

**Before you deploy**
- Make `process_order` idempotent, for example by keying on `orderId`. Standard queues deliver at least once, so duplicates will happen. If you need strict ordering, switch to a FIFO queue (`name = "orders.fifo"`, `fifo_queue = true`).
- Nothing alerts on the DLQ yet. A CloudWatch alarm on `ApproximateNumberOfMessagesVisible > 0` for `orders-dlq` would catch stuck orders.

If you re-enable file writes, I can create these files directly and run `terraform validate`.

### GREEN (skills loaded: aws-serverless)

Your mapping would work as written, but it's missing several things that cause problems in production. I didn't write any files, since your repo has no Terraform of its own yet. Here is a fuller version:

```hcl
resource "aws_sqs_queue" "orders_dlq" {
  name                      = "orders-dlq"
  message_retention_seconds = 1209600 # 14 days
}

resource "aws_sqs_queue" "orders" {
  name                       = "orders"
  visibility_timeout_seconds = 180 # 6x the Lambda timeout (30s)
  receive_wait_time_seconds  = 20  # long polling

  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.orders_dlq.arn
    maxReceiveCount     = 3
  })
}

resource "aws_lambda_function" "processor" {
  function_name = "orders-processor"
  role          = aws_iam_role.processor.arn
  runtime       = "python3.13"
  handler       = "app.handler"
  filename      = "build/processor.zip"
  timeout       = 30

  logging_config {
    log_format = "JSON"
  }
}

resource "aws_lambda_event_source_mapping" "sqs_trigger" {
  event_source_arn = aws_sqs_queue.orders.arn
  function_name    = aws_lambda_function.processor.arn
  batch_size       = 10

  function_response_types = ["ReportBatchItemFailures"]

  scaling_config {
    maximum_concurrency = 10 # cap to protect downstream systems; minimum allowed is 2
  }
}

data "aws_iam_policy_document" "assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "processor" {
  name               = "orders-processor"
  assume_role_policy = data.aws_iam_policy_document.assume.json
}

resource "aws_iam_role_policy_attachment" "logs" {
  role       = aws_iam_role.processor.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

# The event source mapping polls the queue using the function's role
data "aws_iam_policy_document" "sqs_read" {
  statement {
    actions   = ["sqs:ReceiveMessage", "sqs:DeleteMessage", "sqs:GetQueueAttributes"]
    resources = [aws_sqs_queue.orders.arn]
  }
}

resource "aws_iam_role_policy" "sqs_read" {
  role   = aws_iam_role.processor.id
  policy = data.aws_iam_policy_document.sqs_read.json
}

resource "aws_cloudwatch_metric_alarm" "dlq_not_empty" {
  alarm_name          = "orders-dlq-not-empty"
  namespace           = "AWS/SQS"
  metric_name         = "ApproximateNumberOfMessagesVisible"
  dimensions          = { QueueName = aws_sqs_queue.orders_dlq.name }
  statistic           = "Maximum"
  period              = 60
  evaluation_periods  = 1
  threshold           = 0
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"
  # alarm_actions = [aws_sns_topic.alerts.arn]
}
```

**What I changed and why**
- **DLQ and alarm:** without a DLQ, a bad message is retried until retention expires. The alarm tells you when messages land in the DLQ.
- **Visibility timeout:** the SQS default is 30s. If your Lambda timeout is 30s or more, messages become visible again while still being processed, so they get processed twice. AWS requires the visibility timeout to be at least the function timeout, and I set it to 6x.
- **`ReportBatchItemFailures`:** without it, one failed record makes the whole batch of 10 retry, including records that already succeeded. Your handler has to return the failures:

```python
def handler(event, context):
    failures = []
    for record in event["Records"]:
        try:
            process_order(record)
        except Exception:
            logger.exception("Failed", extra={"message_id": record["messageId"]})
            failures.append({"itemIdentifier": record["messageId"]})
    return {"batchItemFailures": failures}
```

- **`maximum_concurrency`:** this stops a queue backlog from using all your account's Lambda concurrency or overwhelming a database.
- **IAM:** the function needs SQS read permissions on the queue, plus logging.
- **Idempotency:** SQS delivers at least once, so make `process_order` idempotent. Powertools idempotency keyed on the order ID works well for this.

**Things to confirm**
- I assumed a 30s timeout. If your processing takes longer, raise `timeout` and keep the visibility timeout at 6x.
- I guessed the runtime, handler and package path, so replace them with yours.
- If order sequence matters, you need an SQS FIFO queue, which changes the queue name and settings.

I can also write this into `.tf` files, add a Powertools-based handler, or render the `sqs-lambda-worker` template from the creating-aws-projects skill if you want a full project.

Total cost: $1.01
