from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path
from typing import Any

from agent.state import AgentState, utc_now
from .models import RunEvent, RunRecord, RunStatus


class SQLiteRunStore:
    """Durable run, event and thread-state storage backed by SQLite."""

    def __init__(self, database_path: str | Path) -> None:
        self.database_path = str(database_path)
        self._lock = threading.RLock()
        Path(self.database_path).parent.mkdir(parents=True, exist_ok=True)
        self.initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA foreign_keys=ON")
        return connection

    def initialize(self) -> None:
        with self._lock, self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS runs (
                    run_id TEXT PRIMARY KEY,
                    thread_id TEXT NOT NULL,
                    agent_id TEXT NOT NULL,
                    agent_version TEXT NOT NULL,
                    status TEXT NOT NULL,
                    input_message TEXT NOT NULL,
                    state_json TEXT,
                    output_message TEXT,
                    validation_errors_json TEXT NOT NULL,
                    error TEXT,
                    attempt INTEGER NOT NULL,
                    cancel_requested INTEGER NOT NULL,
                    client_request_id TEXT UNIQUE,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    started_at TEXT,
                    completed_at TEXT
                );

                CREATE INDEX IF NOT EXISTS idx_runs_thread_id ON runs(thread_id);
                CREATE INDEX IF NOT EXISTS idx_runs_status ON runs(status);

                CREATE TABLE IF NOT EXISTS run_events (
                    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id TEXT NOT NULL,
                    sequence INTEGER NOT NULL,
                    event_type TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE(run_id, sequence),
                    FOREIGN KEY(run_id) REFERENCES runs(run_id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS thread_states (
                    thread_id TEXT PRIMARY KEY,
                    state_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                """
            )
            columns = {
                row["name"]
                for row in connection.execute("PRAGMA table_info(runs)").fetchall()
            }
            if "client_request_id" not in columns:
                connection.execute("ALTER TABLE runs ADD COLUMN client_request_id TEXT")
                connection.execute(
                    "CREATE UNIQUE INDEX IF NOT EXISTS idx_runs_client_request_id "
                    "ON runs(client_request_id) WHERE client_request_id IS NOT NULL"
                )

    def ping(self) -> None:
        with self._connect() as connection:
            connection.execute("SELECT 1").fetchone()

    def create_run(self, run: RunRecord) -> RunRecord:
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                INSERT INTO runs (
                    run_id, thread_id, agent_id, agent_version, status,
                    input_message, state_json, output_message,
                    validation_errors_json, error, attempt, cancel_requested,
                    client_request_id, created_at, updated_at, started_at, completed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                self._run_values(run),
            )
        return run

    def get_run(self, run_id: str) -> RunRecord | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM runs WHERE run_id = ?", (run_id,)
            ).fetchone()
        return self._row_to_run(row) if row else None

    def get_run_by_client_request_id(self, client_request_id: str) -> RunRecord | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM runs WHERE client_request_id = ?",
                (client_request_id,),
            ).fetchone()
        return self._row_to_run(row) if row else None

    def update_run(self, run: RunRecord) -> RunRecord:
        run.updated_at = utc_now()
        with self._lock, self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE runs SET
                    thread_id = ?, agent_id = ?, agent_version = ?, status = ?,
                    input_message = ?, state_json = ?, output_message = ?,
                    validation_errors_json = ?, error = ?, attempt = ?,
                    cancel_requested = ?, client_request_id = ?, created_at = ?,
                    updated_at = ?, started_at = ?, completed_at = ?
                WHERE run_id = ?
                """,
                (*self._run_values(run)[1:], run.run_id),
            )
            if cursor.rowcount != 1:
                raise KeyError(f"Run not found: {run.run_id}")
        return run

    def request_cancel(self, run_id: str) -> RunRecord:
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                UPDATE runs
                SET cancel_requested = 1, updated_at = ?
                WHERE run_id = ? AND status NOT IN (?, ?, ?)
                """,
                (
                    utc_now(),
                    run_id,
                    RunStatus.COMPLETED.value,
                    RunStatus.FAILED.value,
                    RunStatus.CANCELLED.value,
                ),
            )
            row = connection.execute(
                "SELECT * FROM runs WHERE run_id = ?", (run_id,)
            ).fetchone()
        if row is None:
            raise KeyError(f"Run not found: {run_id}")
        return self._row_to_run(row)

    def complete_run_if_not_cancelled(self, run: RunRecord) -> bool:
        run.updated_at = utc_now()
        with self._lock, self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE runs SET
                    thread_id = ?, agent_id = ?, agent_version = ?, status = ?,
                    input_message = ?, state_json = ?, output_message = ?,
                    validation_errors_json = ?, error = ?, attempt = ?,
                    client_request_id = ?, created_at = ?, updated_at = ?,
                    started_at = ?, completed_at = ?
                WHERE run_id = ? AND cancel_requested = 0
                """,
                (
                    run.thread_id,
                    run.agent_id,
                    run.agent_version,
                    run.status.value,
                    run.input_message,
                    run.state.model_dump_json() if run.state else None,
                    run.output_message,
                    json.dumps(run.validation_errors),
                    run.error,
                    run.attempt,
                    run.client_request_id,
                    run.created_at,
                    run.updated_at,
                    run.started_at,
                    run.completed_at,
                    run.run_id,
                ),
            )
        return cursor.rowcount == 1

    def list_recoverable_runs(self) -> list[RunRecord]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM runs WHERE status IN (?, ?) ORDER BY created_at",
                (RunStatus.QUEUED.value, RunStatus.RUNNING.value),
            ).fetchall()
        return [self._row_to_run(row) for row in rows]

    def append_event(
        self,
        run_id: str,
        event_type: str,
        payload: dict[str, Any] | None = None,
    ) -> RunEvent:
        with self._lock, self._connect() as connection:
            sequence = int(
                connection.execute(
                    "SELECT COALESCE(MAX(sequence), 0) + 1 FROM run_events WHERE run_id = ?",
                    (run_id,),
                ).fetchone()[0]
            )
            event = RunEvent(
                run_id=run_id,
                sequence=sequence,
                event_type=event_type,
                payload=payload or {},
            )
            cursor = connection.execute(
                """
                INSERT INTO run_events (
                    run_id, sequence, event_type, payload_json, created_at
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    event.run_id,
                    event.sequence,
                    event.event_type,
                    json.dumps(event.payload),
                    event.created_at,
                ),
            )
            event.event_id = int(cursor.lastrowid)
        return event

    def list_events(self, run_id: str, *, after_sequence: int = 0) -> list[RunEvent]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM run_events
                WHERE run_id = ? AND sequence > ?
                ORDER BY sequence
                """,
                (run_id, after_sequence),
            ).fetchall()
        return [
            RunEvent(
                event_id=row["event_id"],
                run_id=row["run_id"],
                sequence=row["sequence"],
                event_type=row["event_type"],
                payload=json.loads(row["payload_json"]),
                created_at=row["created_at"],
            )
            for row in rows
        ]

    def save_thread_state(self, state: AgentState) -> None:
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                INSERT INTO thread_states (thread_id, state_json, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(thread_id) DO UPDATE SET
                    state_json = excluded.state_json,
                    updated_at = excluded.updated_at
                """,
                (state.thread_id, state.model_dump_json(), utc_now()),
            )

    def load_thread_state(self, thread_id: str) -> AgentState | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT state_json FROM thread_states WHERE thread_id = ?",
                (thread_id,),
            ).fetchone()
        return AgentState.model_validate_json(row["state_json"]) if row else None

    @staticmethod
    def _run_values(run: RunRecord) -> tuple[Any, ...]:
        return (
            run.run_id,
            run.thread_id,
            run.agent_id,
            run.agent_version,
            run.status.value,
            run.input_message,
            run.state.model_dump_json() if run.state else None,
            run.output_message,
            json.dumps(run.validation_errors),
            run.error,
            run.attempt,
            int(run.cancel_requested),
            run.client_request_id,
            run.created_at,
            run.updated_at,
            run.started_at,
            run.completed_at,
        )

    @staticmethod
    def _row_to_run(row: sqlite3.Row) -> RunRecord:
        keys = set(row.keys())
        return RunRecord(
            run_id=row["run_id"],
            thread_id=row["thread_id"],
            agent_id=row["agent_id"],
            agent_version=row["agent_version"],
            status=RunStatus(row["status"]),
            input_message=row["input_message"],
            state=(
                AgentState.model_validate_json(row["state_json"])
                if row["state_json"]
                else None
            ),
            output_message=row["output_message"],
            validation_errors=json.loads(row["validation_errors_json"]),
            error=row["error"],
            attempt=row["attempt"],
            cancel_requested=bool(row["cancel_requested"]),
            client_request_id=(
                row["client_request_id"] if "client_request_id" in keys else None
            ),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            started_at=row["started_at"],
            completed_at=row["completed_at"],
        )
