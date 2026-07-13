# Travel Agent Runtime Demo

A runnable reference implementation of three related layers:

1. an **application-level Agent Runtime** for structured multi-turn travel planning;
2. a small **self-hosted cloud runtime** for durable run lifecycle management;
3. **policy-enforced registered-tool sandboxing** using restricted subprocess workers.

The project is offline-first. It does not require an LLM key, Redis, PostgreSQL, or Kubernetes to demonstrate the runtime mechanics.

## Why this project exists

Long-horizon Agent failures are not only model-quality problems. They also come from state drift, silently skipped constraints, ambiguous completion metrics, duplicate execution, cancellation races, restart recovery, and unsafe tool boundaries.

The project started as an application-runtime experiment around typed state, validation, retry, and partial replanning. An ablation study then produced a counterintuitive result:

```text
full runtime completion rate: 50%
no-validator completion rate: 75%
```

The higher no-validator score was misleading. Trace inspection showed that the apparently completed plan violated the user's budget. The validator reduced nominal completion rate because it surfaced an invalid plan instead of silently accepting it.

The detailed scenarios, configurations, traces, and findings are documented in [`FINDINGS.md`](FINDINGS.md).

That experiment established the reliability theme that now connects the whole repository:

> Do not let the system look successful while failing somewhere the user or operator cannot see.

The later engineering work extends that same objective across additional boundaries:

- typed state and deterministic validation make constraint violations visible;
- durable run records make execution state observable across requests and restarts;
- atomic completion and cancellation updates prevent stale writes from hiding races;
- idempotent submission prevents network retries from silently duplicating work;
- tool allowlists and schema validation prevent unapproved execution;
- subprocess timeouts, resource limits, and `tini` prevent runaway work from leaking resources.

The engineering layer is therefore not a replacement for the evaluation work. It is the next layer of the same reliability problem.

## Architecture

```text
Client
  |
  v
FastAPI control API
  |- POST /agent/message
  |- POST /runs
  `- POST /tools/{tool}/execute
          |
          +-------------------------------+
          |                               |
          v                               v
RuntimeManager ---- AgentRegistry     ToolSandbox ---- ToolRegistry
  |                                      |
  +---- worker queue                     `- restricted subprocess
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

Both Agent API paths read and write the same durable `thread_states` store. Tool executions may optionally attach their start and finish events to a durable `run_id`.

## What the project demonstrates

### Evaluation and behavioral analysis

- controlled ablations for validator and retry behavior;
- scenario-level completion, blocker, replan, and validation measurements;
- trace inspection to distinguish real success from silent constraint violations;
- a concrete finding that completion rate alone is not a sufficient Agent metric;
- a bug discovered through evaluation: confirmation intent was previously treated as an unsupported request;
- a remaining product gap: budget failure needs alternative suggestions rather than repeated invalid replans.

See [`FINDINGS.md`](FINDINGS.md) for the full study.

### Application runtime

- typed `AgentState` with Pydantic;
- explicit `StatePatch` transitions;
- reducer-based nested-state updates;
- partial replanning after changed constraints;
- deterministic budget, itinerary, and flight validation;
- optional geography grounding;
- visible blockers and application trace events.

### Cloud runtime

- asynchronous `POST /runs` API;
- durable `run_id` lifecycle;
- exact Agent-version pinning;
- worker-based execution;
- SQLite-backed runs, events, and thread checkpoints;
- restart recovery for queued/running work;
- cooperative cancellation with an atomic completion guard;
- idempotent run submission through `client_request_id`;
- polling and Server-Sent Events APIs;
- Docker, Docker Compose, and a deliberately single-replica Kubernetes manifest.

### Registered-tool sandbox

- server-side tool allowlist;
- Pydantic argument validation with unknown fields rejected;
- fixed executable and fixed worker script;
- fresh temporary working directory per execution;
- scrubbed environment that does not forward runtime secrets;
- wall-clock timeout and process-group termination;
- bounded returned output;
- POSIX CPU, memory, file-descriptor, and core-dump limits;
- `tini` as container PID 1 to reap orphaned descendants;
- structured execution results;
- optional linkage to append-only run events.

The sandbox intentionally does **not** accept Python source, shell commands, executable paths, or arbitrary module names.

## Quick start

```bash
python -m venv .venv
source .venv/bin/activate       # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt
pytest -q
uvicorn api.main:app --reload
```

Health endpoints:

```bash
curl http://127.0.0.1:8000/health
curl http://127.0.0.1:8000/ready
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

This endpoint executes in the request process but saves its updated state to the same checkpoint store used by asynchronous runs.

## Durable run API

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

Repeating the same `client_request_id` returns the existing run instead of creating a duplicate.

```bash
curl http://127.0.0.1:8000/runs/<run_id>
curl http://127.0.0.1:8000/runs/<run_id>/events
curl -N http://127.0.0.1:8000/runs/<run_id>/events/stream
curl -X POST http://127.0.0.1:8000/runs/<run_id>/cancel
```

