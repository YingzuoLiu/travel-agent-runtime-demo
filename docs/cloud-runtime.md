# Cloud Runtime Upgrade

Version `0.3.0` adds a small self-hosted cloud runtime around the existing travel application runtime.

## Architecture

```text
Client
  |
  v
FastAPI control API
  |  POST /runs
  v
RuntimeManager ---- AgentRegistry (agent_id + exact version)
  |
  +---- local worker queue
  |
  +---- SQLiteRunStore
          |- runs
          |- run_events
          `- thread_states / checkpoints
  |
  v
TravelAgentRuntime
  |- intent -> StatePatch -> reducer
  |- partial replan
  `- deterministic validator
```

The original `/agent/message` endpoint remains available for synchronous demos. The `/runs` API is the runtime-oriented path.

## Run lifecycle

```text
queued -> running -> completed
                  -> failed
queued/running    -> cancelled
```

Every run stores a stable `run_id`, `thread_id`, pinned agent version, input/output, timestamps, validation results, cancellation metadata and the latest serialized `AgentState`.

Important transitions are appended to an immutable event history:

```text
run.queued
run.started
checkpoint.loaded
checkpoint.saved
run.completed | run.failed | run.cancelled
```

## Restart recovery

On startup, the manager scans runs left in `queued` or `running` state. A previously running run is moved back to `queued`, receives a `run.recovered` event and is executed again.

This demonstrates durable recovery, but side-effecting tools would also need idempotency keys before using the pattern for bookings or payments.

## Deliberate limitations

This version uses SQLite and an in-process queue so the repository remains runnable without external services. Therefore:

- deploy one runtime replica only
- cancellation is cooperative at execution boundaries
- there is no distributed worker lease or heartbeat
- there is no tenant authentication, quota or secret manager integration
- external tool calls do not yet have idempotency records

A production-oriented next step is PostgreSQL for runs/checkpoints/events, Redis or Pub/Sub for distributed work dispatch, worker leases and heartbeats, and OpenTelemetry traces.
