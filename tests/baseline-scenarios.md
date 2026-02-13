# Baseline Scenarios

RED phase testing for AWS serverless and Terraform skills. Each scenario validates a specific failure mode — not generic knowledge.

---

## Scenario 1: Terraform State Encryption — SSE-S3 vs SSE-KMS

**Skill:** `terraform-aws`
**Objective:** Validate that the skill prevents the silent SSE-KMS → SSE-S3 override when `encrypt = true` is set without `kms_key_id`.

### Test Prompt

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

### Expected Baseline Behavior (Without Skill)

Agent confirms this is correct:
- Says "yes, `encrypt = true` enables encryption"
- Confirms bucket-level KMS default encryption covers it
- Misses the override behavior
- Does not mention `kms_key_id`

**Predicted rationalizations:**
- "encrypt = true enables server-side encryption"
- "Your bucket KMS policy will handle the encryption"
- "This is the standard backend configuration"

### Target Behavior (With Skill)

Agent identifies the critical gotcha:
- **STOPS** and flags that `encrypt = true` alone sends `AES256` header
- Explains that this **overrides** the bucket's KMS default — state files end up SSE-S3 not SSE-KMS
- Provides corrected config with `kms_key_id`
- Recommends the `DenyNonKMSEncryptedUploads` bucket policy as a safety net

### Pressure Variations

1. "The bucket is already configured for KMS, isn't that enough?"
2. "AWS docs say encrypt = true enables encryption"
3. "I've seen this config in many Terraform examples"

### Success Criteria

- [ ] Identifies that `encrypt = true` alone uses SSE-S3 (AES-256), not SSE-KMS
- [ ] Explains that this overrides the bucket's KMS default encryption
- [ ] Provides corrected config with both `encrypt = true` and `kms_key_id`
- [ ] Does NOT say "this configuration is correct"

---

## Scenario 2: Terraform Backend Environment Isolation Strategy

**Skill:** `terraform-aws`
**Objective:** Validate that the skill gives nuanced guidance on workspace vs separate buckets vs key paths — not a blanket rule.

### Test Prompt

```
We have prod, staging, and 10+ feature branch environments. What's the best way to isolate Terraform state between them? Should I use Terraform workspaces?
```

### Expected Baseline Behavior (Without Skill)

Agent gives a binary answer:
- Either "use workspaces" or "don't use workspaces, use separate buckets"
- Applies one rule to all environment types
- Doesn't distinguish between trust boundaries vs ephemeral envs

**Predicted rationalizations:**
- "Workspaces are the built-in solution for multiple environments"
- "Separate buckets for all environments is safest"
- "Use one approach consistently"

### Target Behavior (With Skill)

Agent gives a tiered recommendation:
- **Workspaces:** Not recommended for environment isolation — weak access controls
- **Separate buckets:** Correct for prod vs non-prod hard trust boundary (IAM scoped per bucket)
- **Key paths within one bucket:** Correct for feature branches within non-prod (practical, no bucket sprawl)
- Explains why the hybrid approach: prod gets its own bucket, feature branches share a non-prod bucket with per-branch keys

### Pressure Variations

1. "Just use workspaces, it's simpler"
2. "We should be consistent and use separate buckets for everything"
3. "Why does it matter for feature branches?"

### Success Criteria

- [ ] Does NOT recommend workspaces for environment isolation
- [ ] Distinguishes between hard trust boundaries (separate buckets) and soft boundaries (key paths)
- [ ] Recommends hybrid: separate bucket for prod, key paths for feature branches
- [ ] Explains IAM access control implications of each approach

---

## Scenario 3: Terraform Bootstrap — Chicken-and-Egg

**Skill:** `terraform-aws`
**Objective:** Validate that the skill explains the bootstrap pattern for creating the state bucket itself.

### Test Prompt

```
I want to use Terraform to create my S3 state bucket and KMS key. How do I handle the fact that Terraform needs a state bucket to run, but I'm trying to create the state bucket with Terraform?
```

### Expected Baseline Behavior (Without Skill)

Agent misses the standard pattern:
- Suggests creating the bucket manually first
- Or suggests using `terraform apply -target`
- Doesn't explain the local-state-first → migrate-state flow
- Doesn't mention bootstrap directory or `prevent_destroy`

**Predicted rationalizations:**
- "Create the bucket manually then import it"
- "Use terraform apply -target to create the bucket first"
- "It's a one-time setup, do it manually"

### Target Behavior (With Skill)

Agent explains the bootstrap pattern:
- **No backend block** in the bootstrap directory — Terraform uses local state by default
- Apply creates S3 bucket + KMS key + bucket policy locally
- Then add `backend "s3"` block and run `terraform init -migrate-state` to move state to S3
- Include `prevent_destroy = true` on the bucket
- Commit bootstrap `terraform.tfstate` (contains only ARNs/IDs, no secrets)

### Pressure Variations

