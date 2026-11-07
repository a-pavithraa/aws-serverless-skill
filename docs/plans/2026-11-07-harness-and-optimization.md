# AWS IaC team harness and skill refresh

Date: 2026-11-07. Status: proposal, nothing built.

## Why

Teams still create AWS resources from the console and the CLI. Nobody owns those resources, so they stay running and keep costing money. Agents now write good Terraform, but they can make the same mistakes faster: an `aws ... create-*` call to get unblocked, `-target` to skip a failing resource, `#checkov:skip` to pass a scan, `Resource: "*"` to fix an AccessDenied, a log group with no retention, a NAT gateway in every dev environment. A skill tells the agent what good looks like. Only a gate stops it taking a shortcut.

The Spring Boot team harness in `springboot-skills-marketplace` taught us this. It puts rules in three places: `AGENTS.md` for context, hooks that check the agent's own changes before a turn ends, and CI that holds the same gates for everyone. This plan moves that design to Terraform on AWS, and brings the three skills up to date with what Lambda, ECS and EKS can do in late 2026.

## Summary

| # | Work | Size | Depends on |
| --- | --- | --- | --- |
| 1 | Fix the existing skills: stale facts, duplicated text, long descriptions | S | – |
| 2 | Run the eight existing test scenarios for real and record the results | S | – |
| 3 | Refresh `aws-serverless` for Lambda 2025–26 | M | 1 |
| 4 | New skill `aws-containers` (ECS and EKS) | M | 1 |
| 5 | New skill `aws-cost` (cost review of Terraform and of an account) | M | 1 |
| 6 | Observability refresh: OpenTelemetry, log cost, alarms as code | M | 3 |
| 7 | New skill `aws-iac-adoption`: bring console-made resources under Terraform | M | 1 |
| 8 | `aws-iac-team-harness`: AGENTS.md, guard and Stop hooks, CI | L | 1–7 inform its rules |
| 9 | Plan-level policy pack (cost, security, reliability rules on plan JSON) | M | 8 |
| 10 | Harness sample project and end-to-end test | M | 8, 9 |

Do 1 and 2 first: they are cheap and tell us which scenarios still fail. Ship the harness (8) with only the gates that need no AWS credentials, then add the policy pack (9).

## What the repository has today

Three skills, about 5,800 lines. Findings from reading them:

- **The tests were never run.** `tests/baseline-results/` holds only `.gitkeep`, and every row in `tests/rationalizations.md` says `Needs verification`. We don't know which content changes agent behaviour.
- **Stale numbers in the skills.** `terraform-aws/SKILL.md` lists reference sizes of 184, 327 and 642 lines; the files are 354, 315 and 631.
- **Duplicated text in every session.** The AWS Pricing MCP setup (about 45 lines of JSON for two OSes) is copied into both `aws-serverless/SKILL.md` and `terraform-aws/SKILL.md`. A `SKILL.md` body loads whenever the skill triggers, so this costs context on every use. It belongs in one reference file.
- **Descriptions are keyword lists.** Both descriptions run to 60+ words of triggers. Claude Code reads every skill description in every session; shorter, "use when" phrasing triggers as well and costs less.
- **Nothing on containers.** `aws-serverless` has a Lambda-vs-ECS table and nothing else on ECS or EKS.
- **No cost skill.** Cost advice is "install the Pricing MCP server". There is no guidance on what to look for.
- **No 2025–26 Lambda features**: Managed Instances, durable functions, SQS provisioned mode, response streaming at 200 MB.
- **Tracing assumes the X-Ray SDK**, which went into maintenance mode on 2026-02-25 and reaches end of support on 2027-02-25.
- **Codex support is manual copy.** The marketplace manifest is Claude Code only.

What already works well and should stay: the "no common knowledge" rule, cited sources, the RED-GREEN-REFACTOR test design, and the `rationalizations.md` table.

## What else is out there

Before building, know what the agent may already have, so these skills only add what's missing.

