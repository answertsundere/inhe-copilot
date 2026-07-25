from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
from pathlib import Path

import pytest
import yaml

from app.repositories.file_policy_repository import FilePolicyRepository
from app.services.admitted_answer_context_service import (
    AdmittedAnswerContextService,
    _requested_claims,
    _structured_sha256,
    build_answer_eligibility_context,
)


MESSAGE = "current customer question"


def _write_pack(path: Path) -> dict:
    pack_path = path / "domain_policy_packs" / "test.yaml"
    pack_path.parent.mkdir(parents=True, exist_ok=True)
    pack_path.write_text(
        yaml.safe_dump(
            {
                "schema_version": "domain-policy-pack/v1",
                "domain_id": "test",
                "version": "1.0.0",
                "claim_policies": {
                    claim_type: {
                        "risk_level": "low",
                        "direct_fact_fast_path_allowed": True,
                        "bounded_inference_policy": "none",
                        "freshness_requirement": "static",
                    }
                    for claim_type in (
                        "material",
                        "material_composition",
                        "dimensions",
                        "gross_weight",
                    )
                },
            },
            allow_unicode=True,
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    return FilePolicyRepository(rules_dir=str(path)).resolve_domain_policy_pack(
        {"catalog_metadata": {"domain_policy_id": "test"}}
    )


def _claim(
    *,
    claim_type: str = "material",
    attribute_key: str = "material",
    message: str = MESSAGE,
) -> dict:
    return {
        "goal_ref": "goal-current",
        "goal_kind": "customer_goal",
        "claim_type": claim_type,
        "attribute_key": attribute_key,
        "source": "current_customer_message",
        "source_span_start": 0,
        "source_span_end": len(message),
        "source_span_sha256": sha256(message.encode("utf-8")).hexdigest(),
        "owner": "turn_understanding_owner",
        "source_stage": "query_fact_type_classifier",
        "question": message,
        "risk_level": "low",
    }


def _understanding(
    *,
    claim_type: str = "material",
    attribute_key: str = "material",
    message: str = MESSAGE,
) -> dict:
    return {
        "schema_version": "turn-understanding/v2",
        "owner": "turn_understanding_owner",
        "source_stage": "query_fact_type_classifier",
        "goal_understanding_status": "valid",
        "goal_understanding_diagnostics": [],
        "requested_claims": [
            _claim(
                claim_type=claim_type,
                attribute_key=attribute_key,
                message=message,
            )
        ],
    }


def _fact(
    uid: str = "fact-1",
    *,
    content: str = "PP",
    claim_type: str = "material",
    attribute_key: str = "material",
    origin: str | None = None,
    identity: str = "SKU-A",
) -> dict:
    return {
        "evidence_uid": uid,
        "origin_evidence_key": origin or f"origin:{uid}",
        "source_type": "product_facts",
        "evidence_role": "product_fact_direct",
        "fact_type": claim_type,
        "attribute_key": attribute_key,
        "content": content,
        "sku_code": identity,
        "fact_review_status": "verified",
        "gate_status": "allowed",
        "direct_answer_allowed": True,
        "material_provenance": "structured_product_record",
    }


def _owner_inputs(pack: dict) -> dict:
    return {
        "domain_policy_pack": pack,
        "conversation_reference_status": {
            "status": "not_required",
            "source_stage": "canonical_context_resolution",
            "reason_codes": [],
        },
        "tool_requirement_status": {
            "status": "not_required",
            "required_tool_refs": [],
            "completed_tool_refs": [],
            "source_stage": "tool_router_and_executor",
            "reason_codes": [],
        },
    }


def _context(
    pack: dict,
    facts: list[dict],
    *,
    understanding: dict | None = None,
    extra_response: dict | None = None,
) -> dict:
    response = {
        "formal_evidence_candidates": facts,
        **(extra_response or {}),
    }
    return AdmittedAnswerContextService().build_for_response(
        response,
        product_identity={"sku_code": "SKU-A"},
        understanding=understanding or _understanding(),
        current_customer_message=MESSAGE,
        answer_eligibility_inputs=_owner_inputs(pack),
    )


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("a" * 20 + "123456789012" + "b" * 32, "a" * 20 + "123456789012" + "b" * 32),
        ("1" * 64, "1" * 64),
        ("A" * 64, "a" * 64),
        ("  " + "a" * 64 + "\n", "a" * 64),
    ],
)
def test_structured_sha256_accepts_only_normalizable_exact_digests(value, expected):
    assert _structured_sha256(value) == expected


@pytest.mark.parametrize(
    "value",
    [
        None,
        123,
        "",
        "a" * 63,
        "a" * 65,
        "0x" + "a" * 64,
        "digest:" + "a" * 64,
        "a" * 32 + " " + "a" * 32,
        "[LONG_ID_REDACTED:123]",
        "g" * 64,
        "a" * 60 + "...",
    ],
)
def test_structured_sha256_rejects_invalid_forms(value):
    assert _structured_sha256(value) == ""


