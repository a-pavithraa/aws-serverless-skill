# Task 8: sandbox deployment evidence for `sqs-lambda-worker`

Date: 2026-11-09. Account `123456789012` (the `personal` AWS profile), region `us-east-1`, local Terraform state. Profile `sqs-lambda-worker.python3.13-arm64-zip`. Template revision `1cf9fce+uncommitted`. Terraform 1.14.4, AWS provider 6.72.0, Powertools layer 3.39.0 (version 42 of `AWSLambdaPowertoolsPythonV3-python313-arm64`).

The deployment used the same local sequence as Task 6: `plan -out`, sanitized summary, `plan_provenance.py write`, `plan_provenance.py verify`, `apply` of the saved plan.

## Cycle

| Step | Result | Log |
| --- | --- | --- |
| Render | profile PASS | `01-render.json` |
| `check_new_project.py` | `harness check: PASS (pass 9, fail 0, unverified 0)` | `03-check.log` |
| Plan | 16 to add, 0 to destroy | `04-plan.log`, `05-plan-summary.md` |
| Provenance write and verify | verified | `06-provenance.log` |
| Apply saved plan | 16 added | `07-apply.log` |
| `verify_deployment.py verify` | `verify-deployment: PASS (pass 8, fail 1, unverified 1)`, exit 0 | `08-verify.log` |
| Destroy from a saved destroy plan | 16 destroyed | `20-plan-destroy.log`, `21-destroy.log` |
| `verify_deployment.py residue` (first run) | FAIL: false positive, see below | `22-residue.log` |
| `verify_deployment.py residue` (after the fix) | PASS. The KMS key is scheduled for deletion on 2026-11-16. | `23-residue-rerun.log` |

The verifier proved these points against the live deployment:

- The credentials and the Terraform outputs point at the expected account and region.
- The deployed `CodeSha256` equals the local package, and the package equals `app/`.
- One order sent to the queue is logged as received once and processed once.
- The same order sent twice is logged as received twice and processed once. The DynamoDB idempotency record stops the second run.
- A message that always fails reaches the dead-letter queue with receive count 4 (`max_receive_count` 3, plus the receive that moved it). The verifier then deletes the probe message.

## Defects found only by the deployment

**The poison-message probe trips the Lambda error alarm.** When every record in a batch fails, Powertools raises `BatchProcessingError`, and Lambda counts the invocation as an error. The probe declared only `dlq-messages` as the alarm it trips, so the verifier reported `lf-sqs-dev-lambda-errors` as an unexpected FAIL. The `alarms` check is not required, so the exit code stayed 0.

Fix: `trips_alarm` now accepts a list, and the template probe declares `["dlq-messages", "lambda-errors"]`. Test `test_lambda_errors_from_the_poison_message_are_expected` went RED, then GREEN. The fix has not had a second live run.

**The residue check failed on a deleted event source mapping.** After destroy, the Resource Groups Tagging API still listed the event source mapping. Lambda returned `ResourceNotFoundException` for the same UUID, so the mapping was gone. The tag index lags behind the delete.

Fix: `residue` asks Lambda about each event source mapping that the tag index lists. A mapping that Lambda does not find is reported, not failed. A live mapping still fails. Tests `test_deleted_mapping_still_in_the_tag_index_is_reported_not_failed` (RED, then GREEN) and `test_live_mapping_left_after_destroy_fails` cover both cases.

## Not verified

- **The `dlq-messages` alarm in ALARM state.** At verify time the alarm had not reached ALARM. The metric arrives after the message, and the verifier did not wait for it.
- **Delivery to a person.** The alarm topic has no confirmed subscriber, so `alerting` is UNVERIFIED.
- **`oldest-message-age` firing**, and concurrency limits under load.
- **The GitHub Actions path**, other regions, and other runtimes or architectures.

## Cost and cleanup

The resources ran for about 15 minutes, at a cost of cents. After destroy, nothing tagged `Project=lf-sqs` is live. The KMS key is pending deletion until 2026-11-16. AWS does not bill keys in that state.
