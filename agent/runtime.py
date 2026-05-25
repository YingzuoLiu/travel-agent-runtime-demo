from __future__ import annotations

import re
from typing import Any, Dict, List, Tuple

from pydantic import BaseModel

from .reducer import apply_patch, append_trace
from .state import AgentState, StatePatch, TravelPlan
from .validator import TravelValidator


class RuntimeResponse(BaseModel):
    message: str
    state: AgentState
    validation_errors: List[str]


class TravelAgentRuntime:
    """
    Minimal orchestration runtime for a travel planning agent.

    This file intentionally uses simple rule-based intent detection so the demo
    can run without real LLM API keys. In production, `detect_intent_and_patch`
    could be replaced by an LLM router, a classifier, or a vLLM-served planner.
    """

    def __init__(self, retry_limit: int = 2):
        self.validator = TravelValidator()
        self.retry_limit = retry_limit

    def handle_user_message(self, state: AgentState, user_message: str) -> RuntimeResponse:
        intent, patch = self.detect_intent_and_patch(state, user_message)

        state = append_trace(
            state,
            event="intent_detected",
            reason=intent,
            payload={"user_message": user_message},
        )

        state = apply_patch(state, patch)

        if patch.trigger_replan:
            state = self.partial_replan(state, reason=patch.reason)

        validation = self.validator.validate(state)
        state = append_trace(
            state,
            event="validation_finished",
            reason="passed" if validation.passed else "failed",
            payload={"errors": validation.errors},
        )

        if not validation.passed:
            state = self.handle_validation_failure(state, validation.errors)

        response = self.render_response(state, validation.errors)
        return RuntimeResponse(
            message=response,
            state=state,
            validation_errors=validation.errors,
        )

    def detect_intent_and_patch(self, state: AgentState, user_message: str) -> Tuple[str, StatePatch]:
        text = user_message.lower()
        updates: Dict[str, Any] = {}
        affected_fields: List[str] = []

        if "tokyo" in text or "东京" in user_message:
            updates["destination"] = "Tokyo"
            affected_fields.append("destination")

        days = self._extract_days(user_message)
        if days:
            updates["days"] = days
            affected_fields.append("days")

        budget = self._extract_budget(user_message)
        if budget:
            updates["budget"] = budget
            affected_fields.append("budget")

        preference_updates: Dict[str, Any] = {}

        if "red-eye" in text or "red eye" in text or "红眼" in user_message:
            preference_updates["avoid_red_eye"] = True

        if "near subway" in text or "靠近地铁" in user_message:
            preference_updates["hotel_near_subway"] = True

        if "relaxed" in text or "轻松" in user_message:
            preference_updates["travel_style"] = "relaxed"

        if preference_updates:
            updates["preferences"] = preference_updates
            affected_fields.append("preferences")

        confirm_words = ["confirm", "looks good", "sounds good", "ok",
                         "okay", "perfect", "great", "yes", "correct"]
        is_confirm = any(w in text for w in confirm_words)
        if not updates and is_confirm:
            return (
                "confirm_plan",
                StatePatch(
                    updates={},
                    reason="user_confirmed_current_plan",
                    affected_fields=[],
                    trigger_replan=False,
                ),
            )

        if not updates:
            return (
                "ask_clarification",
                StatePatch(
                    updates={"blockers": ["Could not identify actionable travel constraints."]},
                    reason="no_actionable_intent_detected",
                    affected_fields=["blockers"],
                    trigger_replan=False,
                ),
            )

        intent = self._infer_intent(state, updates)
        affected_fields = sorted(set(affected_fields + ["itinerary"]))

        return (
            intent,
            StatePatch(
                updates=updates,
                reason=intent,
                affected_fields=affected_fields,
                trigger_replan=True,
                metadata={"raw_user_message": user_message},
            ),
        )

    def partial_replan(self, state: AgentState, reason: str) -> AgentState:
        """
        Rebuild only the simplified itinerary from current structured state.

        In a larger system, this method could call flight, hotel, and POI tools.
        Here we simulate the downstream plan so the runtime behavior is visible.
        """
        if not state.destination or not state.days or not state.budget:
            return append_trace(
                state,
                event="partial_replan_skipped",
                reason="missing_required_fields",
                payload={
                    "destination": state.destination,
                    "days": state.days,
                    "budget": state.budget,
                },
            )

        avoid_red_eye = bool(state.preferences.get("avoid_red_eye", False))
        hotel_near_subway = bool(state.preferences.get("hotel_near_subway", False))
        travel_style = state.preferences.get("travel_style", "balanced")

        flight_type = "daytime" if avoid_red_eye else "red_eye"

        # Very small mock cost model.
        flight_cost = 2300 if flight_type == "daytime" else 1800
        hotel_cost_per_day = 850 if hotel_near_subway else 650
        activity_cost_per_day = 300 if travel_style == "relaxed" else 450

        total_cost = flight_cost + state.days * (hotel_cost_per_day + activity_cost_per_day)

        hotel_tier = "near-subway comfort hotel" if hotel_near_subway else "standard hotel"
        poi_style = "relaxed itinerary" if travel_style == "relaxed" else "balanced itinerary"

        itinerary = TravelPlan(
            destination=state.destination,
            days=state.days,
            flight_type=flight_type,
            hotel_tier=hotel_tier,
            poi_style=poi_style,
            total_cost=total_cost,
            notes=[
                "Generated by partial_replan from current AgentState.",
                f"Replan reason: {reason}",
            ],
        )

        patch = StatePatch(
            updates={
                "itinerary": itinerary,
                "current_stage": "planned",
                "blockers": [],
            },
            reason="partial_replan_completed",
            affected_fields=["itinerary", "current_stage", "blockers"],
            trigger_replan=False,
            metadata={
                "cost_breakdown": {
                    "flight_cost": flight_cost,
                    "hotel_cost_per_day": hotel_cost_per_day,
                    "activity_cost_per_day": activity_cost_per_day,
                }
            },
        )

        return apply_patch(state, patch)

    def handle_validation_failure(self, state: AgentState, errors: List[str]) -> AgentState:
        if state.retry_count >= self.retry_limit:
            patch = StatePatch(
                updates={
                    "blockers": errors,
                    "current_stage": "blocked",
                },
                reason="retry_limit_exceeded_blocker_propagated",
                affected_fields=["blockers", "current_stage"],
                trigger_replan=False,
            )
            return apply_patch(state, patch)

        patch = StatePatch(
            updates={
                "retry_count": state.retry_count + 1,
                "blockers": errors,
                "current_stage": "needs_repair",
            },
            reason="validation_failed_runtime_can_retry",
            affected_fields=["retry_count", "blockers", "current_stage"],
            trigger_replan=False,
        )
        return apply_patch(state, patch)

    def render_response(self, state: AgentState, validation_errors: List[str]) -> str:
        if state.blockers:
            return (
                "The runtime stopped because there are unresolved blockers: "
                + "; ".join(state.blockers)
            )

        if state.itinerary is None:
            return "The runtime updated the state, but no itinerary was generated yet."

        return (
            f"Planned {state.days}-day trip to {state.destination}. "
            f"Flight={state.itinerary.flight_type}, "
            f"Hotel={state.itinerary.hotel_tier}, "
            f"Style={state.itinerary.poi_style}, "
            f"Estimated cost={state.itinerary.total_cost}, "
            f"Budget={state.budget}."
        )

    def _infer_intent(self, state: AgentState, updates: Dict[str, Any]) -> str:
        if state.destination is None and "destination" in updates:
            return "new_trip_plan"

        if "budget" in updates and len(updates) == 1:
            return "modify_budget"

        if "preferences" in updates and len(updates) == 1:
            return "modify_preference"

        return "modify_constraints"

    def _extract_budget(self, text: str) -> int | None:
        budget_patterns = [
            r"(?:budget|under|预算|控制在|改成|调整到)\D{0,10}(\d{4,6})",
            r"(\d{4,6})\s*(?:sgd|rmb|usd|新币|人民币|预算)?",
        ]

        for pattern in budget_patterns:
            match = re.search(pattern, text, flags=re.IGNORECASE)
            if match:
                return int(match.group(1))

        return None

    def _extract_days(self, text: str) -> int | None:
        patterns = [
            r"(\d+)\s*[- ]?day",
            r"(\d+)\s*天",
            r"玩\s*(\d+)\s*天",
        ]

        for pattern in patterns:
            match = re.search(pattern, text, flags=re.IGNORECASE)
            if match:
                return int(match.group(1))

        return None