| Project | Covers | Gap we fill |
| --- | --- | --- |
| `hashicorp/agent-skills` | 16 Terraform skills: style, modules, tests, providers, Stacks, search and import | Nothing AWS-specific on cost, IAM scoping or serverless wiring |
| `aws/agent-toolkit-for-aws` (successor to `awslabs/agent-plugins`) | Many AWS service skills, including serverless, billing, observability | Advice, not gates; no Terraform team harness |
| AWS Labs MCP servers | Terraform (with Checkov), Pricing, Billing and Cost Management, Cost Explorer | Each server's tools cost context in every session |

So the gap is the **harness**: gates that hold whatever skill or MCP server the agent uses. The skills should shrink to what neither HashiCorp's nor AWS's skills say, and point to them for the rest. Check both repositories' skill lists before writing each new reference, and cut anything they already cover.

## 1. Fix the existing skills

- Move the Pricing MCP block into `skills/aws-cost/references/mcp-servers.md` (after step 5) and replace it in both `SKILL.md` files with one line.
- Remove line counts from the loading tables, or generate them in a test. Hand-kept counts go stale.
- Rewrite the three descriptions to two sentences each: when to use it, when not to.
- Add `.codex-plugin` / Codex marketplace metadata the way `springboot-skills-marketplace` does, so Codex users get an install command, not a copy.
- Add a `Last verified` date to each Version Matrix row, so readers know which facts to recheck.

## 2. Run the existing tests

Run each of the eight scenarios once without the skill and once with it, with `claude plugin eval` or a fresh session. Keep it cheap: one run per arm, a Haiku judge, graders that read a named output file. Record results in `tests/baseline-results/scenario-N.md` and update `rationalizations.md`.

Delete or rewrite any scenario where the baseline already passes. Current models may know some of these now (S3 native locking, filter expressions cost RCUs), and a skill section that changes nothing only costs context.

## 3. Refresh `aws-serverless`

Add to `references/lambda-patterns.md`, each with the decision it changes:

| Topic | What to say | Source |
| --- | --- | --- |
| INIT billing (since 2025-08-01) | INIT is billed on ZIP managed runtimes too. Heavy init code and many layers now cost money, not just latency. Query `InitDuration` to measure | AWS Compute Blog |
| Lambda Managed Instances | Runs functions on EC2 that Lambda manages; one environment serves many concurrent requests. Priced as EC2 + 15% management fee on the On-Demand price + $0.20 per million requests, no duration charge. Savings Plans discount only the EC2 part. Fits steady, IO-bound load; wrong for spiky or rarely called functions | Lambda docs and pricing page |
| Durable functions | Multi-step workflows up to one year with checkpoint and replay, no charge while suspended. Decision table vs Step Functions. Limits: 3,000 operations per execution, 100 MB persisted per execution. Needs a qualified ARN (version or alias). Terraform `durable_config` needs AWS provider 6.25+ | Lambda quotas, durable IaC guide |
| Tenant isolation mode | Separate execution environments per tenant ID. Use instead of one function per tenant | re:Invent 2025 |
| SQS ESM provisioned mode | Minimum and maximum pollers, billed per Event Poller Unit. Only for spiky, latency-sensitive queues; default mode otherwise | What's New 2025-11 |
| Response streaming | 200 MB response limit since 2025-07 | What's New 2025-07 |
| Runtime deprecation | Check the runtime deprecation calendar; a gate in the harness (step 9) fails on a deprecated runtime | Lambda runtimes page |

Update the Lambda vs ECS table into a four-way decision: Lambda, Lambda Managed Instances, ECS (Fargate or Managed Instances), EKS. Move it to `aws-containers` and link to it.

## 4. New skill: `aws-containers`

Teams adopting ECS and EKS repeat the same mistakes. Content, each item with its fix:

