from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import subprocess

import pytest

import scripts.run_p1_gold_conversation_baseline as p1_baseline
from app.services.claim_resolution_service import _claim_uid
from app.services.canonical_conversation_turn_service import (
    normalize_conversation_turns,
)
from app.services.high_quality_long_conversation_review_service import (
    HighQualityReviewProjectionError,
    project_trusted_goal_references,
)
from app.services.semantic_fact_type_service import (
    GOAL_IDENTITY_SCHEMA_VERSION,
    _goal_ref,
    canonical_current_customer_turn_uid,
)
from scripts.run_p1_gold_conversation_baseline import (
    P1BaselineIntegrityError,
    _assert_report_safe,
    _build_case_observation_with_capsule,
    _build_projection_failure_capsule,
    _build_post_run_manifest,
    _checkpoint_payload,
    _compact_snapshot_fingerprint,
    _evaluator_source_sha256,
    _finalize_from_checkpoint,
    _load_expert_review,
    _prepare_knowledge_snapshot,
    _runner_source_sha256,
    _runtime_source_tree_sha256,
    _summary_payload,
    _validate_runtime_binding,
    _write_json,
    _write_projection_capsule,
    assess_offline_reconstruction,
    build_case_observation,
)


_SECRET = b"p1-baseline-test-secret"


def test_goal_recall_diagnostic_normalizes_existing_claim_and_dimension_aliases():
    diagnostic = p1_baseline._goal_recall_diagnostic(
        {
            "expected_claims": [
                {"claim_type": "material", "attribute_key": "material"},
                {"claim_type": "dimensions", "attribute_key": "height"},
                {"claim_type": "dimensions", "attribute_key": "width"},
            ],
        },
        {
            "status": "valid",
            "goals": [
                {
                    "goal_kind": "customer_goal",
                    "claim_type": "material_composition",
                    "attribute_key": "material_composition",
                },
                {
                    "goal_kind": "customer_goal",
                    "claim_type": "dimensions",
                    "attribute_key": "overall_height",
                },
                {
                    "goal_kind": "customer_goal",
                    "claim_type": "dimensions",
                    "attribute_key": "overall_width",
                },
            ],
        },
    )

    assert diagnostic == {
        "contract": "canonical_claim_type_and_attribute_slot/v2",
        "numerator": 3,
        "denominator": 3,
        "unexpected_goal_count": 0,
        "status": "scored",
    }


def test_goal_recall_diagnostic_keeps_unrelated_dimension_axis_unmatched():
    diagnostic = p1_baseline._goal_recall_diagnostic(
        {
            "expected_claims": [
                {"claim_type": "dimensions", "attribute_key": "height"},
            ],
        },
        {
            "status": "valid",
            "goals": [
                {
                    "goal_kind": "customer_goal",
                    "claim_type": "dimensions",
                    "attribute_key": "overall_depth",
                },
            ],
        },
    )

    assert diagnostic == {
        "contract": "canonical_claim_type_and_attribute_slot/v2",
        "numerator": 0,
        "denominator": 1,
        "unexpected_goal_count": 1,
        "status": "scored",
    }


def test_goal_recall_diagnostic_separates_presence_identity_and_dimension_scope():
    diagnostic = p1_baseline._goal_recall_diagnostic(
        {
            "expected_claims": [
                {
                    "understanding_expectation": {
                        "goal_kind": "customer_goal",
                        "claim_type_status": "canonical",
                        "claim_type": "dimensions",
                        "attribute_key": "width",
                        "semantic_key": "",
                        "subject_scope": "product",
                        "source_span_start": 0,
                        "source_span_end": 2,
                        "source_span_sha256": "a" * 64,
                    },
                },
                {
                    "understanding_expectation": {
                        "goal_kind": "customer_goal",
                        "claim_type_status": "unmapped",
                        "claim_type": "",
                        "attribute_key": "",
                        "semantic_key": "safety_guarantee",
                        "subject_scope": "",
                        "source_span_start": 3,
                        "source_span_end": 5,
                        "source_span_sha256": "b" * 64,
                    },
                },
                {
                    "understanding_expectation": {
                        "goal_kind": "media_request",
                        "claim_type_status": "unmapped",
                        "claim_type": "",
                        "attribute_key": "",
                        "semantic_key": "installation_video",
                        "subject_scope": "",
                        "source_span_start": 6,
                        "source_span_end": 8,
                        "source_span_sha256": "c" * 64,
                    },
                },
                {"claim_type": "product_identity", "attribute_key": "current_product"},
            ],
        },
        {
            "status": "valid",
            "goals": [
                {
                    "goal_kind": "customer_goal",
                    "claim_type_status": "canonical",
                    "claim_type": "dimensions",
                    "attribute_key": "overall_width",
                    "subject_scope": "",
                    "semantic_key": "",
                    "source_span_start": 0,
                    "source_span_end": 2,
                    "source_span_sha256": "a" * 64,
                },
                {
                    "goal_kind": "customer_goal",
                    "claim_type_status": "unmapped",
                    "claim_type": "",
                    "attribute_key": "",
                    "subject_scope": "",
                    "semantic_key": "safety_guarantee",
                    "source_span_start": 3,
                    "source_span_end": 5,
                    "source_span_sha256": "b" * 64,
                },
                {
                    "goal_kind": "media_request",
                    "claim_type_status": "unmapped",
                    "claim_type": "",
                    "attribute_key": "",
                    "subject_scope": "",
                    "semantic_key": "installation_video",
                    "source_span_start": 6,
                    "source_span_end": 8,
                    "source_span_sha256": "c" * 64,
                },
            ],
        },
    )

    assert diagnostic == {
        "contract": "atomic_goal_identity_and_effective_scope/v4",
        "numerator": 2,
        "denominator": 2,
        "unexpected_goal_count": 0,
        "customer_goal_identity_recall": {
            "numerator": 2,
            "denominator": 2,
            "rate": 1.0,
        },
        "explicit_request_recall": {
            "numerator": 3,
            "denominator": 3,
            "rate": 1.0,
        },
        "dimension_subject_scope_attribution": {
            "numerator": 1,
            "denominator": 1,
            "rate": 1.0,
        },
        "unscored_expected_claim_count": 1,
        "status": "scored",
    }


def test_goal_recall_scope_preserves_explicit_non_product_scope():
    diagnostic = p1_baseline._goal_recall_diagnostic(
        {
            "expected_claims": [{
                "understanding_expectation": {
                    "goal_kind": "customer_goal",
                    "claim_type_status": "canonical",
                    "claim_type": "dimensions",
                    "attribute_key": "width",
                    "semantic_key": "",
                    "subject_scope": "product",
                    "source_span_start": 0,
                    "source_span_end": 2,
                    "source_span_sha256": "a" * 64,
                },
            }],
        },
        {
            "status": "valid",
            "goals": [{
                "goal_kind": "customer_goal",
                "claim_type_status": "canonical",
                "claim_type": "dimensions",
                "attribute_key": "overall_width",
                "subject_scope": "packaging",
                "semantic_key": "",
                "source_span_start": 0,
                "source_span_end": 2,
                "source_span_sha256": "a" * 64,
            }],
        },
    )

    assert diagnostic["dimension_subject_scope_attribution"] == {
        "numerator": 0,
        "denominator": 1,
        "rate": 0.0,
    }


