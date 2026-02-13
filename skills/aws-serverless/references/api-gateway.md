# API Gateway Reference

## HTTP API vs REST API

> **TL;DR**: Default to HTTP API. Use REST API only when you need WAF, caching, usage plans, or request/response transformation.

| Feature | HTTP API | REST API |
|---------|----------|----------|
| **Cost** | ~70% cheaper | Higher |
| **Latency** | Lower | Higher |
| **JWT/OIDC auth** | Native | Via Lambda Authorizer |
| **Lambda Authorizer** | Yes (payload v2.0) | Yes (payload v1.0) |
| **Cognito authorizer** | Yes (JWT) | Yes (full) |
| **AWS_IAM auth** | Yes | Yes |
| **API Keys / Usage Plans** | No | Yes |
| **WAF integration** | No | Yes |
| **Response caching** | No | Yes |
| **Request validation** | No | Yes |
| **Mapping templates** | No | Yes |
| **VPC Link** | Yes (NLB/ALB) | Yes (NLB) |
| **Private endpoints** | No | Yes |
| **Integrations** | Lambda, HTTP proxy | Lambda, HTTP, AWS services |

### When to Choose Each

**Use HTTP API when:**
- Building microservice or public Lambda-backed APIs
- Auth is JWT/OIDC (Cognito, Auth0) or AWS_IAM
- No need for per-client usage quotas
- Cost and latency matter

**Use REST API when:**
- WAF is required (DDoS, SQLi protection)
- Response caching is needed
- API key usage plans (quota/throttle per client)
- Request/response transformation (mapping templates)
- Private VPC endpoints required

---

## Going-Live Checklist

*Source: [theburningmonk.com, 2019](https://theburningmonk.com/2019/11/check-list-for-going-live-with-api-gateway-and-lambda/) — items verified relevant as of 2025.*

### Observability

- **Enable detailed monitoring** on the API Gateway stage. Without it, CloudWatch only reports aggregated metrics across all endpoints — you can't identify which specific endpoint has high latency or errors.
- **Set up per-method latency alarms** using the `Latency` metric (not `Integration Latency`). Alarm on p90/p95/p99 depending on your SLA.
- **Set up per-method error rate alarms** on `4xxError` and `5xxError` using the `Average` statistic — not Sum. An error count is meaningless without request volume context.
- **Set up low success rate alarms** using CloudWatch metric math: `200 count / request count`.
- **Enable X-Ray active tracing** on the API Gateway stage and Lambda function. See [Monitoring](#monitoring--tracing) section below.
- **Emit custom business metrics asynchronously** via stdout (EMF format with Powertools Metrics) — never call CloudWatch API inline in the request path.
- **Apply resource tags** (AppId, Team, CostCenter, Environment) for cost tracking and operational visibility.

### Security

- **Set per-method rate limits** — the default shared regional limit [leaves you vulnerable to DoS](https://theburningmonk.com/2019/10/the-api-gateway-security-flaw-you-need-to-pay-attention-to/). Configure a sensible burst and rate limit per method.
- **Attach a WAF web ACL** with at minimum:
  - IP-based rate limiting rule
  - AWS Managed Rules (Core Rule Set, SQLi rule)
- **Authenticate every endpoint** — choose the right method:
  | Use Case | Auth Method |
  |----------|-------------|
  | User-facing public API | Cognito User Pools or Lambda Authorizer |
  | Internal service-to-service | AWS_IAM (`sigv4`) |
  | SaaS per-client usage quotas | API Key + Usage Plan (REST API only) |
- **Enable request validation** (REST API) to reject malformed requests before Lambda executes — saves invocation costs.
- **Validate responses** in Lambda code to prevent data exfiltration via injection attacks.
- **Never put sensitive data in URLs** — use Authorization headers and body.

### Performance

- **Keep Lambda timeout ≤ 3s** for user-facing APIs. API Gateway has a hard 29s integration timeout. For long operations, use the [async/decoupled pattern](event-driven.md#storage-first-pattern-api-gateway--sqs).
- **Cache at the edge** with CloudFront where possible. For REST API, enable stage-level response caching for read-heavy endpoints.

### Resilience

- **Set circuit breakers** around downstream dependencies to prevent cascade failures and retry storms.
- **Plan for multi-region** if high availability is required — Route 53 health checks + regional API deployments.

### Testing

- **Test end-to-end via HTTP** — don't stop at unit tests with mocked Lambda. Test through the actual API URL to catch IAM permission issues and request validation misconfigurations.
- **Run load tests** to identify scaling bottlenecks in downstream systems (DynamoDB, RDS, other APIs).
- **Consider consumer-driven contract testing** ([Pact](https://docs.pact.io/)) in large organizations where teams share APIs.

### Documentation

- **Publish your OpenAPI/Swagger spec** as part of CI using `aws apigateway get-export`.

---

## Monitoring & Tracing

### Enable X-Ray End-to-End

X-Ray tracing must be enabled on both API Gateway and Lambda to get full distributed traces.

**Terraform (API Gateway REST API):**
```hcl
resource "aws_api_gateway_stage" "main" {
  rest_api_id   = aws_api_gateway_rest_api.main.id
  stage_name    = var.environment

  xray_tracing_enabled = true

  access_log_settings {
    destination_arn = aws_cloudwatch_log_group.api_access_logs.arn
    format = jsonencode({
      requestId      = "$context.requestId"
      ip             = "$context.identity.sourceIp"
      httpMethod     = "$context.httpMethod"
      resourcePath   = "$context.resourcePath"
      status         = "$context.status"
      responseLength = "$context.responseLength"
      latency        = "$context.responseLatency"
      integrationLatency = "$context.integrationLatency"
    })
  }
}

resource "aws_cloudwatch_log_group" "api_access_logs" {
  name              = "/aws/apigateway/${local.name_prefix}/access-logs"
  retention_in_days = 30
}
```

**Terraform (Lambda):**
```hcl
resource "aws_lambda_function" "api" {
  # ...

  tracing_config {
    mode = "Active"  # PassThrough disables X-Ray
  }
}
```

For Powertools handler setup and X-Ray tracing, see `lambda-powertools.md`. For CloudWatch alarms (latency, 5xx error rate), see `monitoring.md`.

---

## Anti-Patterns

- **Don't** use API Gateway to fan-out to multiple Lambda functions for the same request — use SNS/EventBridge internally
- **Don't** set Lambda timeout equal to or longer than 29s (API Gateway will time out the connection first)
- **Don't** use REST API when HTTP API satisfies requirements — the cost difference is significant at scale
- **Don't** put API keys in query string params — they appear in access logs and browser history
- **Don't** rely on Lambda error handling to set HTTP status codes — configure API Gateway responses or use structured response objects
