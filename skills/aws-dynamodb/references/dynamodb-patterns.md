# DynamoDB Patterns & Best Practices

## Table of Contents
1. [Single-Table Design](#single-table-design)
2. [Access Pattern Gotcha: Filter Expressions](#access-pattern-gotcha-filter-expressions)
3. [Multi-Attribute Composite Keys](#multi-attribute-composite-keys)
4. [Cost Optimization](#cost-optimization)
5. [Terraform Examples](#terraform-examples)

---

## Single-Table Design

### Item Collection Pattern
Group related items by partition key:

```
PK              | SK                  | Data
----------------|---------------------|------------------
ORG#acme        | METADATA            | {name, plan...}
ORG#acme        | USER#user1          | {name, email...}
ORG#acme        | USER#user2          | {name, email...}
```

Single Query retrieves org + all users:
```python
response = table.query(
    KeyConditionExpression=Key('PK').eq('ORG#acme')
)
```

---

## Access Pattern Gotcha: Filter Expressions
**Filter expressions do NOT reduce read costs!**

```python
# BAD: Scans entire partition, then filters
response = table.query(
    KeyConditionExpression=Key('PK').eq('ORG#acme'),
    FilterExpression=Attr('status').eq('active')
)
# Reads ALL items, filters after, costs same RCUs

# GOOD: Design key to support the access pattern
# SK = STATUS#active#USER#123
response = table.query(
    KeyConditionExpression=Key('PK').eq('ORG#acme') & Key('SK').begins_with('STATUS#active')
)
```

---

## Multi-Attribute Composite Keys

> Requires Terraform AWS Provider **v6.29.0+** ([PR #45357](https://github.com/hashicorp/terraform-provider-aws/pull/45357))

GSI partition and sort keys can now be composed from **up to 4 attributes each** (8 total per GSI). DynamoDB handles hashing and sort ordering natively — no synthetic concatenated keys needed.

### Before vs After

The GSI in this example has `hash_key = ["tournamentId", "region"]` and `range_key = ["round", "bracket", "matchId"]`.

**Before** — synthetic concatenated attributes, requires string parsing and zero-padding for numeric sort:
```python
item = {
    "PK": "MATCH#match-001",
    "SK": "METADATA",
    "GSI1PK": f"TOURNAMENT#{tournament_id}#REGION#{region}",  # manually joined
    "GSI1SK": f"{round}#{bracket}#{match_id}",                # manually joined
}
```

**After** — natural domain attributes; DynamoDB handles composite hashing and sort ordering:
```python
item = {
    "PK": "MATCH#match-001",
    "SK": "METADATA",
    # GSI partition key (both required when querying)
    "tournamentId": "WINTER2024",
    "region": "NA-EAST",
    # GSI sort key (query left-to-right, stopping at any point)
    "round": "SEMIFINALS",
    "bracket": "UPPER",
    "matchId": "match-001",
}
```

### Query Rules

**Partition key** — every attribute required, equality only. Omitting any one attribute is invalid:
```python
# Valid — both PK attributes present
table.query(
    IndexName="TournamentRegionIndex",
    KeyConditionExpression="tournamentId = :t AND #region = :r",
    ExpressionAttributeNames={"#region": "region"},
    ExpressionAttributeValues={":t": "WINTER2024", ":r": "NA-EAST"},
)

# Invalid — missing region; partial PK is not allowed
table.query(
    IndexName="TournamentRegionIndex",
    KeyConditionExpression="tournamentId = :t",
)
```

**Sort key** — left-to-right, no gaps. You can stop at any SK attribute, but cannot skip one:
```python
# Valid — first SK attribute only
KeyConditionExpression="tournamentId = :t AND #region = :r AND round = :round"

# Valid — first two SK attributes
KeyConditionExpression="tournamentId = :t AND #region = :r AND round = :round AND bracket = :bracket"

# Invalid — skips round, jumps straight to bracket
KeyConditionExpression="tournamentId = :t AND #region = :r AND bracket = :bracket"
```

**Inequality** — allowed only on the last SK attribute in the expression. No further conditions after it:
```python
# Valid — inequality on the first (and only) SK attribute used
KeyConditionExpression="tournamentId = :t AND #region = :r AND round >= :start_round"

# Valid — equality on round, then inequality on bracket (the last SK attr queried)
KeyConditionExpression="tournamentId = :t AND #region = :r AND round = :round AND bracket BETWEEN :a AND :b"

# Invalid — bracket condition follows an inequality on round
KeyConditionExpression="tournamentId = :t AND #region = :r AND round > :round AND bracket = :bracket"
```

### Data Types

Each attribute retains its native type in the composite key:

| Type | Sort Behavior | Gotcha |
|------|--------------|--------|
| `S` (String) | Lexicographic | `"5"` sorts after `"1000"` — zero-pad if needed |
| `N` (Number) | Numeric | `5` < `50` < `500` < `1000` — natural order |
| `B` (Binary) | Byte-order | Raw binary comparison |

### When to Use

| Use Multi-Attribute Keys | Keep Synthetic Keys |
|--------------------------|---------------------|
| New GSIs on existing tables (no backfill needed) | Base table PK/SK (not supported there) |
| Attributes have distinct types (Number + String) | Need `begins_with()` across entity types |
| Query patterns follow hierarchical drill-down | Single-table overloaded GSI with mixed entity types |
| Clean domain model with typed attributes | Legacy tables where migration cost > benefit |

### Terraform Example

```hcl
resource "aws_dynamodb_table" "tournaments" {
  name         = "${var.project}-${var.environment}-tournaments"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "PK"
  range_key    = "SK"

  attribute {
    name = "PK"
    type = "S"
  }

  attribute {
    name = "SK"
    type = "S"
  }

  attribute {
    name = "tournamentId"
    type = "S"
  }

  attribute {
    name = "region"
    type = "S"
  }

  attribute {
    name = "round"
    type = "S"
  }

  attribute {
    name = "bracket"
    type = "S"
  }

  attribute {
    name = "matchId"
    type = "S"
  }

  global_secondary_index {
    name            = "TournamentRegionIndex"
    hash_key        = ["tournamentId", "region"]
    range_key       = ["round", "bracket", "matchId"]
    projection_type = "ALL"
  }

  point_in_time_recovery {
    enabled = true
  }

  server_side_encryption {
    enabled = true
  }

  tags = var.tags
}
```

### Common Patterns

**Time-series IoT** — query at any time granularity:
```hcl
global_secondary_index {
  name            = "DeviceTimeIndex"
  hash_key        = ["deviceId", "locationId"]
  range_key       = ["year", "month", "day", "timestamp"]
  projection_type = "ALL"
}
```

**SaaS multi-tenancy** — tenant-scoped resource queries:
```hcl
global_secondary_index {
  name            = "TenantResourceIndex"
  hash_key        = ["tenantId", "customerId"]
  range_key       = ["resourceType", "resourceId"]
  projection_type = "ALL"
}
```

**E-commerce orders** — seller analytics by region and date:
```hcl
global_secondary_index {
  name            = "SellerOrderIndex"
  hash_key        = ["sellerId", "region"]
  range_key       = ["orderDate", "category", "orderId"]
  projection_type = "ALL"
}
```

### Anti-Patterns

```
❌ Skipping middle sort key attributes in queries
❌ Using inequality on partition key attributes
❌ Adding conditions after an inequality operator
❌ Querying sort key attributes out of definition order
❌ Forgetting ExpressionAttributeNames for reserved words (region, status, etc.)
❌ Using multi-attribute keys when you need begins_with() across entity types
```

---

## Cost Optimization

### Billing Modes

| Mode | Cost | When to Use |
|------|------|-------------|
| On-demand | ~3.5× provisioned (fully utilized) | Unpredictable or spiky traffic |
| Provisioned | Pay per reserved unit, throttles at limit | Predictable load with ≥28.8% average utilization |
| Reserved capacity | Discounted provisioned | Stable, long-running workloads |

### Storage Classes

| Class | Cost | Use When |
|-------|------|----------|
| Standard | ~$0.25/GB-month | Frequently accessed data |
| Standard-IA | ~$0.10/GB-month | Storage dominates cost (storage > 50% of throughput spend) |

> AWS's documented threshold: switch to Standard-IA when storage cost exceeds 50% of your throughput (reads + writes) cost. Standard-IA read/write rates are ~25% higher than Standard ($0.155 vs $0.125 per million reads; $0.780 vs $0.625 per million writes). Enable TTL to avoid paying for stale data.

---

### Cost Multipliers (the hidden costs)

**Item size** — rounds up per KB per operation:
```
Read  20KB item  →  5 RCUs  (ceil(20/4))
Write 10KB item  →  10 WCUs (ceil(10/1))
Write same item to a GSI → another 10 WCUs
```

**Secondary indexes** — every write to the base table propagates to each GSI:
```
1 write to table with 3 GSIs = 4× write capacity consumed
```

**Transactions** — carry a 2× cost premium vs standard reads/writes.

**Global Tables** — each write is replicated to every region; storage is also replicated. Only deploy when cross-region active-active is genuinely required.

**Strongly consistent reads** — 2× the cost of eventually consistent. Avoid unless your access pattern strictly requires them.

---

### Reducing Item Size

- Remove attributes that are never read
- Shorten attribute names — DynamoDB bills the name bytes on every read

### Secondary Index Hygiene

- Delete unused GSIs immediately — every write still propagates to them
- Use `KEYS_ONLY` or `INCLUDE` projections instead of `ALL` where possible; projected item size drives both write and read costs on the index

### Vertical Sharding

Split frequently-updated fields from static data:
```
# Instead of updating 10KB item for view count:
PK           | SK           | data (10KB)
USER#123     | PROFILE      | {name, bio, avatar...}

# Split into:
PK           | SK           | data
USER#123     | PROFILE      | {name, bio...} (9.5KB)
USER#123     | STATS        | {views: 1000} (0.1KB)
```

Writing 0.1KB instead of 10KB for stat updates cuts write cost 100×.

---

## Terraform Examples

### DynamoDB Streams with Lambda

`stream_view_type` **cannot be changed after creation** — deleting and recreating the stream risks data loss. Default to `NEW_AND_OLD_IMAGES` unless storage cost is a specific concern. See `event-driven.md` for consumer limits, error handling, and processing patterns.

```hcl
resource "aws_dynamodb_table" "with_streams" {
  # ... table config

  stream_enabled   = true
  stream_view_type = "NEW_AND_OLD_IMAGES"  # Immutable post-creation — choose deliberately
}

resource "aws_lambda_event_source_mapping" "dynamodb" {
  event_source_arn  = aws_dynamodb_table.with_streams.stream_arn
  function_name     = aws_lambda_function.stream_processor.arn
  starting_position = "LATEST"
  batch_size        = 100

  filter_criteria {
    filter {
      pattern = jsonencode({
        eventName = ["INSERT", "MODIFY"]
      })
    }
  }
}
```