def test_valid_digest_with_long_numeric_run_survives_requested_claim_projection():
    understanding = _understanding()
    digest = "a" * 20 + "123456789012" + "b" * 32
    understanding["requested_claims"][0]["source_span_sha256"] = digest

    projected = _requested_claims(understanding)

    assert projected[0]["source_span_sha256"] == digest


def test_correct_digest_passes_and_other_message_digest_fails_closed(tmp_path):
    pack = _write_pack(tmp_path)
    accepted = _context(pack, [_fact()])
    invalid = _understanding()
    invalid["requested_claims"][0]["source_span_sha256"] = sha256(
        b"other message"
    ).hexdigest()
    rejected = _context(pack, [_fact()], understanding=invalid)

    assert accepted["answer_eligibility_context"][
        "fast_path_preconditions_complete"
    ] is True
    assert rejected["answer_eligibility_context"][
        "fast_path_preconditions_complete"
    ] is False
    assert "canonical_customer_goal_source_span_digest_mismatch" in rejected[
        "answer_eligibility_context"
    ]["fast_path_block_reasons"]


@pytest.mark.parametrize("with_evidence", [True, False])
def test_dependency_presence_blocks_whether_supported_or_unresolved(
    tmp_path,
    with_evidence,
):
    pack = _write_pack(tmp_path)
    understanding = _understanding()
    understanding["requested_claims"].append({
        "goal_kind": "evidence_dependency",
        "claim_type": "material",
        "attribute_key": "material",
        "question": MESSAGE,
        "risk_level": "low",
        "supporting_only": True,
    })

    context = _context(
        pack,
        [_fact()] if with_evidence else [],
        understanding=understanding,
    )

    assert context["answer_eligibility_context"][
        "fast_path_preconditions_complete"
    ] is False
    assert "evidence_dependency_present" in context[
        "answer_eligibility_context"
    ]["fast_path_block_reasons"]


def test_dependency_only_in_claim_resolution_blocks_fast_path(tmp_path):
    pack = _write_pack(tmp_path)
    understanding = _understanding()
    requested = understanding["requested_claims"]
    direct = {
        "evidence_uid": "fact-1",
        "fact_type": "material",
        "attribute_key": "material",
    }
    eligibility = build_answer_eligibility_context(
        understanding=understanding,
        requested_claims=requested,
        current_customer_message=MESSAGE,
        claim_resolutions=[
            {
                "goal_ref": "goal-current",
                "claim_type": "material",
                "attribute_key": "material",
                "status": "supported",
                "supporting_only": False,
                "support_basis": "direct_evidence",
                "evidence_uids": ["fact-1"],
            },
            {
                "goal_ref": "",
                "claim_type": "material",
                "attribute_key": "material",
                "status": "supported",
                "supporting_only": True,
                "support_basis": "direct_evidence",
                "evidence_uids": ["fact-1"],
            },
        ],
        domain_policy_pack=pack,
        conversation_reference_status=_owner_inputs(pack)[
            "conversation_reference_status"
        ],
        tool_requirement_status=_owner_inputs(pack)["tool_requirement_status"],
        admitted_direct_facts=[direct],
        product_identity={"sku_code": "SKU-A"},
        has_actions=False,
        has_media=False,
    )

    assert eligibility["fast_path_preconditions_complete"] is False
    assert "evidence_dependency_present" in eligibility[
        "fast_path_block_reasons"
    ]


def test_exactly_one_goal_aligned_direct_evidence_passes(tmp_path):
    context = _context(_write_pack(tmp_path), [_fact()])

    assert context["answer_eligibility_context"][
        "fast_path_preconditions_complete"
    ] is True
    assert context["claim_resolutions"][0]["evidence_uids"] == ["fact-1"]


@pytest.mark.parametrize(
    "fact_change",
    [
        {"claim_types_supported": ["dimensions"], "fact_type": "dimensions"},
        {"attribute_key": "height"},
        {
            "product_identity_scope": [
                {"namespace": "sku_code", "value": "SKU-B"}
            ]
        },
        {"product_identity_scope": []},
    ],
)
def test_uid_match_cannot_bypass_goal_attribute_or_identity_alignment(
    tmp_path,
    fact_change,
):
    pack = _write_pack(tmp_path)
    understanding = _understanding()
    direct = {
        "evidence_uid": "fact-1",
        "fact_type": "material",
        "attribute_key": "material",
        "claim_types_supported": ["material", "material_composition"],
        "product_identity_scope": [
            {"namespace": "sku_code", "value": "SKU-A"}
        ],
        **fact_change,
    }
    eligibility = build_answer_eligibility_context(
        understanding=understanding,
        requested_claims=understanding["requested_claims"],
        current_customer_message=MESSAGE,
        claim_resolutions=[
            {
                "goal_ref": "goal-current",
                "claim_type": "material",
                "attribute_key": "material",
                "status": "supported",
                "supporting_only": False,
                "support_basis": "direct_evidence",
                "evidence_uids": ["fact-1"],
            }
        ],
        domain_policy_pack=pack,
        conversation_reference_status=_owner_inputs(pack)[
            "conversation_reference_status"
        ],
        tool_requirement_status=_owner_inputs(pack)["tool_requirement_status"],
        admitted_direct_facts=[direct],
        product_identity={"sku_code": "SKU-A"},
        has_actions=False,
        has_media=False,
    )

    assert eligibility["fast_path_preconditions_complete"] is False
    assert "single_direct_evidence_not_verified" in eligibility[
        "fast_path_block_reasons"
    ]


