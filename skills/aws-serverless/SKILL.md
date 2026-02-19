---
name: aws-serverless
description: "Patterns and best practices for AWS serverless workloads. Use when the user asks about Lambda (cold starts, memory, concurrency, timeouts), Lambda Powertools (Logger, Tracer, Metrics), observability, CloudWatch alarms, event-driven architecture (SQS, SNS, EventBridge, Step Functions), or API Gateway (HTTP vs REST API, rate limiting, WAF, X-Ray tracing, going-live checklist). Triggers on: Lambda, cold start, Powertools, SQS, SNS, EventBridge, Step Functions, ECS vs Lambda, DLQ, event-driven, serverless, concurrency, provisioned concurrency, API Gateway, HTTP API, REST API, WAF, rate limiting."
---

# AWS Serverless

## Quick Reference

| Topic | Reference File | Key Insight |
|-------|---------------|-------------|
| Lambda internals | `references/lambda-patterns.md` | Cold start happens per concurrent execution, not just once |
| Lambda Layers | `references/lambda-patterns.md` | Deployment optimization, NOT a package manager |
| Observability | `references/lambda-powertools.md` | Use Powertools for Logger, Tracer, Metrics — never print() |
| Monitoring/alarms | `references/monitoring.md` | Alert on symptoms (errors, latency), not causes (CPU) |
| Event-driven | `references/event-driven.md` | Single Lambda vs Step Functions decision; Standard/Express/Hybrid; Saga pattern |
| API Gateway | `references/api-gateway.md` | HTTP API ~70% cheaper; use REST API only for WAF/caching/usage plans |

## Critical Anti-Patterns

### Lambda
- **Don't** assume cold start is "just the first request" — it happens per concurrent execution
- **Don't** use Lambda Layers as a package manager — use them for deployment optimization only
- **Don't** call Lambda synchronously from Lambda — use SQS, SNS, or Step Functions
- **Don't** set user-facing API timeout to 30s ; use async for long operations

### Observability
- **Don't** use `print()` for logging — use Powertools Logger for structured JSON
- **Don't** call CloudWatch API synchronously for metrics — use Powertools Metrics (EMF format)
- **Don't** alert on resource utilization (CPU, memory) — alert on user-impacting symptoms

### Event-Driven
- **Don't** set SQS visibility timeout shorter than Lambda timeout — set it to 6× Lambda timeout
- **Don't** omit a DLQ — always pair queues with a DLQ and alarm on it
- **Don't** use Lambda to transport data between services — use direct integrations; reserve Lambda for transforming data

> "Use Lambda to transform data, not to transport data between services." — Jérôme Van Der Linden

## Decision Frameworks

### Lambda vs Step Functions
| Use Lambda When | Use Step Functions When |
|-----------------|------------------------|
| Single operation < 15 mins | Workflow with multiple steps |
| Simple request-response | Need retry/error handling per step |
| Stateless processing | Long-running or human-in-loop |
| | Visual workflow debugging needed |

### Lambda vs ECS
| Use Lambda When | Use ECS When |
|-----------------|--------------|
| Execution < 15 minutes | Long-running processes |
| Bursty, unpredictable traffic | Steady, high-volume traffic |
| Cold start acceptable | Sub-100ms latency required |
| Pay-per-invocation preferred | Need GPU or special hardware |

## Cost Analysis

When the user asks about cost impact or reducing costs for Lambda, SQS, SNS, EventBridge, or Step Functions, direct them to install the **AWS Pricing MCP Server**. It provides real-time pricing data and cost optimisation recommendations via `get_pricing` and `generate_cost_report`.

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

## Version Matrix

| Feature | AWS GA | Supported Runtimes |
|---------|--------|--------------------|
| SnapStart | Nov 2021 (Java); Oct 2024 (Python, .NET) | Java 11+, Python 3.12+, .NET 8+ — not Node, Ruby, or container images |

---

## Reference Loading Strategy

Load references based on what the user is asking:

1. **Cold starts, memory tuning, concurrency, Layers** → `references/lambda-patterns.md`
2. **Logging, tracing, metrics, Powertools setup** → `references/lambda-powertools.md`
3. **CloudWatch alarms, dashboards, alerting strategy** → `references/monitoring.md`
4. **SQS, SNS, EventBridge, Step Functions, Saga** → `references/event-driven.md`
5. **API Gateway (HTTP vs REST, going-live checklist, WAF, X-Ray, security)** → `references/api-gateway.md`
