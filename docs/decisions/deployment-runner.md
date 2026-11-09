# Decision: deployment runner and plan provenance

Date: 2026-11-08. Plan Task 5.

## Decision

Integrate an existing runner when the project has one. Ship a GitHub Actions reference (`skills/aws-iac-team-harness/assets/project/.github/workflows/`) only for projects without one.

- **Atlantis / HCP Terraform / Spacelift teams:** keep the runner. Call `harness/check.py` in its pre-plan stage, `harness/plan_summary.py` on `terraform show -json` output for the PR comment, and the Checkov plan scan with `--external-checks-dir harness/checkov` in its policy stage. Do not install `terraform-deploy.yml` alongside it: two apply paths for one state is the failure this avoids.
- **No runner:** install both reference workflows.

## Reference flow

| Stage | Trigger | Credentials | What it does |
| --- | --- | --- | --- |
| `harness-checks` | every PR, push to main | none (`contents: read`) | `python harness/check.py .` |
| `terraform-deploy` / plan | push to `main` only (jobs also guarded by `if: github.ref == 'refs/heads/main'`) | `AWS_PLAN_ROLE_ARN` via OIDC | `init -lockfile=readonly`, `plan -out=tfplan`, sanitized summary to the job summary, Checkov plan scan, `plan_provenance.py write`, upload `tfplan` + `plan-meta.json` (1-day retention) |
| `terraform-deploy` / apply | after plan, waits for environment approval | `AWS_APPLY_ROLE_ARN` via OIDC | download, `plan_provenance.py verify` (commit, account, region, root, environment, Terraform version, backend, SHA-256), `apply tfplan` |

Workflow-level `concurrency: terraform-state-<env>` with `cancel-in-progress: false` serializes runs per state; a newer pending run replaces an older pending one, never an in-progress apply. State locking stays on (no `-lock=false`). If state changed after the plan, Terraform refuses the saved plan as stale: push again (or re-run) to plan and approve anew.

PR code never receives credentials: no `pull_request_target`, and the deploy workflow has no PR trigger. Plans run only on merged commits, so provider and data-source code that executes during plan is reviewed code.

## Settings the YAML cannot enforce (administrator checklist)

1. Branch protection on `main`: required review, required `harness-checks`, no force-push.
2. Environment `<env>` with required reviewers; prevent self-review; restrict to the `main` branch.
3. Plan role trust: `token.actions.githubusercontent.com:sub` = `repo:<org>/<repo>:ref:refs/heads/main`, `aud` = `sts.amazonaws.com`. Permissions: read-only on resources, read on state, read/write on the state lock object (S3 `use_lockfile`).
4. Apply role trust: `sub` = `repo:<org>/<repo>:environment:<env>`. The agent's own role must not be able to assume it.
5. Repository variables: `AWS_PLAN_ROLE_ARN`, `AWS_APPLY_ROLE_ARN`, `AWS_REGION`, optionally `TF_ROOT`, `TF_ENVIRONMENT`.
6. Repository visibility: the `tfplan` artifact contains attribute values (Terraform plans are not redacted). Keep the repository private, or replace the artifact with an encrypted store before using this on a public repository.

## Evidence status

Tested: `tests/scripts/test_ci.py` checks the workflow properties above statically and covers the summary (no values printed, destructive and stateful changes flagged, known-after-apply attributes listed) and provenance verification (each fact mismatch and a modified plan refused).

**UNVERIFIED:** no GitHub repository, environment or OIDC roles exist for this work, so the workflows have not run, and items 1–6 have not been exercised. A real run on a sandbox repository is required before claiming the CI path works. Task 6's sandbox deploy runs the same sequence locally (plan `-out`, summary, provenance write/verify, apply saved plan).
