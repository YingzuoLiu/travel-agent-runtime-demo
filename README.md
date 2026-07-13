# Travel Agent Runtime Demo

A runnable reference implementation of two related layers:

1. an **application-level agent runtime** for structured multi-turn travel planning;
2. a small **self-hosted cloud runtime** for durable run lifecycle management.

The project is intentionally offline-first. It does not require an LLM API key, Redis, PostgreSQL or a Kubernetes cluster to demonstrate the runtime mechanics.

## What changed in v0.3

The original agent already separated state, patching, validation and replanning from prompt text. Version `0.3.0` adds the outer execution-management layer:

- asynchronous `POST /runs` API
- durable `run_id` lifecycle
- exact agent-version pinning
- worker-based execution
- SQLite-backed runs, events and thread checkpoints
- restart recovery for queued/running work
- cooperative cancellation
- polling and Server-Sent Events trace APIs
- Docker, Docker Compose and a single-replica Kubernetes manifest
- CI on Python 3.11 and 3.12

```text
Client
  |
  v
FastAPI control API
  |  POST /runs
  v
RuntimeManager ---- AgentRegistry
  |                    `- travel-agent:0.3.0
  |
  +---- worker queue
  |
  +---- SQLiteRunStore
  |       |- runs
  |       |- run_events
  |       `- thread_states
  |
  v
TravelAgentRuntime
  |- intent detection
  |- StatePatch + reducer
  |- partial replan
  |- deterministic validator
  `- blocker propagation
```

## Why this is a runtime, not only an API wrapper

A normal synchronous wrapper looks like:

```text
HTTP request -> agent.run() -> HTTP response
```

The `/runs` path manages execution as a first-class resource:

```text
queued -> running -> completed
                  -> failed
queued/running    -> cancelled
```

Each run stores:

- `run_id` and `thread_id`
- pinned `agent_id` and `agent_version`
- input, output and validation errors
- attempt and cancellation metadata
- timestamps
- the latest serialized `AgentState`
- an append-only runtime event history

This outer lifecycle is separate from the travel agent's internal planner/reducer/validator behavior.

## Application runtime

The travel agent keeps important task state outside the prompt:

```text
User message
    |
    v
Intent detection
    |
    v
StatePatch
    |
    v
Reducer
    |
    v
Partial replan
    |
    v
Deterministic validator
    |
    v
Blocker or final response
```

Core behavior includes:

- typed `AgentState` with Pydantic
- explicit `StatePatch` transitions
- reducer-based nested state updates
- partial replanning after changed constraints
- deterministic budget, itinerary and flight checks
- optional geocoding-based grounding
- retry metadata and visible blockers
- application trace events

The rule-based intent detector keeps the repository runnable without model credentials. It can later be replaced with an LLM or classifier that produces the same `StatePatch` schema.

## Project structure

```text
travel-agent-runtime-demo/
├── agent/                    # application-level travel runtime
│   ├── state.py
│   ├── reducer.py
│   ├── runtime.py
│   ├── validator.py
│   └── tools/
├── runtime_service/          # cloud runtime layer
│   ├── models.py             # run/event API models and lifecycle
│   ├── registry.py           # exact agent-version registry
│   ├── store.py              # SQLite runs/events/checkpoints
│   └── manager.py            # queue, worker, recovery, cancellation
├── api/main.py               # synchronous and asynchronous FastAPI APIs
├── deploy/k8s/runtime.yaml   # deliberately single-replica SQLite deployment
├── docs/cloud-runtime.md
├── tests/
├── Dockerfile
├── docker-compose.yml
└── requirements.txt
```

## Quick start

Install and test:

```bash
python -m venv .venv
source .venv/bin/activate       # Windows: .venv\Scripts\activate
pip install -r requirements.txt
pytest -q
```

Start the API:

```bash
uvicorn api.main:app --reload
```

Health endpoints:

```bash
curl http://127.0.0.1:8000/health
curl http://127.0.0.1:8000/ready
```

## Synchronous compatibility API

The original endpoint remains available:

```bash
curl -X POST http://127.0.0.1:8000/agent/message \
  -H "Content-Type: application/json" \
  -d '{
    "thread_id": "tokyo-trip-sync",
    "user_message": "I want a 5-day Tokyo trip under 9000 SGD."
  }'
