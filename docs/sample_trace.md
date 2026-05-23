# docs/sample_trace.md

# Sample Runtime Trace

This document shows a simplified execution trace for the travel planning Agent Runtime demo.

The goal is to demonstrate:

* intent detection
* state patch generation
* reducer-based state updates
* partial replanning
* deterministic validation
* blocker propagation
* execution observability

---

# Scenario

User starts a Tokyo travel planning session.

## Turn 1

User message:

```text
I want a 5-day Tokyo trip under 7000 SGD. Make it relaxed.
```

---

# Runtime Flow

```text
User Message
    ↓
Intent Detection
    ↓
StatePatch Generation
    ↓
Reducer
    ↓
Partial Replanning
    ↓
Validator
    ↓
Response Generation
```

---

# 1. Intent Detection

The runtime first identifies the user intent.

```json
{
  "intent": "new_trip_plan"
}
```

The runtime extracts structured constraints:

```json
{
  "destination": "Tokyo",
  "days": 5,
  "budget": 7000,
  "preferences": {
    "travel_style": "relaxed"
  }
}
```

---

# 2. StatePatch Generation

Instead of directly mutating the whole AgentState, the runtime generates a structured StatePatch.

```json
{
  "updates": {
    "destination": "Tokyo",
    "days": 5,
    "budget": 7000,
    "preferences": {
      "travel_style": "relaxed"
    }
  },
  "reason": "new_trip_plan",
  "affected_fields": [
    "destination",
    "days",
    "budget",
    "preferences",
    "itinerary"
  ],
  "trigger_replan": true
}
```

This keeps state transitions explicit and traceable.

---

# 3. Reducer Applies Patch

The reducer merges the patch into the typed AgentState.

```text
Before:
- destination = None
- budget = None
- itinerary = None
```

```text
After:
- destination = Tokyo
- budget = 7000
- preferences.travel_style = relaxed
```

The reducer also appends a trace event:

```json
{
  "event": "state_patch_applied",
  "reason": "new_trip_plan"
}
```

---

# 4. Partial Replanning

The runtime detects that itinerary-related fields changed.

```json
{
  "trigger_replan": true,
  "affected_fields": [
    "budget",
    "preferences",
    "itinerary"
  ]
}
```

The planner rebuilds only the affected travel plan.

Example generated itinerary:

```json
{
  "destination": "Tokyo",
  "days": 5,
  "flight_type": "red_eye",
  "hotel_tier": "standard hotel",
  "poi_style": "relaxed itinerary",
  "total_cost": 6550
}
```

---

# 5. Validator

The deterministic validator checks hard constraints outside the LLM.

Validation rules include:

* budget limit
* day consistency
* flight constraints
* required fields

Example validation result:

```json
{
  "passed": true,
  "errors": []
}
```

---

# 6. Final Response

The runtime generates the final response.

```text
Planned 5-day trip to Tokyo.
Flight=red_eye
Hotel=standard hotel
Style=relaxed itinerary
Estimated cost=6550
Budget=7000
```

---

# Turn 2 — User Modifies Constraints

User message:

```text
Change the budget to 9000 and avoid red-eye flights.
```

---

# Intent Detection

```json
{
  "intent": "modify_constraints"
}
```

---

# StatePatch

```json
{
  "updates": {
    "budget": 9000,
    "preferences": {
      "avoid_red_eye": true
    }
  },
  "reason": "modify_constraints",
  "affected_fields": [
    "budget",
    "preferences",
    "itinerary"
  ],
  "trigger_replan": true
}
```

The runtime updates only affected fields instead of rebuilding the entire conversation.

---

# Partial Replanning

The runtime replans the itinerary using the updated constraints.

Updated itinerary:

```json
{
  "destination": "Tokyo",
  "days": 5,
  "flight_type": "daytime",
  "hotel_tier": "standard hotel",
  "poi_style": "relaxed itinerary",
  "total_cost": 7050
}
```

---

# Validation Failure Example

If the replanned itinerary exceeds budget:

```json
{
  "passed": false,
  "errors": [
    "Budget exceeded"
  ]
}
```

The runtime records blockers and retry metadata.

```json
{
  "retry_count": 1,
  "blockers": [
    "Budget exceeded"
  ],
  "current_stage": "needs_repair"
}
```

---