**ECS**
- Capacity choice: Fargate, Fargate Spot, ECS Managed Instances (since 2025-09; Spot support since 2025-12, needs its own capacity provider), EC2. Spot only for work that survives a two-minute stop.
- ECS Express Mode (2025-11) for a quick service, and when to outgrow it.
- Native blue/green deployments (since 2025-07): CodeDeploy is no longer needed. Lifecycle hooks for checks before traffic moves.
- Right-size task CPU and memory from Container Insights before adding autoscaling. Overprovisioned tasks don't get cheaper by scaling.
- Graviton (`runtime_platform { cpu_architecture = "ARM64" }`) with a multi-arch image.
- Tasks in private subnets with no public IPv4 (each one costs $0.005 an hour); VPC endpoints for ECR, S3 (gateway, free), CloudWatch Logs, instead of NAT for image pulls.
- One task role per service, never the execution role doing the app's work.

**EKS**
- Version calendar: standard support is 14 months; after that the cluster moves to extended support at $0.60 an hour instead of $0.10, without asking. The harness flags a version near the end of standard support.
- EKS Auto Mode vs Karpenter vs managed node groups.
- Pod Identity over IRSA for new work (no OIDC provider per cluster); IRSA when a workload needs several roles.
- EKS Capabilities (managed Argo CD, ACK, kro): billed per hour plus per managed resource; an Argo CD Application counts once per target cluster.
- Cost: requests and limits set, Spot node pools for stateless work, consolidation on.

Check `aws/agent-toolkit-for-aws` for overlap first; keep only what it doesn't say.

## 5. New skill: `aws-cost`

Two jobs: review Terraform before it's applied, and review an account that already exists.

**Before apply** (also encoded as policy in step 9):

| Waste | Rule |
| --- | --- |
| Log groups that never expire | Every `aws_cloudwatch_log_group` sets `retention_in_days`; Lambda and ECS log groups are created in Terraform, not left to the service |
| Debug-level logs in prod | Lambda `logging_config` with `log_format = "JSON"` and `application_log_level` set per environment |
| NAT gateway for S3 and DynamoDB traffic | Gateway endpoints for S3 and DynamoDB (free); NAT at $0.045/GB processed |
| One NAT gateway per AZ in dev | One NAT in non-prod, or none when nothing needs the internet |
| Public IPv4 everywhere | $0.005 per address-hour since 2024-02, idle or not |
| x86 by default | arm64 for Lambda, Fargate, RDS, ElastiCache unless a dependency needs x86 |
| gp2 volumes | gp3 |
| Old engine and cluster versions | EKS and RDS extended support charges |
| Untagged resources | `default_tags` with `Owner`, `CostCenter`, `Environment`, `ManagedBy = terraform`; note that `aws_autoscaling_group` doesn't take `default_tags` |
| No budget | `aws_budgets_budget` and Cost Anomaly Detection monitor per account, created by the bootstrap project |
| Lambda log cost | Lambda logs can go to S3 or Firehose from $0.25/GB with tiered pricing; CloudWatch Infrequent Access for logs nobody queries live |

**After apply** (account review): Cost Optimization Hub and Compute Optimizer findings, idle resources (unattached EBS and EIPs, idle load balancers, stopped instances with volumes), resources with no `ManagedBy` tag (feeds step 7), Savings Plans coverage. Point to the Billing and Cost Management MCP server for the data, and say what to do with each finding.

**Cost estimates:** Infracost on the plan in CI for a diff per pull request. The Pricing MCP server's `analyze_terraform_project` for an agent's question in a session. Both are optional: Infracost needs an API key, the MCP server needs `uv` and credentials.

## 6. Observability refresh

The Spring Boot harness taught us observability is for the agent to verify its own work, not only for production. Changes:

