from eval.review_runner import evaluate_review_cases


def test_labeled_review_fixture_has_no_silent_misses_or_false_positives():
    result = evaluate_review_cases()

    assert result["fixture_count"] == 10
    assert result["fixtures_passed"] == 10
    assert result["all_fixtures_passed"] is True
    assert result["unexpected_findings"] == 0
    assert result["missing_expected_findings"] == 0
