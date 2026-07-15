from eval.review_runner import evaluate_review_cases


def test_labeled_review_fixture_has_no_silent_misses_or_false_positives():
    result = evaluate_review_cases()

    assert result["case_count"] == 10
    assert result["case_accuracy"] == 1.0
    assert result["precision"] == 1.0
    assert result["recall"] == 1.0
    assert result["false_positive"] == 0
    assert result["false_negative"] == 0