```

This endpoint executes in the request process and keeps its compatibility state in memory. Use `/runs` to exercise the durable runtime layer.

## Durable run API

List registered agent versions:

```bash
curl http://127.0.0.1:8000/agents
```

Create an asynchronous run:

```bash
curl -X POST http://127.0.0.1:8000/runs \
  -H "Content-Type: application/json" \
  -d '{
    "thread_id": "tokyo-trip-001",
    "user_message": "I want a 5-day Tokyo trip under 9000 SGD.",
    "agent_id": "travel-agent",
    "agent_version": "0.3.0"
  }'
```

The API returns `202 Accepted` with a stable `run_id`.

Inspect the run:

```bash
curl http://127.0.0.1:8000/runs/<run_id>
```

Inspect append-only runtime events:

```bash
curl http://127.0.0.1:8000/runs/<run_id>/events
```

Stream events with SSE:

```bash
curl -N http://127.0.0.1:8000/runs/<run_id>/events/stream
```

Request cancellation:

```bash
curl -X POST http://127.0.0.1:8000/runs/<run_id>/cancel
```

Continue the same thread in a new run:

```bash
curl -X POST http://127.0.0.1:8000/runs \
  -H "Content-Type: application/json" \
  -d '{
    "thread_id": "tokyo-trip-001",
    "user_message": "Change the budget to 10000 and avoid red-eye flights."
  }'
```

The worker loads the latest persisted state for `tokyo-trip-001`, applies the new patch and saves a new checkpoint.

## Runtime event example

```text
run.queued
run.started
checkpoint.loaded
checkpoint.saved
run.completed
```

Application events such as `intent_detected`, `state_patch_applied` and `validation_finished` remain inside `AgentState.execution_trace`. This intentionally separates:

- infrastructure/run lifecycle events;
- agent reasoning and state-transition events.

## Restart recovery

At startup, `RuntimeManager` scans durable records left in `queued` or `running` state.

A previously running task is moved back to `queued`, receives a `run.recovered` event and is executed again. This demonstrates recovery semantics, but side-effecting tools such as booking or payment APIs would additionally require idempotency keys.

## Docker

```bash
docker compose up --build
```

The named volume persists `runtime_data/runtime.db` across container restarts.

The image:

- uses a multi-stage build;
- runs as a non-root user;
- excludes `.env`, local databases and development artifacts;
- exposes an HTTP health check without depending on `curl`.

## Kubernetes

A minimal manifest is provided:

```bash
kubectl apply -f deploy/k8s/runtime.yaml
```

It deliberately uses:

- one replica;
- a persistent volume;
- `Recreate` deployment strategy;
- readiness and liveness probes;
- resource requests and limits;
- a non-root security context.

SQLite and an in-process queue are not a truthful horizontally scalable architecture. Before increasing replicas, replace them with PostgreSQL plus Redis, Pub/Sub or another distributed dispatch system.

## Deliberate limitations

This is a cloud-runtime prototype, not a complete enterprise agent platform:

- SQLite instead of PostgreSQL
- in-process queue instead of distributed workers
- no worker lease or heartbeat
- cancellation only at cooperative execution boundaries
- no authentication, tenant isolation or quotas
- no external secret manager integration
- no tool-call idempotency ledger
- no OpenTelemetry backend or evaluation dashboard
- no real flight, hotel, payment or booking API

## Production-oriented next steps

A natural next version would add:

```text
PostgreSQL runs/checkpoints/events
+ Redis or Pub/Sub queue
+ worker lease and heartbeat
+ idempotent tool-call records
+ OpenTelemetry traces and metrics
+ authentication and tenant quotas
+ run-level canary version routing
```

See [`docs/cloud-runtime.md`](docs/cloud-runtime.md) for the execution model and design boundaries.

## How to describe the project

> A self-hosted Agent Runtime prototype that separates application-level planning, structured state updates and deterministic validation from cloud execution concerns such as run lifecycle, version pinning, durable checkpoints, worker dispatch, cancellation, restart recovery and event observability.