- **Tracing:** the X-Ray SDK is in maintenance mode. New code uses OpenTelemetry (ADOT layer or the OTel SDK) and CloudWatch Application Signals. Check what Powertools Tracer does after the SDK's end of support and say it in the reference; don't guess.
- **Logs:** Lambda's native JSON format and log levels in Terraform, before Powertools Logger. Retention always set. Cost classes and destinations (step 5).
- **Alarms as code:** the alarm modules in `monitoring.md` become a policy rule: a DLQ without an alarm, or a Lambda with an async destination but no alarm on it, fails the plan check.
- **Agent verification:** a project skill, `verify-deployment`, that after an apply to a sandbox invokes the function or calls the endpoint, then reads its logs and metrics with Logs Insights to prove the change works, including errors the response hides. Same idea as the Spring harness's browser verification.

## 7. New skill: `aws-iac-adoption`

For the account full of console-made resources. Steps the skill walks through:

1. **Find what Terraform doesn't own.** Compare a resource inventory (AWS Config, Resource Explorer, or tags) against the state files. Resources with no `ManagedBy = terraform` tag and not in any state are unmanaged. Open-source `noclickops` does the state comparison.
2. **Find who made them.** CloudTrail create events whose principal isn't the pipeline's role. Turn that into a scheduled report, and an EventBridge rule that alerts on create calls from people in prod.
3. **Decide each one:** import, delete, or leave with an owner tag. Unowned and unused → delete after a notice period.
4. **Import.** Terraform 1.14's `terraform query` with `list` blocks finds resources by type and tag and writes `import` and `resource` blocks with `-generate-config-out`. Clean the generated config: remove computed attributes, replace hard-coded IDs with references. Plan must show no changes after import. For a provider without list resources, `import` blocks plus `-generate-config-out` on `terraform plan`.
5. **Stop it recurring.** SCP denying create actions without required tags (`aws:RequestTag`, only for actions that support it; check the Service Authorization Reference), AWS Config `required-tags` for the rest, and read-only console roles for humans in prod.

HashiCorp's `terraform-search-import` skill covers step 4 mechanics; link it and keep only the AWS parts here.

## 8. `aws-iac-team-harness`

Same shape as `spring-boot-team-harness`: a script that adds files to a Terraform repository and owns them through a lock file, so a rerun updates what nobody edited.

### Files it adds

| File | Effect |
| --- | --- |
| `AGENTS.md` section | Done means `scripts/harness-check.sh` passes. Never create, change or delete AWS resources with the CLI or console; change Terraform. Never `apply` from a session. How to fix each gate |
| `CLAUDE.md` | `@AGENTS.md` |
| `.claude/settings.json`, `.codex/hooks.json` | Register the hooks; allow `terraform fmt/validate/plan/test`, `tflint`, `checkov`, `trivy`; deny reading `*.tfvars` with secrets and `.terraform/` state copies |
| `.claude/hooks/guard.sh` | PreToolUse guard (below) |
| `.claude/hooks/verify-on-stop.sh` | Stop hook (below) |
| `.github/workflows/terraform.yml` | Full gates, plan, Infracost comment, apply behind environment approval |
| `.github/workflows/drift.yml` | Scheduled plan with `-detailed-exitcode`; opens an issue on drift. Plus the unmanaged-resource report from step 7 |
| `.github/workflows/harness-integrity.yml` | Fails a PR that weakens the gates (below) |
| `.tflint.hcl`, `.checkov.yaml`, `policy/` | Linter, scanner and plan-policy config |
| Project skills | `add-service` (module layout: function + role + log group + alarms), `import-resource` (step 7), `verify-deployment` (step 6) |

### Guard hook: shortcuts it refuses

