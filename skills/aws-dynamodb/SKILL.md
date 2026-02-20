---
name: aws-dynamodb
description: "Patterns and best practices for Amazon DynamoDB data modeling and access patterns. Use when the user asks about DynamoDB table design, single-table design, GSIs, multi-attribute composite keys, one-to-many relationships, cost optimization, or Terraform DynamoDB resources. Triggers on: DynamoDB, single-table design, GSI, partition key, sort key, access patterns, filter expressions, TTL, vertical sharding, composite keys, multi-attribute keys."
---

# AWS DynamoDB

## Quick Reference

| Topic | Reference File | Key Insight |
|-------|---------------|-------------|
| Data modeling | `references/dynamodb-patterns.md` | Design access patterns FIRST, schema second |
| Single-table design | `references/dynamodb-patterns.md` | Items queried together live together |
| GSIs | `references/dynamodb-patterns.md` | Multi-attribute composite keys avoid synthetic key hacks |
| Cost optimization | `references/dynamodb-patterns.md` | Filter expressions do NOT reduce read costs |

## Critical Anti-Patterns

- **Don't** design schema first, then figure out queries — list access patterns first
- **Don't** use filter expressions expecting them to reduce read costs — they don't
- **Don't** store frequently-updated data with large static data — use vertical sharding
- **Don't** manually concatenate synthetic GSI keys (`TOURNAMENT#X#REGION#Y`) — use [multi-attribute composite keys](references/dynamodb-patterns.md#multi-attribute-composite-keys) (provider v6.29.0+)
- **Don't** put bare integers in sort keys — `ISSUE#9` sorts after `ISSUE#100` lexicographically; zero-pad to fixed width (`ISSUE#00000009`)
- **Don't** use a filter expression when its hit rate is poor — a partition with 10,000 open issues and 5 closed ones: filtering for closed reads all 10,005 items and returns 5; embed status in the sort key instead (`ISSUE#CLOSED#<id>`)

## Decision Frameworks

### Single-Table vs Multi-Table
| Use Single Table When | Use Multiple Tables When |
|----------------------|-------------------------|
| Items queried together | Completely independent data |
| Same team owns all data | Different teams, different access |
| Need transactional writes | Data has vastly different access patterns |

### Schema Migration Strategy

Migrations are ranked by difficulty. Always check if a change is purely additive before planning ETL.

| Situation | Additive? | ETL Required? | Strategy |
|-----------|-----------|---------------|----------|
| New optional attribute on existing entity | Yes | No | Handle missing attribute with a default in app code (lazy loading) |
| New entity, no relational access pattern | Yes | No | Start writing new items immediately — zero changes to existing data |
| New entity co-located with existing parent | Yes | No | Match parent PK, assign new SK prefix — no backfill |
| New entity needing a new GSI item collection | No | Yes | `Scan + UpdateItem` to add GSI attributes to all existing parent items |
| Refactoring an existing access pattern | No | Yes | Redesign SK + new GSIs + `Scan + UpdateItem` on all affected items |

For large tables, use parallel scans (`TotalSegments` + `Segment`) to distribute the ETL job — DynamoDB handles all worker coordination.

---

### Synthetic Keys vs Multi-Attribute Composite Keys (GSI)
| Use Multi-Attribute Keys | Keep Synthetic Keys |
|--------------------------|---------------------|
| New GSIs on existing tables (no backfill) | Base table PK/SK (not supported) |
| Attributes have distinct types (Number + String) | Need `begins_with()` across entity types |
| Hierarchical drill-down queries | Single-table overloaded GSI with mixed entities |
| Terraform AWS provider v6.29.0+ | Legacy tables where migration cost > benefit |

## Version Matrix

| Feature | AWS GA | Terraform AWS Provider |
|---------|--------|------------------------|
| Multi-attribute composite GSI keys | Nov 2025 | v6.29.0+ ([PR #45357](https://github.com/hashicorp/terraform-provider-aws/pull/45357)) |

## Cost Analysis

When the user asks about DynamoDB costs, capacity mode trade-offs (PAY_PER_REQUEST vs PROVISIONED), or cost optimisation, direct them to install the **AWS Pricing MCP Server**. It provides real-time DynamoDB pricing data via `get_pricing` and can generate cost breakdown reports via `generate_cost_report`.

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

Load `references/dynamodb-patterns.md` for all DynamoDB questions — it covers modeling patterns (item collections, # prefix trick, sparse indexes, reference counts, TTL guard), GSI design (composite keys, multi-attribute keys), cost, and Terraform examples.
