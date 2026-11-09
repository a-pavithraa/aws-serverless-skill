## Infrastructure harness

This section is written by the aws-iac-team-harness installer. Change it through the installer, not by hand.

**Done means the check passed.** Before you say a change is finished, run:

```bash
python harness/check.py .
```

Report its last line (`harness check: PASS|FAIL|UNVERIFIED ...`). `UNVERIFIED` is not a pass: a tool was missing, `terraform init` failed, or values could not be resolved. Say which, do not round it up.

| Check | Catches | Do not |
| --- | --- | --- |
| `fmt`, `validate` | formatting, invalid configuration | |
| `tflint` | deprecated runtimes, provider mistakes | add `# tflint-ignore` |
| `checkov` (per environment file) | missing retention, unauthenticated routes, wide IAM, functions without a managed log group or alarm | add `#checkov:skip`, edit `.checkov.yaml` or `harness/baseline.json` to get green |
| `terraform-test` | the root's own mocked tests | delete or weaken a `run` block |

Each finding names its fix. Fix the configuration; if a finding is wrong for this project, say so and leave the exception to a reviewer.

**Infrastructure changes are Terraform changes.** Do not create, change or delete AWS resources with the AWS CLI, console, SAM, CDK or SDK scripts. Read-only calls are fine.

**Do not run** `terraform apply`, `destroy`, `import`, `state rm|mv|push`, `force-unlock`, or any command with `-target`, `-auto-approve` or `-lock=false`. Apply runs in CI from the approved plan of the merged commit. Use `import {}`, `moved {}` and `removed {}` blocks instead of state commands.

**When a plan destroys or replaces anything**, list each address and why before you finish.

**Before you say a deployed change works**, run the verifier against the sandbox and paste its last line:

```bash
uv run --with boto3 python harness/verify_deployment.py verify . --profile <sandbox-profile> \
  --expect-account <id> --expect-region <region>
```

`UNVERIFIED` (exit 2) is not a pass: logs or evidence were missing. Exit 3 means the credentials or outputs point at another account or region; stop.

**Access denied is the boundary working.** Your AWS role is read-only (plus invoking sandbox functions). Do not look for another role or credentials.

Files the harness owns (`harness/`, this section) are listed in `harness/lock.json`. Do not edit them.

### Skills

When a request matches one of these, read the code it touches, then load the skill and follow it (the Skill tool in Claude Code, `$name` in Codex):

- A new AWS application or service: `creating-aws-projects`
- Terraform layout, state, IAM, KMS or CI pipelines: `terraform-aws`
- Lambda, API Gateway, SQS, SNS, EventBridge or Step Functions behavior: `aws-serverless`
- DynamoDB table design: `aws-dynamodb`
- These checks, a baseline, or verifying a deployment: `aws-iac-team-harness`
