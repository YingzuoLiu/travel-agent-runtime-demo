from __future__ import annotations

import asyncio
import json
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Query, Request, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from agent import AgentState, TravelAgentRuntime
from runtime_service import (
    AgentDescriptor,
    RunCreateRequest,
    RunEvent,
    RunRecord,
    RuntimeManager,
    SQLiteRunStore,
    build_default_registry,
)


class AgentMessageRequest(BaseModel):
    thread_id: str = Field(..., description="Conversation or task thread id.")
    user_message: str = Field(..., description="User message to process.")
    state: Optional[AgentState] = Field(
        default=None,
        description="Optional client-provided state. If omitted, server loads the durable thread checkpoint.",
    )


class AgentMessageResponse(BaseModel):
    assistant_message: str
    updated_state: AgentState
    validation_errors: list[str]


def create_app(*, database_path: str | Path | None = None, worker_count: int | None = None) -> FastAPI:
    resolved_database_path = Path(database_path or os.getenv("RUNTIME_DB_PATH", "runtime_data/runtime.db"))
    resolved_worker_count = worker_count or int(os.getenv("RUNTIME_WORKER_COUNT", "1"))
    registry = build_default_registry()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        store = SQLiteRunStore(resolved_database_path)
        manager = RuntimeManager(store=store, registry=registry, worker_count=resolved_worker_count)
        manager.start()
        app.state.run_store = store
        app.state.runtime_manager = manager
        app.state.agent_registry = registry
        yield
        manager.stop()

    app = FastAPI(
        title="Travel Agent Runtime Demo",
        description=(
            "A stateful travel agent plus a durable run API with version pinning, "
            "worker execution, checkpoints, cancellation and event history."
        ),
        version="0.3.0",
        lifespan=lifespan,
    )

    def get_manager(request: Request) -> RuntimeManager:
        return request.app.state.runtime_manager

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/ready")
    def ready(request: Request) -> dict[str, str]:
        request.app.state.run_store.ping()
        return {"status": "ready"}

    @app.get("/agents", response_model=list[AgentDescriptor])
    def list_agents(request: Request) -> list[AgentDescriptor]:
        return request.app.state.agent_registry.list_agents()

    @app.post("/agent/message", response_model=AgentMessageResponse)
    def handle_agent_message(payload: AgentMessageRequest, request: Request) -> AgentMessageResponse:
        """Backward-compatible synchronous endpoint backed by the durable thread store."""
        store: SQLiteRunStore = request.app.state.run_store
        runtime = TravelAgentRuntime(retry_limit=2)
        state_value = payload.state or store.load_thread_state(payload.thread_id) or AgentState(thread_id=payload.thread_id)
        result = runtime.handle_user_message(state_value, payload.user_message)
        store.save_thread_state(result.state)
        return AgentMessageResponse(
            assistant_message=result.message,
            updated_state=result.state,
            validation_errors=result.validation_errors,
        )

    @app.post("/runs", response_model=RunRecord, status_code=status.HTTP_202_ACCEPTED)
    def create_run(payload: RunCreateRequest, request: Request) -> RunRecord:
        try:
            return get_manager(request).submit(payload)
        except KeyError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.get("/runs/{run_id}", response_model=RunRecord)
    def get_run(run_id: str, request: Request) -> RunRecord:
        run = get_manager(request).get_run(run_id)
        if run is None:
            raise HTTPException(status_code=404, detail="Run not found")
        return run

    @app.post("/runs/{run_id}/cancel", response_model=RunRecord)
    def cancel_run(run_id: str, request: Request) -> RunRecord:
        try:
            return get_manager(request).request_cancel(run_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Run not found") from exc

    @app.get("/runs/{run_id}/events", response_model=list[RunEvent])
    def list_run_events(run_id: str, request: Request, after_sequence: int = Query(default=0, ge=0)) -> list[RunEvent]:
        if get_manager(request).get_run(run_id) is None:
            raise HTTPException(status_code=404, detail="Run not found")
        return request.app.state.run_store.list_events(run_id, after_sequence=after_sequence)

    @app.get("/runs/{run_id}/events/stream")
    async def stream_run_events(run_id: str, request: Request, after_sequence: int = Query(default=0, ge=0)) -> StreamingResponse:
        manager = get_manager(request)
        if manager.get_run(run_id) is None:
            raise HTTPException(status_code=404, detail="Run not found")

        async def event_stream():
            sequence = after_sequence
            while True:
                if await request.is_disconnected():
                    return
                events = request.app.state.run_store.list_events(run_id, after_sequence=sequence)
                for event in events:
                    sequence = event.sequence
                    data = json.dumps(event.model_dump(mode="json"))
                    yield f"event: {event.event_type}\ndata: {data}\n\n"
                run = manager.get_run(run_id)
                if run is None or (run.status.is_terminal and not events):
                    return
                await asyncio.sleep(0.2)

        return StreamingResponse(event_stream(), media_type="text/event-stream")

    @app.get("/threads/{thread_id}/state", response_model=AgentState)
    def get_thread_state(thread_id: str, request: Request) -> AgentState:
        state_value = request.app.state.run_store.load_thread_state(thread_id)
        if state_value is None:
            raise HTTPException(status_code=404, detail="Thread state not found")
        return state_value

    return app


app = create_app()