1. "Can't I just use -backend=false?"
2. "Is there a simpler way that doesn't require migration?"
3. "Why not just create the bucket via AWS CLI?"

### Success Criteria

- [ ] Explains the local-state-first approach (no backend block = local default)
- [ ] Describes `terraform init -migrate-state` as the migration step
- [ ] Mentions `prevent_destroy = true` on the state bucket
- [ ] Does NOT suggest `-target` as the solution

---

## Scenario 4: DynamoDB Filter Expression Cost Misconception

**Skill:** `aws-dynamodb`
**Objective:** Validate that the skill corrects the common belief that filter expressions reduce read costs.

### Test Prompt

```
I have a DynamoDB table with millions of items. I'm querying with a filter expression to return only 10 matching items out of 1000. Does the filter expression reduce my read cost?
```

### Expected Baseline Behavior (Without Skill)

Agent confirms filter expressions reduce cost:
- "Yes, filter expressions only return matching items"
- "You'll be charged for the 10 items returned"
- Misses that DynamoDB reads all items before filtering

**Predicted rationalizations:**
- "Filter expressions limit the data returned"
- "You only pay for what you receive"
- "It's more efficient than fetching everything"

### Target Behavior (With Skill)

Agent corrects the misconception:
- **CLEARLY** states filter expressions do NOT reduce read costs
- DynamoDB reads all 1000 items first, charges for all 1000, then filters client-side
- Recommends designing the table/GSI to avoid needing filters at query time
- Mentions that sparse indexes or composite keys can eliminate the filter entirely

### Pressure Variations

1. "But I'm only getting 10 items back, why would I pay for 1000?"
2. "The AWS console shows reduced consumed capacity"
3. "It must be more efficient than scanning the whole table"

### Success Criteria

- [ ] Clearly states filter expressions do NOT reduce read (RCU) costs
- [ ] Explains DynamoDB reads all items in a Query/Scan before applying filter
- [ ] Recommends redesigning the data model to avoid runtime filters
- [ ] Does NOT confirm filter expressions reduce cost

---

## Scenario 5: DynamoDB GSI — Synthetic Key vs Multi-Attribute Composite Key

**Skill:** `aws-dynamodb`
**Objective:** Validate that the skill recommends multi-attribute composite keys instead of manually concatenated synthetic keys for new GSIs.

### Test Prompt

```
I need a GSI on my DynamoDB table where I can query by region AND tournament_id together. I was planning to create a synthetic key by concatenating them: "REGION#us-east#TOURNAMENT#abc123". Is this the right approach?
```

### Expected Baseline Behavior (Without Skill)

Agent confirms synthetic key approach:
- "Yes, concatenated keys are the standard DynamoDB pattern"
- "REGION#TOURNAMENT#value is a common composite key"
- No mention of multi-attribute composite keys (Nov 2025 feature)
- Provides HCL with string concatenation

**Predicted rationalizations:**
- "Synthetic keys are the established DynamoDB pattern"
- "This is how single-table design works"
- "It's the recommended approach"

### Target Behavior (With Skill)

Agent recommends multi-attribute composite keys:
- **QUESTIONS** synthetic key approach for new GSIs
- Recommends multi-attribute composite keys (DynamoDB feature, Nov 2025)
- Requires Terraform AWS provider v6.29.0+
- Shows `hash_key = ["region", "tournament_id"]` list syntax
- Explains when synthetic keys are still needed (base table PK/SK, `begins_with` patterns, old provider versions)

### Pressure Variations

1. "Synthetic keys are what everyone uses for this"
2. "I've seen this pattern in all the DynamoDB books"
3. "Alex DeBrie recommends synthetic keys"

### Success Criteria

- [ ] Recommends multi-attribute composite keys for new GSIs
- [ ] Mentions Terraform AWS provider v6.29.0+ requirement
- [ ] Shows `hash_key = ["attr1", "attr2"]` list syntax
- [ ] Explains when synthetic keys are still appropriate
- [ ] Does NOT just confirm synthetic key concatenation as the only option

---

## Scenario 6: DynamoDB Schema-First Design Anti-Pattern

**Skill:** `aws-dynamodb`
**Objective:** Validate that the skill stops schema-first design and insists on access-pattern-first modeling.

### Test Prompt

```
I'm building a multi-tenant SaaS app with Users, Organizations, Projects, and Tasks. Help me design the DynamoDB tables — I'm thinking one table per entity.
```

### Expected Baseline Behavior (Without Skill)

Agent designs schema first:
- Creates 4 separate tables (Users, Organizations, Projects, Tasks)
- Assigns PKs without asking about access patterns
- Recommends relational-style foreign key references
- No discussion of single-table design or co-location

**Predicted rationalizations:**
- "One table per entity is the standard approach"
- "Keep things simple and separate"
- "You can always add GSIs later"
- "This mirrors your domain model"

### Target Behavior (With Skill)

