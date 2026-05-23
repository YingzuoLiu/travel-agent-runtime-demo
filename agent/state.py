from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class TraceEvent(BaseModel):
    """A small execution log entry for observability and debugging."""

    event: str
    reason: str
    payload: Dict[str, Any] = Field(default_factory=dict)
    timestamp: str = Field(default_factory=utc_now)


class TravelPlan(BaseModel):
    """A simplified travel plan produced by the runtime."""

    destination: str
    days: int
    flight_type: str
    hotel_tier: str
    poi_style: str
    total_cost: int
    notes: List[str] = Field(default_factory=list)


class AgentState(BaseModel):
    """
    Typed task state for a multi-turn travel planning agent.

    In production, this state could be persisted in Redis or a database.
    This demo keeps it in memory so the repository can run without external services.
    """

    thread_id: str
    destination: Optional[str] = None
    days: Optional[int] = None
    budget: Optional[int] = None

    preferences: Dict[str, Any] = Field(default_factory=dict)
    itinerary: Optional[TravelPlan] = None
    tool_outputs: Dict[str, Any] = Field(default_factory=dict)

    blockers: List[str] = Field(default_factory=list)
    retry_count: int = 0
    current_stage: str = "initialized"
    execution_trace: List[TraceEvent] = Field(default_factory=list)


class StatePatch(BaseModel):
    """
    A structured state update generated from user intent or runtime events.

    The patch makes state transitions explicit instead of directly mutating the
    whole AgentState.
    """

    updates: Dict[str, Any]
    reason: str
    affected_fields: List[str]
    trigger_replan: bool = False
    locked_fields: List[str] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)
