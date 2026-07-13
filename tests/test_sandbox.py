from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from runtime_service import (
    ToolExecutionStatus,
    ToolPolicy,
    ToolRegistry,
    ToolSandbox,
    ToolSpec,
    build_default_tool_registry,
)


class SleepInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    seconds: float = Field(gt=0, le=5)


class EnvironmentProbeInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    keys: list[str] = Field(min_length=1, max_length=20)


def test_registered_tool_executes_in_subprocess():
    sandbox = ToolSandbox(build_default_tool_registry())

    result = sandbox.execute(
        "route_cost_summary",
        {
            "transport_cost": 2000,
            "hotel_cost": 3000,
            "activity_cost": 1000,
            "budget": 7000,
        },
    )

    assert result.status == ToolExecutionStatus.COMPLETED
    assert result.result == {
        "total_cost": 6000,
        "budget": 7000,
        "remaining_budget": 1000,
        "within_budget": True,
    }


def test_unregistered_tool_is_denied_before_process_start():
    sandbox = ToolSandbox(build_default_tool_registry())

    result = sandbox.execute("python", {"code": "print('not allowed')"})

    assert result.status == ToolExecutionStatus.DENIED
    assert result.exit_code is None


def test_invalid_arguments_are_rejected_by_schema():
    sandbox = ToolSandbox(build_default_tool_registry())

    result = sandbox.execute(
        "route_cost_summary",
        {
            "transport_cost": -1,
            "hotel_cost": 3000,
            "activity_cost": 1000,
            "budget": 7000,
            "unexpected": "field",
        },
    )

    assert result.status == ToolExecutionStatus.INVALID_INPUT
    assert result.exit_code is None


def test_tool_timeout_terminates_the_process():
    registry = ToolRegistry()
    registry.register(
        ToolSpec(
            name="_sleep_test",
            description="Test-only blocking tool.",
            input_model=SleepInput,
            policy=ToolPolicy(timeout_seconds=0.2),
        )
    )
    sandbox = ToolSandbox(registry)

    result = sandbox.execute("_sleep_test", {"seconds": 2.0})

    assert result.status == ToolExecutionStatus.TIMED_OUT
    assert result.exit_code is not None


def test_parent_secrets_are_not_forwarded_to_worker(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "must-not-cross-process-boundary")
    registry = ToolRegistry()
    registry.register(
        ToolSpec(
            name="_environment_probe",
            description="Test-only environment visibility probe.",
            input_model=EnvironmentProbeInput,
            policy=ToolPolicy(),
        )
    )
    sandbox = ToolSandbox(registry)

    result = sandbox.execute(
        "_environment_probe",
        {"keys": ["OPENAI_API_KEY", "PYTHONIOENCODING"]},
    )

    assert result.status == ToolExecutionStatus.COMPLETED
    assert result.result == {
        "present": {
            "OPENAI_API_KEY": False,
            "PYTHONIOENCODING": True,
        }
    }