Agent stops and asks about access patterns first:
- **STOPS** before designing schema
- Asks: "What queries will your application run? List them first."
- Probes: "Which entities are always fetched together?"
- Only after access patterns are defined, suggests table structure
- Likely recommends single-table if entities are co-accessed

### Pressure Variations

1. "Just give me a starting schema, I'll figure out the queries later"
2. "One table per entity is simpler to understand"
3. "We can always migrate the schema later"

### Success Criteria

- [ ] **STOPS** before suggesting a schema
- [ ] Asks for access patterns before designing table structure
- [ ] Does NOT default to one-table-per-entity
- [ ] Explains that DynamoDB schema follows queries, not the other way around

---

## Scenario 7: Lambda Layers as Dependency Manager Anti-Pattern

**Skill:** `aws-serverless`
**Objective:** Validate that the skill discourages using Lambda Layers as a package manager substitute.

### Test Prompt

```
I have 5 Lambda functions that all use the same 3 Python libraries (boto3, requests, pydantic). I want to avoid bundling them in each function. Should I put them in a Lambda Layer?
```

### Expected Baseline Behavior (Without Skill)

Agent recommends Lambda Layers for shared dependencies:
- "Yes, Layers are perfect for shared libraries"
- "This reduces deployment package size"
- "It's a common best practice"
- No mention of cold start impact
- No alternative (container images, smaller functions)

**Predicted rationalizations:**
- "Layers reduce package size and speed up deployment"
- "Sharing dependencies across functions is the point of Layers"
- "AWS specifically designed Layers for this use case"

### Target Behavior (With Skill)

Agent warns about the trade-off:
- **Cautions** that Layers add cold start latency (Lambda must load the Layer at init time)
- For frequently invoked functions: layers may increase p99 cold start times
- Recommends Layers only for: code/assets that genuinely can't be bundled (large binaries, shared custom code), not as a package manager
- Alternative: each function bundles only what it needs; use container images for large dependencies

### Pressure Variations

1. "boto3 is already on every Lambda, so that's fine"
2. "The deployment packages are too large without Layers"
3. "This is the AWS-recommended pattern"

### Success Criteria

- [ ] Warns that Layers add cold start latency
- [ ] Does NOT unconditionally recommend Layers for shared libraries
- [ ] Distinguishes valid Layer use cases from package manager misuse
- [ ] Mentions container images as an alternative for large dependencies

---

## Scenario 8: SQS Lambda Trigger — Missing DLQ and Error Handling

**Skill:** `aws-serverless`
**Objective:** Validate that the skill insists on DLQ configuration and explicit error handling when setting up SQS-triggered Lambda.

### Test Prompt

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

### Expected Baseline Behavior (Without Skill)

Agent accepts the configuration:
- "Looks good"
- May mention batch_size is reasonable
- Misses DLQ entirely
- No mention of maxReceiveCount or redrive policy
- No visibility timeout alignment
- No bisect_batch_on_function_error

**Predicted rationalizations:**
- "The basic trigger setup is correct"
- "You can add a DLQ later if you see issues"
- "SQS handles retries automatically"

### Target Behavior (With Skill)

Agent flags multiple missing pieces:
- **DLQ is missing** — failed messages will retry indefinitely or be lost
- `maxReceiveCount` and redrive policy on the source queue
- SQS visibility timeout must be ≥ Lambda timeout × 6
- Recommends `bisect_batch_on_function_error = true` — isolates the failing message in a batch
- Recommends `function_response_types = ["ReportBatchItemFailures"]` — partial batch success

### Pressure Variations

1. "SQS has built-in retry, do I really need a DLQ?"
2. "I'll add error handling in the application code"
3. "We can monitor and add a DLQ if we see failures"

### Success Criteria

- [ ] Flags missing DLQ as a critical gap
- [ ] Mentions visibility timeout alignment with Lambda timeout
- [ ] Recommends `bisect_batch_on_function_error = true`
- [ ] Recommends `ReportBatchItemFailures` for partial batch success
- [ ] Does NOT say the configuration looks correct

---

## Running the Tests

### Phase 1 — Baseline (RED)

For each scenario:
1. Start a fresh Claude Code session
2. Load **no skills**
3. Run the test prompt exactly as written
4. Save full response to `baseline-results/scenario-N.md`
5. Extract rationalizations verbatim → add to `rationalizations.md`

### Phase 2 — Target (GREEN)

For each scenario:
1. Start a fresh session
2. Load the relevant skill
3. Run the **identical** prompt
4. Check each success criterion
5. Document pass/fail

### Phase 3 — Pressure Testing (REFACTOR)

For passing scenarios:
1. Run each pressure variation
2. If the agent can be talked out of correct behavior, document the rationalization
3. Add a counter to the skill
4. Re-test

## Success Metrics

- [ ] All 8 baseline scenarios show clear behavior gaps (agent fails without skill)
- [ ] All 8 target scenarios pass all success criteria
- [ ] Pressure variations don't break compliance
- [ ] Every rationalization in `rationalizations.md` has a counter in the skill content
