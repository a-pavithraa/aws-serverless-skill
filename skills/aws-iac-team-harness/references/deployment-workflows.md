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
