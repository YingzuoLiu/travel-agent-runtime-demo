import threading
import time

from agent.runtime import RuntimeResponse, TravelAgentRuntime
from agent.state import AgentState
from runtime_service import (
    AgentRegistry,
    RunCreateRequest,
    RunRecord,
    RunStatus,
    RuntimeManager,
    SQLiteRunStore,
    build_default_registry,
)


def wait_for_terminal(manager: RuntimeManager, run_id: str, timeout: float = 10.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        run = manager.get_run(run_id)
        if run is not None and run.status.is_terminal:
            return run
        time.sleep(0.02)
    raise AssertionError(f"Run did not finish: {run_id}")


class BlockingRuntime(TravelAgentRuntime):
    def __init__(self, started: threading.Event, release: threading.Event):
        super().__init__()
        self.started = started
        self.release = release

    def handle_user_message(self, state: AgentState, user_message: str) -> RuntimeResponse:
        self.started.set()
        if not self.release.wait(timeout=10):
            raise TimeoutError("test release event was not set")
        return super().handle_user_message(state, user_message)


def blocking_registry(started: threading.Event, release: threading.Event) -> AgentRegistry:
    registry = AgentRegistry()
    registry.register(
        "travel-agent",
        "0.3.0",
        lambda: BlockingRuntime(started, release),
        description="Blocking test runtime",
    )
    return registry


def test_manager_persists_state_and_events(tmp_path):
    store = SQLiteRunStore(tmp_path / "runtime.db")
    manager = RuntimeManager(store, build_default_registry())
    manager.start()
    try:
        first = manager.submit(RunCreateRequest(thread_id="trip-001", user_message="I want a 5-day Tokyo trip under 7000 SGD."))
        first_result = wait_for_terminal(manager, first.run_id)
        assert first_result.status == RunStatus.COMPLETED
        assert first_result.state is not None
        assert first_result.state.destination == "Tokyo"
        second = manager.submit(RunCreateRequest(thread_id="trip-001", user_message="Change the budget to 9000 and avoid red-eye flights."))
        second_result = wait_for_terminal(manager, second.run_id)
        assert second_result.state is not None
        assert second_result.state.destination == "Tokyo"
        assert second_result.state.budget == 9000
        assert second_result.state.itinerary is not None
        assert second_result.state.itinerary.flight_type == "daytime"
    finally:
        manager.stop()


def test_cancelled_before_start(tmp_path):
    store = SQLiteRunStore(tmp_path / "runtime.db")
    manager = RuntimeManager(store, build_default_registry())
    submitted = manager.submit(RunCreateRequest(thread_id="cancel-before", user_message="I want a 5-day Tokyo trip under 9000 SGD."))
    manager.request_cancel(submitted.run_id)
    manager.start()
    try:
        result = wait_for_terminal(manager, submitted.run_id)
        assert result.status == RunStatus.CANCELLED
        events = [event.event_type for event in store.list_events(submitted.run_id)]
        assert "run.cancel_requested" in events
        assert "run.cancelled" in events
    finally:
        manager.stop()


def test_cancelled_after_execution_boundary(tmp_path):
    started = threading.Event()
    release = threading.Event()
    store = SQLiteRunStore(tmp_path / "runtime.db")
    manager = RuntimeManager(store, blocking_registry(started, release))
    manager.start()
    try:
        submitted = manager.submit(RunCreateRequest(thread_id="cancel-running", user_message="I want a 5-day Tokyo trip under 9000 SGD."))
        assert started.wait(timeout=5)
        manager.request_cancel(submitted.run_id)
        release.set()
        result = wait_for_terminal(manager, submitted.run_id)
        assert result.status == RunStatus.CANCELLED
        assert store.load_thread_state("cancel-running") is None
        reasons = [event.payload.get("reason") for event in store.list_events(submitted.run_id) if event.event_type == "run.cancelled"]
        assert reasons == ["cancelled_after_execution_boundary"]
        # A cancel that commits before finalize_completed_run's compare-and-set
        # UPDATE must win: no checkpoint or completion event may appear, even
        # though the runtime step itself ran to completion.
        event_types = [event.event_type for event in store.list_events(submitted.run_id)]
        assert "checkpoint.saved" not in event_types
        assert "run.completed" not in event_types
    finally:
        release.set()
        manager.stop()


def test_running_run_is_recovered_after_restart(tmp_path):
    database_path = tmp_path / "runtime.db"
    store = SQLiteRunStore(database_path)
    run = RunRecord(run_id="run_recovery_test", thread_id="recovery-thread", agent_id="travel-agent", agent_version="0.3.0", status=RunStatus.RUNNING, input_message="I want a 5-day Tokyo trip under 9000 SGD.", attempt=1)
    store.create_run(run)
    store.append_event(run.run_id, "run.started", {"attempt": 1})
    manager = RuntimeManager(SQLiteRunStore(database_path), build_default_registry())
    manager.start()
    try:
        result = wait_for_terminal(manager, run.run_id)
        # No extra wait beyond wait_for_terminal's own polling: the moment
        # `result.status` is observed as terminal, the checkpoint and its
        # describing events must already be committed alongside it.
        assert result.status == RunStatus.COMPLETED
        assert result.attempt == 2
        events = [event.event_type for event in manager.store.list_events(run.run_id)]
        assert "run.recovered" in events
        assert "checkpoint.saved" in events
        assert events[-2] == "checkpoint.saved"
        assert events[-1] == "run.completed"
        assert manager.store.load_thread_state("recovery-thread") is not None
    finally:
        manager.stop()


def test_finalize_completed_run_is_idempotent_on_duplicate_call(tmp_path):
    store = SQLiteRunStore(tmp_path / "runtime.db")
    run = RunRecord(
        run_id="run_finalize_test",
        thread_id="finalize-thread",
        agent_id="travel-agent",
        agent_version="0.3.0",
        status=RunStatus.RUNNING,
        input_message="I want a 5-day Tokyo trip under 9000 SGD.",
        attempt=1,
    )
    store.create_run(run)
    run.state = AgentState(thread_id="finalize-thread", destination="Tokyo", days=5, budget=9000)
    run.output_message = "Planned."
    run.validation_errors = []

    first = store.finalize_completed_run(run)
    assert first is True
    assert run.status == RunStatus.COMPLETED

    events_after_first = store.list_events(run.run_id)
    event_types_after_first = [event.event_type for event in events_after_first]
    assert event_types_after_first.count("checkpoint.saved") == 1
    assert event_types_after_first.count("run.completed") == 1

    second = store.finalize_completed_run(run)

    assert second is False
    # A duplicate call must not write any new checkpoint or event: the
    # conditional UPDATE affects zero rows because status is no longer
    # RUNNING, so nothing past it in the method body ever runs.
    events_after_second = store.list_events(run.run_id)
    assert events_after_second == events_after_first

    persisted = store.get_run(run.run_id)
    assert persisted is not None
    assert persisted.status == RunStatus.COMPLETED


def test_finalize_completed_run_rejects_when_cancel_requested_first(tmp_path):
    store = SQLiteRunStore(tmp_path / "runtime.db")
    run = RunRecord(
        run_id="run_cancel_race_test",
        thread_id="cancel-race-thread",
        agent_id="travel-agent",
        agent_version="0.3.0",
        status=RunStatus.RUNNING,
        input_message="I want a 5-day Tokyo trip under 9000 SGD.",
        attempt=1,
    )
    store.create_run(run)

    # Simulate a cancel committing to the database first, in the window
    # between a worker starting execution and it finishing.
    cancelled = store.request_cancel(run.run_id)
    assert cancelled.cancel_requested is True
    assert cancelled.status == RunStatus.RUNNING

    run.state = AgentState(thread_id="cancel-race-thread", destination="Tokyo", days=5, budget=9000)
    run.output_message = "Planned."
    run.validation_errors = []

    result = store.finalize_completed_run(run)

    assert result is False
    persisted = store.get_run(run.run_id)
    assert persisted is not None
    # RuntimeManager -- not finalize_completed_run -- owns the transition to
    # CANCELLED once this returns False; the row is left RUNNING here.
    assert persisted.status == RunStatus.RUNNING
    assert persisted.state is None
    assert store.load_thread_state("cancel-race-thread") is None
    events = [event.event_type for event in store.list_events(run.run_id)]
    assert "checkpoint.saved" not in events
    assert "run.completed" not in events


def test_two_workers_complete_independent_runs(tmp_path):
    store = SQLiteRunStore(tmp_path / "runtime.db")
    manager = RuntimeManager(store, build_default_registry(), worker_count=2)
    manager.start()
    try:
        runs = [manager.submit(RunCreateRequest(thread_id=f"parallel-{index}", user_message="I want a 5-day Tokyo trip under 9000 SGD.")) for index in range(8)]
        results = [wait_for_terminal(manager, run.run_id) for run in runs]
        assert all(result.status == RunStatus.COMPLETED for result in results)
        assert len({result.run_id for result in results}) == 8
    finally:
        manager.stop()


def test_idempotent_submit_returns_existing_run(tmp_path):
    store = SQLiteRunStore(tmp_path / "runtime.db")
    manager = RuntimeManager(store, build_default_registry())
    request = RunCreateRequest(thread_id="idempotent", user_message="I want a 5-day Tokyo trip under 9000 SGD.", client_request_id="request-123")
    first = manager.submit(request)
    second = manager.submit(request)
    assert first.run_id == second.run_id
    assert len(store.list_events(first.run_id)) == 1


def test_store_survives_new_store_instance(tmp_path):
    database_path = tmp_path / "runtime.db"
    manager = RuntimeManager(SQLiteRunStore(database_path), build_default_registry())
    manager.start()
    try:
        submitted = manager.submit(RunCreateRequest(thread_id="persistent-thread", user_message="I want a 5-day Tokyo trip under 9000 SGD."))
        completed = wait_for_terminal(manager, submitted.run_id)
    finally:
        manager.stop()
    reopened = SQLiteRunStore(database_path)
    persisted = reopened.get_run(completed.run_id)
    assert persisted is not None
    assert persisted.status == RunStatus.COMPLETED
    assert reopened.load_thread_state("persistent-thread") is not None