| Shortcut | Why it's refused |
| --- | --- |
| `aws` CLI calls that create, update, delete, put, attach, tag or run (`create-*`, `put-*`, `delete-*`, `update-*`, `attach-*`, `run-instances`, `s3 rm/mb/cp` to a bucket, `cloudformation deploy`, …) | The resource exists outside Terraform. Read calls (`describe-*`, `get-*`, `list-*`, `logs tail`, `sts get-caller-identity`) pass |
| `terraform apply`, `destroy`, `import` (CLI form), `state rm/mv/push`, `force-unlock`, `taint` | Changes real infrastructure or state from a laptop. Apply runs in CI. Use `import`/`moved`/`removed` blocks in code instead |
| `-target=` | Hides the rest of the plan |
| `-auto-approve` | No human read the plan |
| `-lock=false` | Concurrent state writes |
| `sam deploy`, `cdk deploy`, `serverless deploy`, `copilot deploy`, `eksctl create`, `kubectl apply` against a non-local context | Other deploy paths around Terraform |
| Edits that add `#checkov:skip`, `#trivy:ignore`, `#tflint-ignore`, or touch `.checkov.yaml`, `.trivyignore`, `.tflint.hcl`, `policy/`, the baseline files | Silencing the gate instead of fixing the code |
| Edits that add `lifecycle { ignore_changes = all }` or remove `prevent_destroy` | Hides drift, or allows deleting a stateful resource |
| Edits to `backend.tf` | Pointing state somewhere else |
| `git push --force`, `git reset --hard`, `git clean -f` | As in the Spring harness |

Like the Spring guard it's advisory: a command it doesn't parse gets through, so `harness-integrity.yml` backs it up. The real boundary is IAM: developer sessions run under a read-only role in shared accounts. The skill says so, and the bootstrap step offers that role.

### Stop hook: gates on the session's changes

Runs when a turn ends and the session changed `*.tf`, `*.tftest.hcl`, `*.tfvars` or `policy/`. Blocks only on findings in files the session changed, as in the Spring harness. No AWS credentials needed.

1. `terraform fmt -check -recursive` (blocks; the hook can run `fmt` itself first)
2. `terraform init -backend=false` then `terraform validate` in each changed root and module
3. `tflint --recursive` with the AWS ruleset (no deep check: that needs credentials)
4. `checkov -d .` (or `trivy config .`), with the baseline file
5. `terraform test` for tests using `mock_provider` with `command = plan` (Terraform 1.7+; `override_during = plan` needs 1.11+)

Steps 4–5 take tens of seconds; skip code that already passed, give up after one failed retry on the same code, and log one JSON line per run to `.git/harness/events.jsonl` for `report.py`, as the Spring harness does.

### CI: gates that need credentials

Plan with a read-only OIDC role, then on the plan JSON: Checkov plan scan (cross-resource checks), the policy pack (step 9), Infracost diff as a PR comment. Apply only from `main`, behind an environment with reviewers, `cancel-in-progress: false`.

### Existing repositories: baseline

A repository full of findings can't go green on day one. `baseline.py` records today's findings (`checkov --create-baseline`, a dated `.trivyignore` entry per finding, policy exceptions in `policy/exceptions.json` with an expiry date) so new code is held to the gates while old findings stay listed. The integrity check fails a PR that adds to a baseline; removing fixed entries passes.

### Harness integrity check

Fails a PR that, from any tool: adds baseline entries or exceptions; adds inline skip or ignore comments; changes `.tflint.hcl`, `.checkov.yaml`, `policy/`, hooks, hook registrations or the workflows; removes `prevent_destroy`. Runs the base branch's copy of the check. A maintainer accepts an intended change with a `harness-rule-change` label.

### Decisions for you

1. **Plan policy engine.** Checkov custom checks (YAML graph checks or Python) keep one tool. OPA/Conftest is more expressive on plan JSON and is what most teams use for this, but it's a second tool and a second language (Rego). Recommendation: Checkov custom checks first; Conftest only if a rule can't be written there.
2. **OpenTofu.** Support both from the start (the commands match), or Terraform only?
3. **Other IaC.** CDK and SAM out of scope for the harness, with the guard refusing their deploy commands? Recommended.
4. **Sandbox apply in CI.** An ephemeral apply in a sandbox account per PR, with smoke checks and destroy, catches what plan can't (permissions, service limits). It costs money and a dedicated account. Offer it as an opt-in workflow, not a default.

## 9. Plan-level policy pack

Rules that read the plan JSON (`resource_changes` and `configuration`), each with a message that says how to fix it. These encode the skills, so they hold even when no skill loads.

