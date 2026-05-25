"""
eval/runner.py — Ablation eval harness for TravelAgentRuntime.

Runs long-horizon scenario sequences under different runtime configurations
and records structured metrics from the execution trace.

Usage:
    python eval/runner.py
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import List, Optional

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from agent import AgentState, TravelAgentRuntime
from agent.validator import TravelValidator


@dataclass
class Scenario:
    name: str
    description: str
    turns: List[str]


SCENARIOS: List[Scenario] = [
    Scenario(
        name="happy_path_5turn",
        description="Normal 5-turn trip planning, no conflicts.",
        turns=[
            "I want a 5-day Tokyo trip under 7000 SGD.",
            "Make it a relaxed style.",
            "I prefer to avoid red-eye flights.",
            "I want a hotel near subway.",
            "Change the budget to 9000.",
        ],
    ),
    Scenario(
        name="budget_conflict_recovery",
        description="Agent plans a trip, then user sets a budget lower than cost.",
        turns=[
            "I want a 7-day Tokyo trip under 15000 SGD.",
            "Avoid red-eye. Hotel near subway.",
            "Actually cut budget to 4000.",
            "OK raise budget to 6000.",
            "Keep everything else the same.",
        ],
    ),
    Scenario(
        name="conflicting_preferences_stall",
        description="User sends contradictory signals. Tests blocker propagation.",
        turns=[
            "I want a 10-day Tokyo trip under 5000 SGD.",
            "Avoid red-eye. Hotel near subway.",
            "Keep budget at 5000.",
            "I insist the budget stays at 5000.",
            "Fine, raise budget to 8000.",
        ],
    ),
    Scenario(
        name="memory_drift_8turn",
        description="8-turn sequence; early preferences must survive later updates.",
        turns=[
            "Plan a 6-day Tokyo trip, budget 10000 SGD.",
            "I want a relaxed travel style.",
            "Avoid red-eye flights.",
            "Hotel near subway please.",
            "Change the trip to 8 days.",
            "Raise budget to 12000.",
            "Keep the relaxed style and no red-eye.",
            "Confirm everything looks good.",
        ],
    ),
]


@dataclass
class ScenarioRes
