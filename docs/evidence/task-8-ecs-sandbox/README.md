# Task 8: sandbox deployment evidence for `ecs-web`

Date: 2026-11-09. Account `123456789012` (the `personal` AWS profile), region `us-east-1`, local Terraform state. Profile `ecs-web.python3.13-arm64-container`. Template revision `1cf9fce+uncommitted`. Terraform 1.14.4, AWS provider 6.72.0, Docker 28.5.1 (`buildx`, `linux/arm64`).

The deployment used the same local sequence as Task 6 (saved plan, sanitized summary, provenance write and verify, apply of the saved plan), with the two-step first deploy from the template README: repository first, image push, then the service by digest.

## Attempt 1: default VPC without an internet gateway (`attempt-1-no-igw/`)

The account's default VPC has no attached internet gateway; its route table keeps `0.0.0.0/0 → igw-d4769bae` in state `blackhole`. With no `subnet_ids`, Express Mode tried to create an internet-facing load balancer there. CloudTrail shows `CreateLoadBalancer` failing every minute with `InvalidSubnetException: VPC vpc-bd239dc0 has no internet gateway`. The ECS service showed no events. Its deployment stayed `IN_PROGRESS` with 0 requested tasks. Terraform waited for its 30-minute create timeout (`10-apply-service.log`).

Fix: the template reads the default VPC's internet gateway with `data "aws_internet_gateway"` filtered on `attachment.vpc-id` and `attachment.state = available`. The plan now fails at once (`04-plan-default-vpc.log`):

```
Error: no matching EC2 Internet Gateway found
```

A first version of the check matched route tables with a route to `igw-*`. It passed against this account, because the blackhole route still names a gateway, so it was replaced.

Attempt 1 was destroyed (`attempt-1-no-igw/21`–`24`). The residue check then needed two fixes, both with tests: the tag index lists deleted ECS clusters, services and security group rules for a while, and Express Mode left one task definition `ACTIVE`. The template README's Remove section and the teardown now deregister and delete the task definitions.

## Attempt 2: the sandbox network fixture

Attempt 2 ran in a temporary sandbox VPC with an internet gateway and two public subnets (`docs/evidence/task-9-ec2-sandbox/fixture-sandbox-vpc.tf`; removed after the runs, replaced by the `network` template), applied from a reviewed saved plan (`docs/evidence/task-9-ec2-sandbox/00-network-*.log`).

| Step | Result | Log |
| --- | --- | --- |
| Render, install, check | `harness check: PASS (pass 9, fail 0, unverified 0)` | `01`–`03` |
| Plan against the default VPC | fails: `no matching EC2 Internet Gateway found` | `04-plan-default-vpc.log` |
| Plan and apply without the service | 13 added | `05-plan-repository.log`, `06-apply-repository.log` |
| Build and push the image | source hash `d46ef431…`, image `sha256:fcce5459…` | `07-build.log` |
| Plan the service, provenance, apply | 3 added; apply took 343 s | `08`–`11` |
| `verify_deployment.py verify` | `PASS (pass 6, fail 0, unverified 2)`, exit 0 | `13-verify.log` |
| Broken image: plan and apply | apply failed after 902 s | `14`–`16` |
| Service after the broken image | circuit breaker: `deployment failed: tasks failed to start`, rolled back | `17-service-after-broken.json` |
| Verify after the broken image | FAIL, exit 1: tasks run `fcce…`, Terraform says `50e8…` | `18-verify-after-broken.log` |
| Restore: plan and apply the good digest | 1 changed | `19-plan-restore.log`, `19-apply-restore.log` |
| Verify right after the restore | FAIL: `rollout not complete: PRIMARY=IN_PROGRESS, DRAINING=COMPLETED` | `19-verify-restored.log` |
| Verify a minute later | `PASS (pass 6, fail 0, unverified 2)`, exit 0 | `20-verify-restored-later.log` |
| Destroy from a saved destroy plan | 16 destroyed in 538 s | `final/21-plan-destroy.log`, `final/22-destroy.log` |
| `verify_deployment.py residue` | PASS after the ECS-task fix. Two KMS keys are scheduled for deletion on 2026-11-16. | `final/23-residue.log`, `final/24-residue-rerun.log` |

The verifier proved these points against the live service:

- The credentials and the Terraform outputs point at the expected account and region.
- Every running task runs the `image_digest` output, the rollout is complete, and running equals desired.
- Every registered target is healthy. Express Mode lists its target groups on the service revision, not on the service: a production group and an alternate that the canary shifts traffic to. The first verify (`13-verify-before-revision-fix.log`) failed `health` for that reason; the verifier now reads both groups from the revision.
- `GET /hello` answers 200, echoes the correlation ID, and returns `source_sha256` equal to `source-hash` of this checkout's `app/`.
- The log group has the request's line, found by its correlation ID.

A deliberately broken image (a container that exits at start) never served traffic. ECS's circuit breaker rolled back, and `/hello` kept answering from the good image. The apply failed, which is the signal a pipeline needs. The verifier then failed on the digest, because Terraform's state named the broken image.

## Findings for the template

- Without an attached internet gateway, Express Mode fails silently. The plan-time check is the only clear signal.
- `wait_for_steady_state` returns before the canary's old tasks finish draining. A verify right after apply can report `rollout not complete`; the README says to wait and run it again.
- Express Mode registers task definitions that Terraform does not own and the service's deletion leaves behind.
- Express Mode creates its own deployment alarm; ECS showed `alarms: DISABLED` on the deployment and used the circuit breaker to roll back.

## Not verified

- **Traces.** No response carried a trace ID.
- **Delivery to a person.** The alarm topic has no confirmed subscriber.
- **Private subnets and an internal load balancer**, `network_name` against a live network, the GitHub Actions path, other regions.

## Cost and cleanup

The service ran for about 2 hours in total across both attempts, at a cost of well under a dollar. After destroy, nothing tagged `Project=lf-web` is live. The two KMS keys are pending deletion until 2026-11-16. AWS does not bill keys in that state.