## Sandboxed tool API

List the only tools clients are allowed to request:

```bash
curl http://127.0.0.1:8000/tools
```

Execute a deterministic tool:

```bash
curl -X POST http://127.0.0.1:8000/tools/route_cost_summary/execute \
  -H "Content-Type: application/json" \
  -d '{
    "run_id": null,
    "arguments": {
      "transport_cost": 2000,
      "hotel_cost": 3000,
      "activity_cost": 1000,
      "budget": 7000
    }
  }'
```

An unknown tool is denied before any subprocess starts. Invalid arguments are rejected before execution. The default registry exposes:

```text
route_cost_summary
rank_trip_options
```

## Security boundary

The current backend is a **registered-tool process sandbox**, not a general untrusted-code service.

It protects the runtime from accidental or unauthorized tool selection, malformed inputs, inherited API keys, runaway execution time, and excessive POSIX resource use. Registered tools remain trusted service code.

The descriptor reports `network_mode: host` because the process backend does not claim to block outbound network access. It also does not create a private mount namespace, so it cannot safely run arbitrary user code or untrusted third-party MCP servers.

The Docker image starts the service under `tini`, which runs as container PID 1, forwards signals, and reaps orphaned descendants. This prevents timed-out tools that spawn child processes from leaving unreaped zombies in long-running containers. Running directly on a host still relies on the host init or service manager for orphan reaping.

A stronger boundary should use an ephemeral container, Kubernetes Job, gVisor sandbox, or microVM with:

```text
read-only root filesystem
+ isolated writable workspace
+ no host mounts
+ dropped capabilities
+ seccomp/AppArmor
+ disabled or allowlisted network
+ non-root UID
+ CPU/memory/PID limits
+ execution deadline
+ approved image/dependency set
```

See [`docs/cloud-runtime.md`](docs/cloud-runtime.md) for the detailed execution and security model.

## Agent integration boundary

The sandbox is currently exposed as an independent control-plane API. `TravelAgentRuntime` does not yet invoke tools from an LLM or planner-driven tool loop.

This keeps the current threat model narrow and testable: external clients may request only registered tools through the API. A later Agent tool-calling integration must add per-Agent tool permissions, prompt-injection defenses, approval policies for side effects, per-call idempotency, and trace linkage between planner decisions and sandbox executions.

## Cancellation semantics

Cancellation is cooperative: code already executing inside an Agent step is not forcibly interrupted. The database sets `cancel_requested` atomically, and completion uses `WHERE cancel_requested = 0`. A cancel arriving at the execution boundary cannot be overwritten by a stale whole-row write.

## Restart recovery

At startup, `RuntimeManager` requeues durable records left in `queued` or `running`. A previously running task receives a `run.recovered` event and executes again.

This is safe for the deterministic demo. Booking and payment tools would additionally require per-tool-call idempotency records.

## Tests and CI

The suite covers:

- state patching and deterministic validation;
- multi-turn checkpoint continuation;
- state sharing between synchronous and asynchronous APIs;
- cancellation before start and after an execution boundary;
- restart recovery and two-worker execution;
- idempotent run submission;
- tool allowlisting and argument-schema rejection;
- subprocess timeout termination;
- parent-secret environment scrubbing;
- sandbox API execution and run-event linkage.

GitHub Actions runs compile checks, Ruff, scoped mypy, and pytest on Python 3.11 and 3.12. A separate container smoke job builds the Docker image and verifies that `/usr/bin/tini` is the configured entrypoint.

## Deployment boundary

SQLite and the in-process queue keep the project self-contained, but they are not horizontally scalable. The Kubernetes manifest therefore uses one replica and persistent storage.

Before increasing replicas, replace them with:

```text
PostgreSQL runs/checkpoints/events
+ Redis, Pub/Sub, or another distributed queue
+ worker lease and heartbeat
+ idempotent tool-call ledger
+ OpenTelemetry traces and metrics
+ container-backed sandbox workers
```

## Deliberate limitations

This is a cloud-runtime prototype, not a complete Agent Platform:

- SQLite instead of PostgreSQL;
- local queue instead of distributed workers;
- no worker lease or heartbeat;
- no authentication, tenant isolation, or quotas;
- no external secret manager integration;
- no tool-call idempotency ledger yet;
- process sandbox does not isolate host networking or the full host filesystem;
- POSIX resource limits are weaker on Windows;
- no arbitrary user-code execution endpoint;
- sandbox is not yet integrated into the Agent decision loop;
- no OpenTelemetry backend or evaluation dashboard;
- no real flight, hotel, payment, or booking API.

> An evidence-driven Agent Runtime prototype that connects behavioral evaluation with structured state, deterministic validation, durable execution lifecycle, checkpoint recovery, cancellation safety, idempotent submission, event observability, and policy-enforced registered-tool sandboxing.
