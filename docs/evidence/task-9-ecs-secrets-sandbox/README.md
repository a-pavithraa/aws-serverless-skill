# ECS secrets pattern: sandbox evidence

Date: 2026-11-09. Account `123456789012` (the `personal` AWS profile), region `us-east-1`, local Terraform state. Template revision `1cf9fce+uncommitted`. Terraform 1.14.4, AWS provider 6.72.0, Docker 28.5.1.

The run deployed the `network` template, then `ecs-web` with `secret_names = "DB_PASSWORD,API_TOKEN"` and `network_name = "lf-net-dev"`, each from a saved plan with provenance.

## Steps

| Step | Result | Log |
| --- | --- | --- |
| Network: check, plan, apply | `harness check: PASS`; 19 added | `net-*` |
| `ecs-web`: check | `harness check: PASS (pass 9, fail 0, unverified 0)` | `web-03-check.log` |
| Plan and apply without a digest | 14 added, including the secret `lf-web-dev/app` without a value | `web-04-*` |
| Set the value with `put-secret-value` | one version; the JSON file was deleted after | `web-05-put-secret.log` |
| `bash build_image.sh` | digest `sha256:58c1a415…` | `web-06-build.log` |
| Plan and apply with the digest | 3 added; apply took 293 s | `web-07-*` |
| `verify_deployment.py verify` | `PASS (pass 6, fail 0, unverified 2)`, exit 0. The probe's `expect_json` required `secrets_loaded = ["DB_PASSWORD", "API_TOKEN"]` | `web-08-verify.log` |
| Task definition | `secrets` holds the two `valueFrom` references; `environment` holds only `SECRET_NAMES` | `web-09-task-definition.json` |
| Where the values appear | not in the task definition, not in `terraform.tfstate`, not in the `/hello` response | `web-09-task-definition.json`, `web-10-hello.json` |
| Secret without the `API_TOKEN` key, then a forced deployment | the new task stopped: `TaskFailedToStart ResourceInitializationError: unable to pull secrets or registry auth: ... did not contain json key API_TOKEN`. The old task kept answering 200 | `web-11-missing-key.log` |
| Destroy and residue | images deleted; 17 and 19 destroyed; task definitions removed; residue PASS for `lf-web` and `lf-net`. The secret is reported as `deletion requested`; Secrets Manager keeps it 7 days | `*-20-plan-destroy.log`, `*-21-destroy.log`, `*-23-residue.log` |

The stopped reason matches the runbook's entry "A task that cannot read its secret".

## Findings

- `aws ecs describe-services` does not name the task definition of an Express Mode service. Read it from a running task (`describe-tasks`, `taskDefinitionArn`). The verifier already reads digests from the tasks.

## Not verified

- Rotation: the template has none (Checkov `CKV2_AWS_57` is skipped with its reason). The runbook rotates by hand.
- A customer managed KMS key on the secret (`CKV_AWS_149` is skipped with its reason).

## Cost and cleanup

The service ran for about 25 minutes, at a cost of well under a dollar. Nothing tagged `lf-web` or `lf-net` is live. The secret and three KMS keys are pending deletion; AWS bills neither in that state.
