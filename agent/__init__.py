from .contracts import BaseRuntimeState, RuntimeProtocol, RuntimeResponse, TraceEvent, utc_now
from .state import AgentState, StatePatch, TravelPlan

# `agent/__init__.py` imports only from `.contracts` (Core) and `.state`
# (AgentState/StatePatch/TravelPlan are the current Travel state shape, not
# yet moved to `domains/travel/`) -- it does not import `.runtime` at all.
# `TravelAgentRuntime` lives in `agent/runtime.py`, a Travel-specific
# implementation slated to move to `domains/travel/runtime.py` in Phase 1B;
# re-exporting it here would make this Core package depend on a concrete
# domain runtime. Callers that need it import it directly from
# `agent.runtime` (or, after Phase 1B, `domains.travel.runtime`).

__all__ = [
    "AgentState",
    "StatePatch",
    "TravelPlan",
    "BaseRuntimeState",
    "RuntimeProtocol",
    "RuntimeResponse",
    "TraceEvent",
    "utc_now",
]
