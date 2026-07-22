"""Characterization of the current SQLite schema produced by SQLiteRunStore.

This is the baseline for Phase 2 of the domain-generalization plan, which
adds `domain_id`/`schema_version` columns to `runs` and `thread_states` via
an `ALTER TABLE ADD COLUMN` migration (the same pattern already used for
`client_request_id`). Locking the current column set first makes it
possible to prove the migration is additive and does not silently change
or drop an existing column.
"""

from __future__ import annotations

import sqlite3

from runtime_service.store import SQLiteRunStore

EXPECTED_COLUMNS = {
    "runs": [
        ("run_id", "TEXT", 0, 1),
        ("thread_id", "TEXT", 1, 0),
        ("agent_id", "TEXT", 1, 0),
        ("agent_version", "TEXT", 1, 0),
        ("status", "TEXT", 1, 0),
        ("input_message", "TEXT", 1, 0),
        ("state_json", "TEXT", 0, 0),
        ("output_message", "TEXT", 0, 0),
        ("validation_errors_json", "TEXT", 1, 0),
        ("error", "TEXT", 0, 0),
        ("attempt", "INTEGER", 1, 0),
        ("cancel_requested", "INTEGER", 1, 0),
        ("client_request_id", "TEXT", 0, 0),
        ("created_at", "TEXT", 1, 0),
        ("updated_at", "TEXT", 1, 0),
        ("started_at", "TEXT", 0, 0),
        ("completed_at", "TEXT", 0, 0),
    ],
    "run_events": [
        ("event_id", "INTEGER", 0, 1),
        ("run_id", "TEXT", 1, 0),
        ("sequence", "INTEGER", 1, 0),
        ("event_type", "TEXT", 1, 0),
        ("payload_json", "TEXT", 1, 0),
        ("created_at", "TEXT", 1, 0),
    ],
    "thread_states": [
        ("thread_id", "TEXT", 0, 1),
        ("state_json", "TEXT", 1, 0),
        ("updated_at", "TEXT", 1, 0),
    ],
}


def _columns(database_path) -> dict[str, list[tuple]]:
    connection = sqlite3.connect(database_path)
    connection.row_factory = sqlite3.Row
    try:
        result = {}
        for table in EXPECTED_COLUMNS:
            rows = connection.execute(f"PRAGMA table_info({table})").fetchall()
            result[table] = [
                (row["name"], row["type"], row["notnull"], row["pk"])
                for row in rows
            ]
        return result
    finally:
        connection.close()


def test_schema_matches_current_column_snapshot(tmp_path):
    SQLiteRunStore(tmp_path / "runtime.db")

    columns = _columns(tmp_path / "runtime.db")
    assert columns == EXPECTED_COLUMNS


def test_expected_tables_are_exactly_runs_run_events_thread_states(tmp_path):
    SQLiteRunStore(tmp_path / "runtime.db")

    connection = sqlite3.connect(tmp_path / "runtime.db")
    try:
        rows = connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
        ).fetchall()
    finally:
        connection.close()

    assert {row[0] for row in rows} == set(EXPECTED_COLUMNS)
