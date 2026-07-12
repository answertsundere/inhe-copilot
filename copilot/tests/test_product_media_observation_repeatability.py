from scripts.test_product_media_observation_repeatability import _report


def _attempt(*, execution="success", completion="complete_json", rejections=()):
    return {
        "observation_set": [], "attributes": [], "values": [], "identities": ["IID"], "regions": [],
        "rejections": list(rejections), "high_risk": False,
        "execution_result": execution, "completion_result": completion,
    }


def test_execution_or_completion_failure_is_not_a_semantic_rejection_comparison():
    report = _report([
        {"media_asset_id": 1, "first": _attempt(), "second": _attempt()},
        {"media_asset_id": 2, "first": _attempt(execution="provider_error", completion="not_started"),
         "second": _attempt(execution="success", completion="complete_json")},
    ])

    assert report["execution_attempt_count"] == 4
    assert report["execution_success_count"] == 2
    assert report["semantic_comparable_pair_count"] == 1
    assert report["semantic_rejection_consistency_rate"] == 1
    assert report["execution_failure_distribution"] == {"provider_error": 1}
    assert report["preprocessing_profile"] == "raw_original"


def test_empty_semantic_comparison_cannot_pass():
    report = _report([{
        "media_asset_id": 1,
        "first": _attempt(execution="timeout_error", completion="not_started"),
        "second": _attempt(execution="timeout_error", completion="not_started"),
    }])

    assert report["semantic_comparable_pair_count"] == 0
    assert report["semantic_rejection_consistency_rate"] == 0
    assert report["execution_success_rate"] == 0
