# Travel Agent Runtime Demo

A minimal but runnable **Agent Runtime demo** for multi-turn travel planning.

This project is **not** a full travel product and does not connect to real flight or hotel booking APIs. It is a compact reference implementation designed to show the runtime layer behind a multi-turn travel planning assistant.

The demo focuses on:

* typed `AgentState` with Pydantic
* `StatePatch`-based state updates
* reducer-based state merging
* deterministic validation
* optional geography grounding with a geocoding tool
* partial replanning
* blocker propagation
* execution trace logging
* a minimal FastAPI service entrypoint

---

## Why this exists

Pure prompt-based travel planning agents often suffer from:

* forgetting previous constraints
* regenerating the whole plan after every small change
* silently ignoring hard constraints like budget or flight preferences
* hallucinating destinations or geographically unrealistic plans
* continuing execution even after validation failure
* having no clear trace of what happened

This demo separates the agent into a small runtime:

```text
User Message
    ↓
Intent Detection
    ↓
StatePatch
    ↓
Reducer
    ↓
Partial Replanning
    ↓
Validator
    ↓
Blocker / Final Response
```

The main idea is that long-running planning behavior should not rely only on prompt text. Important task state, hard constraints, and validation results should live in explicit runtime components.

---

## Project structure

```text
travel-agent-runtime-demo/
├── agent/
│   ├── state.py              # Pydantic AgentState, StatePatch, TravelPlan, trace events
│   ├── reducer.py            # applies patches and records trace events
│   ├── validator.py          # deterministic business-rule and optional geography validation
│   ├── runtime.py            # end-to-end runtime orchestration
│   └── tools/
│       ├── __init__.py
│       └── geocode_tool.py   # optional Nominatim-compatible geocoding tool
│
├── api/
│   └── main.py               # FastAPI endpoint around handle_user_message
│
├── examples/
│   └── demo_run.py           # runnable local demo
│
├── tests/
│   ├── test_state_patch.py
│   ├── test_validator.py
│   ├── test_geography_validator.py
│   ├── test_partial_replan.py
│   └── test_api.py
│
├── traces/
│   └── sample_trace.json
│
├── requirements.txt
└── README.md
```

---

## Quick start

Install dependencies:

```bash
pip install -r requirements.txt
```

Run the local demo:

```bash
python examples/demo_run.py
```

Run tests:

```bash
pytest -q
```

Start the FastAPI service:

```bash
uvicorn api.main:app --reload
```

Then call:

```bash
curl -X POST http://127.0.0.1:8000/agent/message \
  -H "Content-Type: application/json" \
  -d '{
    "thread_id": "tokyo_trip_001",
    "user_message": "I want a 5-day Tokyo trip under 7000 SGD. Make it relaxed."
  }'
```

---

## Example scenario

```text
User: I want a 5-day Tokyo trip under 7000 SGD.
User: Change the budget to 9000 and avoid red-eye flights.
```

The runtime does not simply regenerate everything from scratch.

It converts the user message into a structured `StatePatch`:

```json
{
  "updates": {
    "budget": 9000,
    "preferences": {
      "avoid_red_eye": true
    }
  },
  "affected_fields": ["budget", "preferences", "itinerary"],
  "trigger_replan": true
}
```

Then it updates the typed state, triggers partial replanning, and validates the new itinerary.

---

## Key design choices

### 1. Pydantic AgentState

`AgentState` keeps long-running task state outside the prompt.

It stores destination, days, budget, preferences, itinerary, blockers, retry count, and execution trace.

Using Pydantic makes the runtime state explicit, serializable, and easier to validate at API boundaries.

---

### 2. StatePatch + Reducer

A user message does not directly mutate the whole state.

Instead, the runtime creates a `StatePatch`:

```python
StatePatch(
    updates={"budget": 9000},
    affected_fields=["budget", "itinerary"],
    reason="modify_budget",
    trigger_replan=True,
)
```

The reducer applies the patch and appends a trace event.

This makes state transitions explicit and auditable.

Instead of asking the LLM to remember every previous constraint, the runtime keeps the current task state in a structured form and updates only the affected fields.

---

### 3. Deterministic Validator

Hard constraints are checked outside the LLM.

For example:

* total cost must not exceed budget
* red-eye flights must be avoided if requested
* required fields must exist before itinerary generation
* itinerary day count must match the requested number of days

This reduces the risk of tool hallucination, inconsistent plans, and silent constraint violations.

The validator returns structured validation errors. If validation keeps failing after retries, the runtime records blockers instead of continuing silently.

---

### 4. Optional Geography Grounding

The validator can consume optional geography evidence, such as geocoding results, to check whether a destination can be grounded to real-world coordinates.

In this minimal demo, the geocoding dependency is injected for testing and extension purposes. In a cleaner production runtime, the tool execution would happen in the runtime or executor layer, while the validator would only consume the returned structured evidence.

This keeps external grounding separate from the default offline runtime path.

For example, the validator can be extended to:

* check whether a destination city can be geocoded
* verify whether a destination exists in the real world
* use coordinates as a grounding signal for future POI validation
* support Haversine distance checks between locations
* detect geographically unrealistic itinerary candidates

The current implementation keeps this capability optional.

By default, the demo still runs without network access or external map services.

