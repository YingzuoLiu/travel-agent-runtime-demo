"""Characterization of the default agent registry contents.

Locks the exact set of (agent_id, version, description) tuples exposed by
`build_default_registry()`, so Phase 2's generalization to
`(domain_id, schema_version)`-aware registration cannot silently drop or
rename a currently-registered agent version.
"""

from __future__ import annotations

from runtime_service.registry import build_default_registry


def test_default_registry_lists_exact_agent_versions():
    registry = build_default_registry()

    descriptors = [
        (descriptor.agent_id, descriptor.version, descriptor.description)
        for descriptor in registry.list_agents()
    ]

    assert descriptors == [
        (
            "travel-agent",
            "0.3.0",
            "Rule-based travel planning runtime with typed state and deterministic validation.",
        ),
        (
            "travel-agent",
            "0.5.0",
            "Evidence-review travel runtime with typed Budget and Preference reviewers, "
            "deadline-aware orchestration, deterministic reduction and validator-gated replanning.",
        ),
    ]


def test_default_registry_resolves_both_versions_to_working_runtimes():
    registry = build_default_registry()

    runtime_v3 = registry.resolve("travel-agent", "0.3.0")
    runtime_v5 = registry.resolve("travel-agent", "0.5.0")

    assert runtime_v3.enable_review_workflow is False
    assert runtime_v5.enable_review_workflow is True