def test_goal_recall_uses_trusted_policy_identity_for_unmapped_goal():
    diagnostic = p1_baseline._goal_recall_diagnostic(
        {
            "expected_claims": [{
                "understanding_expectation": {
                    "goal_kind": "customer_goal",
                    "claim_type_status": "unmapped",
                    "claim_type": "",
                    "attribute_key": "",
                    "semantic_key": "ordinary_durability_guidance",
                    "policy_intent_ref": "product_durability_practical_guidance",
                    "subject_scope": "",
                    "source_span_start": 0,
                    "source_span_end": 4,
                    "source_span_sha256": "a" * 64,
                },
            }],
        },
        {
            "status": "valid",
            "goals": [{
                "goal_kind": "customer_goal",
                "claim_type_status": "unmapped",
                "claim_type": "",
                "attribute_key": "",
                "semantic_key": "daily_use_durability_guidance",
                "policy_intent_ref": "product_durability_practical_guidance",
                "subject_scope": "",
                "source_span_start": 0,
                "source_span_end": 4,
                "source_span_sha256": "a" * 64,
            }],
        },
    )

    assert diagnostic["customer_goal_identity_recall"] == {
        "numerator": 1,
        "denominator": 1,
        "rate": 1.0,
    }


def test_reconstructed_fixed8_goal_labels_are_versioned_and_contract_valid():
    root = Path(__file__).parent / "fixtures" / "p1_conversation_reconstructed"
    dataset, inventory, _manifest = p1_baseline._preflight_dataset(
        root / "v1.json",
        root / "v1.manifest.json",
        contract=p1_baseline._resolve_dataset_contract(
            "conversation-reconstructed-v1"
        ),
    )
    expectations = [
        item["understanding_expectation"]
        for scenario in dataset["scenarios"]
        for item in scenario["expected_claims"]
        if "understanding_expectation" in item
    ]

    assert inventory["validation_status"] == "passed"
    assert dataset["dataset_version"] == "1.2.0"
    assert len(expectations) == 17
    assert sum(
        item["goal_kind"] == "customer_goal" for item in expectations
    ) == 16
    assert sum(
        item["goal_kind"] == "media_request" for item in expectations
    ) == 1
    assert sum(bool(item["subject_scope"]) for item in expectations) == 4


def test_reconstructed_goal_labels_bind_each_span_to_its_current_message():
    root = Path(__file__).parent / "fixtures" / "p1_conversation_reconstructed"
    dataset = json.loads((root / "v1.json").read_text(encoding="utf-8"))

    for scenario in dataset["scenarios"]:
        message = scenario["api_request_template"]["message"]
        for claim in scenario["expected_claims"]:
            expectation = claim.get("understanding_expectation")
            if not isinstance(expectation, dict):
                continue
            source = message[
                expectation["source_span_start"]:
                expectation["source_span_end"]
            ]
            assert expectation["source_span_sha256"] == hashlib.sha256(
                source.encode("utf-8")
            ).hexdigest()


def _goal(
    message: str,
    source_text: str,
    *,
    claim_type: str,
    attribute_key: str,
    conversation_history: list[dict] | None = None,
) -> dict:
    start = message.index(source_text)
    end = start + len(source_text)
    digest = hashlib.sha256(source_text.encode("utf-8")).hexdigest()
    goal = {
        "schema_version": GOAL_IDENTITY_SCHEMA_VERSION,
        "goal_kind": "customer_goal",
        "claim_type_status": "canonical",
        "claim_type": claim_type,
        "claim_type_exact_match": True,
        "attribute_key": attribute_key,
        "semantic_key": "",
        "policy_intent_ref": "",
        "policy_goal_family": "",
        "policy_intent_kind": "",
        "goal_summary": source_text,
        "confidence": 1.0,
        "source": "current_customer_message",
        "source_span_start": start,
        "source_span_end": end,
        "source_span_sha256": digest,
        "source_text_sha256": digest,
        "source_turn_uid": canonical_current_customer_turn_uid(
            message,
            conversation_history=conversation_history,
        ),
        "owner": "turn_understanding_owner",
        "source_stage": "semantic_fact_type_service",
        "claim_type_reason_code": "",
    }
    goal["goal_ref"] = _goal_ref(goal)
    return goal


def _response(
    message: str = "材质和尺寸分别是什么",
    *,
    conversation_history: list[dict] | None = None,
) -> dict:
    goals = [
        _goal(
            message,
            "材质",
            claim_type="material",
            attribute_key="material",
            conversation_history=conversation_history,
        ),
        _goal(
            message,
            "尺寸",
            claim_type="dimensions",
            attribute_key="dimensions",
            conversation_history=conversation_history,
        ),
    ]
    resolutions = []
    clauses = []
    for index, goal in enumerate(goals, start=1):
        claim_uid = _claim_uid({"goal_ref": goal["goal_ref"]})
        resolutions.append({
            "goal_ref": goal["goal_ref"],
            "claim_uid": claim_uid,
            "claim_type": goal["claim_type"],
            "attribute_key": goal["attribute_key"],
            "status": "supported",
            "support_basis": "direct_evidence",
            "evidence_uids": [f"evidence-{index}"],
            "reason": "",
        })
        clauses.append({
            "clause_ref": f"clause-{index}",
            "goal_ref": claim_uid,
            "clause_kind": "supported_fact",
            "text": f"已核对{goal['goal_summary']}。",
            "evidence_uids": [f"evidence-{index}"],
        })
    return {
        "analysis_pipeline": {
            "version": "analysis-pipeline-v1",
            "stages": [
                {"stage": "canonical_input", "status": "completed"},
                {"stage": "graph_execution", "status": "completed"},
            ],
        },
        "turn_understanding": {
            "schema_version": "turn-understanding/v2",
            "owner": "turn_understanding_owner",
            "source_stage": "query_fact_type_classifier",
            "goal_understanding_status": "valid",
            "customer_goals": goals,
        },
        "minimal_decision_context": {
            "claim_resolutions": resolutions,
        },
        "model_first_answer_composer": {
            "clauses": clauses,
        },
    }


def _project(
    response: dict,
    message: str = "材质和尺寸分别是什么",
    *,
    conversation_history: list[dict] | None = None,
) -> dict:
    return project_trusted_goal_references(
        response,
        customer_message=message,
        conversation_history=conversation_history,
        alias_secret=_SECRET,
    )


def test_valid_server_goal_refs_become_stable_linked_aliases():
    response = _response()
    result = _project(response)
    serialized = json.dumps(result, ensure_ascii=False)

    assert result["goal_count"] == 2
    assert result["resolution_count"] == 2
    assert result["clause_count"] == 2
    assert re.search(r"\bgoal-[0-9a-f]{16}\b", serialized) is None
    assert re.search(r"\bclaim-[0-9a-f]{16}\b", serialized) is None
    assert {
        item["goal_alias"] for item in result["goals"]
    } == {
        item["goal_alias"] for item in result["resolutions"]
    }
    assert {
        item["claim_alias"] for item in result["resolutions"]
    } == {
        item["claim_alias"] for item in result["composer_clauses"]
    }


def test_goal_projection_keeps_validated_dimension_scope_as_safe_enum():
    response = _response()
    response["turn_understanding"]["customer_goals"][1][
        "subject_scope"
    ] = "product"

    result = _project(response)
    projected_dimension = next(
        item
        for item in result["goals"]
        if item["attribute_key"] == "dimensions"
    )

    assert projected_dimension["subject_scope"] == "product"
    assert "goal_summary" not in projected_dimension
    assert "source_text" not in projected_dimension


def test_goal_alias_projection_is_independent_of_input_order():
    response = _response()
    reversed_response = deepcopy(response)
    reversed_response["turn_understanding"]["customer_goals"].reverse()
    reversed_response["minimal_decision_context"][
        "claim_resolutions"
    ].reverse()
    reversed_response["model_first_answer_composer"]["clauses"].reverse()

    assert _project(response) == _project(reversed_response)


