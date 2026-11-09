# Task 9: sandbox deployment evidence for `alb-ec2`

Date: 2026-11-09. Account `123456789012` (the `personal` AWS profile), region `us-east-1`, local Terraform state. Profile `alb-ec2.python3.13-arm64-ami`. Template revision `1cf9fce+uncommitted`. Terraform 1.14.4, AWS provider 6.72.0.

The deployment used the same local sequence as Task 6: saved plan, sanitized summary, provenance write and verify, apply of the saved plan. The group ran two `t4g.micro` instances in a temporary sandbox VPC (`fixture-sandbox-vpc.tf` in this folder), passed in as `subnet_ids`, because the account's default VPC has no internet gateway.

## Steps

| Step | Result | Log |
| --- | --- | --- |
| Network fixture: plan and apply | 7 added | `00-network-plan.log`, `00-network-apply.log` |
| Render, install, check | `harness check: PASS` | `01`–`03` |
| Plan, provenance, apply | 20 added; apply took 163 s | `04`–`07` |
| `verify_deployment.py verify` | all checks PASS except `alarms`: `healthy-hosts` in ALARM while the instances booted | `09-verify.log` |
| Mark one instance Unhealthy | replaced in 108 s; `/hello` answered 200 throughout | `10-replacement.log` |
| Verify after the replacement | PASS, every alarm OK | `11-verify-after-replacement.log` |
| Broken `app/`, no alarm on the refresh | refresh still `InProgress` after 40 minutes; stopped by hand | `12`–`15`, `23-rollback.log` |
| Add `alarm_specification` to the refresh | apply moved the launch template; refresh refused while the alarm was in ALARM | `24-*.log` |
| Broken `app/` again, with the alarm | alarm fired; refresh rolled back by itself in 433 s; `/hello` answered 200 throughout | `26-*.log`, `27-refresh-broken.log` |
| Verify after the rollback | FAIL, exit 1: instances not on version 4, `source_sha256` is not this checkout's `app/` | `28-verify-after-broken.log` |
| Restore `app/`: plan and apply | launch template version 5; refresh refused (`A CloudWatch monitor is in alarm`) | `29-*.log` |
| Start the refresh by hand | first command failed (see below); with `--desired-configuration`, `Successful` | `30-start-refresh-manual.log`, `31-refresh-manual-wait.log` |
| Verify after the restore | `PASS (pass 6, fail 0, unverified 2)`, exit 0 | `32-verify-restored.log` |
| Destroy from a saved destroy plan | 20 destroyed | `33-plan-destroy.log`, `34-destroy.log` |
| `verify_deployment.py residue` | FAIL: 24 instances and 11 volumes from the whole run; after the fix below, PASS | `35-residue.log`, `36-residue-rerun.log` |

The replacement script printed `probe 200000` and counted every probe as failed. curl wrote `200`, and a fallback appended `000`. Each probe answered 200.

The verifier proved these points against the live group:

- The credentials and the Terraform outputs point at the expected account and region.
- Every instance is InService and Healthy, on the group's launch template version and the expected AMI, and no refresh is running.
- Every registered target is healthy.
- `GET /hello` answers 200 and returns `source_sha256` equal to `source-hash` of this checkout's `app/`. The instance computes the hash itself.
- The log group has the request's line, found by its request ID.

## Findings for the template

- **A refresh without an alarm never fails.** New instances that never pass `/health` are replaced again and again. The refresh stayed `InProgress` for 40 minutes (`14-refresh-broken.log`). The template now gives the refresh `alarm_specification` with `unhealthy-hosts`. With the alarm, a broken refresh rolled back in about 7 minutes, and the load balancer kept serving the old instances.
- **A refresh cannot start while its alarm is in ALARM.** The apply still moves the group to the new launch template version. The next plan shows no change, so nothing restarts the refresh. The runbook says to start it by hand.
- **Manual refresh needs the target version.** `start-instance-refresh` with `AutoRollback: true` and no `DesiredConfiguration` fails: `The AutoRollback parameter cannot be set to true when the DesiredConfiguration parameter is empty`. The runbook command now passes the launch template ID and version, and the template outputs `launch_template_id`.
- **While a refresh runs, the group refuses updates** (`An active instance refresh with a desired configuration exists`, `16-apply-restore.log`). Roll back the refresh first.
- **`healthy-hosts` fires after the first deploy** while the instances boot, because it treats missing data as breaching. The runbook says so.
- **`unhealthy-hosts` can read OK and then refuse a refresh.** Twice, a wait for OK passed and the refresh start then failed with `A CloudWatch monitor is in alarm`. The alarm history shows it moving between OK and ALARM in that period.

## Finding for the verifier

The tag index still listed every instance and root volume the run had created, including the replaced ones. Each was terminated or deleted. The residue check now asks EC2: an instance that is `terminated` or `shutting-down`, or that `describe-instances` no longer returns, and a volume that `describe-volumes` reports as `InvalidVolume.NotFound`, are reported, not failed. A purged instance comes back as an empty `Reservations` list, not as an error.

## Not verified

- **Traces.** No response carried a trace ID.
- **Delivery to a person.** The alarm topic has no confirmed subscriber.
- **HTTPS.** The sandbox ran on plain HTTP; no certificate was available.
- **A new AMI.** Every refresh changed `app/`, not the AMI.
- `network_name` against a live network, the GitHub Actions path, other regions.

## Cost and cleanup

The group ran for about 3 hours, at a cost of well under a dollar. After destroy, nothing tagged `Project=lf-vm` is live. One KMS key is pending deletion until 2026-11-16. AWS does not bill keys in that state. The sandbox VPC was destroyed after the network template run (`docs/evidence/task-9-network-sandbox/17-fixture-destroy.log`).
