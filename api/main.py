from __future__ import annotations

from typing import Dict, Optional

from fastapi import FastAPI
from pydantic import BaseModel, Field

from agent import AgentState, TravelAgentRuntime


app = FastAPI(
    title="Travel Agent Runtime Demo",
    description="Minimal FastAPI wrapper around a multi-turn travel Agent Runtime.",
    version="0.2.0",
)

runtime = TravelAgentRuntime(retry_limit=2)

# Demo-only in-memory store.
# Production integration point:
# Replace this dict with Redis, keyed by thread_id.
STATE_STORE: Dict[str, AgentState] = {}


class AgentMessageRequest(BaseModel):
    thread_id: str = Field(..., description="Conversation or task thread id.")
    user_message: str = Field(..., description="User message to process.")
    state: Optional[AgentState] = Field(
        default=None,
        description="Optional client-provided state. If omitted, server loads from STATE_STORE.",
    )


class AgentMessageResponse(BaseModel):
    assistant_message: str
    updated_state: AgentState
    validation_errors: list[str]


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/agent/message", response_model=AgentMessageResponse)
def handle_agent_message(request: AgentMessageRequest) -> AgentMessageResponse:
    """
    Minimal service entrypoint around TravelAgentRuntime.handle_user_message.

    Demo behavior:
    - load state from request.state, or from in-memory STATE_STORE
    - process user message
    - save updated state back to STATE_STORE

    Production behavior:
    - load/save AgentState from Redis by thread_id
    - optionally call vLLM inside runtime.detect_intent_and_patch
    """
    state = request.state or STATE_STORE.get(request.thread_id) or AgentState(thread_id=request.thread_id)

    result = runtime.handle_user_message(state, request.user_message)
    STATE_STORE[request.thread_id] = result.state

    return AgentMessageResponse(
        assistant_message=result.message,
        updated_state=result.state,
        validation_errors=result.validation_errors,
    )
