from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from agent.review.orchestrator import WorkflowOrchestrator
from agent.state import AgentState, TravelPlan


DEFAULT_CASES_PATH = Path(__file__).with_name("review_cases.json")


def load_cases(path: Path = DEFAULT_CASES_PATH) -> list[dict[str, Any]]:
    return json.loads(path.read_text(encoding="utf-8"))


def state_from_case(case: dict[str, Any]) -> AgentState:
    return AgentState(
        thread_id=f"review-eval-{case['case_id']}",
        destination="Tokyo",
        days=5,
        budget=case["budget"],
        preferences=case["preferences"],
        itinerary=TravelPlan(
            destination="Tokyo",
            days=5,
            flight_type="red_eye",
            hotel_tier="standard hotel",
            poi_style="balanced itinerary",
            total_cost=case["total_cost"],
        ),
        tool_outputs={"memory_refs": case["memory_refs"]},
    )


def evaluate_review_cases(
    cases: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    orchestrator = WorkflowOrchestrator()
    results: list[dict[str, Any]] = []
    true_positive = 0
    false_positive = 0
    false_negative = 0

    for case in cases or load_cases():
        workflow = orchestrator.run_sync(state_from_case(case))
        predicted = {finding.finding_type.value for finding in workflow.findings}
        expected = set(case["expected_finding_types"])
        true_positive += len(predicted & expected)
        false_positive += len(predicted - expected)
        false_negative += len(expected - predicted)
        results.append(
            {
                "case_id": case["case_id"],
                "expected": sorted(expected),
                "predicted": sorted(predicted),
                "workflow_status": workflow.status.value,
                "matched": predicted == expected,
            }
        )

    precision_denominator = true_positive + false_positive
    recall_denominator = true_positive + false_negative
    return {
        "case_count": len(results),
        "case_accuracy": (
            sum(result["matched"] for result in results) / len(results)
            if results
            else 0.0
        ),
        "precision": (
            true_positive / precision_denominator if precision_denominator else 1.0
        ),
        "recall": true_positive / recall_denominator if recall_denominator else 1.0,
        "true_positive": true_positive,
        "false_positive": false_positive,
        "false_negative": false_negative,
        "results": results,
    }


if __name__ == "__main__":
    print(json.dumps(evaluate_review_cases(), indent=2))