| Area | Rule |
| --- | --- |
| Cost | Log group without `retention_in_days`; `retention_in_days = 0` in non-prod |
| Cost | Lambda or Fargate on x86_64 without a `harness:x86-reason` tag |
| Cost | `aws_nat_gateway` count per VPC > 1 in non-prod |
| Cost | `gp2` volume type |
| Cost | `associate_public_ip_address = true` / `assign_public_ip = true` on a task or instance in a private-subnet design |
| Cost | EKS `version` within 60 days of end of standard support (table kept in the pack, dated) |
| Cost | Missing required tags after `default_tags` merge (`tags_all`) |
| Reliability | `aws_lambda_event_source_mapping` from SQS without `function_response_types = ["ReportBatchItemFailures"]` |
| Reliability | SQS queue used by Lambda with `visibility_timeout_seconds` < 6 × function timeout |
| Reliability | Queue without a redrive policy; DLQ without an alarm |
| Reliability | Async-invoked function without an `on_failure` destination |
| Reliability | Stateful resource (RDS, DynamoDB, S3 with data, EFS) without `prevent_destroy` or deletion protection in prod |
| Security | IAM statement with `Resource = "*"` on a write action; `aws_lambda_permission` for a service principal without `source_arn` |
| Security | Function URL with `authorization_type = "NONE"` without a `harness:public-reason` tag |
| Currency | Deprecated Lambda runtime |
| Change safety | Plan deletes or replaces a stateful resource: fail unless the PR has a `destroy-approved` label |

Each rule gets a passing and a failing fixture under `tests/policy/`.

## 10. Harness sample and tests

Mirror `springboot-skills-marketplace/tests/harness-sample`: a small Terraform project (API Gateway → Lambda → SQS → Lambda → DynamoDB, plus one ECS service) with seeded violations, and `check.sh` that applies the harness, runs every gate in a Docker image with Terraform, TFLint, Checkov and Conftest pinned, and asserts each seeded violation is caught and each fix passes. Script tests for `apply_harness.py`, `baseline.py` and the guard (one case per refused command and one per allowed lookalike, such as `aws s3 ls` and `terraform plan -out`).

## Order of work and pull requests

1. PR: step 1 fixes.
2. PR: step 2 test results; delete scenarios that no longer fail.
3. PRs: steps 3, 4, 5, 6, 7, one skill each, each with two or three new RED/GREEN scenarios from the shortcuts listed here.
4. PR: harness core (step 8) without the policy pack, plus the sample (step 10).
5. PR: policy pack (step 9) and its fixtures.
6. PR: `verify-deployment` and the opt-in sandbox apply.

## Facts to recheck before writing them into a skill

These came from secondary sources or conflicted between sources:

- Lambda Managed Instances pricing example and whether multi-concurrency applies to every runtime.
- Durable functions: supported runtimes, maximum execution timeout, retention range, CMK support in Terraform.
- ECS native blue/green: when linear and canary arrived; Service Connect and VPC Lattice limits.
- SQS provisioned mode maximum pollers (2,000 or 10,000).
- Container Insights enhanced pricing.
- What Powertools Tracer uses after the X-Ray SDK's end of support.
- Which `Create*` actions support `aws:RequestTag` (reported missing for `s3:CreateBucket`).
- TFLint AWS deep-check configuration syntax in the current release.

## Sources

