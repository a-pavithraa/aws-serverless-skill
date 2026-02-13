# Skill Testing Framework

RED-GREEN-REFACTOR methodology for validating that skills effectively change agent behavior.

## Core Purpose

Establish what agents do wrong *without* the skill loaded, then verify skills correct those failures. Each scenario targets a specific failure mode — not general knowledge gaps.

## Three Phases

**Phase 1 (RED):** Run each scenario with no skills loaded. Document the agent's exact failure — what it got wrong, what rationalization it used.

**Phase 2 (GREEN):** Load the relevant skill. Run the identical prompt. Verify the success criteria now pass.

**Phase 3 (REFACTOR):** Run pressure variations on passing scenarios. If the agent can be talked out of correct behavior, update the skill to counter those rationalizations. Re-test until bulletproof.

## Test Execution

```bash
# For each scenario:
# 1. Start a fresh session with NO skills loaded
# 2. Run the test prompt exactly as written
# 3. Save full response to baseline-results/scenario-N.md
# 4. Note rationalizations verbatim in rationalizations.md

# Then:
# 1. Start a fresh session WITH the relevant skill loaded
# 2. Run identical prompt
# 3. Check against success criteria
# 4. Run pressure variations
```

## Folder Structure

```
tests/
  README.md                  # this file
  baseline-scenarios.md      # 8 test scenarios
  rationalizations.md        # rationalization tracking table
  baseline-results/
    scenario-1.md            # actual agent response WITHOUT skill
    scenario-2.md
    ...
```

## Success Metrics

A skill is effective when:
- All baseline scenarios show a clear behavior gap (RED)
- All target scenarios pass success criteria (GREEN)
- Pressure variations don't break compliance (REFACTOR)
- Rationalizations are countered in skill content

## Skill-to-Scenario Mapping

| Skill | Scenarios |
|-------|-----------|
| `terraform-aws` | 1, 2, 3 |
| `aws-dynamodb` | 4, 5, 6 |
| `aws-serverless` | 7, 8 |