def test_goal_projection_uses_canonical_history_position():
    history = [
        {"role": "customer", "content": "前一个问题"},
        {"role": "assistant", "content": "前一个回答"},
    ]
    canonical_history, _ = normalize_conversation_turns(
        history,
        strict=False,
    )
    response = _response(conversation_history=canonical_history)

    result = _project(response, conversation_history=history)

    assert result["status"] == "valid"
    with pytest.raises(
        HighQualityReviewProjectionError,
        match="canonical_goal_provenance_invalid",
    ):
        _project(response, conversation_history=[])


def test_goal_projection_normalizes_legacy_history_like_pipeline():
    raw_history = [
        {"role": "customer", "content": "前一个问题"},
        {"role": "assistant", "content": "前一个回答"},
        {"role": "customer", "content": "继续核对"},
    ]
    canonical_history, diagnostics = normalize_conversation_turns(
        raw_history,
        strict=False,
    )
    response = _response(conversation_history=canonical_history)

    result = _project(response, conversation_history=raw_history)

    assert diagnostics["status"] == "degraded"
    assert result["status"] == "valid"


@pytest.mark.parametrize("status", ["degraded", "invalid"])
def test_non_authoritative_understanding_without_refs_is_business_result(status):
    response = _response()
    response["turn_understanding"].update(
        goal_understanding_status=status,
        customer_goals=[],
    )
    response["minimal_decision_context"]["claim_resolutions"] = []
    response["model_first_answer_composer"]["clauses"] = []

    result = _project(response)

    assert result["status"] == "not_authoritative"
    assert result["reason_code"] == f"goal_understanding_{status}"
    assert result["goal_count"] == 0


def test_valid_understanding_without_goals_fails_closed():
    response = _response()
    response["turn_understanding"]["customer_goals"] = []
    response["minimal_decision_context"]["claim_resolutions"] = []
    response["model_first_answer_composer"]["clauses"] = []

    with pytest.raises(
        HighQualityReviewProjectionError,
        match="canonical_customer_goals_missing",
    ):
        _project(response)


@pytest.mark.parametrize(
    ("mutate", "reason"),
    [
        (
            lambda value: value["turn_understanding"].update(
                owner="public_request"
            ),
            "turn_understanding_owner_invalid",
        ),
        (
            lambda value: value["turn_understanding"].update(
                goal_understanding_status="degraded"
            ),
            "non_authoritative_goal_references_present",
        ),
        (
            lambda value: value["turn_understanding"][
                "customer_goals"
            ][0].update(owner=""),
            "canonical_goal_provenance_invalid",
        ),
        (
            lambda value: value["turn_understanding"][
                "customer_goals"
            ][0].update(source_turn_uid="turn-" + "0" * 20),
            "canonical_goal_provenance_invalid",
        ),
        (
            lambda value: value["turn_understanding"][
                "customer_goals"
            ][0].update(source_span_start=1),
            "canonical_goal_provenance_invalid",
        ),
        (
            lambda value: value["turn_understanding"][
                "customer_goals"
            ][0].update(source_span_sha256="0" * 64),
            "canonical_goal_provenance_invalid",
        ),
        (
            lambda value: value["turn_understanding"][
                "customer_goals"
            ][0].update(goal_ref="goal-not-canonical"),
            "canonical_goal_provenance_invalid",
        ),
        (
            lambda value: value["minimal_decision_context"][
                "claim_resolutions"
            ][0].update(goal_ref=""),
            "claim_resolution_goal_ref_missing",
        ),
        (
            lambda value: value["minimal_decision_context"][
                "claim_resolutions"
            ][0].update(goal_ref="goal-0000000000000000"),
            "claim_resolution_goal_ref_untrusted",
        ),
        (
            lambda value: value["minimal_decision_context"][
                "claim_resolutions"
            ][0].update(claim_uid="claim-0000000000000000"),
            "claim_resolution_identity_invalid",
        ),
        (
            lambda value: value["model_first_answer_composer"][
                "clauses"
            ][0].update(goal_ref="claim-0000000000000000"),
            "composer_claim_reference_untrusted",
        ),
    ],
)
def test_untrusted_goal_identity_and_cross_stage_references_fail_closed(
    mutate,
    reason,
):
    response = _response()
    mutate(response)

    with pytest.raises(HighQualityReviewProjectionError, match=reason):
        _project(response)


@pytest.mark.parametrize(
    "payload",
    [
        {"customer_message": "编号是12345678901234567890"},
        {"customer_message": "手机号13800138000"},
        {"customer_message": "邮箱 buyer@example.com"},
        {"customer_message": "查看https://private.example.test/a"},
        {"customer_message": "api_key=secret-value"},
        {"customer_message": "地址是杭州市西湖区文三路88号"},
    ],
)
def test_customer_pii_and_unknown_long_identifiers_are_still_scanned(
    payload,
):
    with pytest.raises(
        P1BaselineIntegrityError,
        match="report_privacy_validation_failed",
    ):
        _assert_report_safe(payload)


def test_fractional_report_metric_does_not_look_like_long_identifier():
    _assert_report_safe({"coverage": {"rate": 1 / 6}})


@pytest.mark.parametrize(
    "value",
    [
        "12345678901234567890",
        12345678901234567890,
        13800138000.0,
    ],
)
def test_unknown_string_or_integer_like_long_identifier_still_fails(value):
    with pytest.raises(
        P1BaselineIntegrityError,
        match="report_privacy_validation_failed",
    ):
        _assert_report_safe({"unknown_identifier": value})


def test_only_typed_valid_fingerprints_are_removed_from_content_scan():
    _assert_report_safe({
        "source_tree_sha256": "a" * 64,
        "formal_provider_identity": {
            "host_fingerprint": "b" * 12,
        },
    })

    with pytest.raises(
        P1BaselineIntegrityError,
        match="controlled_fingerprint_invalid",
    ):
        _assert_report_safe({"source_tree_sha256": "12345678901234567890"})
    with pytest.raises(
        P1BaselineIntegrityError,
        match="report_privacy_validation_failed",
    ):
        _assert_report_safe({"unknown_digest": "12345678901234567890"})


@pytest.mark.parametrize("field", ["prompt", "reasoning", "api_key"])
def test_prompt_reasoning_and_credentials_are_forbidden_report_fields(field):
    with pytest.raises(
        P1BaselineIntegrityError,
        match="prohibited_report_field",
    ):
        _assert_report_safe({field: "not allowed"})


def test_raw_internal_goal_or_claim_refs_cannot_be_written():
    with pytest.raises(
        P1BaselineIntegrityError,
        match="raw_internal_goal_reference_forbidden",
    ):
        _assert_report_safe({"value": "goal-0123456789abcdef"})
    with pytest.raises(
        P1BaselineIntegrityError,
        match="raw_internal_goal_reference_forbidden",
    ):
        _assert_report_safe({"value": "claim-fedcba9876543210"})


def test_split_report_files_are_utf8_json_and_contain_no_raw_refs(tmp_path):
    result = _project(_response())
    payloads = {
        "summary.json": {
            "schema_version": "summary/v1",
            "real_customer_accuracy": None,
        },
        "manifest.json": {
            "schema_version": "manifest/v1",
            "source_tree_sha256": "a" * 64,
        },
        "cases/case_TEST.json": result,
        "review_pack.json": {
            "schema_version": "review/v1",
            "items": [result],
        },
    }

    for relative, payload in payloads.items():
        path = tmp_path / relative
        metadata = _write_json(path, payload)
        with path.open("r", encoding="utf-8") as handle:
            assert json.load(handle) == payload
        assert metadata["sha256"] == hashlib.sha256(
            path.read_bytes()
        ).hexdigest()
        serialized = path.read_text(encoding="utf-8")
        assert re.search(r"\bgoal-[0-9a-f]{16}\b", serialized) is None
        assert re.search(r"\bclaim-[0-9a-f]{16}\b", serialized) is None


