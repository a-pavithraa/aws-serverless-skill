# DynamoDB Patterns & Best Practices

## Table of Contents
1. [Data Modeling Fundamentals](#data-modeling-fundamentals)
2. [Single-Table Design](#single-table-design)
3. [Access Patterns](#access-patterns)
4. [Multi-Attribute Composite Keys](#multi-attribute-composite-keys)
5. [One-to-Many Relationships](#one-to-many-relationships)
6. [Cost Optimization](#cost-optimization)
7. [Terraform Examples](#terraform-examples)

---

## Data Modeling Fundamentals

### Key Principle: Access Patterns First
Unlike relational databases, DynamoDB requires you to know your access patterns before designing the schema:

```
Relational: Design schema → Write queries
DynamoDB:   Define access patterns → Design schema → Write code
```

---

## Single-Table Design

### When to Use Single-Table
Use single-table design when:
- You need to fetch related items in one request
- Your access patterns are well-defined
- You want consistent performance at scale

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

**Before** — manual concatenation, string parsing, zero-padding:
```python
item = {
    "PK": "MATCH#match-001",
    "SK": "METADATA",
    "GSI1PK": f"TOURNAMENT#{tournament_id}#REGION#{region}",
    "GSI1SK": f"{round}#{bracket}#{match_id}",
}
```

**After** — natural domain attributes, typed values:
```python
item = {
    "PK": "MATCH#match-001",
    "SK": "METADATA",
    "tournamentId": "WINTER2024",
    "region": "NA-EAST",
    "round": "SEMIFINALS",
    "bracket": "UPPER",
}
```

### Query Rules

**Partition key** — ALL attributes required, equality only:
```python
# All partition attrs must be present with =
KeyConditionExpression='tournamentId = :t AND #region = :r'
```

**Sort key** — left-to-right, no gaps:
```python
# round only
KeyConditionExpression='... AND round = :round'

# round + bracket
KeyConditionExpression='... AND round = :round AND bracket = :bracket'

# INVALID: skipping round to query bracket
KeyConditionExpression='... AND bracket = :bracket'
```

**Inequality** — must be the **last** condition:
```python
# Valid: inequality on last sort attr queried
KeyConditionExpression='... AND round >= :start_round'
KeyConditionExpression='... AND round = :round AND bracket BETWEEN :a AND :b'

# Invalid: conditions after inequality
KeyConditionExpression='... AND round > :round AND bracket = :bracket'
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

## One-to-Many: Multi-Attribute Composite Keys (GSI)

For hierarchical queries without string concatenation, use a [multi-attribute GSI](#multi-attribute-composite-keys):
```hcl
global_secondary_index {
  name            = "GeoIndex"
  hash_key        = ["country"]
  range_key       = ["state", "city", "storeId"]
  projection_type = "ALL"
}
```

Query at any level of the hierarchy with typed attributes:
```python
# All stores in USA
table.query(IndexName='GeoIndex',
    KeyConditionExpression='country = :country',
    ExpressionAttributeValues={':country': 'USA'})

# All stores in California
table.query(IndexName='GeoIndex',
    KeyConditionExpression='country = :country AND #state = :state',
    ExpressionAttributeNames={'#state': 'state'},
    ExpressionAttributeValues={':country': 'USA', ':state': 'CA'})

# Specific city
table.query(IndexName='GeoIndex',
    KeyConditionExpression='country = :country AND #state = :state AND city = :city',
    ExpressionAttributeNames={'#state': 'state'},
    ExpressionAttributeValues={':country': 'USA', ':state': 'CA', ':city': 'SF'})
```

Prefer this over Strategy 4 when adding a GSI to an existing table (no backfill needed) or when attributes have distinct types.

---

## Cost Optimization

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

---

## Terraform Examples

### DynamoDB Table with GSI
```hcl
resource "aws_dynamodb_table" "main" {
  name         = "${var.project}-${var.environment}"
  billing_mode = "PAY_PER_REQUEST"  # On-demand
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
    name = "GSI1PK"
    type = "S"
  }
  
  attribute {
    name = "GSI1SK"
    type = "S"
  }
  
  global_secondary_index {
    name            = "GSI1"
    hash_key        = "GSI1PK"
    range_key       = "GSI1SK"
    projection_type = "ALL"
  }
  
  ttl {
    attribute_name = "expiresAt"
    enabled        = true
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

