from __future__ import annotations

import json
import sys
from typing import Any


def route_cost_summary(payload: dict[str, Any]) -> dict[str, Any]:
    total = int(payload["transport_cost"]) + int(payload["hotel_cost"]) + int(
        payload["activity_cost"]
    )
    budget = int(payload["budget"])
    return {
        "total_cost": total,
        "budget": budget,
        "remaining_budget": budget - total,
        "within_budget": total <= budget,
    }


def rank_trip_options(payload: dict[str, Any]) -> dict[str, Any]:
    options = payload["options"]
    cost_weight = float(payload["cost_weight"])
    duration_weight = float(payload["duration_weight"])

    normalized: list[dict[str, Any]] = []
    max_cost = max(float(item.get("cost", 0)) for item in options) or 1.0
    max_duration = max(float(item.get("duration_hours", 0)) for item in options) or 1.0

    for index, item in enumerate(options):
        cost = float(item.get("cost", 0))
        duration = float(item.get("duration_hours", 0))
        score = cost_weight * (1 - cost / max_cost) + duration_weight * (
            1 - duration / max_duration
        )
        normalized.append(
            {
                "index": index,
                "name": str(item.get("name", f"option-{index}")),
                "score": round(score, 6),
            }
        )

    normalized.sort(key=lambda item: (-float(item["score"]), int(item["index"])))
    return {"ranking": normalized}


TOOLS = {
    "route_cost_summary": route_cost_summary,
    "rank_trip_options": rank_trip_options,
}


def main() -> int:
    if len(sys.argv) != 2:
        print("exactly one tool name is required", file=sys.stderr)
        return 2

    tool_name = sys.argv[1]
    tool = TOOLS.get(tool_name)
    if tool is None:
        print("tool is not available in the sandbox worker", file=sys.stderr)
        return 3

    try:
        payload = json.loads(sys.stdin.buffer.read().decode("utf-8"))
        if not isinstance(payload, dict):
            raise TypeError("tool input must be a JSON object")
        result = tool(payload)
    except Exception as exc:
        print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
        return 4

    sys.stdout.write(json.dumps(result, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