@pytest.mark.parametrize(
    "resolution_change",
    [
        {"claim_type": "dimensions"},
        {"attribute_key": "height"},
    ],
)
def test_resolution_must_match_current_goal_contract(
    tmp_path,
    resolution_change,
):
    pack = _write_pack(tmp_path)
    understanding = _understanding()
    direct = {
        "evidence_uid": "fact-1",
        "fact_type": "material",
        "attribute_key": "material",
        "claim_types_supported": ["material", "material_composition"],
        "product_identity_scope": [
            {"namespace": "sku_code", "value": "SKU-A"}
        ],
    }
    resolution = {
        "goal_ref": "goal-current",
        "claim_type": "material",
        "attribute_key": "material",
        "status": "supported",
        "supporting_only": False,
        "support_basis": "direct_evidence",
        "evidence_uids": ["fact-1"],
        **resolution_change,
    }
    eligibility = build_answer_eligibility_context(
        understanding=understanding,
        requested_claims=understanding["requested_claims"],
        current_customer_message=MESSAGE,
        claim_resolutions=[resolution],
        domain_policy_pack=pack,
        conversation_reference_status=_owner_inputs(pack)[
            "conversation_reference_status"
        ],
        tool_requirement_status=_owner_inputs(pack)["tool_requirement_status"],
        admitted_direct_facts=[direct],
        product_identity={"sku_code": "SKU-A"},
        has_actions=False,
        has_media=False,
    )

    assert eligibility["fast_path_preconditions_complete"] is False
    assert "single_direct_evidence_not_verified" in eligibility[
        "fast_path_block_reasons"
    ]


@pytest.mark.parametrize(
    "second",
    [
        _fact("fact-2", content="PE"),
        _fact("fact-2", content="PP"),
    ],
)
def test_two_independent_direct_evidence_records_block(tmp_path, second):
    context = _context(
        _write_pack(tmp_path),
        [_fact(), deepcopy(second)],
    )

    assert context["answer_eligibility_context"][
        "fast_path_preconditions_complete"
    ] is False
    assert "multiple_direct_evidence_present" in context[
        "answer_eligibility_context"
    ]["fast_path_block_reasons"]


def test_same_origin_transport_duplicate_is_deduplicated_and_passes(tmp_path):
    first = _fact("fact-1", origin="shared-origin")
    second = _fact("fact-2", origin="shared-origin")

    context = _context(_write_pack(tmp_path), [first, second])

    assert context["answer_eligibility_context"][
        "fast_path_preconditions_complete"
    ] is True
    assert len(context["direct_product_facts"]) == 1
    assert "duplicate_evidence" in {
        item["reason"] for item in context["rejected_evidence"]
    }


def test_reference_only_does_not_count_as_second_direct_evidence(tmp_path):
    reference = _fact("reference-1")
    reference["reference_only"] = True

    context = _context(_write_pack(tmp_path), [_fact(), reference])

    assert context["answer_eligibility_context"][
        "fast_path_preconditions_complete"
    ] is True
    assert len(context["direct_product_facts"]) == 1


@pytest.mark.parametrize(
    ("extra_response", "reason"),
    [
        (
            {
                "recommended_assets": [{
                    "evidence_uid": "media-1",
                    "source_type": "media_reference",
                    "evidence_role": "media_reference",
                    "asset_type": "image",
                }]
            },
            "media_candidate_present",
        ),
        (
            {
                "product_context_pack": {
                    "generic_rules": [{
                        "evidence_uid": "action-1",
                        "source_type": "generic_rule",
                        "evidence_role": "service_action",
                        "content": "manual action",
                    }]
                }
            },
            "service_action_present",
        ),
    ],
)
def test_media_and_service_action_keep_existing_fast_path_blocks(
    tmp_path,
    extra_response,
    reason,
):
    context = _context(
        _write_pack(tmp_path),
        [_fact()],
        extra_response=extra_response,
    )

    assert context["answer_eligibility_context"][
        "fast_path_preconditions_complete"
    ] is False
    assert reason in context["answer_eligibility_context"][
        "fast_path_block_reasons"
    ]


def test_other_attribute_evidence_does_not_count_for_current_goal(tmp_path):
    understanding = _understanding(
        claim_type="gross_weight",
        attribute_key="gross_weight",
    )
    context = _context(
        _write_pack(tmp_path),
        [_fact(claim_type="dimensions", attribute_key="height", content="80cm")],
        understanding=understanding,
    )

    assert "single_direct_evidence_not_verified" in context[
        "answer_eligibility_context"
    ]["fast_path_block_reasons"]


def test_identity_mismatch_does_not_count_for_current_goal(tmp_path):
    context = _context(
        _write_pack(tmp_path),
        [_fact(identity="SKU-B")],
    )

    assert "single_direct_evidence_not_verified" in context[
        "answer_eligibility_context"
    ]["fast_path_block_reasons"]
