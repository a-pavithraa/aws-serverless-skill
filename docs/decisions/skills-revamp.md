# Decision: skills revamp (plan Task 7a)

Date: 2026-11-08. The revamp follows the Spring Boot marketplace's revamp: a best-practices audit, trigger-style descriptions with triggering evals, a one-command install and a Skills section in `AGENTS.md`.

## Changes

| File | Decision | Why |
| --- | --- | --- |
| All `SKILL.md` descriptions | Rewritten to start with "Use when", name the user's words, and name the skill to use instead | The old descriptions were keyword lists of 60 or more words. `test_docs.py` now enforces the form. |
| `terraform-aws`, `aws-serverless` and `aws-dynamodb` `SKILL.md` | The 45-line AWS Pricing MCP setup block is replaced with three lines that link to the server's README | The block loaded on every trigger of three skills. The setup belongs to the server's README. |
| `terraform-aws/SKILL.md` | Hand-kept line counts removed. A rule now points at the harness: no apply, destroy, state commands, `-target` or `-auto-approve` from an agent session | The counts were wrong twice (plan §1). The rule now has a check behind it. |
| `aws-serverless/SKILL.md` | "Never print(), use Powertools Logger" is replaced. Lambda native JSON logging is enough, the log level is set in one place, and the X-Ray SDK is not added by default | Native `logging_config` JSON logging exists, and the X-Ray SDK has been in maintenance since 2026-02-25 |
| `references/lambda-powertools.md` | Current versions added. A tracing decision section added. `log_event=True` removed from the example. The layer ARN now comes from AWS's SSM parameter, pinned to 3.39.0. Runtime changed from `python3.11` to `python3.13` | Versions were read from GitHub releases on 2026-11-08. The SSM path was read from the account. `log_event` writes request bodies to the logs. |
| `references/lambda-patterns.md` | SQS limit corrected from 256 KB to 1 MiB. Recursive loop detection corrected (S3, EventBridge and Lambda-to-Lambda loops are detected). Example runtime `nodejs18.x` changed to `nodejs24.x`. The unconfirmed EventBridge size number was removed in favor of a link | Each change cites the AWS page read on 2026-11-08 |
| `.claude-plugin/marketplace.json` | Adds `creating-aws-projects` and `aws-iac-team-harness`, version 2.0.0 | `test_docs.py` requires every skill folder to be listed |
| `install.py` | New. Claude Code: adds the marketplace, installs the plugin and turns on auto-update. Codex: copies the skill folders | Ported from the Spring marketplace and reduced to one local plugin. Tested for Codex in `test_install.py`. |
| Harness `AGENTS.md` section | Gains a Skills section | The Spring trial raised Haiku's skill loading from 6/10 to 10/10 with this section |
| `README.md` | Rewritten. It lists every skill, check and script, the test command and the install | `test_docs.py` enforces the content |

## `DynamoDBDesign.md` stays, with a recommendation to remove it

The file is at the repository root, and no skill loads it. Its header says that its content is "extracted directly from the book" (*The DynamoDB Book*, chapters 15 to 22). Copying it into a skill reference would spread book text further. The non-obvious modeling patterns already exist in `aws-dynamodb/references/dynamodb-patterns.md` in the repository's own words.

Recommendation: delete `DynamoDBDesign.md` from the public repository. This revamp did not delete it, because it is the owner's file.

## Triggering eval results

`tests/fixtures/triggering/run.py` sends 20 prompts that do not name a skill: 15 that should load one of the five skills and 5 that should load none. Each prompt runs once per model in a clean project with only these skills installed. The results are in `tests/fixtures/triggering/results/`.

| Run | Sonnet | Haiku |
| --- | --- | --- |
| `run-1`: descriptions only | 17/20 | 14/20 |
| `run-2-routing`: descriptions and the harness `AGENTS.md` Skills section (`--routing routing.md`) | 20/20 | 12/20 |

No run loaded a wrong skill, and no run loaded a skill for the 5 unrelated prompts. Every miss loaded no skill at all. Without the Skills section, the misses are short factual questions, such as the visibility timeout for a 30-second consumer, or HTTP API against REST API with WAF. The model answers those from its own knowledge. The descriptions already name each of these topics, so this pass did not change them further.

The Skills section closed every Sonnet miss. Haiku results changed between runs in both directions: `harness-2` and `harness-3` passed in `run-1` and missed in `run-2-routing`. One run per prompt does not separate a description problem from Haiku's variance. To measure Haiku, run each prompt at least three times.

Recommendation: install the harness `AGENTS.md` section in repositories where the skills are used. It is the measured fix for under-triggering on Sonnet.

## Not done in this pass

- **The RED/GREEN runs of the 8 scenarios** in `tests/baseline-scenarios.md`, run twice each. Each run is a full agent session with tools, and a person must judge each result against the success criteria. A person should run them.
- **A section-by-section rewrite of each large reference** (`cicd-patterns.md` and `dynamodb-patterns.md` are both over 500 lines). This pass corrected only the claims that research note 03 marks as wrong and that a primary source confirmed. Trimming the rest needs the scenario results, so that a scenario shows whether a cut changes behavior.
- **The comparison in plan Task 7** (old skills against refreshed skills against templates with the harness). It needs repeated agent sessions on identical tasks, with time and repair counts recorded.
