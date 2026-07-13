import time

from fastapi.testclient import TestClient

from api.main import create_app


def wait_for_run(client: TestClient, run_id: str, timeout: float = 3.0) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        body = client.get(f"/runs/{run_id}").json()
        if body["status"] in {"completed", "failed", "cancelled"}:
            return body
        time.sleep(0.02)
    raise AssertionError("run did not finish")


def test_fastapi_agent_message_endpoint(tmp_path):
    app = create_app(database_path=tmp_path / "runtime.db")
    with TestClient(app) as client:
        response = client.post(
            "/agent/message",
            json={
                "thread_id": "api_test_thread",
                "user_message": "I want a 5-day Tokyo trip under 7000 SGD.",
            },
        )
    assert response.status_code == 200
    body = response.json()
    assert body["updated_state"]["destination"] == "Tokyo"
    assert body["updated_state"]["budget"] == 7000


def test_sync_and_async_endpoints_share_thread_state(tmp_path):
    app = create_app(database_path=tmp_path / "runtime.db")
    with TestClient(app) as client:
        first = client.post(
            "/agent/message",
            json={
                "thread_id": "shared-thread",
                "user_message": "I want a 5-day Tokyo trip under 7000 SGD.",
            },
        )
        assert first.status_code == 200
        submitted = client.post(
            "/runs",
            json={
                "thread_id": "shared-thread",
                "user_message": "Change the budget to 9000 and avoid red-eye flights.",
            },
        )
        result = wait_for_run(client, submitted.json()["run_id"])
        assert result["state"]["destination"] == "Tokyo"
        assert result["state"]["budget"] == 9000
        assert result["state"]["preferences"]["avoid_red_eye"] is True


def test_async_run_api_and_event_history(tmp_path):
    app = create_app(database_path=tmp_path / "runtime.db")
    with TestClient(app) as client:
        response = client.post(
            "/runs",
            json={
                "thread_id": "api-run-thread",
                "user_message": "I want a 5-day Tokyo trip under 9000 SGD.",
            },
        )
        assert response.status_code == 202
        run_id = response.json()["run_id"]
        body = wait_for_run(client, run_id)
        assert body["status"] == "completed"
        assert body["agent_version"] == "0.3.0"
        events = client.get(f"/runs/{run_id}/events").json()
        assert events[0]["event_type"] == "run.queued"
        assert events[-1]["event_type"] == "run.completed"
        state = client.get("/threads/api-run-thread/state")
        assert state.status_code == 200
        assert state.json()["destination"] == "Tokyo"


def test_tool_sandbox_api_and_run_event_linkage(tmp_path):
    app = create_app(database_path=tmp_path / "runtime.db")
    with TestClient(app) as client:
        tools = client.get("/tools")
        assert tools.status_code == 200
        assert {item["name"] for item in tools.json()} == {
            "rank_trip_options",
            "route_cost_summary",
        }

        submitted = client.post(
            "/runs",
            json={
                "thread_id": "sandbox-run-thread",
                "user_message": "I want a 5-day Tokyo trip under 9000 SGD.",
            },
        )
        run_id = submitted.json()["run_id"]
        wait_for_run(client, run_id)

        execution = client.post(
            "/tools/route_cost_summary/execute",
            json={
                "run_id": run_id,
                "arguments": {
                    "transport_cost": 2000,
                    "hotel_cost": 3000,
                    "activity_cost": 1000,
                    "budget": 7000,
                },
            },
        )
        assert execution.status_code == 200
        assert execution.json()["status"] == "completed"
        assert execution.json()["result"]["remaining_budget"] == 1000

        events = client.get(f"/runs/{run_id}/events").json()
        event_types = [event["event_type"] for event in events]
        assert "sandbox.execution_started" in event_types
        assert "sandbox.execution_finished" in event_types


def test_run_submission_is_idempotent(tmp_path):
    app = create_app(database_path=tmp_path / "runtime.db")
    payload = {
        "thread_id": "idempotent-thread",
        "user_message": "I want a 5-day Tokyo trip under 9000 SGD.",
        "client_request_id": "client-request-001",
    }
    with TestClient(app) as client:
        first = client.post("/runs", json=payload)
        second = client.post("/runs", json=payload)
        assert first.status_code == 202
        assert second.status_code == 202
        assert first.json()["run_id"] == second.json()["run_id"]


def test_unknown_agent_version_is_rejected(tmp_path):
    app = create_app(database_path=tmp_path / "runtime.db")
    with TestClient(app) as client:
        response = client.post(
            "/runs",
            json={
                "thread_id": "bad-version",
                "user_message": "Plan Tokyo",
                "agent_version": "99.0.0",
            },
        )
    assert response.status_code == 422
