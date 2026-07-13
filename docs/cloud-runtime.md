# Cloud Runtime Upgrade

Version `0.3.0` adds a self-hosted execution-management layer around the travel application runtime.

## Architecture

```text
Client
  |
  v
FastAPI API
  |- /agent/message
  `- /runs
        |
        v
RuntimeManager ---- AgentRegistry
  |
  +---- local worker queue
  |
  +---- SQLiteRunStore
          |- runs
          |- run_events
          `- thread_states / checkpoints
```

Both API paths use the same durable `thread_states` table. This avoids split-brain conversation state when a client switches between the synchronous compatibility endpoint and the asynchronous run API.

## Run lifecycle

```text
queued -> running -> completed
                  -> failed
queued/running    -> cancelled
```

Every run records its stable `run_id`, thread, pinned Agent version, input/output, timestamps, validation results, cancellation metadata, optional `client_request_id`, and latest serialized `AgentState`.

Important transitions are append-only events:

```text
run.queued
run.started
checkpoint.loaded
checkpoint.saved
run.completed | run.failed | run.cancelled
```

## Submission idempotency

Clients may send a `client_request_id` when creating a run. The database applies a unique constraint to this field. Repeating the same submission returns the existing run instead of creating another queued task.

This protects the control API from duplicate runs caused by HTTP retries. It is separate from tool-call idempotency: future booking or payment tools still need their own per-call ledger.

## Cancellation race handling

Cancellation remains cooperative because an in-process Agent step cannot be forcibly interrupted safely. However, cancellation state is no longer protected only by a read-then-write sequence:

1. `request_cancel` sets `cancel_requested = 1` directly in the database;
2. final completion uses a conditional update with `WHERE cancel_requested = 0`;
3. if the condition fails, the run is finalized as cancelled and no thread checkpoint is committed.

This closes the boundary race where a stale `RunRecord` could previously overwrite a cancel request.

## Restart recovery

On startup, the manager scans records left in `queued` or `running`. A previously running run is moved back to `queued`, receives `run.recovered`, and is executed again.

The test suite verifies recovery, cancellation before start, cancellation at an execution boundary, two-worker execution, shared thread state, and submission idempotency.

## Deliberate limitations

SQLite and an in-process queue keep the repository runnable without external services. Therefore:

- deploy one runtime replica only;
- there is no distributed worker lease or heartbeat;
- cancellation occurs at cooperative execution boundaries;
- there is no tenant authentication, quota, or secret-manager integration;
- external side-effecting tools do not yet have idempotency records;
- there is no tool/code sandbox yet.

A production-oriented next step is PostgreSQL for runs/checkpoints/events, Redis or Pub/Sub for distributed work dispatch, worker leases and heartbeats, a tool-call idempotency ledger, and OpenTelemetry traces.
