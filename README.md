# Travel Agent Runtime Demo

A minimal but runnable **Agent Runtime demo** for multi-turn travel planning.

This project is **not** a full travel product and does not connect to real flight or hotel APIs. It is a compact reference implementation designed to show the runtime layer behind a multi-turn travel planning assistant.

The demo focuses on:

- typed `AgentState` with Pydantic
- `StatePatch`-based state updates
- reducer-based state merging
- deterministic validation
- partial replanning
- blocker propagation
- execution trace logging
- a minimal FastAPI service entrypoint

---

## Why this exists

Pure prompt-based travel planning agents often suffer from:

- forgetting previous constraints
- regenerating the whole plan after every small change
- silently ignoring hard constraints like budget or flight preferences
- continuing execution even after validation failure
- having no clear trace of what happened

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

---

## Project structure

```text
travel-agent-runtime-demo/
├── agent/
│   ├── state.py          # Pydantic AgentState, StatePatch, TravelPlan, trace events
│   ├── reducer.py        # applies patches and records trace events
│   ├── validator.py      # deterministic business-rule validation
│   └── runtime.py        # end-to-end runtime orchestration
│
├── api/
│   └── main.py           # FastAPI endpoint around handle_user_message
│
├── examples/
│   └── demo_run.py       # runnable local demo
│
├── tests/
│   ├── test_state_patch.py
│   ├── test_validator.py
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

The reducer applies the patch and appends a trace event. This makes state transitions explicit and auditable.

### 3. Deterministic Validator

Hard constraints are checked outside the LLM.

For example:

- total cost must not exceed budget
- red-eye flights must be avoided if requested
- required fields must exist before itinerary generation

This reduces the risk of tool hallucination and inconsistent plans.

### 4. Partial Replanning

When a user changes only the budget or a preference, the runtime does not need to rebuild the entire conversation.

It updates affected fields and replans the itinerary based on current structured state.

### 5. Blocker Propagation

If validation fails repeatedly, the runtime stops and records blockers instead of continuing silently.

This prevents silent failure and repeated reasoning loops.

---

## Production integration points

This demo intentionally keeps external dependencies minimal.

### Redis integration point

The current demo keeps `AgentState` in memory.

In production, Redis can be used for:

- session-level `AgentState` persistence
- short-term working memory
- tool result cache
- idempotency keys
- execution trace buffering
- retry metadata

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

### vLLM integration point

The current demo uses simple rule-based intent detection so it can run without API keys or model servers.

In production, vLLM or any OpenAI-compatible model server can be connected at:

- intent detection
- planner step generation
- natural language response generation
- repair prompt generation after validation failure

A natural integration point is:

```text
TravelAgentRuntime.detect_intent_and_patch(...)
```

In production, this method could call a local vLLM-served model and parse the result into a Pydantic `StatePatch`.

The demo does not include vLLM because the focus here is runtime structure, not model serving setup.

---

## What this demo intentionally does not include

- real flight or hotel APIs
- real payment or booking flow
- frontend UI
- production Redis deployment
- production vLLM deployment
- complex long-term memory system

Those can be added later, but this version focuses on the core runtime pattern.
