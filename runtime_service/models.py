from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field

from agent.state import AgentState, utc_now


class RunStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"

    @property
