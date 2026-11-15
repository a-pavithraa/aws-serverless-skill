# Deployment workflows

## Pick the runner

- **The project already deploys through Atlantis, HCP Terraform, Spacelift or another runner:** keep that runner. Call `harness/check.py` in its pre-plan stage, `harness/plan_summary.py` on the `terraform show -json` output for the pull request comment, and the Checkov plan scan with `--external-checks-dir harness/checkov` in its policy stage. Do not install `terraform-deploy.yml` next to it: two apply paths for one state is the failure this avoids.
- **The project has no runner:** install both reference workflows with `apply_harness.py --workflows`.

## What the reference workflows do

| Stage | Trigger | Credentials | What it does |
| --- | --- | --- | --- |
| `harness-checks` | every pull request, push to `main` | none (`contents: read`) | `python harness/check.py .` |
| `terraform-deploy`, plan | push to `main` only; the jobs also check `github.ref == 'refs/heads/main'` | `AWS_PLAN_ROLE_ARN` through OIDC | `init -lockfile=readonly`, `plan -out=tfplan`, the sanitized summary in the job summary, the Checkov plan scan, `plan_provenance.py write`, then upload `tfplan` and `plan-meta.json` with 1-day retention |
| `terraform-deploy`, apply | after the plan, when the environment's reviewer approves | `AWS_APPLY_ROLE_ARN` through OIDC | download, `plan_provenance.py verify` (commit, account, region, root, environment, Terraform version, backend, SHA-256), `apply tfplan` |

- `concurrency: terraform-state-<env>` with `cancel-in-progress: false` runs one deployment per state at a time. A newer pending run replaces an older pending one. It never cancels an apply in progress.
- State locking stays on. If the state changed after the plan, Terraform refuses the saved plan as stale. Push again, or re-run, to plan and approve again.
- Pull request code never gets credentials. There is no `pull_request_target`, and the deploy workflow has no pull request trigger. Plans run only on merged commits, so the provider and data-source code that runs during a plan has been reviewed.

## Administrator checklist

The YAML cannot enforce these settings. Go through them with the user before you say the workflows are ready.

1. **Branch protection on `main`:** required review, required `harness-checks`, no force-push.
2. **Environment `<env>`:** required reviewers, self-review prevented, deployments only from `main`.
3. **Plan role trust:** `token.actions.githubusercontent.com:sub` = `repo:<org>/<repo>:ref:refs/heads/main` and `aud` = `sts.amazonaws.com`. Permissions: read-only on resources, read on the state, and read and write on the state lock object (S3 `use_lockfile`).
4. **Apply role trust:** `sub` = `repo:<org>/<repo>:environment:<env>`. The agent's own role must not be able to assume it.
5. **Repository variables:** `AWS_PLAN_ROLE_ARN`, `AWS_APPLY_ROLE_ARN`, `AWS_REGION`, and optionally `TF_ROOT` and `TF_ENVIRONMENT`.
6. **Repository visibility:** the `tfplan` artifact holds attribute values, because Terraform does not redact plans. Keep the repository private, or replace the artifact with an encrypted store before you use the workflow on a public repository.

## Probe through a rollout

`verify_deployment.py verify` fails while a rollout is in progress. `verify_deployment.py watch-rollout` is for that window: started next to the apply, it waits for the rollout to start (`--start-wait`, default 300 s), sends the HTTP probes from `.verify/probes.json` once every `--interval` (default 5 s) until the rollout ends or `--timeout` (default 1800 s, at most 3600 s), then sends one more round.

| Result | PASS | FAIL | UNVERIFIED |
| --- | --- | --- | --- |
| `rollout` | the rollout started and completed | ECS `rolloutState` `FAILED`; an instance refresh `Failed`, `Cancelled`, `RollbackFailed` or `RollbackSuccessful` | no rollout started within `--start-wait`, or still running at `--timeout` |
| `rollout-probes` | every request answered as the probe expects | any request failed, including a dropped connection | no request sent |
| `rollout-overlap` (reported) | two or more `source_sha256` values answered: old and new together, the expected overlap | | one value throughout |
| `rollout-result` | after the rollout every answer is this checkout's `app/` | the service answers other source: rolled back, or another commit deployed | |

The report lists each `instance` and `source_sha256` value that answered and how often. During the rollout the source hash is recorded, not required; after it, `rollout-result` requires it for probes with `expect_source_hash`.

How the rollout state is read. Check the field names against the current documentation before relying on them in another tool:

- **Standard ECS rolling deployments and Express Mode:** `DescribeServices` → `deployments[]`. `rolloutState` is `IN_PROGRESS`, `COMPLETED` or `FAILED` ("only returned for services that use the rolling update (`ECS`) deployment type that aren't behind a Classic Load Balancer"); `status` is `PRIMARY` for the newest deployment ([Deployment](https://docs.aws.amazon.com/AmazonECS/latest/APIReference/API_Deployment.html), verified 2026-11-15). The watch counts a rollout as complete when one deployment is left and it is `COMPLETED`. Express Mode deploys as a canary: 5 % of traffic to the new tasks, 3 minutes of bake time, then 100 %, then old tasks stop after another 3 minutes ([Updating an Express Mode service](https://docs.aws.amazon.com/AmazonECS/latest/developerguide/express-service-update-full.html), verified 2026-11-15). The `ecs-web` sandbox run (`docs/evidence/task-8-ecs-sandbox`, 2026-11-09) showed the old deployment as `DRAINING`, a status the API reference does not list, and a circuit-breaker rollback as `PRIMARY=IN_PROGRESS` that later completes on the old image; `rollout-result` catches that case through the source hash. `DescribeServiceDeployments` reports blue/green and canary stages (`lifecycleStage`, `status` such as `ROLLBACK_SUCCESSFUL`; [ServiceDeployment](https://docs.aws.amazon.com/AmazonECS/latest/APIReference/API_ServiceDeployment.html), verified 2026-11-15); the watch does not read it yet.
- **Auto Scaling instance refresh:** `DescribeInstanceRefreshes`, newest first. `Pending`, `InProgress`, `Baking`, `Cancelling` and `RollbackInProgress` are in progress; `Successful` is complete; the rest are failures ([InstanceRefresh](https://docs.aws.amazon.com/autoscaling/ec2/APIReference/API_InstanceRefresh.html), verified 2026-11-15).

A workflow runs it in the background of the apply step, with the same read-only role the verify uses, and fails the job on its exit code after the apply:

```bash
python harness/verify_deployment.py watch-rollout . --expect-account "$ACCOUNT" --expect-region "$AWS_REGION" \
  --json > rollout.json & WATCH=$!
terraform -chdir=infra apply tfplan
wait "$WATCH"
```

The watch reads `terraform output` when it starts, so it needs a service that already exists: not the first deploy. The reference `terraform-deploy.yml` does not run it. Wiring it in needs boto3 and read permissions for ECS, Auto Scaling and the load balancer in the apply job, and a run against a real rollout to show it works; neither exists yet, so the workflow is unchanged.

**Status:** `watch-rollout` and the repeated probes (`repeat`, `expect_distinct`, `expect_same`) are unit-tested with fakes (`tests/scripts/test_verification.py`). They have not run against a sandbox account.
