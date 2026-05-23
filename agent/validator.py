from __future__ import annotations

from typing import List

from pydantic import BaseModel

from .state import AgentState


class ValidationResult(BaseModel):
    passed: bool
    errors: List[str]


class TravelValidator:
    """
    Deterministic validation layer.

    The goal is to keep hard business constraints outside the LLM prompt.
    """

    def validate_required_fields(self, state: AgentState) -> List[str]:
        errors: List[str] = []

        if not state.destination:
            errors.append("Missing required field: destination")

        if not state.days:
            errors.append("Missing required field: days")

        if not state.budget:
            errors.append("Missing required field: budget")

        return errors

    def validate_budget(self, state: AgentState) -> List[str]:
        errors: List[str] = []

        if state.itinerary is None or state.budget is None:
            return errors

        if state.itinerary.total_cost > state.budget:
            errors.append(
                f"Budget exceeded: total_cost={state.itinerary.total_cost}, budget={state.budget}"
            )

        return errors

    def validate_no_red_eye(self, state: AgentState) -> List[str]:
        errors: List[str] = []

        if state.itinerary is None:
            return errors

        avoid_red_eye = bool(state.preferences.get("avoid_red_eye", False))

        if avoid_red_eye and state.itinerary.flight_type == "red_eye":
            errors.append("Flight constraint violated: red-eye flight is not allowed")

        return errors

    def validate_itinerary_days(self, state: AgentState) -> List[str]:
        errors: List[str] = []

        if state.itinerary is None or state.days is None:
            return errors

        if state.itinerary.days != state.days:
            errors.append(
                f"Day count mismatch: itinerary_days={state.itinerary.days}, requested_days={state.days}"
            )

        return errors

    def validate(self, state: AgentState) -> ValidationResult:
        errors: List[str] = []

        errors.extend(self.validate_required_fields(state))
        errors.extend(self.validate_budget(state))
        errors.extend(self.validate_no_red_eye(state))
        errors.extend(self.validate_itinerary_days(state))

        return ValidationResult(passed=len(errors) == 0, errors=errors)