def test_checkpoint_persists_runner_and_knowledge_start_identity():
    payload = _checkpoint_payload(
        dataset_hash="a" * 64,
        runtime={
            "runtime_commit": "b" * 40,
            "source_tree_sha256": "c" * 64,
        },
        runner_source_sha256="d" * 64,
        formal_knowledge_before={
            "formal_content_sha256": "e" * 64,
            "tables": [],
        },
        dml_start_offset=17,
        completed_files=[],
    )

    assert payload["runner_source_sha256"] == "d" * 64
    assert payload["formal_knowledge_before"] == {
        "formal_content_sha256": "e" * 64,
        "tables": [],
    }
    assert payload["dml_start_offset"] == 17
    assert payload["projection_capsule_count"] == 0
    assert payload["projection_capsule_files"] == []
    _assert_report_safe(payload)


def _capsule_scenario() -> dict:
    return {
        "scenario_uid": "scenario-projection-capsule",
        "business_domain": "product_fact",
        "risk_level": "low",
        "must_handoff": False,
        "expected_claims": [],
        "api_request_template": {
            "message": str(_response.__defaults__[0]),
            "conversation_history": [],
        },
    }


def _capsule(response: dict) -> dict:
    return _build_projection_failure_capsule(
        run_uid_alias="run_TEST",
        case_uid_alias="case_TEST",
        case_index=1,
        status_code=200,
        response=response,
        alias_secret=_SECRET,
    )


def test_projection_capsule_contains_only_shapes_aliases_and_hashes():
    response = _response()
    response["suggested_reply"] = (
        "Call 13800138000 for order 123456789012345678."
    )
    response["unexpected_private_field"] = "https://private.example/path"

    capsule = _capsule(response)
    serialized = json.dumps(capsule, ensure_ascii=False)

    assert capsule["projection_status"] == "pending"
    assert capsule["used_for_scoring"] is False
    assert capsule["used_for_agent_input"] is False
    assert capsule["can_change_can_send"] is False
    assert capsule["authoritative_business_result"] is False
    assert capsule["runtime_customer_goal_count"] == 2
    assert capsule["resolution_count"] == 2
    assert capsule["clause_count"] == 2
    assert "13800138000" not in serialized
    assert "123456789012345678" not in serialized
    assert "private.example" not in serialized
    assert "goal-" not in serialized
    assert "claim-" not in serialized
    assert capsule["customer_visible_reply"]["privacy_finding_count"] > 0
    _assert_report_safe(capsule)


def test_projection_excludes_unbound_supporting_only_compatibility_resolution():
    response = _response()
    response["minimal_decision_context"]["claim_resolutions"].append({
        "claim_uid": "claim-legacy-support",
        "goal_ref": "",
        "goal_kind": "",
        "claim_type": "supporting_fact",
        "status": "supported",
        "supporting_only": True,
        "evidence_uids": ["evidence-support"],
    })

    result = _project(response)

    assert result["resolution_count"] == 2
    assert len(result["resolutions"]) == 2


def test_projection_rejects_clause_bound_to_excluded_compatibility_resolution():
    response = _response()
    response["minimal_decision_context"]["claim_resolutions"].append({
        "claim_uid": "claim-legacy-support",
        "goal_ref": "",
        "goal_kind": "",
        "claim_type": "supporting_fact",
        "status": "supported",
        "supporting_only": True,
        "evidence_uids": ["evidence-support"],
    })
    response["model_first_answer_composer"]["clauses"].append({
        "clause_ref": "clause-support",
        "goal_ref": "claim-legacy-support",
        "clause_kind": "supported_fact",
        "text": "compatibility dependency must not render",
        "evidence_uids": ["evidence-support"],
    })

    with pytest.raises(
        HighQualityReviewProjectionError,
        match="composer_claim_reference_untrusted",
    ):
        _project(response)


def test_projection_capsule_exposes_mutation_shapes_without_classifying_owner():
    response = _response()
    goals = response["turn_understanding"]["customer_goals"]
    resolutions = response["minimal_decision_context"]["claim_resolutions"]
    clauses = response["model_first_answer_composer"]["clauses"]
    goals[1]["goal_kind"] = "evidence_dependency"
    goals[1]["supporting_for_goal_ref"] = goals[0]["goal_ref"]
    resolutions[0]["goal_ref"] = "goal-missing"
    resolutions[1]["supporting_for_goal_ref"] = goals[0]["goal_ref"]
    clauses[0]["goal_ref"] = "claim-missing"
    goals.append(deepcopy(goals[0]))
    goals[-1]["goal_kind"] = "legacy_diagnostic"
    goals[-1]["owner"] = "forged_owner"
    goals[-1]["source"] = {"unexpected": "shape"}
    goals[-1]["source_stage"] = None

    capsule = _capsule(response)

    assert capsule["runtime_customer_goal_count"] == 3
    assert (
        capsule["goals"][1]["supporting_for_goal_ref"]["canonical_format"]
        is True
    )
    assert (
        capsule["goals"][1][
            "supporting_ref_matches_trusted_goal"
        ]
        is True
    )
    assert (
        capsule["resolutions"][0]["goal_ref_matches_trusted_goal"]
        is False
    )
    assert (
        capsule["resolutions"][1][
            "supporting_ref_matches_trusted_goal"
        ]
        is True
    )
    assert (
        capsule["clauses"][0][
            "goal_ref_matches_resolution_claim"
        ]
        is False
    )
    assert (
        capsule["goals"][0]["goal_ref"]["alias"]
        == capsule["goals"][2]["goal_ref"]["alias"]
    )
    unknown_kind = capsule["goals"][2]["goal_kind"]
    assert unknown_kind["allowlisted"] is False
    assert "canonical_value" not in unknown_kind
    contract = capsule["goals"][2]["contract_fields"]
    assert contract["owner"]["allowlisted"] is False
    assert contract["source"]["value_type"] == "dict"
    assert contract["source_stage"]["value_type"] == "NoneType"
    assert "forged_owner" not in json.dumps(capsule)
    assert "legacy_diagnostic" not in json.dumps(capsule)


def test_projection_capsule_observes_non_product_goal_shapes_without_refs():
    response = _response()
    goals = response["turn_understanding"]["customer_goals"]
    goals.extend([
        {"goal_kind": "service_action"},
        {"goal_kind": "media_request"},
        {"goal_kind": "contextual_constraint"},
        {"goal_kind": "legacy_diagnostic"},
    ])

    capsule = _capsule(response)
    projected = capsule["goals"][-4:]

    assert [
        item["goal_kind"].get("canonical_value")
        for item in projected[:3]
    ] == [
        "service_action",
        "media_request",
        "contextual_constraint",
    ]
    assert all(
        item["goal_ref"]["present"] is False
        for item in projected
    )
    assert projected[3]["goal_kind"]["allowlisted"] is False


def test_projection_capsule_aliases_are_stable_and_secret_scoped():
    first = _capsule(_response())
    second = _capsule(_response())
    other_secret = _build_projection_failure_capsule(
        run_uid_alias="run_TEST",
        case_uid_alias="case_TEST",
        case_index=1,
        status_code=200,
        response=_response(),
        alias_secret=b"different-capsule-secret",
    )

    first_aliases = [
        item["goal_ref"]["alias"]
        for item in first["goals"]
    ]
    assert first_aliases == [
        item["goal_ref"]["alias"]
        for item in second["goals"]
    ]
    assert first_aliases != [
        item["goal_ref"]["alias"]
        for item in other_secret["goals"]
    ]
    assert len(first_aliases) == len(set(first_aliases))
    assert all(
        re.fullmatch(r"goal_[A-Z2-7]{16}", value)
        for value in first_aliases
    )


