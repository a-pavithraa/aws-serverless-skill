# Task 6: sandbox deployment evidence for `apigw-lambda`

Date: 2026-11-08. Account `123456789012` (the `personal` AWS profile), region `us-east-1`, local Terraform state. Profile `apigw-lambda.python3.13-arm64-zip`. Template revision `1cf9fce+uncommitted`. Terraform 1.14.4, AWS provider 6.72.0.

The deployment followed the same sequence as the reference workflow, run locally: `plan -out`, sanitized summary, `plan_provenance.py write`, `plan_provenance.py verify`, `apply` of the saved plan. No GitHub run took place (see `docs/decisions/deployment-runner.md`).

## Final template: clean cycle (`final/`)

| Step | Result | Log |
| --- | --- | --- |
| Render | profile PASS | `final/01-render.json` |
| `check_new_project.py` | `harness check: PASS (pass 9, fail 0, unverified 0)` | `final/03-check.log` |
| Plan | 18 to add, 0 to destroy | `final/04-plan.log`, `final/05-plan-summary.md` |
| Provenance write and verify | verified | `final/06-provenance.log` |
| Apply saved plan | 18 added | `final/07-apply.log` |
| `verify_deployment.py verify` | `verify-deployment: PASS (pass 7, fail 0, unverified 1)`, exit 0 | `final/08-verify.log` |
| Alarm action (forced ALARM state) | `Successfully executed action arn:aws:sns:...:lf-sandbox-dev-alarms` | `final/09-alarm-action.log` |
| Destroy from a saved destroy plan | 18 destroyed | `final/10-plan-destroy.log`, `final/11-destroy.log` |
| `verify_deployment.py residue` | PASS. Two KMS keys are scheduled for deletion on 2026-11-15. | `final/12-residue.log` |

The verifier proved these points against the live deployment:

- The credentials and the Terraform outputs point at the expected account and region.
- The deployed `CodeSha256` equals the local package, and the package equals `app/`.
- A signed request returns 200 with the correlation ID echoed.
- An unsigned request returns 403.
- The function log has an event for the request ID that carries the correlation ID.
- X-Ray has the request's trace.

## Failure cases on the first sandbox (files `01` to `19`)

| Case | Exit | Result | Log |
| --- | --- | --- | --- |
| Healthy deployment | 0 | all required checks PASS | `05-verify-healthy.log` |
| Expected region `eu-west-1` | 3 | target FAIL, no request sent | `06-verify-wrong-target.log` |
| Expected account `000000000000` | 3 | target FAIL, no request sent | `06-verify-wrong-target.log` |
| Log wait 0 s | 2 | `logs:hello` UNVERIFIED, not PASS | `07-verify-no-log-wait.log` |
| Handler that raises (deployed) | 1 | `probe:hello` FAIL with status 500 | `09-verify-broken.log` |
| Good handler in `app/`, broken one still deployed | 1 | `artifact` FAIL with the two hashes | `11-verify-stale-artifact.log` |
| Good handler deployed again | 0 | required checks PASS. The alarms from the seeded failure are reported, but they do not decide the exit code. | `13-verify-restored.log` |

The rebuilt package had the same SHA-256 as the first deployment (`s+KwjjCT…`). `archive_file` packaging is reproducible.

## Defect found only by the deployment

The first template encrypted the alarm topic with the AWS managed key `alias/aws/sns`. Checkov's `CKV_AWS_26` passes that setting. When the seeded failure fired the alarms, CloudWatch could not publish:

```
"error": "CloudWatch Alarms does not have authorization to access the SNS topic encryption key."
```

(`14-alarms-fired.log`). No mocked test, static check or plan showed the problem.

The fix:

- The template now creates a customer managed key for the alarm topic. The key policy lets `cloudwatch.amazonaws.com` use the key, with an `aws:SourceAccount` condition.
- A new harness check, `HARNESS_AWS_3`, fails an alarm topic that uses `alias/aws/sns`. It has a seeded-fault test and a false-positive test.

After the fix, the alarm action ran successfully (`16-alarm-action-after-fix.log`, `final/09-alarm-action.log`). The key policy is written inline on `aws_kms_key`. As an `aws_iam_policy_document`, Checkov's identity-policy checks (`CKV_AWS_109`, `CKV_AWS_111`, `CKV_AWS_356`) flagged `Resource: "*"`. In a key policy, `"*"` means the key itself.

## Not verified

- **Delivery to a person.** The topic has no confirmed subscriber. An email subscription needs a person to click the confirmation link. The verifier reports `alerting` as UNVERIFIED.
- **The GitHub Actions path** (OIDC roles, environment approval, artifact handoff).
- **Regions other than `us-east-1`, and other runtimes or architectures.**

## Cost and cleanup

The resources ran for about 45 minutes in total, at a cost of cents. After both destroys, nothing tagged `Project=lf-sandbox` is live. The two KMS keys are pending deletion until 2026-11-15. AWS does not bill keys in that state.
