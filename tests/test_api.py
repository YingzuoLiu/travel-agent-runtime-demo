from fastapi.testclient import TestClient

from api.main import app


def test_fastapi_agent_message_endpoint():
    client = TestClient(app)

    response = client.post(
        "/agent/message",
        json={
            "thread_id": "api_test_thread",
            "user_message": "I want a 5-day Tokyo trip under 7000 SGD.",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert "assistant_message" in body
    assert body["updated_state"]["destination"] == "Tokyo"
    assert body["updated_state"]["budget"] == 7000