def test_projection_capsule_hashes_unallowlisted_exception_text():
    raw_detail = (
        "failed for 13800138000 at https://private.example/path"
    )

    projected = p1_baseline._capsule_exception(
        RuntimeError(raw_detail)
    )
    serialized = json.dumps(projected)

    assert projected["exception_class"] == "unallowlisted_exception"
    assert projected["reason_code"] == ""
    assert projected["value_sha256"]
    assert "13800138000" not in serialized
    assert "private.example" not in serialized


@pytest.mark.parametrize(
    ("field", "value", "expected_type"),
    [
        ("owner", None, "NoneType"),
        ("owner", "turn_understanding_owner", "str"),
        ("owner", {"owner": "nested"}, "dict"),
        ("owner", ["turn_understanding_owner"], "list"),
    ],
)
def test_projection_capsule_records_contract_field_type_without_raw_value(
    field,
    value,
    expected_type,
):
    response = _response()
    response["turn_understanding"][field] = value

    capsule = _capsule(response)
    shape = capsule["turn_understanding_contract"][field]

    assert shape["value_type"] == expected_type
    if value == "turn_understanding_owner":
        assert shape["canonical_value"] == value
    else:
        assert "canonical_value" not in shape


@pytest.mark.parametrize(
    ("value", "expected_type", "canonical"),
    [
        (None, "NoneType", False),
        ("goal-safe-reference", "str", True),
        ({"raw": "goal-private-reference"}, "dict", False),
        (["goal-private-reference"], "list", False),
    ],
)
def test_projection_capsule_malformed_reference_is_hash_only(
    value,
    expected_type,
    canonical,
):
    response = _response()
    response["turn_understanding"]["customer_goals"][0][
        "goal_ref"
    ] = value

    capsule = _capsule(response)
    reference = capsule["goals"][0]["goal_ref"]
    serialized = json.dumps(capsule)

    assert reference["value_type"] == expected_type
    assert reference["canonical_format"] is canonical
    if canonical:
        assert reference["alias"]
    elif value is not None:
        assert reference["value_sha256"]
        assert "private-reference" not in serialized


def test_projection_failure_updates_pending_capsule_before_reraising(tmp_path):
    response = _response()
    response["minimal_decision_context"]["claim_resolutions"][0][
        "goal_ref"
    ] = ""
    case_alias = p1_baseline._case_alias(
        "scenario-projection-capsule",
        _SECRET,
    )
    capsule_path = (
        tmp_path / "projection_capsules" / f"{case_alias}.json"
    )
    records = []

    with pytest.raises(
        P1BaselineIntegrityError,
        match="claim_resolution_goal_ref_missing",
    ):
        _build_case_observation_with_capsule(
            output_dir=tmp_path,
            capsule_path=capsule_path,
            capsule_records=records,
            run_uid_alias="run_TEST",
            case_uid_alias=case_alias,
            case_index=1,
            status_code=200,
            scenario=_capsule_scenario(),
            response=response,
            scored={"error_type": "", "latency_ms": 10},
            alias_secret=_SECRET,
        )

    persisted = json.loads(capsule_path.read_text(encoding="utf-8"))
    assert persisted["projection_status"] == "projection_failed"
    assert persisted["exception"]["present"] is True
    assert persisted["exception"]["reason_code"].startswith(
        "trusted_reference_projection_failed:"
    )
    assert len(records) == 1
    assert records[0]["sha256"] == hashlib.sha256(
        capsule_path.read_bytes()
    ).hexdigest()


def test_projection_failure_preserves_allowlisted_provenance_reason(tmp_path):
    response = _response()
    response["turn_understanding"]["customer_goals"][0][
        "source_turn_uid"
    ] = "turn-" + "0" * 20
    case_alias = p1_baseline._case_alias(
        "scenario-provenance-reason",
        _SECRET,
    )
    capsule_path = (
        tmp_path / "projection_capsules" / f"{case_alias}.json"
    )

    with pytest.raises(
        P1BaselineIntegrityError,
        match=(
            "trusted_reference_projection_failed:"
            "canonical_goal_provenance_invalid:"
            "customer_goal_identity_mismatch,"
            "customer_goal_source_turn_uid_invalid"
        ),
    ):
        _build_case_observation_with_capsule(
            output_dir=tmp_path,
            capsule_path=capsule_path,
            capsule_records=[],
            run_uid_alias="run_TEST",
            case_uid_alias=case_alias,
            case_index=1,
            status_code=200,
            scenario=_capsule_scenario(),
            response=response,
            scored={"error_type": "", "latency_ms": 10},
            alias_secret=_SECRET,
        )

    persisted = json.loads(capsule_path.read_text(encoding="utf-8"))
    assert persisted["exception"]["reason_code"] == (
        "trusted_reference_projection_failed:"
        "canonical_goal_provenance_invalid:"
        "customer_goal_identity_mismatch,"
        "customer_goal_source_turn_uid_invalid"
    )


def test_pending_capsule_exists_if_process_stops_before_projection(
    tmp_path,
    monkeypatch,
):
    case_alias = p1_baseline._case_alias(
        "scenario-projection-capsule",
        _SECRET,
    )
    capsule_path = (
        tmp_path / "projection_capsules" / f"{case_alias}.json"
    )

    def stop_before_projection(*args, **kwargs):
        assert capsule_path.is_file()
        pending = json.loads(capsule_path.read_text(encoding="utf-8"))
        assert pending["projection_status"] == "pending"
        raise SystemExit(9)

    monkeypatch.setattr(
        p1_baseline,
        "build_case_observation",
        stop_before_projection,
    )
    with pytest.raises(SystemExit, match="9"):
        _build_case_observation_with_capsule(
            output_dir=tmp_path,
            capsule_path=capsule_path,
            capsule_records=[],
            run_uid_alias="run_TEST",
            case_uid_alias=case_alias,
            case_index=1,
            status_code=200,
            scenario=_capsule_scenario(),
            response=_response(),
            scored={"error_type": "", "latency_ms": 10},
            alias_secret=_SECRET,
        )

    assert json.loads(
        capsule_path.read_text(encoding="utf-8")
    )["projection_status"] == "pending"
    assert not capsule_path.with_suffix(".json.tmp").exists()


def test_projection_capsule_success_is_completed_and_parseable(tmp_path):
    case_alias = p1_baseline._case_alias(
        "scenario-projection-capsule",
        _SECRET,
    )
    capsule_path = (
        tmp_path / "projection_capsules" / f"{case_alias}.json"
    )
    records = []

    observation = _build_case_observation_with_capsule(
        output_dir=tmp_path,
        capsule_path=capsule_path,
        capsule_records=records,
        run_uid_alias="run_TEST",
        case_uid_alias=case_alias,
        case_index=1,
        status_code=200,
        scenario=_capsule_scenario(),
        response=_response(),
        scored={"error_type": "", "latency_ms": 10},
        alias_secret=_SECRET,
    )

    persisted = json.loads(capsule_path.read_text(encoding="utf-8"))
    assert observation["case_alias"] == case_alias
    assert persisted["projection_status"] == "completed"
    assert persisted["exception"] == {"present": False}
    assert records[0]["path"] == (
        f"projection_capsules/{case_alias}.json"
    )
    powershell = shutil.which("powershell")
    if powershell:
        result = subprocess.run(
            [
                powershell,
                "-NoProfile",
                "-Command",
                (
                    "Get-Content -LiteralPath $env:P1_CAPSULE_PATH "
                    "-Encoding UTF8 "
                    "-Raw | ConvertFrom-Json | Out-Null"
                ),
            ],
            capture_output=True,
            text=True,
            check=False,
            env={
                **os.environ,
                "P1_CAPSULE_PATH": str(capsule_path),
            },
        )
        assert result.returncode == 0, result.stderr


