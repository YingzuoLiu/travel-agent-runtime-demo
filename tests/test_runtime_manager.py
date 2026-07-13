import time

from runtime_service import (
    RunCreateRequest,
    RunStatus,
    RuntimeManager,
    SQLiteRunStore,
    build_default_registry,
)


def wait_for_terminal(manager: RuntimeManager, run_id: str, timeout: float = 3.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        run = manager.get_run(run_id)
        if run is not None and run.status.is_terminal:
            return run
        time.sleep(0.02)
    raise AssertionError(f"Run did not finish: {run_id}")


def test_manager_persists_state_and_events(tmp_path):
    store = SQLiteRunStore(tmp_path / "runtime.db")
    manager = RuntimeManager(store, build_default_registry())
    manager.start()
    try:
        first = manager.submit(
            RunCreateRequest(
                thread_id="trip-001",
                user_message="I want a 5-day Tokyo trip under 7000 SGD.",
            )
        )
        first_result = wait_for_terminal(manager, first.run_id)
        assert first_result.status == RunStatus.COMPLETED
        assert first_result.state is not None
        assert first_result.state.destination == "Tokyo"

        second = manager.submit(
            RunCreateRequest(
                thread_id="trip-001",
                user_message="Change the budget to 9000 and avoid red-eye flights.",
            )
        )
        second_result = wait_for_terminal(manager, second.run_id)
        assert second_result.state is not None
        assert second_result.state.destination == "Tokyo"
        assert second_result.state.budget == 9000
        assert second_result.state.itinerary is not None
        assert second_result.state.itinerary.flight_type == "daytime"

        event_types = [event.event_type for event in store.list_events(second.run_id)]
        assert event_types == [
            "run.queued",
            "run.started",
            "checkpoint.loaded",
            "checkpoint.saved",
            "run.completed",
        ]
    finally:
        manager.stop()


def test_store_survives_new_store_instance(tmp_path):
    database_path = tmp_path / "runtime.db"
    manager = RuntimeManager(SQLiteRunStore(database_path), build_default_registry())
    manager.start()
    try:
        submitted = manager.submit(
            RunCreateRequest(
                thread_id="persistent-thread",
                user_message="I want a 5-day Tokyo trip under 9000 SGD.",
            )
        )
        completed = wait_for_terminal(manager, submitted.run_id)
    finally:
        manager.stop()

    reopened = SQLiteRunStore(database_path)
    persisted = reopened.get_run(completed.run_id)
    assert persisted is not None
    assert persisted.status == RunStatus.COMPLETED
    assert reopened.load_thread_state("persistent-thread") is not None
