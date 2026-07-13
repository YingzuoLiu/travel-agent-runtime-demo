# Travel Agent Runtime Demo

A runnable reference implementation of two related layers:

1. an **application-level Agent Runtime** for structured multi-turn travel planning;
2. a small **self-hosted cloud runtime** for durable run lifecycle management.

The project is offline-first: it does not require an LLM key, Redis, PostgreSQL, or Kubernetes to demonstrate the runtime mechanics.

## Architecture

```text
Client
  |
  v
FastAPI control API
  |- POST /agent/message   synchronous compatibility path
  `- POST /runs            asynchronous runtime path
          |
          v
RuntimeManager ---- AgentRegistry (agent_id + exact version)
  |
  +---- worker queue
  |
  +---- SQLiteRunStore
  |       |- runs
  |       |- run_events
  |       `- thread_states / checkpoints
  |
  v
TravelAgentRuntime
  |- intent -> StatePatch -> reducer
  |- partial replan
  |- deterministic validator
  `- blocker propagation
```

Both API paths read and write the same durable `thread_states` store. A thread created through `/agent/message` can therefore continue through `/runs`, and vice versa.

## What v0.3 demonstrates

- asynchronous `POST /runs` API;
- durable `run_id` lifecycle;
- exact Agent-version pinning;
- worker-based execution;
- SQLite-backed runs, events, and thread checkpoints;
- restart recovery for queued/running work;
- cooperative cancellation with an atomic completion guard;
- idempotent run submission through `client_request_id`;
- polling and Server-Sent Events APIs;
- Docker, Docker Compose, and a deliberately single-replica Kubernetes manifest;
- CI with Ruff, mypy, and pytest on Python 3.11 and 3.12.

## Why this is more than an API wrapper

A synchronous wrapper is simply:

```text
HTTP request -> agent.run() -> HTTP response
```

The `/runs` path treats execution as a first-class resource:

```text
queued -> running -> completed
                  -> failed
queued/running    -> cancelled
```

Each run stores its input/output, status, timestamps, attempt count, pinned Agent version, latest serialized state, cancellation metadata, and append-only event history.

## Application runtime

The travel Agent keeps important state outside the prompt:

```text
User message
  -> intent detection
  -> StatePatch
  -> reducer
  -> partial replan
  -> deterministic validator
  -> blocker or final response
```

Core components include typed `AgentState`, explicit patch transitions, nested-state reduction, deterministic constraint validation, partial replanning, blocker propagation, and application trace events.

## Quick start

```bash
python -m venv .venv
source .venv/bin/activate       # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt
pytest -q
uvicorn api.main:app --reload
```

## Synchronous compatibility API

```bash
curl -X POST http://127.0.0.1:8000/agent/message \
  -H "Content-Type: application/json" \
  -d '{
    "thread_id": "tokyo-trip-001",
    "user_message": "I want a 5-day Tokyo trip under 9000 SGD."
  }'
```

This endpoint executes in the request process but persists its updated state to the same SQLite checkpoint store used by asynchronous runs.

## Durable run API

Create a run:

```bash
curl -X POST http://127.0.0.1:8000/runs \
  -H "Content-Type: application/json" \
  -d '{
    "thread_id": "tokyo-trip-001",
    "user_message": "Change the budget to 10000 and avoid red-eye flights.",
    "agent_id": "travel-agent",
    "agent_version": "0.3.0",
    "client_request_id": "request-20260713-001"
  }'
```

Repeating the same request with the same `client_request_id` returns the existing run instead of creating a duplicate.

Inspect execution:

```bash
curl http://127.0.0.1:8000/runs/<run_id>
curl http://127.0.0.1:8000/runs/<run_id>/events
curl -N http://127.0.0.1:8000/runs/<run_id>/events/stream
curl -X POST http://127.0.0.1:8000/runs/<run_id>/cancel
```

## Cancellation semantics

Cancellation is cooperative: code already executing inside an Agent step is not forcibly interrupted. The store sets `cancel_requested` atomically, and completion uses a conditional update (`WHERE cancel_requested = 0`). A cancel arriving at the execution boundary therefore cannot be silently overwritten by a stale whole-row write.

## Restart recovery

At startup, the manager scans durable records left in `queued` or `running`. A previously running task is moved back to `queued`, receives a `run.recovered` event, and executes again.

This is safe for the current deterministic demo. Real booking or payment tools would additionally require per-tool-call idempotency records.

## Deployment boundary

SQLite and the in-process queue keep the project self-contained, but they are not a horizontally scalable architecture. The Kubernetes manifest therefore uses one replica and persistent storage.

Before increasing replicas, replace them with:

```text
PostgreSQL runs/checkpoints/events
+ Redis, Pub/Sub, or another distributed queue
+ worker lease and heartbeat
+ idempotent tool-call ledger
+ OpenTelemetry traces and metrics
```

## Tests

The suite covers:

- state patching and deterministic validation;
- multi-turn checkpoint continuation;
- state sharing between synchronous and asynchronous APIs;
- cancellation before start and after an execution boundary;
- restart recovery;
- two-worker execution;
- idempotent run submission;
- persistent events and state across store instances.

## Deliberate limitations

This is a cloud-runtime prototype, not a complete Agent Platform:

- SQLite instead of PostgreSQL;
- local queue instead of distributed workers;
- no worker lease or heartbeat;
- no authentication, tenant isolation, or quotas;
- no external secret manager integration;
- no tool-call idempotency ledger yet;
- no code/tool sandbox yet;
- no OpenTelemetry backend or evaluation dashboard;
- no real flight, hotel, payment, or booking API.

> A self-hosted Agent Runtime prototype that separates application-level planning, structured state updates, and deterministic validation from cloud execution concerns such as run lifecycle, version pinning, durable checkpoints, worker dispatch, cancellation, restart recovery, idempotent submission, and event observability.
