from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest

import scripts.run_p1_gold_conversation_baseline as p1_baseline
from app.services.high_quality_long_conversation_review_service import (
    load_and_validate_review_dataset,
)
from scripts.run_p1_gold_conversation_baseline import (
    P1BaselineIntegrityError,
)
from scripts import compare_model_first_answer_composer as evaluator


_PROJECT_ROOT = Path(__file__).resolve().parents[1]
_FIXTURE_ROOT = (
    _PROJECT_ROOT / "tests" / "fixtures" / "p1_conversation_reconstructed"
)
_DATASET_PATH = _FIXTURE_ROOT / "v1.json"
_MANIFEST_PATH = _FIXTURE_ROOT / "v1.manifest.json"


def test_reconstructed_contract_is_distinct_from_missing_original_fixed8():
    contract = p1_baseline._resolve_dataset_contract(
        "conversation-reconstructed-v1"
    )

    assert contract.dataset_id == "p1-conversation-reconstructed-v1"
    assert contract.case_count == 8
    assert contract.source_class == "conversation_reconstructed"
    assert contract.real_customer_accuracy is None
    assert contract.original_fixed8_restored is False


def test_unknown_dataset_contract_fails_closed():
    with pytest.raises(
        P1BaselineIntegrityError,
        match="dataset_contract_unknown",
    ):
        p1_baseline._resolve_dataset_contract("fixed8")


def test_parser_keeps_legacy_contract_as_default():
    args = p1_baseline.build_parser().parse_args([])

    assert args.dataset_contract == "legacy-real-derived-v4"


def test_parser_accepts_explicit_reconstructed_contract():
    args = p1_baseline.build_parser().parse_args([
        "--dataset-contract",
        "conversation-reconstructed-v1",
    ])

    assert args.dataset_contract == "conversation-reconstructed-v1"


def test_reconstructed_fixture_has_fixed_coverage_and_no_accuracy_claim():
    dataset, validation = load_and_validate_review_dataset(_DATASET_PATH)
    manifest = json.loads(_MANIFEST_PATH.read_text(encoding="utf-8"))

    assert validation["validation_status"] == "passed"
    assert len(dataset["scenarios"]) == 8
    assert [row["reconstruction_alias"] for row in dataset["scenarios"]] == [
        f"rc-{index:02d}" for index in range(1, 9)
    ]
    assert dataset["source_class"] == "conversation_reconstructed"
    assert manifest["real_customer_accuracy"] is None
    assert manifest["optimization_unverified"] is True
    assert manifest["original_fixed8_restored"] is False
    assert manifest["privacy_declaration"]["scan_passed"] is True

    p1_baseline._validate_reconstructed_dataset_contract(dataset, manifest)


def test_reconstructed_fixture_passes_runner_preflight():
    contract = p1_baseline._resolve_dataset_contract(
        "conversation-reconstructed-v1"
    )

    dataset, inventory, manifest = p1_baseline._preflight_dataset(
        _DATASET_PATH,
        _MANIFEST_PATH,
        contract=contract,
    )

    assert dataset["dataset_id"] == contract.dataset_id
    assert inventory["scenario_count"] == contract.case_count
    assert inventory["conversation_history_turn_count"] == 40
    assert manifest["content_sha256"] == contract.dataset_sha256


def test_reconstructed_labels_remain_outside_agent_payload():
    dataset = json.loads(_DATASET_PATH.read_text(encoding="utf-8"))

    payload = evaluator._agent_payload(dataset["scenarios"][0])
    serialized = json.dumps(payload, ensure_ascii=False)

    for field in (
        "expected_contract",
        "prohibited_outcomes",
        "reconstruction_alias",
        "source_class",
    ):
        assert field not in serialized


@pytest.mark.parametrize(
    "field",
    (
        "expected_contract",
        "prohibited_outcomes",
        "reconstruction_alias",
        "source_class",
    ),
)
def test_reconstructed_evaluation_fields_are_rejected_inside_agent_payload(
    field,
):
    dataset = json.loads(_DATASET_PATH.read_text(encoding="utf-8"))
    scenario = deepcopy(dataset["scenarios"][0])
    scenario["api_request_template"][field] = "forbidden"

    with pytest.raises(ValueError, match=f"evaluation_field_leakage:{field}"):
        evaluator._agent_payload(scenario)


def test_reconstructed_checkpoint_and_summary_keep_evidence_class_explicit():
    contract = p1_baseline._resolve_dataset_contract(
        "conversation-reconstructed-v1"
    )
    checkpoint = p1_baseline._checkpoint_payload(
        contract=contract,
        dataset_hash=contract.dataset_sha256,
        runtime={
            "runtime_commit": "a" * 40,
            "source_tree_sha256": "b" * 64,
        },
        runner_source_sha256="c" * 64,
        formal_knowledge_before={},
        dml_start_offset=0,
        completed_files=[],
    )
    summary = p1_baseline._summary_payload(
        contract=contract,
        observations=[],
        scored_rows=[],
        deterministic_summary={},
        status="incomplete_execution",
        integrity_stop_reason="",
        owner_counts={},
        formal_knowledge={},
    )

    for payload in (checkpoint, summary):
        assert payload["dataset_contract"] == contract.contract_name
        assert payload["source_class"] == "conversation_reconstructed"
        assert payload["real_customer_accuracy"] is None
        assert payload["optimization_unverified"] is True
        assert payload["original_fixed8_restored"] is False
    assert summary["scenario_count"] == 8


@pytest.mark.parametrize(
    ("mutator", "reason"),
    [
        (
            lambda dataset, manifest: dataset.__setitem__(
                "source_class", "real_customer"
            ),
            "reconstructed_source_class_mismatch",
        ),
        (
            lambda dataset, manifest: dataset["scenarios"][1].__setitem__(
                "reconstruction_alias", "rc-01"
            ),
            "reconstructed_alias_sequence_mismatch",
        ),
        (
            lambda dataset, manifest: manifest.__setitem__(
                "real_customer_accuracy", 1.0
            ),
            "reconstructed_accuracy_claim_forbidden",
        ),
        (
            lambda dataset, manifest: manifest.__setitem__(
                "original_fixed8_restored", True
            ),
            "reconstructed_original_equivalence_forbidden",
        ),
        (
            lambda dataset, manifest: manifest.__setitem__(
                "optimization_unverified", False
            ),
            "reconstructed_optimization_claim_forbidden",
        ),
    ],
)
def test_reconstructed_contract_fails_closed_on_identity_or_claim_mutation(
    mutator,
    reason,
):
    dataset = json.loads(_DATASET_PATH.read_text(encoding="utf-8"))
    manifest = json.loads(_MANIFEST_PATH.read_text(encoding="utf-8"))
    mutated_dataset = deepcopy(dataset)
    mutated_manifest = deepcopy(manifest)
    mutator(mutated_dataset, mutated_manifest)

    with pytest.raises(P1BaselineIntegrityError, match=reason):
        p1_baseline._validate_reconstructed_dataset_contract(
            mutated_dataset,
            mutated_manifest,
        )