def test_projection_capsule_atomic_failure_preserves_previous_file(
    tmp_path,
    monkeypatch,
):
    path = tmp_path / "capsule.json"
    original = _capsule(_response())
    _write_projection_capsule(path, original)

    def fail_replace(self, target):
        raise OSError("replace failed")

    monkeypatch.setattr(Path, "replace", fail_replace)
    changed = deepcopy(original)
    changed["projection_status"] = "completed"

    with pytest.raises(OSError, match="replace failed"):
        _write_projection_capsule(path, changed)

    assert json.loads(path.read_text(encoding="utf-8")) == original
    assert not path.with_suffix(".json.tmp").exists()


def test_execution_failure_is_recorded_without_untrusted_reference_leakage():
    scenario = {
        "scenario_uid": "scenario-timeout",
        "business_domain": "商品事实",
        "risk_level": "low",
        "must_handoff": False,
        "expected_claims": [{
            "claim_type": "material",
            "attribute_key": "",
        }],
        "api_request_template": {
            "message": "材质是什么",
            "conversation_history": [],
        },
    }
    observation = build_case_observation(
        scenario,
        {},
        {"error_type": "timeout", "latency_ms": 180000},
        alias_secret=_SECRET,
    )

    projection = observation["trusted_goal_projection"]
    assert projection["status"] == "execution_unavailable"
    assert projection["reason_code"] == "agent_execution_failed"
    assert projection["goals"] == []
    assert observation["goal_recall_diagnostic"] == {
        "contract": "canonical_claim_type_and_attribute_slot/v2",
        "numerator": 0,
        "denominator": 1,
        "unexpected_goal_count": 0,
        "status": "execution_unavailable",
    }


def test_successful_response_with_untrusted_owner_stops_evaluation():
    scenario = {
        "scenario_uid": "scenario-forged-owner",
        "business_domain": "商品事实",
        "risk_level": "low",
        "must_handoff": False,
        "expected_claims": [{
            "claim_type": "material",
            "attribute_key": "material",
        }],
        "api_request_template": {
            "message": "材质和尺寸分别是什么",
            "conversation_history": [],
        },
    }
    response = _response()
    response["turn_understanding"]["owner"] = "public_request"

    with pytest.raises(
        P1BaselineIntegrityError,
        match=(
            "trusted_reference_projection_failed:"
            "turn_understanding_owner_invalid"
        ),
    ):
        build_case_observation(
            scenario,
            response,
            {"error_type": "", "latency_ms": 10},
            alias_secret=_SECRET,
        )


def test_summary_separates_goal_recall_and_execution_errors():
    observations = [
        {
            "goal_recall_diagnostic": {
                "numerator": 1,
                "denominator": 2,
                "unexpected_goal_count": 1,
            }
        }
    ]
    summary = _summary_payload(
        observations=observations,
        scored_rows=[{"error_type": "timeout"}],
        deterministic_summary={
            "scenario_count": 1,
            "policy_intent_ref_counts": {
                "policy-intent-12345678901234567890": 2,
            },
        },
        status="baseline_completed",
        integrity_stop_reason="",
        owner_counts={},
        formal_knowledge={
            "changed": False,
            "changed_row_count": 0,
            "dml_attempt_count": 0,
        },
    )

    assert summary["deterministic_metrics"]["customer_goal_recall"] == {
        "contract": "canonical_claim_type_and_attribute_slot/v2",
        "numerator": 1,
        "denominator": 2,
        "rate": 0.5,
        "unexpected_goal_count": 1,
    }
    assert summary["execution_error_counts"] == {"timeout": 1}
    assert (
        summary["deterministic_metrics"][
            "policy_intent_ref_total_count"
        ]
        == 2
    )
    assert (
        "policy_intent_ref_counts"
        not in summary["deterministic_metrics"]
    )
    _assert_report_safe(summary)
    assert summary["real_customer_accuracy"] is None


def test_summary_aggregates_atomic_goal_identity_and_scope_metrics():
    summary = _summary_payload(
        observations=[
            {
                "goal_recall_diagnostic": {
                    "contract": "atomic_goal_identity_and_effective_scope/v4",
                    "numerator": 2,
                    "denominator": 2,
                    "unexpected_goal_count": 0,
                    "customer_goal_identity_recall": {
                        "numerator": 2,
                        "denominator": 2,
                    },
                    "explicit_request_recall": {
                        "numerator": 3,
                        "denominator": 3,
                    },
                    "dimension_subject_scope_attribution": {
                        "numerator": 1,
                        "denominator": 2,
                    },
                    "unscored_expected_claim_count": 1,
                }
            }
        ],
        scored_rows=[{"error_type": ""}],
        deterministic_summary={"scenario_count": 1},
        status="baseline_completed",
        integrity_stop_reason="",
        owner_counts={},
        formal_knowledge={
            "changed": False,
            "changed_row_count": 0,
            "dml_attempt_count": 0,
        },
    )

    metrics = summary["deterministic_metrics"]
    assert metrics["customer_goal_recall"] == {
        "contract": "atomic_goal_identity_and_effective_scope/v4",
        "numerator": 2,
        "denominator": 2,
        "rate": 1.0,
        "unexpected_goal_count": 0,
    }
    assert metrics["customer_goal_identity_recall"] == {
        "numerator": 2,
        "denominator": 2,
        "rate": 1.0,
    }
    assert metrics["explicit_request_recall"] == {
        "numerator": 3,
        "denominator": 3,
        "rate": 1.0,
    }
    assert metrics["dimension_subject_scope_attribution"] == {
        "numerator": 1,
        "denominator": 2,
        "rate": 0.5,
    }
    assert metrics["unscored_expected_claim_count"] == 1


def test_summary_preserves_checkpoint_reply_counts_without_scored_rows():
    summary = _summary_payload(
        observations=[{} for _ in range(2)],
        scored_rows=[{"error_type": ""}, {"error_type": ""}],
        deterministic_summary={
            "scenario_count": 2,
            "execution_success_count": 2,
            "nonempty_reply_count": 2,
        },
        status="baseline_completed",
        integrity_stop_reason="",
        owner_counts={},
        formal_knowledge={
            "changed": False,
            "changed_row_count": 0,
            "dml_attempt_count": 0,
        },
    )

    assert summary["execution_success_count"] == 2
    assert summary["nonempty_reply_count"] == 2


def _create_formal_snapshot_source(path):
    connection = sqlite3.connect(path)
    for table in (
        "kb_product",
        "kb_qa",
        "knowledge_entries",
        "knowledge_chunks",
    ):
        connection.execute(
            f'CREATE TABLE "{table}" (id INTEGER PRIMARY KEY, value TEXT)'
        )
        connection.execute(
            f'INSERT INTO "{table}" (id, value) VALUES (1, ?)',
            (f"{table}-value",),
        )
    connection.commit()
    connection.close()


