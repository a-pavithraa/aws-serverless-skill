# Task 9: sandbox deployment evidence for `apigw-step-functions`

Date: 2026-11-09. Account `123456789012` (the `personal` AWS profile), region `us-east-1`, local Terraform state. Profile `apigw-step-functions.asl-jsonpath-managed-definition`. Template revision `1cf9fce+uncommitted`. Terraform 1.14.4, AWS provider 6.72.0. The account already had the API Gateway CloudWatch role that stage logging needs.

The deployment used the same local sequence as Task 6: `plan -out`, sanitized summary, `plan_provenance.py write`, `plan_provenance.py verify`, `apply` of the saved plan.

## Cycle

| Step | Result | Log |
| --- | --- | --- |
| Render | profile PASS | `01-render.json` |
| `check_new_project.py` | `harness check: PASS (pass 8, fail 0, unverified 0)` | `03-check.log` |
| Plan | 26 to add, 0 to destroy | `04-plan.log`, `05-plan-summary.md` |
| Provenance write and verify | verified | `06-provenance.log` |
| Apply saved plan | 26 added | `07-apply.log` |
| `verify_deployment.py verify` (first) | FAIL: every probe 500, see below | `08-verify-first.log` |
| Fix: plan and apply | 1 added, 2 changed, 1 destroyed | `09-plan-trust-fix.log`, `10-apply-trust-fix.log` |
| `verify_deployment.py verify` | `verify-deployment: PASS (pass 12, fail 0, unverified 4)`, exit 0 | `11-verify.log` |
| Destroy from a saved destroy plan | 26 destroyed | `20-plan-destroy.log`, `21-destroy.log` |
| `verify_deployment.py residue` | PASS. The KMS key is scheduled for deletion on 2026-11-16. | `22-residue.log` |

The verifier proved these points against the live deployment:

- The credentials and the Terraform outputs point at the expected account and region.
- The deployed state machine is `EXPRESS`, `ACTIVE`, and its definition equals `workflow/definition.asl.json`.
- An order that the workflow processes answers 200 with `order_id`, `status` and `correlation_id`.
- An order that the workflow rejects answers 422, not 200.
- An order that runs past `TimeoutSeconds` answers 504, not 200 and not API Gateway's own timeout.
- Every response carries the caller's `x-correlation-id`.
- An unsigned request answers 403 for each probe.
- The workflow log group has events for each request, found by its correlation ID.
- The timeout probe put `api-5xx` in ALARM, as the probe declares.

## Defect found only by the deployment

Every probe got `500 {"message": "Internal server error"}`. A test invocation showed the cause:

```
Execution failed due to configuration error: API Gateway does not have permission to assume the provided role arn:aws:iam::123456789012:role/lf-flow-dev-api
```

The trust policy of the integration's credentials role had an `aws:SourceAccount` condition. API Gateway does not send that key when it assumes an integration role. The fix removes the condition from that one trust policy; the Step Functions role keeps it. Mocked tests cannot see IAM trust evaluation, so no test covers this; the sandbox run is the check.

## Not verified

- **Traces.** The response template sets `x-trace-id` from `$context.xrayTraceId`, but no response carried it, so the verifier could not look the traces up. The trace checks are reported only, not required.
- **`executions-timed-out` in ALARM.** It was still `OK` when the verifier read it. The metric arrives after the response.
- **Delivery to a person.** The alarm topic has no confirmed subscriber.
- **The GitHub Actions path**, other regions, and `auth_mode = "none"` against a live API.

## Cost and cleanup

The resources ran for about 20 minutes, at a cost of cents. After destroy, nothing tagged `Project=lf-flow` is live. The KMS key is pending deletion until 2026-11-16. AWS does not bill keys in that state.
