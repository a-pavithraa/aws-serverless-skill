# Decision: deployment runner and plan provenance

Date: 2026-11-08. Plan Task 5.

## Decision

Integrate an existing runner when the project has one. Ship a GitHub Actions reference (`skills/aws-iac-team-harness/assets/project/.github/workflows/`) only for projects without one.

- **Atlantis / HCP Terraform / Spacelift teams:** keep the runner. Call `harness/check.py` in its pre-plan stage, `harness/plan_summary.py` on `terraform show -json` output for the PR comment, and the Checkov plan scan with `--external-checks-dir harness/checkov` in its policy stage. Do not install `terraform-deploy.yml` alongside it: two apply paths for one state is the failure this avoids.
- **No runner:** install both reference workflows.

## Reference flow and administrator checklist

The stages, their credentials and the six settings the YAML cannot enforce are in `skills/aws-iac-team-harness/references/deployment-workflows.md`, so that an installed skill carries them.

## Evidence status

Tested: `tests/scripts/test_ci.py` checks the workflow properties above statically and covers the summary (no values printed, destructive and stateful changes flagged, known-after-apply attributes listed) and provenance verification (each fact mismatch and a modified plan refused).

**UNVERIFIED:** no GitHub repository, environment or OIDC roles exist for this work, so the workflows have not run, and the administrator checklist has not been exercised. A real run on a sandbox repository is required before claiming the CI path works. Task 6's sandbox deploy runs the same sequence locally (plan `-out`, summary, provenance write/verify, apply saved plan).