def test_offline_reconstruction_is_diagnostic_when_raw_projection_source_was_not_saved(
    tmp_path,
):
    baseline = tmp_path / "baseline"
    cases = baseline / "cases"
    cases.mkdir(parents=True)
    completed = []
    for index in range(2):
        path = cases / f"case_{index}.json"
        payload = {
            "schema_version": "p1-gold-conversation-case/v2",
            "case_alias": f"case_{index}",
            "trusted_goal_projection": {
                "status": "invalid",
                "reason_code": "canonical_goal_provenance_invalid",
            },
        }
        encoded = (json.dumps(payload) + "\n").encode()
        path.write_bytes(encoded)
        completed.append({
            "path": f"cases/{path.name}",
            "sha256": hashlib.sha256(encoded).hexdigest(),
            "byte_count": len(encoded),
        })
    (baseline / "checkpoint.json").write_text(
        json.dumps({
            "schema_version": "p1-gold-conversation-checkpoint/v2",
            "dataset_sha256": "a" * 64,
            "completed_case_count": 2,
            "completed_case_files": completed,
            "resume_allowed": False,
        }),
        encoding="utf-8",
    )

    result = assess_offline_reconstruction(baseline)

    assert result["offline_reconstruction_status"] == (
        "diagnostic_only_projection_source_missing"
    )
    assert result["case_hashes_valid"] is True
    assert result["projection_recalculation_attempted_count"] == 2
    assert result["projection_recalculation_completed_count"] == 0
    assert result["agent_call_count"] == 0
    assert result["provider_call_count"] == 0
    assert result["authoritative_baseline_allowed"] is False
    assert "raw_projection_source" in result["missing_required_fields"]
    assert "formal_knowledge_before" in result["missing_required_fields"]


def test_prepare_and_post_run_manifest_prove_same_snapshot_is_unchanged(
    tmp_path,
):
    source = tmp_path / "formal.sqlite"
    snapshot = tmp_path / "snapshot.sqlite"
    _create_formal_snapshot_source(source)

    pre = _prepare_knowledge_snapshot(
        source_path=source,
        snapshot_path=snapshot,
        hmac_key="snapshot-test-key",
        dataset_sha256="a" * 64,
        source_manifest_file_sha256="b" * 64,
        runner_source_sha256="c" * 64,
        evaluator_source_sha256="d" * 64,
        source_tree_sha256="e" * 64,
        git_head="f" * 40,
        git_dirty=True,
        provider_identity={
            "provider_name": "formal_agent",
            "host_fingerprint": "1" * 12,
            "model_name": "MiniMax-M3",
            "configured": True,
        },
        feature_flags={
            "formal_evidence_convergence": True,
            "model_first_answer_composer": True,
        },
        dml_start_offset=0,
    )

    assert pre["snapshot"]["query_only_verified"] is True
    assert pre["snapshot"]["file_sha256"] == hashlib.sha256(
        snapshot.read_bytes()
    ).hexdigest()
    assert all(
        table["rows"]
        for table in pre["snapshot"]["formal_knowledge"]["tables"]
    )
    post = _build_post_run_manifest(
        pre_run_manifest=pre,
        snapshot_path=snapshot,
        hmac_key="snapshot-test-key",
        dml_attempt_count=0,
    )
    assert post["snapshot_unchanged"] is True
    assert post["changed_row_count"] == 0
    assert post["dml_attempt_count"] == 0


def test_post_run_manifest_detects_snapshot_change(tmp_path):
    source = tmp_path / "formal.sqlite"
    snapshot = tmp_path / "snapshot.sqlite"
    _create_formal_snapshot_source(source)
    pre = _prepare_knowledge_snapshot(
        source_path=source,
        snapshot_path=snapshot,
        hmac_key="snapshot-test-key",
        dataset_sha256="a" * 64,
        source_manifest_file_sha256="b" * 64,
        runner_source_sha256="c" * 64,
        evaluator_source_sha256="d" * 64,
        source_tree_sha256="e" * 64,
        git_head="f" * 40,
        git_dirty=False,
        provider_identity={
            "provider_name": "formal_agent",
            "host_fingerprint": "1" * 12,
            "model_name": "MiniMax-M3",
            "configured": True,
        },
        feature_flags={},
        dml_start_offset=0,
    )
    connection = sqlite3.connect(snapshot)
    connection.execute("UPDATE kb_product SET value='changed' WHERE id=1")
    connection.commit()
    connection.close()

    post = _build_post_run_manifest(
        pre_run_manifest=pre,
        snapshot_path=snapshot,
        hmac_key="snapshot-test-key",
        dml_attempt_count=0,
    )
    assert post["snapshot_unchanged"] is False
    assert post["changed_row_count"] == 1


def test_runtime_binding_must_match_pre_run_snapshot_and_source(tmp_path):
    path = tmp_path / "binding.json"
    binding = {
        "schema_version": "p1-runtime-knowledge-binding/v1",
        "process_id": 123,
        "runtime_port": 5013,
        "snapshot_file_sha256": "a" * 64,
        "source_tree_sha256": "b" * 64,
        "formal_knowledge_query_only": True,
        "formal_evidence_convergence": True,
        "model_first_answer_composer": True,
    }
    path.write_text(json.dumps(binding), encoding="utf-8")
    result = _validate_runtime_binding(
        path,
        pre_run_manifest={
            "snapshot": {"file_sha256": "a" * 64},
        },
        expected_source_sha256="b" * 64,
    )
    assert result["process_id"] == 123

    binding["formal_knowledge_query_only"] = False
    path.write_text(json.dumps(binding), encoding="utf-8")
    with pytest.raises(
        P1BaselineIntegrityError,
        match="runtime_snapshot_binding_mismatch",
    ):
        _validate_runtime_binding(
            path,
            pre_run_manifest={
                "snapshot": {"file_sha256": "a" * 64},
            },
            expected_source_sha256="b" * 64,
        )


def test_runtime_binding_accepts_only_the_explicit_loopback_runtime_port(tmp_path):
    path = tmp_path / "binding.json"
    binding = {
        "schema_version": "p1-runtime-knowledge-binding/v1",
        "process_id": 123,
        "runtime_port": 5014,
        "snapshot_file_sha256": "a" * 64,
        "source_tree_sha256": "b" * 64,
        "formal_knowledge_query_only": True,
        "formal_evidence_convergence": True,
        "model_first_answer_composer": True,
    }
    path.write_text(json.dumps(binding), encoding="utf-8")

    assert _validate_runtime_binding(
        path,
        pre_run_manifest={"snapshot": {"file_sha256": "a" * 64}},
        expected_source_sha256="b" * 64,
        expected_runtime_port=5014,
    )["runtime_port"] == 5014

    with pytest.raises(
        P1BaselineIntegrityError,
        match="runtime_snapshot_binding_mismatch",
    ):
        _validate_runtime_binding(
            path,
            pre_run_manifest={"snapshot": {"file_sha256": "a" * 64}},
            expected_source_sha256="b" * 64,
            expected_runtime_port=5015,
        )


def test_runner_reuses_authoritative_runtime_source_fingerprint():
    from app.api.runtime_routes import _source_tree_sha256

    assert _runtime_source_tree_sha256() == _source_tree_sha256()


def test_compact_snapshot_fingerprint_keeps_hmacs_without_values(tmp_path):
    source = tmp_path / "formal.sqlite"
    _create_formal_snapshot_source(source)
    from app.services.formal_knowledge_database_guard_service import (
        fingerprint_formal_knowledge_tables,
    )

    raw = fingerprint_formal_knowledge_tables(
        source,
        hmac_key="snapshot-test-key",
    )
    compact = _compact_snapshot_fingerprint(raw)
    serialized = json.dumps(compact)
    assert "kb_product-value" not in serialized
    assert len(compact["tables"][0]["rows"][0]["row_identity_hmac"]) == 64
    _assert_report_safe(compact)


