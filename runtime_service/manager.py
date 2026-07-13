from __future__ import annotations

import queue
import threading
import traceback
from uuid import uuid4

from agent.state import AgentState, utc_now

from .models import RunCreateRequest, RunRecord, RunStatus
from .registry import AgentRegistry
from .store import SQLiteRunStore


class RuntimeManager:
    """Durable run lifecycle manager with a small in-process worker pool.

    The queue is intentionally local for the demo. Because run metadata and
    checkpoints live in SQLite, queued/running work can be recovered when the
    process restarts. A production deployment can replace the queue with Redis,
    Pub/Sub or a workflow engine while keeping the API and storage contracts.
    """

    def __init__(
        self,
        store: SQLiteRunStore,
        registry: AgentRegistry,
        *,
        worker_count: int = 1,
    ) -> None:
        if worker_count < 1:
            raise ValueError("worker_count must be at least 1")
        self.store = store
        self.registry = registry
        self.worker_count = worker_count
        self._queue: queue.Queue[str | None] = queue.Queue()
        self._workers: list[threading.Thread] = []
        self._started = False
        self._lock = threading.Lock()

    def start(self) -> None:
        with self._lock:
            if self._started:
                return
            self._started = True
            for index in range(self.worker_count):
                worker = threading.Thread(
                    target=self._worker_loop,
                    name=f"agent-runtime-worker-{index}",
                    daemon=True,
                )
                worker.start()
                self._workers.append(worker)

            for run in self.store.list_recoverable_runs():
                if run.status == RunStatus.RUNNING:
                    run.status = RunStatus.QUEUED
                    run.started_at = None
                    run.error = None
                    self.store.update_run(run)
                    self.store.append_event(
                        run.run_id,
                        "run.recovered",
                        {"reason": "runtime_restart"},
                    )
                self._queue.put(run.run_id)

    def stop(self) -> None:
        with self._lock:
            if not self._started:
                return
            for _ in self._workers:
                self._queue.put(None)
            for worker in self._workers:
                worker.join(timeout=5)
            self._workers.clear()
            self._started = False

    def submit(self, request: RunCreateRequest) -> RunRecord:
        self.registry.resolve(request.agent_id, request.agent_version)
        run = RunRecord(
            run_id=f"run_{uuid4().hex}",
            thread_id=request.thread_id,
            agent_id=request.agent_id,
            agent_version=request.agent_version,
            status=RunStatus.QUEUED,
            input_message=request.user_message,
            state=request.state,
        )
        self.store.create_run(run)
        self.store.append_event(
            run.run_id,
            "run.queued",
            {
                "agent_id": run.agent_id,
                "agent_version": run.agent_version,
                "thread_id": run.thread_id,
            },
        )
        self._queue.put(run.run_id)
        return run

    def get_run(self, run_id: str) -> RunRecord | None:
        return self.store.get_run(run_id)

    def request_cancel(self, run_id: str) -> RunRecord:
        run = self._require_run(run_id)
        if run.status.is_terminal:
            return run
        run.cancel_requested = True
        self.store.update_run(run)
        self.store.append_event(
            run_id,
            "run.cancel_requested",
            {"status": run.status.value},
        )
        return run

    def _worker_loop(self) -> None:
        while True:
            run_id = self._queue.get()
            try:
                if run_id is None:
                    return
                self._execute_run(run_id)
            finally:
                self._queue.task_done()

    def _execute_run(self, run_id: str) -> None:
        run = self._require_run(run_id)
        if run.status.is_terminal:
            return
        if run.cancel_requested:
            self._mark_cancelled(run, reason="cancelled_before_start")
            return

        run.status = RunStatus.RUNNING
        run.started_at = utc_now()
        run.attempt += 1
        self.store.update_run(run)
        self.store.append_event(
            run.run_id,
            "run.started",
            {"attempt": run.attempt},
        )

        try:
            runtime = self.registry.resolve(run.agent_id, run.agent_version)
            persisted_state = self.store.load_thread_state(run.thread_id)
            state = run.state or persisted_state or AgentState(thread_id=run.thread_id)
            self.store.append_event(
                run.run_id,
                "checkpoint.loaded",
                {
                    "source": (
                        "request"
                        if run.state is not None
                        else "thread_store"
                        if persisted_state is not None
                        else "new_state"
                    )
                },
            )

            result = runtime.handle_user_message(state, run.input_message)
            latest = self._require_run(run_id)
            if latest.cancel_requested:
                latest.state = result.state
                self._mark_cancelled(latest, reason="cancelled_after_execution_boundary")
                return

            run.state = result.state
            run.output_message = result.message
            run.validation_errors = result.validation_errors
            run.status = RunStatus.COMPLETED
            run.completed_at = utc_now()
            self.store.save_thread_state(result.state)
            self.store.update_run(run)
            self.store.append_event(
                run.run_id,
                "checkpoint.saved",
                {
                    "thread_id": run.thread_id,
                    "trace_events": len(result.state.execution_trace),
                },
            )
            self.store.append_event(
                run.run_id,
                "run.completed",
                {"validation_errors": result.validation_errors},
            )
        except Exception as exc:  # pragma: no cover - injected failures only
            run = self._require_run(run_id)
            run.status = RunStatus.FAILED
            run.error = f"{type(exc).__name__}: {exc}"
            run.completed_at = utc_now()
            self.store.update_run(run)
            self.store.append_event(
                run.run_id,
                "run.failed",
                {
                    "error": run.error,
                    "traceback": traceback.format_exc(limit=5),
                },
            )

    def _mark_cancelled(self, run: RunRecord, *, reason: str) -> None:
        run.status = RunStatus.CANCELLED
        run.completed_at = utc_now()
        self.store.update_run(run)
        self.store.append_event(run.run_id, "run.cancelled", {"reason": reason})

    def _require_run(self, run_id: str) -> RunRecord:
        run = self.store.get_run(run_id)
        if run is None:
            raise KeyError(f"Run not found: {run_id}")
        return run
