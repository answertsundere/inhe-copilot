from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

import pytest

from scripts.qualify_risk_tier_fast_path import (
    DATASET_ID,
    FROZEN_DATASET_SHA256,
    NEGATIVE_MUTATIONS,
    _runtime_identity,
    _sha256,
    _write_json,
    run_eligibility_matrix,
    validate_dataset,
)


FIXTURE = (
    Path(__file__).parent
    / "fixtures"
    / "risk_tier_fast_path"
    / "v1.json"
)
MANIFEST = (
    Path(__file__).parent
    / "fixtures"
    / "risk_tier_fast_path"
    / "v1.manifest.json"
)


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_versioned_fixture_has_required_real_derived_coverage_and_privacy():
    dataset = _load(FIXTURE)
    manifest = _load(MANIFEST)

    validate_dataset(dataset, manifest)

    assert dataset["dataset_id"] == DATASET_ID
    assert manifest["positive_count"] == 30
    assert manifest["negative_count"] >= 30
    assert manifest["anonymous_product_count"] >= 10
    assert len(manifest["fact_type_counts"]) >= 3
    assert manifest["privacy_scan"]["passed"] is True
    assert len(manifest["evaluator_source_sha256"]) == 64
    int(manifest["evaluator_source_sha256"], 16)
    assert set(NEGATIVE_MUTATIONS) <= {
        case["mutation"]
        for case in dataset["cases"]
        if case["kind"] == "negative"
    }


def test_evaluator_labels_are_not_part_of_the_service_request_payload():
    dataset = _load(FIXTURE)

    for case in dataset["cases"]:
        encoded_request = json.dumps(
            case["request"],
            ensure_ascii=False,
            sort_keys=True,
        )
        assert '"expected"' not in encoded_request
        assert '"mutation"' not in encoded_request
        assert "benchmark" not in encoded_request.lower()
        assert "rubric" not in encoded_request.lower()
        assert "correct_answer" not in encoded_request.lower()


def test_repaired_contract_qualifies_three_rounds_without_composer():
    report, exit_code = run_eligibility_matrix(
        _load(FIXTURE),
        _load(MANIFEST),
        rules_dir=str(Path(__file__).parents[1] / "rules"),
    )

    assert exit_code == 0
    assert report["status"] == "qualified"
    assert report["stop_reason"] == ""
    assert report["attempted"] is True
    assert report["rounds_completed"] == 3
    assert report["positive_count"] == 30
    assert report["positive_eligible_count"] == report["positive_count"]
    assert report["positive_failed_count"] == 0
    assert report["positive_failure_reasons"] == {}
    assert report["negative_blocked_count"] == report["negative_count"] == 40
    assert report["negative_eligible_count"] == 0
    assert report["negative_eligible_mutations"] == []
    assert all(
        round_result["stable_against_round_one"] is True
        for round_result in report["rounds"]
    )
    assert report["composer_call_count"] == 0
    assert report["fast_path_shadow_implemented"] is False
    assert report["formal_reply_change_count"] == 0
    assert report["can_send_true_count"] == 0
    assert report["used_for_final_reply"] is False
    assert report["can_change_can_send"] is False
    assert report["stopped_before_full_path_baseline"] is False
    assert report["stopped_before_shadow_fast_path"] is False


def test_unknown_domain_and_public_context_injection_are_blocked():
    report, _exit_code = run_eligibility_matrix(
        _load(FIXTURE),
        _load(MANIFEST),
        rules_dir=str(Path(__file__).parents[1] / "rules"),
    )
    first_round = report["rounds"][0]["results"]
    by_mutation = {
        result["mutation"]: result
        for result in first_round
        if result["kind"] == "negative"
    }

    for mutation in (
        "domain_policy_missing",
        "domain_policy_invalid_schema",
        "domain_policy_invalid_version",
        "public_context_injection",
    ):
        assert by_mutation[mutation]["eligible"] is False
        assert "domain_policy_not_loaded" in by_mutation[mutation]["block_reasons"]


def test_one_round_is_attempted_but_never_reported_as_qualified():
    report, exit_code = run_eligibility_matrix(
        _load(FIXTURE),
        _load(MANIFEST),
        rules_dir=str(Path(__file__).parents[1] / "rules"),
        max_rounds=1,
    )

    assert exit_code == 2
    assert report["status"] == "attempted"
    assert report["stop_reason"] == "qualification_incomplete"
    assert report["rounds_completed"] == 1
    assert report["positive_eligible_count"] == 30
    assert report["negative_blocked_count"] == 40


def test_dataset_hash_tampering_fails_closed():
    dataset = _load(FIXTURE)
    manifest = _load(MANIFEST)
    dataset["cases"][0]["request"]["customer_message"] = "tampered"

    with pytest.raises(ValueError, match="dataset_hash_mismatch"):
        validate_dataset(dataset, manifest)


def test_fixture_and_manifest_cannot_be_rebased_to_tampered_content():
    dataset = _load(FIXTURE)
    manifest = _load(MANIFEST)
    dataset["cases"][0]["case_uid"] = "changed-uid"
    manifest["dataset_sha256"] = _sha256(dataset)

    with pytest.raises(ValueError, match="frozen_dataset_hash_mismatch"):
        validate_dataset(dataset, manifest)

    assert FROZEN_DATASET_SHA256 == _load(MANIFEST)["dataset_sha256"]


@pytest.mark.parametrize(
    ("retained_kind", "expected_reason"),
    [
        ("positive", "negative_denominator_empty"),
        ("negative", "positive_denominator_empty"),
    ],
)
def test_empty_denominator_fails_closed(retained_kind, expected_reason):
    dataset = deepcopy(_load(FIXTURE))
    dataset["cases"] = [
        case for case in dataset["cases"] if case["kind"] == retained_kind
    ]
    manifest = deepcopy(_load(MANIFEST))
    manifest["dataset_sha256"] = _sha256(dataset)

    with pytest.raises(ValueError, match=expected_reason):
        validate_dataset(dataset, manifest)


def test_report_write_is_atomic_and_leaves_parseable_json(tmp_path):
    output = tmp_path / "report.json"
    _write_json(str(output), {"status": "attempted", "count": 70})

    assert json.loads(output.read_text(encoding="utf-8")) == {
        "count": 70,
        "status": "attempted",
    }
    assert list(tmp_path.glob("*.tmp")) == []
    assert list(tmp_path.glob(".*.tmp")) == []


def test_runtime_identity_has_recomputable_contract_hash_shape():
    identity = _runtime_identity()

    assert len(identity["runtime_commit"]) == 40
    int(identity["runtime_commit"], 16)
    assert len(identity["source_contract_sha256"]) == 64
    int(identity["source_contract_sha256"], 16)
    assert identity["source_file_count"] == 2
