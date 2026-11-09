# AWS skills for coding agents

Skills for Claude Code and Codex that create AWS applications in Terraform from tested templates, install the checks every agent and developer must pass, and give current guidance for Lambda, API Gateway, DynamoDB and Terraform.

## Install

```bash
git clone https://github.com/a-pavithraa/aws-serverless-skill.git
cd aws-serverless-skill
python3 install.py            # Claude Code
python3 install.py --codex    # Codex
```

The script needs Python 3.10 or later. You can run it again safely. For Claude Code, it adds this marketplace, installs the plugin at user scope and turns on auto-update. For Codex, it copies the skill folders into `~/.codex/skills` and replaces only the folders that it copied before.

Without the script, in Claude Code:

```
/plugin marketplace add a-pavithraa/aws-serverless-skill
/plugin install aws-infrastructure-skills@aws-serverless-skill
```

## Skills

### `creating-aws-projects`

Creates a new AWS application from a tested Copier template. Each template has a small working application, Terraform, scoped IAM, logs with retention, alarms, a dashboard, a runbook, mocked Terraform tests and the probes that the deployment verifier sends.

| Pattern | Status |
| --- | --- |
| `apigw-lambda` (HTTP API, Lambda Python 3.13 on arm64) | Template exists. Verified in a sandbox account (`docs/evidence/task-6-sandbox`). The profile stays `candidate` until a person reviews the evidence. |
| `sqs-lambda-worker` (SQS queue, dead-letter queue, Lambda Python 3.13 on arm64, Powertools batch and idempotency) | Template exists. Verified in a sandbox account (`docs/evidence/task-8-sqs-sandbox`). The profile stays `candidate` until a person reviews the evidence. |
| `ecs-web` (ECS Express Mode, Fargate arm64, Python 3.13 container) | Template exists. Sandbox evidence: `docs/evidence/task-8-ecs-sandbox`. The profile stays `candidate` until a person reviews the evidence. |
| `apigw-step-functions` (REST API, synchronous Express workflow) | Template exists. Sandbox evidence: `docs/evidence/task-9-sfn-sandbox`. The profile stays `candidate` until a person reviews the evidence. |
| `network` (VPC from `terraform-aws-modules/vpc`, own state, subnet IDs in SSM) | Template exists. Sandbox evidence: `docs/evidence/task-9-network-sandbox`. The profile stays `candidate` until a person reviews the evidence. |
| `alb-ec2` (Application Load Balancer, Auto Scaling group, AL2023 arm64, Python 3.13) | Template exists. Sandbox evidence: `docs/evidence/task-9-ec2-sandbox`. The profile stays `candidate` until a person reviews the evidence. |

The skill renders only runtime profiles that pass the gate in `scripts/profiles.py`. `scripts/render.py` refuses an existing directory. `scripts/check_new_project.py` checks the result.

### `aws-iac-team-harness`

Installs checks into a Terraform repository with `scripts/apply_harness.py`. A rerun updates only the files that nobody edited.

| Script | What it does |
| --- | --- |
| `check.py` | Runs `fmt`, `init`, `validate`, `tflint`, `checkov` (once for each `envs/*.tfvars`) and `terraform-test` on each Terraform root. Reports PASS, FAIL or UNVERIFIED for each check. A missing tool is never a pass. |
| `baseline.py` | Records the findings that a repository already has, each with an owner, a reason and an expiry date. New findings still fail. |
| `plan_summary.py` | Summarizes `terraform show -json` without attribute values, and flags stateful resources that are destroyed or replaced. |
| `plan_provenance.py` | Binds a saved plan to its commit, account, region, root, backend and Terraform version. The apply job refuses the plan if any of them changed. |
| `verify_deployment.py` | Checks a deployment: target, deployed code hash, signed and unsigned probes, logs by request ID, then traces, alarms and alerting. |

Custom Checkov checks exist only where no upstream check covers the requirement. `references/coverage.md` lists each one with the test that proves it.

### `terraform-aws`

Guidance for Terraform on AWS: module layout, state, IAM, KMS, secrets and CI pipelines.

### `aws-serverless`

Guidance for Lambda, API Gateway, SQS, SNS, EventBridge and Step Functions: cold starts and INIT billing, concurrency, runtimes, Powertools and tracing, alarms and payload limits.

### `aws-dynamodb`

Guidance for DynamoDB data modeling: access patterns, keys, indexes, hot partitions, capacity mode and cost.

## Test

```bash
uv run --no-project --with copier==9.19.1 --with pyyaml python -m unittest discover -s tests/scripts
```

The suite needs Terraform, TFLint 0.65.0 and Checkov 3.4.3 on PATH, and network access for `terraform init`. Set `GITHUB_TOKEN` so that `tflint --init` does not hit the GitHub rate limit. The suite runs about 15 minutes, because each check test renders a project and runs every tool on it. Run one suite at a time: the Terraform plugin cache is not safe for concurrent use.

`tests/fixtures/triggering/run.py` checks that each skill loads for the prompts it should answer. `tests/baseline-scenarios.md` holds the agent scenarios. See `tests/README.md`.

## Design rules

- **No common knowledge.** Each section has something that a model does not produce correctly without it.
- **Rules that can fail a build are checks, not prose.** The harness fails the build. The skills explain why.
- **Cite sources.** Facts carry a link and the date someone verified them. `tests/scripts/test_docs.py` fails on a verification date older than one year.

## Credits

- DynamoDB modeling patterns: [Alex DeBrie](https://www.alexdebrie.com/), author of [The DynamoDB Book](https://www.dynamodbbook.com/)
- Serverless and Lambda patterns: [Yan Cui (theburningmonk)](https://theburningmonk.com/)
