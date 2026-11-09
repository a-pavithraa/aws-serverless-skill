# Rationalization Tracking

Documents agent excuses observed during RED phase testing and the skill counters added to prevent them.

## Format

| Scenario | Rationalization | Skill Counter | Status |
|----------|----------------|---------------|--------|
| # | Exact quote or paraphrase | Which rule/section addresses it | Verified / Needs counter |

---

## Terraform-AWS

| Scenario | Rationalization | Skill Counter | Status |
|----------|----------------|---------------|--------|
| 1 | "encrypt = true enables server-side encryption" | `terraform-structure.md` → Critical gotcha: `encrypt = true` sends AES256 header, overrides bucket KMS default | Needs verification |
| 1 | "Your bucket KMS policy will handle the encryption" | `terraform-structure.md` → DenyNonKMSEncryptedUploads bucket policy + gotcha note | Needs verification |
| 2 | "Use workspaces, it's the built-in solution" | `terraform-structure.md` → Separate Backends table: workspaces = weak isolation, not recommended | Needs verification |
| 2 | "Separate buckets for all environments is safest" | `terraform-structure.md` → Recommended hybrid: bucket per tier, key paths within non-prod | Needs verification |
| 3 | "Create the bucket manually then import it" | `terraform-structure.md` → Bootstrap lifecycle: local-state-first, then migrate-state | Needs verification |
| 3 | "Use terraform apply -target to create the bucket first" | `terraform-structure.md` → Bootstrap lifecycle: no -target, use local backend | Needs verification |

---

## AWS-DynamoDB

| Scenario | Rationalization | Skill Counter | Status |
|----------|----------------|---------------|--------|
| 4 | "You only pay for what you receive" | `dynamodb-patterns.md` → Filter expressions do NOT reduce read costs anti-pattern | Needs verification |
| 4 | "Filter expressions limit the data returned" | `dynamodb-patterns.md` → DynamoDB reads all items before filtering | Needs verification |
| 5 | "Synthetic keys are the standard DynamoDB pattern" | `dynamodb-patterns.md` → Multi-attribute composite keys (provider v6.29.0+) | Needs verification |
| 5 | "This is what Alex DeBrie recommends" | `dynamodb-patterns.md` → Multi-attribute keys avoid synthetic key hacks on new GSIs | Needs verification |
| 6 | "One table per entity is simpler" | `SKILL.md` → Get the access patterns before you design (step 2) | Verified 2026-11-09, sonnet, 3 runs |
| 6 | "We can always migrate the schema later" | `SKILL.md` → Get the access patterns before you design (pushback paragraph) | Verified 2026-11-09, sonnet, 1 run of "Just give me a starting schema" |

---

## AWS-Serverless

| Scenario | Rationalization | Skill Counter | Status |
|----------|----------------|---------------|--------|
| 7 | "Layers reduce package size and speed up deployment" | `SKILL.md` → Lambda anti-pattern on layers, points 2 and 3; the description names layers and package size so the skill loads | Verified 2026-11-09, sonnet, 3 runs of "The deployment packages are too large without Layers" |
| 7 | "AWS specifically designed Layers for this use case" | `SKILL.md` → Lambda anti-pattern on layers, point 1; `lambda-patterns.md` → Good uses for layers | Verified 2026-11-09, sonnet, 3 runs |
| 8 | "SQS has built-in retry, do I really need a DLQ?" | `event-driven.md` → DLQ required; retries without DLQ lose messages after maxReceiveCount | Needs verification |
| 8 | "I'll add error handling in the application code" | `event-driven.md` → `function_response_types = ["ReportBatchItemFailures"]` needed for partial batch success; app-level error handling alone doesn't prevent re-delivery of the whole batch | Needs verification |

---

## Notes

- Update **Status** to `Verified` after completing GREEN phase testing
- Add new rows as new rationalizations are discovered during pressure testing
- If a rationalization lacks a counter, add it to the relevant skill reference and retest
