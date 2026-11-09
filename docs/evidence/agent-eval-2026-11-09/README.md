# Agent runs with and without the skills: 2026-11-09

Sonnet on Claude Code 2.1.319, headless (`claude -p`), run by `agent_eval.py` in this folder. No AWS credentials: the AWS config and credentials files pointed to an empty file. User settings and installed plugins were not loaded. Each arm ran twice.

The working folders, session streams and check logs were in `D:/pills-ai/eval/`. Another process deleted that folder the same evening, so only the numbers below remain. Re-run the prompts in this folder to reproduce them.

## Tool access

A safety check refused sessions with unrestricted Bash. The sessions had the file tools and these Bash rules: `terraform fmt`, `init`, `validate`, `test` and `-chdir=*`; `cd`, `ls` and `cat`; and `python` only for `profiles.py`, `check_new_project.py`, `apply_harness.py`, `check.py` and the Copier `render.py` command. PowerShell was disallowed. A command outside these rules waited for an approval that never came.

## 1. The Kiro project with and without the harness

`D:\ivr\agent-desktop-app-infra` was copied twice. One copy got `apply_harness.py`. The original was not changed.

| | Without the harness | With the harness |
| --- | --- | --- |
| Checks a developer or agent runs | `terraform fmt` and `validate`: both pass | `harness/check.py`: FAIL (pass 3, fail 2, unverified 1), 207 s |
| TFLint | not run | `terraform_unused_declarations`: `data.aws_subnet.private` is never used. A real finding |
| Checkov | not run | 6 findings. `CKV2_AWS_5` (the security group is attached through a local) and `CKV2_AWS_23` (alias to an external load balancer) are false positives. `CKV_AWS_136`, `CKV_AWS_65`, `CKV_AWS_158` and `CKV_AWS_338` are policy choices for the team |
| `terraform test` | none | UNVERIFIED: no `tests/*.tftest.hcl` |

### The same change by an agent

Prompt: [prompt-kiro.txt](prompt-kiro.txt). The harness copy also had the repository's skills in `.claude/skills`.

| Run | Seconds | Turns | Cost | Output tokens | What it verified |
| --- | --- | --- | --- | --- | --- |
| Without harness, 1 | 104 | 26 | $0.23 | 6,928 | `terraform fmt -check` and `validate` |
| Without harness, 2 | 88 | 26 | $0.30 | 9,000 | nothing: `terraform version` waited for approval |
| With harness, 1 | 122 | 29 | $0.27 | 7,372 | `harness/check.py`, and the check on the original code to show the findings were already there |
| With harness, 2 | 80 | 24 | $0.25 | 4,997 | `harness/check.py` |

All four runs made the same change: a flag that defaults to off, a module call on the existing `event-queue` module, `DISCONNECT_QUEUE_URL` only when the flag is on, the queue ARN added to `iam/dev/task-role-policy.json` for DevOps, and the docs. No run added a finding. The harness changed what the agent verified, not the code it wrote.

## 2. A new project with and without the skills

Prompt: [prompt-new.txt](prompt-new.txt). The skills arm had the repository's skills in `.claude/skills`. Each output was copied, the harness was installed in the copy, and `harness/check.py` ran on it.

| Run | Seconds | Turns | Cost | Output tokens | Harness check on the output |
| --- | --- | --- | --- | --- | --- |
| Without skills, 1 | 168 | 17 | $0.24 | 14,527 | FAIL: 12 Checkov findings. Three are `CKV_AWS_309`: the routes have no authorization, so the API is public. No tests |
| Without skills, 2 | 175 | 15 | $0.27 | 15,643 | FAIL: 6 Checkov findings, scored with an empty `envs/dev.tfvars` because the run wrote none. No tests |
| With skills, 1 | 173 | 21 | $0.17 | 4,051 | PASS (7 of 7), including mocked `terraform test` and app tests |
| With skills, 2 | 69 | 11 | $0.12 | 2,169 | no output: the profile command used a path form the rules did not match, and waited for approval |

Without the skills, Sonnet still wrote an account guard, default tags, KMS, point-in-time recovery, tracing, alarms and throttling, with no tests. With the skills, the project came from the template: IAM auth on the API, a Lambda alias for rollback, a runbook, probes, mocked tests, and checks that pass.

Skills run 1 found two faults in the skills:

- **It stopped before the DynamoDB table.** The scenario 6 rule in `aws-dynamodb` stopped a build request. Fixed in commit `855833c`: a build with one entity table now uses the ID as the key and asks for other access patterns at the end.
- **It skipped `apply_harness.py`.** `check_new_project.py` still passed, because `check.py` falls back to the skill's own copy of the harness. Fixed after this run: `check_new_project.py` now has a `harness-installed` check that fails until the harness files and the `AGENTS.md` section are in the project.
