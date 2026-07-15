# Evidence Review Workflow

The optional `travel-agent:0.5.0` path extends the existing candidate-plan flow with a
Pi-inspired, evidence-driven review stage:

```text
Candidate TravelPlan
        |
        v
PlanEvidenceBuilder
        |
        +-- ContextProjector --> BudgetChecker
        `-- ContextProjector --> PreferenceReviewer
                              |
                              v
                     typed ReviewerReport
                              |
                              v
                  deterministic FindingReducer
                              |
                              v
                     typed ReplanDirective
                              |
                              v
                     partial_replan
                              |
                              v
                 deterministic TravelValidator
```

This is not a general multi-Agent framework. It is a feature-flagged experiment that asks
whether specialized, context-limited review adds useful evidence before the existing final
Validator gate.

## One fact snapshot, two role projections

`PlanEvidenceBuilder` is the only component that canonicalizes candidate-plan facts. It
builds a read-only snapshot containing the plan, budget, structured preferences, cost
ledger, and already-loaded memory references.

`ContextProjector` does not recompute these facts. It only produces typed role-specific
views:

- `BudgetReviewContext` receives the plan total, budget limit, and cost ledger;
- `PreferenceReviewContext` receives the plan, current explicit preferences, and relevant
  memory references;
- the Budget checker cannot see the preference or memory payload.

Distance, duration, and route facts can be added to the same `PlanEvidence` layer when the
Schedule and Geography roles are implemented. They should not become a Geography
reviewer's private calculation.

## Findings are observations, not state changes

Each reviewer returns a `ReviewerReport` containing:

- all rule IDs that it actually checked;
- structured `SkippedCheck` records for unavailable or unconfigured coverage;
- zero or more `ReviewFinding` objects.

An empty `findings` list therefore means no violation was found among the recorded checks.
It does not hide missing coverage.

Every finding uses machine-readable `EvidenceRef` objects with source type, source ID,
field, observed value, expected value, unit, and optional tool-call provenance. Reviewers
cannot directly mutate `AgentState` or submit a `StatePatch`.

The deterministic reducer filters refuted findings, deduplicates by stable rule/type/target
keys, sorts by severity, and emits controlled `ReplanDirective` actions. Cross-dimension
LLM root-cause merging is deliberately out of scope for this version.

Only `confirmed` findings can produce automatic replan directives. A `plausible` semantic
finding remains visible in the trace but cannot mutate the plan without later confirmation.

## Offline preference baseline and semantic extension point

The repository remains offline-first. The default `PreferenceReviewer` deterministically
checks structured preferences and already-loaded memory references. It accepts an optional
async semantic analyzer, which is the integration boundary for a real LLM-based reviewer.

When no semantic analyzer is configured, the report records
`preference.semantic_alignment` as an optional skipped check. It does not pretend that an
LLM review ran. Tests inject a fake semantic analyzer to verify typed `llm_semantic`
findings without requiring an API key.

## Deadline, retry, and partial-result semantics

`WorkflowOrchestrator` uses `asyncio` tasks plus a semaphore. All work shares one absolute
workflow deadline. Each attempt uses the smaller of:

```text
per-task timeout
remaining workflow time
```

Only explicitly transient `RetryableReviewerError` failures and timeouts may consume the
remaining attempt budget. Missing required evidence is `blocked`; cancellation is not
retried; ordinary programming or schema errors fail immediately.

Task states are explicit:

```text
completed | failed | cancelled | timed_out | blocked
```

If at least one reviewer succeeds while another fails, times out, blocks, or omits a
required check, the workflow status is `completed_partial`. Completed findings are still
reduced and retained. If no reviewer completes, the workflow is `failed`.

Cancelling the async workflow records unfinished tasks as `cancelled` and preserves any
already-completed findings for diagnosis, but returns no replan directives. Cancellation
therefore cannot produce a state-changing repair after the caller has stopped the workflow.

## Opt-in execution

The original agent version is preserved:

```text
travel-agent:0.3.0  -> original planner/replan/validator path
travel-agent:0.5.0  -> evidence review + typed replan + final validator
```

For direct Python use:

```python
runtime = TravelAgentRuntime(enable_review_workflow=True)
```

For the durable API, submit `agent_version: "0.5.0"`.

## Labeled fixture

`eval/review_cases.json` contains ten clean, single-error, compound-error, memory, and
current-request-overrides-memory cases. Run the deterministic fixture with:

```bash
python -m eval.review_runner
```

The fixture is a mechanics and regression check, not evidence that multiple reviewers are
better than one. A fair architecture experiment still needs the same model, fact inputs,
prompt effort, and comparable token budget for generalist and specialist conditions.

Its result should be reported as `10/10 deterministic regression fixtures passed`, not as
model accuracy, precision, or recall. The fixtures and reviewer rules were designed together
and are not an independently labeled evaluation set.

Budget review uses the expanded tool cost ledger as the authoritative total only when all
expected ledger fields are present. A missing ledger falls back to the plan total with an
explicit evidence issue; a complete ledger that disagrees with the plan total records a
`cost_total_mismatch` issue instead of silently trusting the upstream aggregate.

## Deliberate next boundaries

- add Schedule and Geography consumers after shared route/time facts exist;
- persist workflow/task rows and cache keys only after the in-process contract is stable;
- propagate durable run cancellation into in-flight async reviewer tasks;
- add a real semantic analyzer and report token/latency measurements;
- compare generalist vs specialist detection separately from end-to-end
  reviewer/replan/validator quality;
- keep the final deterministic Validator mandatory in every reviewed configuration.