The geography validation tests use a fake geocoding tool instead of calling a live external API. This keeps the test suite deterministic and avoids flaky failures caused by network availability, rate limits, or third-party service behavior.

This follows the same design principle as the rest of the project:

```text
The LLM should not be the only component deciding whether a travel plan is valid.
```
---

### 5. Partial Replanning

When a user changes only the budget or a preference, the runtime does not need to rebuild the entire conversation.

It updates affected fields and replans the itinerary based on the current structured state.

For example:

```text
Original request:
5-day Tokyo trip under 7000 SGD

Follow-up:
Change the budget to 9000 and avoid red-eye flights
```

The runtime only updates the affected state fields and regenerates the dependent itinerary.

This is closer to how a production agent runtime should behave: user edits become structured state transitions, not full prompt resets.

---

### 6. Blocker Propagation

If validation fails repeatedly, the runtime stops and records blockers instead of continuing silently.

For example:

```text
Budget exceeded after retry
Red-eye flight still selected despite user preference
Missing required destination
Destination could not be geocoded
```

The runtime can then surface the blocker to the user or trigger a repair path.

This prevents repeated reasoning loops and makes failure states visible.

---

### 7. Execution Trace Logging

Each important state transition can be recorded as a trace event.

This makes the runtime easier to debug and evaluate.

Instead of only seeing the final answer, the developer can inspect:

* what user message was received
* what patch was generated
* what fields were affected
* whether replanning was triggered
* what validation errors occurred
* when blockers were added

This is useful for debugging multi-turn agent behavior, regression testing, and future evaluation harnesses.

---

## Optional geography validation example

The geography validation layer is intentionally designed as an injectable dependency.

A fake geocoding tool can be used in tests:

```python
class FakeGeocodeTool:
    def __init__(self, results):
        self.results = results
        self.calls = []

    def search(self, query, country=None, limit=3):
        self.calls.append(
            {
                "query": query,
                "country": country,
                "limit": limit,
            }
        )
        return self.results
```

Then it can be injected into the validator:

```python
validator = TravelValidator(
    geocode_tool=fake_tool,
    enable_geography_validation=True,
    default_country="China",
)
```

This allows the validator to check whether a destination can be resolved without depending on the LLM's internal knowledge.

The same interface can later be backed by:

* Nominatim
* Google Maps
* Amap / 高德地图
* an internal POI database
* a production geocoding or routing service

---

## Production integration points

This demo intentionally keeps external dependencies minimal.

The goal is to show the runtime pattern first, while leaving clear extension points for production systems.

---

### Redis integration point

The current demo keeps `AgentState` in memory.

In production, Redis can be used for:

* session-level `AgentState` persistence
* short-term working memory
* tool result cache
* idempotency keys
* execution trace buffering
* retry metadata

A natural place to integrate Redis is inside the API layer:

```text
POST /agent/message
    ↓
load AgentState from Redis by thread_id
    ↓
runtime.handle_user_message(...)
    ↓
save updated AgentState back to Redis
```

The demo does not include Redis because the goal is to keep the repository runnable without external services.

---

### vLLM integration point

The current demo uses simple rule-based intent detection so it can run without API keys or model servers.

In production, vLLM or any OpenAI-compatible model server can be connected at:

* intent detection
* planner step generation
* natural language response generation
* repair prompt generation after validation failure

A natural integration point is:

```text
TravelAgentRuntime.detect_intent_and_patch(...)
```

In production, this method could call a local vLLM-served model and parse the result into a Pydantic `StatePatch`.

The demo does not include vLLM because the focus here is runtime structure, not model serving setup.

---

### Geography grounding integration point

The current demo includes an optional `NominatimGeocodeTool` as a lightweight external grounding example.

It is not enabled by default. The default runtime remains offline and does not depend on external map services.

A natural production upgrade path would be:

```text
TravelValidator
    ↓
Geocode / POI tool
    ↓
destination existence check
    ↓
POI-city consistency check
    ↓
route distance or travel-time validation
```

For production use, this layer should be backed by a production-grade geocoding provider, route API, caching layer, quota handling, fallback strategy, and data quality monitoring.

The current version only demonstrates the first step: making external geography grounding available to the validator without coupling the whole runtime to an external service.

---

## What this demo intentionally does not include

This repository intentionally does not include:

* real flight or hotel booking APIs
* real payment or booking flow
* frontend UI
* production Redis deployment
* production vLLM deployment
* production-grade map, route, or POI APIs
* complex long-term memory system
* full multi-agent orchestration framework

Those can be added later, but this version focuses on the core runtime pattern:

```text
stateful multi-turn interaction
+ structured state updates
+ deterministic validation
+ blocker propagation
+ traceable execution
```

---

## How to explain this project

This project can be summarized as:

```text
A minimal Agent Runtime demo for travel planning that separates state management,
partial replanning, deterministic validation, and blocker handling from the LLM prompt.
```

The key idea is not to build a complete travel app.

The key idea is to show how an agent runtime can make multi-turn planning more reliable by keeping task state, validation rules, and failure handling explicit.

The optional geography validation layer extends this idea by showing how real-world grounding tools can be connected to the validator without breaking the default offline demo path.

---

## Test status

Run:

```bash
pytest -q
```

Expected result:

```text
9 passed
```