- [AWS Lambda standardizes billing for INIT phase](https://aws.amazon.com/blogs/compute/aws-lambda-standardizes-billing-for-init-phase)
- [Lambda tiered pricing for CloudWatch Logs and new destinations](https://aws.amazon.com/blogs/compute/aws-lambda-introduces-tiered-pricing-for-amazon-cloudwatch-logs-and-additional-logging-destinations)
- [Lambda Managed Instances docs](https://docs.aws.amazon.com/lambda/latest/dg/lambda-managed-instances.html) and [Lambda pricing](https://aws.amazon.com/lambda/pricing/)
- [Lambda quotas (durable functions)](https://docs.aws.amazon.com/lambda/latest/dg/gettingstarted-limits.md), [durable functions with IaC](https://docs.aws.amazon.com/lambda/latest/dg/durable-getting-started-iac.md), [CMKs for durable functions with Terraform](https://aws.amazon.com/blogs/compute/implementing-customer-managed-keys-for-aws-lambda-durable-functions-with-terraform/)
- [Serverless ICYMI Q4 2025](https://aws.amazon.com/blogs/compute/serverless-icymi-q4-2025)
- [SQS ESM provisioned mode](https://aws.amazon.com/about-aws/whats-new/2025/11/aws-lambda-provisioned-mode-sqs-esm) and [Compute Blog post](https://aws.amazon.com/blogs/compute/low-latency-high-throughput-sqs-event-processing-with-aws-lambda-provisioned-mode/)
- [Response streaming 200 MB](https://aws.amazon.com/about-aws/whats-new/2025/07/aws-lambda-response-streaming-200-mb-payloads)
- [X-Ray SDK migration to OpenTelemetry](https://docs.aws.amazon.com/fr_fr/xray/latest/devguide/xray-sdk-migration.html), [X-Ray with Lambda](https://docs.aws.amazon.com/xray/latest/devguide/xray-services-lambda.md)
- [ECS Managed Instances](https://docs.aws.amazon.com/AmazonECS/latest/developerguide/ManagedInstances.html), [ECS Express Mode announcement](https://aws-news.com/article/2025-11-21-announcing-amazon-ecs-express-mode), [ECS native blue/green](https://dev.to/t-kikuc/ecs-native-bluegreen-is-here-with-strong-hooks-and-dark-canary-8ff), [ECS Fargate cost checklist](https://aws.amazon.com/blogs/containers/cost-optimization-checklist-for-ecs-fargate)
- [EKS Capabilities](https://docs.aws.amazon.com/eks/latest/userguide/capabilities.html), [EKS pricing](https://aws.amazon.com/eks/pricing/), [Pod Identity vs IRSA](https://docs.rafay.co/blog/2024/10/03/pod-identity-versus-irsa-for-amazon-eks---part-1/)
- [Amazon VPC pricing charges](https://cloudburn.io/blog/amazon-vpc-pricing), [EKS hidden costs](https://www.perfectscale.io/blog/eks-pricing-components-hidden-costs-and-6-ways-to-optimize)
- [Terraform test mocking](https://developer.hashicorp.com/terraform/language/tests/mocking), [Terraform 1.14 query and list resources](https://dev.to/x4nent/terraform-114-the-complete-guide-to-list-resources-tfqueryhcl-actions-block-and-terraform-350j)
- [OPA on Terraform plans](https://scalr.com/learning-center/policy-enforcement-for-terraform-opentofu-with-opa-and-scalr/), [Guardrails for AI-generated IaC](https://dev.to/dc-shimla/guardrails-for-ai-generated-iac-how-mycoco-made-speed-sustainable-2f1k), [tfforge](https://github.com/Mrg77/tfforge)
- [ClickOps guide](https://towardsthecloud.com/blog/clickops), [noclickops](https://awesome.ecosyste.ms/projects/github.com%2Fsakisv%2Fnoclickops)
- [Tag governance with SCPs](https://copa.vinodaws.people.aws.dev/now-we-know/tagging-tag-governance/)
- [TFLint AWS ruleset rules](https://github.com/terraform-linters/tflint-ruleset-aws/blob/master/docs/rules/README.md)
- [HashiCorp Agent Skills](https://github.com/hashicorp/agent-skills), [Agent Toolkit for AWS](https://github.com/aws/agent-toolkit-for-aws), [AWS Labs MCP servers](https://awslabs.github.io/mcp/servers), [Billing and Cost Management MCP server](https://aws.amazon.com/about-aws/whats-new/2025/08/aws-billing-cost-management-mcp-server)
