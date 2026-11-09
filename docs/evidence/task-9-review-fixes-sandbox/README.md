# Final review fixes: sandbox evidence

Date: 2026-11-09. Account `123456789012` (the `personal` AWS profile), region `us-east-1`, local Terraform state. Template revision `1cf9fce+uncommitted`. Terraform 1.14.4, AWS provider 6.72.0.

The final review (Codex) and the Terraform conventions pass changed two behaviors that only AWS can confirm. This run deployed the `network` template, then `alb-ec2` by `network_name` only, then `apigw-step-functions`, each from a saved plan with provenance, and verified each one.

## What changed and what the run shows

| Change | Result | Log |
| --- | --- | --- |
| `alb-ec2` takes `network_name` or `subnet_ids`; no default VPC | `network_name = "lf-net-dev"` alone: 20 added; both instances in the `lf-net` subnets | `vm-04-plan.log`, `vm-07-apply.log`, `vm-08-instances.log` |
| `alb-ec2` launch template asks for a public address | Both instances got public IPv4 addresses (`13.218.208.105`, `32.192.194.193`), with the instance security group on the interface | `vm-08-instances.log` |
| — | Verify: every required check PASS; `healthy-hosts` in ALARM while the instances booted, as the runbook says | `vm-09-verify.log` |
| Step Functions logs no execution data; executions are named by correlation ID | Verify `PASS (pass 12, fail 0, unverified 4)`, exit 0: the log check finds each probe's events by its correlation ID | `flow-09-verify.log` |
| — | Two requests with the same `x-correlation-id`: both 200. Express accepts a repeated execution name | `flow-10-repeated-name.log` |
| — | 12 log events carry the correlation ID; none carries the order body | `flow-11-log-events.json` |
| Destroy and residue | 26, 20 and 19 destroyed; residue PASS for `lf-flow`, `lf-vm` and `lf-net`, with the account check from the review fix | `*-20-plan-destroy.log`, `*-21-destroy.log`, `*-22-residue.log` |

The first project check of `alb-ec2` failed on Checkov `CKV_AWS_88` (instance with a public IP), and the first check of `apigw-step-functions` on `CKV_AWS_285` (execution data not logged). Both are the intended result of a fix. Each is now a skip with its reason in the template's `.checkov.yaml`, and the checks passed after that (`vm-03-check.log`, `flow-03-check.log`).

## Not verified

- `ecs-web` was not deployed again. Its changes (the `network_name` or `subnet_ids` requirement, the IAM role name, and `build_image.sh`) are covered by the mocked tests and a `bash -n` check of the rendered script, not by a live build.
- `subnet_ids` from outside a `network` project, and a subnet that does not map public addresses by default. The launch template sets the address either way, but this run used `network` subnets, which map one.

## Cost and cleanup

The resources ran for about 30 minutes, with no NAT gateway, at a cost of well under a dollar. Nothing tagged `lf-flow`, `lf-vm` or `lf-net` is live.