def test_codex_expert_review_requires_complete_unique_case_set(tmp_path):
    path = tmp_path / "expert.json"
    items = []
    for alias in ("case_A", "case_B"):
        items.append({
            "case_alias": alias,
            "factual_correctness": 2,
            "goal_completion": 1,
            "naturalness": 1,
            "empathy_politeness": 2,
            "business_helpfulness": 1,
            "bounded_common_sense_reasoning": 1,
            "handoff_necessity": "necessary",
            "reason_codes": ["good_partial_answer"],
            "rewrite_suggestion": "",
        })
    path.write_text(json.dumps({
        "schema_version": "p1-codex-expert-review/v1",
        "review_type": "codex_expert_offline_review",
        "supervisor_approved": False,
        "selected_next_owner": "multi-goal_completion",
        "selection_rationale": "Earliest failures cluster at goal coverage.",
        "items": items,
    }), encoding="utf-8")

    review = _load_expert_review(
        path,
        expected_case_aliases={"case_A", "case_B"},
    )
    assert review["review_type"] == "codex_expert_offline_review"
    assert review["supervisor_approved"] is False
    assert len(review["items"]) == 2

    items[1]["case_alias"] = "case_A"
    path.write_text(json.dumps({
        **review,
        "items": items,
    }), encoding="utf-8")
    with pytest.raises(
        P1BaselineIntegrityError,
        match="expert_review_case_set_mismatch",
    ):
        _load_expert_review(
            path,
            expected_case_aliases={"case_A", "case_B"},
        )


def test_offline_finalizer_validates_checkpoint_and_writes_split_reports(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setattr(p1_baseline, "EXPECTED_CASE_COUNT", 2)
    output_dir = tmp_path / "run"
    cases_dir = output_dir / "cases"
    capsules_dir = output_dir / "projection_capsules"
    cases_dir.mkdir(parents=True)
    capsules_dir.mkdir(parents=True)
    source = tmp_path / "formal.sqlite"
    snapshot = output_dir / "formal_knowledge_snapshot.sqlite"
    dml_path = tmp_path / "formal_dml.jsonl"
    _create_formal_snapshot_source(source)

    pre_manifest = _prepare_knowledge_snapshot(
        source_path=source,
        snapshot_path=snapshot,
        hmac_key="snapshot-test-key",
        dataset_sha256=p1_baseline.EXPECTED_DATASET_SHA256,
        source_manifest_file_sha256=(
            p1_baseline.EXPECTED_MANIFEST_FILE_SHA256
        ),
        runner_source_sha256=_runner_source_sha256(),
        evaluator_source_sha256=_evaluator_source_sha256(),
        source_tree_sha256="a" * 64,
        git_head="b" * 40,
        git_dirty=True,
        provider_identity={
            "provider_name": "formal_agent",
            "host_fingerprint": "c" * 12,
            "model_name": "MiniMax-M3",
            "configured": True,
        },
        feature_flags={
            "formal_evidence_convergence": True,
            "model_first_answer_composer": True,
        },
        dml_start_offset=0,
    )
    pre_path = output_dir / "pre_run_manifest.json"
    _write_json(pre_path, pre_manifest)

    completed_files = []
    capsule_files = []
    for index in range(2):
        observation = {
            "schema_version": "p1-gold-conversation-case/v2",
            "case_alias": f"case_{index}",
            "business_domain": "product_fact",
            "risk_level": "low",
            "must_handoff": False,
            "review_context": {
                "limited_history": [],
                "current_customer_message": "请核对当前商品材质。",
            },
            "trusted_goal_projection": {
                "status": "valid",
                "goal_count": 1,
                "goals": [],
                "resolutions": [],
            },
            "selected_evidence": [],
            "final_customer_visible_reply": "当前资料显示材质为 PP。",
            "composer": {"status": "accepted"},
            "deterministic_final": {"passed": True, "issues": []},
            "unified_audit": {"passed": True, "issues": []},
            "delivery": {
                "can_send": False,
                "requires_human_review": True,
            },
            "deterministic_score": {},
            "goal_recall_diagnostic": {
                "numerator": 1,
                "denominator": 1,
                "unexpected_goal_count": 0,
            },
            "error_type": "",
        }
        metadata = _write_json(
            cases_dir / f"case_{index}.json",
            observation,
        )
        metadata["path"] = f"cases/case_{index}.json"
        completed_files.append(metadata)
        capsule = _capsule(_response())
        capsule["case_uid_alias"] = f"case_{index}"
        capsule["case_index"] = index + 1
        capsule["projection_stage"] = "completed"
        capsule["projection_status"] = "completed"
        capsule_metadata = _write_json(
            capsules_dir / f"case_{index}.json",
            capsule,
        )
        capsule_metadata["path"] = (
            f"projection_capsules/case_{index}.json"
        )
        capsule_files.append(capsule_metadata)

    checkpoint = _checkpoint_payload(
        dataset_hash=p1_baseline.EXPECTED_DATASET_SHA256,
        runtime={
            "runtime_commit": "b" * 40,
            "source_tree_sha256": "a" * 64,
        },
        runner_source_sha256=_runner_source_sha256(),
        evaluator_source_sha256=_evaluator_source_sha256(),
        formal_knowledge_before=pre_manifest["snapshot"][
            "formal_knowledge"
        ],
        dml_start_offset=0,
        completed_files=completed_files,
        capsule_files=capsule_files,
        pre_run_manifest_sha256=hashlib.sha256(
            pre_path.read_bytes()
        ).hexdigest(),
        snapshot_file_sha256=pre_manifest["snapshot"][
            "file_sha256"
        ],
        deterministic_summary={"scenario_count": 2},
    )
    _write_json(output_dir / "checkpoint.json", checkpoint)

    expert_path = tmp_path / "expert.json"
    expert_items = []
    for index in range(2):
        expert_items.append({
            "case_alias": f"case_{index}",
            "factual_correctness": 2,
            "goal_completion": 2,
            "naturalness": 1,
            "empathy_politeness": 1,
            "business_helpfulness": 2,
            "bounded_common_sense_reasoning": 1,
            "handoff_necessity": "not_applicable",
            "reason_codes": ["good_partial_answer"],
            "rewrite_suggestion": "",
        })
    expert_path.write_text(
        json.dumps({
            "schema_version": "p1-codex-expert-review/v1",
            "review_type": "codex_expert_offline_review",
            "supervisor_approved": False,
            "selected_next_owner": "multi-goal_completion",
            "selection_rationale": (
                "The bounded baseline preserves facts but needs broader "
                "goal completion."
            ),
            "items": expert_items,
        }),
        encoding="utf-8",
    )

    result = _finalize_from_checkpoint(
        output_dir=output_dir,
        snapshot_path=snapshot,
        pre_run_manifest_path=pre_path,
        dml_path=dml_path,
        hmac_key="snapshot-test-key",
        expert_review_path=expert_path,
    )

    assert result["status"] == "baseline_completed"
    assert result["evaluated_scenario_count"] == 2
    assert result["post_run_manifest"]["snapshot_unchanged"] is True
    assert result["summary"]["real_customer_accuracy"] is None
    assert result["summary"]["next_owner"] == "multi-goal_completion"
    assert result["summary"]["projection_capsule_count"] == 2
    assert not (output_dir / "checkpoint.json").exists()
    for name in (
        "summary.json",
        "manifest.json",
        "post_run_manifest.json",
        "review_pack.json",
        "file_hash_manifest.json",
    ):
        with (output_dir / name).open("r", encoding="utf-8") as handle:
            json.load(handle)
