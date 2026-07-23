from canonicalize import canonicalize


def test_canonicalize_replaces_timestamp_like_strings():
    payload = {"timestamp": "2026-07-22T10:15:30.123456+00:00", "other": "2026-07-22"}

    result = canonicalize(payload)

    assert result["timestamp"] == "<TIMESTAMP>"
    # "2026-07-22" alone (no time component) is not a timestamp match and
    # must be left untouched, since plain date-like strings can be
    # legitimate domain data.
    assert result["other"] == "2026-07-22"


def test_canonicalize_replaces_known_random_id_prefixes_consistently():
    finding_a = "finding_" + "a" * 32
    finding_b = "finding_" + "b" * 32
    directive_a = "directive_" + "c" * 32

    payload = {
        "finding_id": finding_a,
        "finding_ids": [finding_a, finding_b],
        "directive_id": directive_a,
    }

    result = canonicalize(payload)

    assert result["finding_id"] == "<FINDING_ID#1>"
    # Same raw id appearing again (as a back-reference) must map to the
    # same placeholder, not a new one.
    assert result["finding_ids"] == ["<FINDING_ID#1>", "<FINDING_ID#2>"]
    assert result["directive_id"] == "<DIRECTIVE_ID#1>"


def test_canonicalize_replaces_duration_ms_by_key_regardless_of_value():
    payload = {"duration_ms": 12.345, "nested": {"duration_ms": 0.0}}

    result = canonicalize(payload)

    assert result["duration_ms"] == "<DURATION_MS>"
    assert result["nested"]["duration_ms"] == "<DURATION_MS>"


def test_canonicalize_leaves_ordinary_domain_strings_untouched():
    payload = {
        "destination": "Tokyo",
        "hotel_tier": "near-subway comfort hotel",
        "rule_id": "budget.total_cost_within_limit",
    }

    result = canonicalize(payload)

    assert result == payload


def test_canonicalize_is_reproducible_across_two_separate_calls():
    finding_a = "finding_" + "1" * 32
    finding_b = "finding_" + "2" * 32
    payload = {
        "timestamp": "2026-07-22T10:15:30+00:00",
        "finding_id": finding_a,
        "related": [finding_b, finding_a],
        "duration_ms": 5.0,
    }

    first = canonicalize(payload)
    second = canonicalize(payload)

    assert first == second
