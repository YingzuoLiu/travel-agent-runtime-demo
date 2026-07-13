import time

from fastapi.testclient import TestClient

from api.main import create_app


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

        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            run_response = client.get(f"/runs/{run_id}")
            body = run_response.json()
            if body["status"] in {"completed", "failed", "cancelled"}:
                break
            time.sleep(0.02)
        else:
            raise AssertionError("run did not finish")

        assert body["status"] == "completed"
        assert body["agent_version"] == "0.3.0"
        events = client.get(f"/runs/{run_id}/events").json()
        assert events[0]["event_type"] == "run.queued"
        assert events[-1]["event_type"] == "run.completed"
        state = client.get("/threads/api-run-thread/state")
        assert state.status_code == 200
        assert state.json()["destination"] == "Tokyo"


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
