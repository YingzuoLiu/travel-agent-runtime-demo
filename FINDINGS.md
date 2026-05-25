# Eval Findings: TravelAgentRuntime Ablation Study

## What this project does

This repo implements a multi-turn travel planning agent runtime and an
ablation eval harness that measures how different runtime components
affect task reliability across long-horizon conversations.

The runtime has four key components:
- **State**: typed, patch-based state that persists all user constraints
- **Validator**: deterministic constraint checker (budget, flight type, day count)
- **Retry**: recovery mechanism when validation fails
- **Partial replan**: rebuilds the itinerary from current state after any change

The eval harness runs four scenario types under four runtime configurations
and records completion rate, blocker count, replan count, and validation
failures for each combination.

---

## Scenarios

| Scenario | Turns | What it tests |
|---|---|---|
| happy_path_5turn | 5 | Normal planning, no conflicts |
| budget_conflict_recovery | 5 | Budget set below cost mid-session, then recovered |
| conflicting_preferences_stall | 5 | Irreconcilable budget constraint, tests blocker propagation |
| memory_drift_8turn | 8 | Early preferences must survive later updates; confirm intent at end |

---

## Ablation configurations

| Config | Validator | Retry limit |
|---|---|---|
| full_runtime | enabled | 2 |
| no_validator | disabled | 2 |
| no_retry | enabled | 0 |
| no_validator_no_retry | disabled | 0 |

---

## Results

| Scenario | full_runtime | no_validator | no_retry | no_validator_no_retry |
|---|---|---|---|---|
| happy_path_5turn | ✓ | ✓ | ✓ | ✓ |
| budget_conflict_recovery | ✗ | ✗ | ✗ | ✗ |
| conflicting_preferences_stall | ✗ | ✓ | ✗ | ✓ |
| memory_drift_8turn | ✓ | ✓ | ✓ | ✓ |

**Completion rate:**

| Config | Rate |
|---|---|
| full_runtime | 50% (2/4) |
| no_validator | 75% (3/4) |
| no_retry | 50% (2/4) |
| no_validator_no_retry | 75% (3/4) |

---

## Key findings

### Finding 1: higher completion rate without validator is misleading

`no_validator` completes `conflicting_preferences_stall` that
`full_runtime` blocks. But inspection shows the "completed" plan
has `total_cost > budget` — a direct constraint violation.

The validator is working correctly. It sacrifices completion rate
to preserve plan correctness. An agent runtime that optimises
completion rate without a validation layer will silently produce
wrong answers.

**Takeaway**: completion rate is not a sufficient eval metric for
agent correctness. You need a separate constraint-satisfaction check.

### Finding 2: confirm intent was missing — bug found and fixed

All four configs failed `memory_drift_8turn` in the first eval run.
Trace inspection showed turn 8 ("Confirm everything looks good")
was not matched by any intent pattern. The runtime wrote a blocker
(`"Could not identify actionable travel constraints"`) into state
instead of treating it as a no-op confirmation.

Root cause: `detect_intent_and_patch` had no handler for
affirmative/confirm utterances. When `updates` was empty and the
input was not a known keyword, it defaulted to the clarification
blocker path.

Fix: added a confirm intent check before the fallback blocker path.
If the user message contains affirmative words and no structured
update is needed, the runtime returns a no-op patch and preserves
the current planned state.

After fix: `memory_drift_8turn` passes under all four configs.
`full_runtime` completion rate improved from 25% to 50%.

### Finding 3: budget_conflict_recovery fails across all configs

The `budget_conflict_recovery` scenario sets budget to 4000 SGD
mid-session, which causes `total_cost > budget`. The validator
flags it. Turn 4 raises budget to 6000, but the replan cost
(7-day trip with red-eye avoidance and subway hotel) still
exceeds 6000, so validation fails again and retry limit is hit.

This is not a bug — it is correct behaviour. The scenario exposes
that the cost model needs either a cheaper tier option or a
user-facing suggestion to reduce trip length. This points to a
missing "suggest alternatives on budget failure" recovery path,
which would be the next feature to implement.

---

## Interview summary

> I built a deterministic agent runtime for multi-turn travel
> planning and designed an ablation eval harness to measure how
> validator, retry, and intent detection components affect task
> reliability. Running four scenarios across four configurations,
> I found that removing the validator raised apparent completion
> rate from 50% to 75% — but the extra completions were plans
> that violated budget constraints. I also caught and fixed a
> missing confirm intent that caused all 8-turn sessions to fail
> at the final turn. The key insight is that completion rate alone
> is not a sufficient metric for agent correctness; constraint
> satisfaction must be measured separately.

