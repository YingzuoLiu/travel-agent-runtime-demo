"""Test-only canonicalization for characterization golden fixtures.

Production trace/state payloads intentionally contain non-deterministic
observability fields: ISO-8601 timestamps, `uuid4()`-based ids
(`workflow_<hex>`, `review_task_<hex>`, `finding_<hex>`, `directive_<hex>`),
and wall-clock `duration_ms` measurements. Comparing those verbatim across
two runs of the same scenario would always fail even when behavior is
unchanged.

This module normalizes exactly those fields into stable placeholders so a
golden fixture captures semantic content instead of run-to-run noise. It
must never be imported by production code (`agent/`, `runtime_service/`,
`api/`, `domains/`) -- it exists only to make characterization tests
reproducible.
"""

from __future__ import annotations

import re
from typing import Any

_TIMESTAMP_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?(\+\d{2}:\d{2}|Z)?$"
)

# Prefixes actually used by uuid4()-based id generation in the codebase:
#   f"workflow_{uuid4().hex}"     (WorkflowOrchestrator.run)
#   f"review_task_{uuid4().hex}" (WorkflowOrchestrator.run)
#   f"finding_{uuid4().hex}"     (BudgetChecker / PreferenceReviewer)
#   f"directive_{uuid4().hex}"   (FindingReducer)
_RANDOM_ID_RE = re.compile(r"^(workflow|review_task|finding|directive)_[0-9a-f]{32}$")

_DURATION_KEYS = {"duration_ms"}

_TIMESTAMP_PLACEHOLDER = "<TIMESTAMP>"
_DURATION_PLACEHOLDER = "<DURATION_MS>"


def canonicalize(value: Any) -> Any:
    """Return a deep copy of `value` with non-deterministic fields normalized.

    Random ids are replaced with placeholders assigned in first-seen order
    per prefix (e.g. the first finding id encountered becomes
    ``<FINDING_ID#1>``, the second ``<FINDING_ID#2>``), so that cross
    references between fields -- e.g. a `finding_id` emitted by a reviewer
    and later echoed in the reducer's trace payload -- remain structurally
    verifiable without depending on the actual random value. Traversal order
    over dicts/lists is deterministic (insertion order), so calling this on
    two separate runs of the same code path yields identical output even
    though the underlying random strings differ between runs.
    """
    id_map: dict[str, str] = {}
    counters: dict[str, int] = {}
    return _walk(value, id_map, counters)


def _walk(value: Any, id_map: dict[str, str], counters: dict[str, int]) -> Any:
    if isinstance(value, dict):
        result = {}
        for key, item in value.items():
            if key in _DURATION_KEYS:
                result[key] = _DURATION_PLACEHOLDER
            else:
                result[key] = _walk(item, id_map, counters)
        return result
    if isinstance(value, list):
        return [_walk(item, id_map, counters) for item in value]
    if isinstance(value, str):
        if _TIMESTAMP_RE.match(value):
            return _TIMESTAMP_PLACEHOLDER
        match = _RANDOM_ID_RE.match(value)
        if match:
            if value not in id_map:
                prefix = match.group(1)
                counters[prefix] = counters.get(prefix, 0) + 1
                id_map[value] = f"<{prefix.upper()}_ID#{counters[prefix]}>"
            return id_map[value]
        return value
    return value
