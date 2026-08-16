from __future__ import annotations

from copy import deepcopy

import pytest

from app.agent.nodes.evidence_builder import _formal_understanding
from app.agent.nodes.query_fact_type_classifier import (
    _turn_understanding_from_result,
)
from app.services import semantic_fact_type_service as service


def _raw_goal(
    message: str,
    source_text: str,
    *,
    semantic_key: str,
    start: int | None = None,
    claim_type: str = "",
    goal_kind: str = "customer_goal",
) -> dict:
    canonical = bool(claim_type)
    return {
        "goal_kind": goal_kind,
        "claim_type_status": "canonical" if canonical else "unmapped",
        "claim_type": claim_type,
        "attribute_key": "",
        "semantic_key": "" if canonical else semantic_key,
        "policy_intent_ref": "",
        "source_text": source_text,
    }


@pytest.mark.parametrize(
    ("message", "first_text", "second_text", "first_type", "second_key"),
    [
        (
            "material request and durability request",
            "material request",
            "durability request",
            "material",
            "drop_durability",
        ),
        (
            "dimensions request and space fit request",
            "dimensions request",
            "space fit request",
            "dimensions",
            "space_fit_advice",
        ),
    ],
)
def test_distinct_atomic_spans_create_two_authoritative_claims(
    message,
    first_text,
    second_text,
    first_type,
    second_key,
):
    goals, status, diagnostics = service._sanitize_customer_goals(
        [
            _raw_goal(
                message,
                first_text,
                semantic_key="",
                claim_type=first_type,
            ),
            _raw_goal(
                message,
                second_text,
                semantic_key=second_key,
            ),
        ],
        message=message,
    )

    understanding = _turn_understanding_from_result(
        {"customer_message": message},
        {
            "query_fact_type": first_type,
            "risk_hint": "medium",
            "secondary_fact_types": [],
            "customer_goals": goals,
            "goal_understanding_status": status,
            "goal_understanding_diagnostics": diagnostics,
        },
    )

    assert status == "valid"
    assert diagnostics == []
    assert len(goals) == 2
    assert len({goal["goal_ref"] for goal in goals}) == 2
    assert len(understanding["requested_claims"]) == 2


def test_equivalent_unique_sources_in_one_clause_share_canonical_provenance():
    message = "fictional product body material?"
    narrow_source = "body material"

    full_goals, full_status, full_diagnostics = (
        service._sanitize_customer_goals(
            [_raw_goal(
                message,
                message,
                semantic_key="",
                claim_type="material",
            )],
            message=message,
            canonicalize_source_clauses=True,
        )
    )
    narrow_goals, narrow_status, narrow_diagnostics = (
        service._sanitize_customer_goals(
            [_raw_goal(
                message,
                narrow_source,
                semantic_key="",
                claim_type="material",
            )],
            message=message,
            canonicalize_source_clauses=True,
        )
    )

    assert full_status == narrow_status == "valid"
    assert full_diagnostics == narrow_diagnostics == []
    assert full_goals == narrow_goals
    assert full_goals[0]["source_span_start"] == 0
    assert full_goals[0]["source_span_end"] == len(message)
    assert full_goals[0]["goal_summary"] == message


def test_multiple_atomic_sources_in_one_clause_keep_exact_provenance():
    message = "confirm width and height"
    width = "width"
    height = "height"

    goals, status, diagnostics = service._sanitize_customer_goals(
        [
            _raw_goal(
                message,
                width,
                semantic_key="",
                claim_type="dimensions",
            ),
            _raw_goal(
                message,
                height,
                semantic_key="",
                claim_type="dimensions",
            ),
        ],
        message=message,
        canonicalize_source_clauses=True,
    )

    assert status == "valid"
    assert diagnostics == []
    assert {
        (goal["source_span_start"], goal["source_span_end"])
        for goal in goals
    } == {
        (message.index(width), message.index(width) + len(width)),
        (message.index(height), message.index(height) + len(height)),
    }


def test_media_request_stays_separate_from_factual_fallback():
    message = "send the dimension image or state the dimensions"
    goals, status, diagnostics = service._sanitize_customer_goals(
        [
            _raw_goal(
                message,
                "send the dimension image",
                semantic_key="dimension_image_request",
                goal_kind="media_request",
            ),
            _raw_goal(
                message,
                "state the dimensions",
                semantic_key="",
                claim_type="dimensions",
            ),
        ],
        message=message,
    )

    understanding = _turn_understanding_from_result(
        {"customer_message": message},
        {
            "query_fact_type": "dimensions",
            "risk_hint": "medium",
            "secondary_fact_types": [],
            "customer_goals": goals,
            "goal_understanding_status": status,
            "goal_understanding_diagnostics": diagnostics,
        },
    )

    assert status == "valid"
    assert diagnostics == []
    assert [goal["goal_kind"] for goal in goals] == [
        "media_request",
        "customer_goal",
    ]
    assert len(understanding["customer_goals"]) == 2
    assert len(understanding["requested_claims"]) == 1
    assert understanding["requested_claims"][0]["claim_type"] == "dimensions"


def test_media_request_cannot_be_promoted_to_canonical_fact():
    message = "send the dimension image"
    goals, status, diagnostics = service._sanitize_customer_goals(
        [
            _raw_goal(
                message,
                message,
                semantic_key="",
                claim_type="dimensions",
                goal_kind="media_request",
            ),
        ],
        message=message,
    )

    assert status == "degraded"
    assert diagnostics == ["media_request_canonical_claim_forbidden"]
    assert len(goals) == 1
    assert goals[0]["goal_kind"] == "media_request"
    assert goals[0]["claim_type_status"] == "unmapped"
    assert goals[0]["claim_type"] == ""


def test_identical_whole_sentence_provenance_is_rejected():
    message = "material and durability"
    first = _raw_goal(
        message,
        message,
        semantic_key="",
        claim_type="material",
    )
    second = _raw_goal(
        message,
        message,
        semantic_key="drop_durability",
    )

    goals, status, diagnostics = service._sanitize_customer_goals(
        [first, second],
        message=message,
    )

    assert goals == []
    assert status == "invalid"
    assert diagnostics[0] == "duplicate_resolved_provenance"


def test_unique_source_text_uses_server_owned_span():
    message = "材质是PP，尺寸为80cm📦。"
    raw = _raw_goal(
        message,
        "尺寸为80cm📦",
        semantic_key="",
        claim_type="dimensions",
        start=0,
    )
    goals, status, diagnostics = service._sanitize_customer_goals(
        [raw],
        message=message,
    )

    assert status == "valid"
    assert diagnostics == []
    assert len(goals) == 1
    assert goals[0]["source_span_start"] == message.index("尺寸为80cm📦")
    assert goals[0]["source_span_end"] == (
        message.index("尺寸为80cm📦") + len("尺寸为80cm📦")
    )


@pytest.mark.parametrize(
    ("message", "source_text"),
    [
        ("这款是什么材质？", "什么材质"),
        ("规格是：宽80cm，全角标点正常。", "宽80cm"),
        ("能放下📦吗？尺寸是80×40cm。", "尺寸是80×40cm"),
    ],
)
def test_server_resolves_exact_unicode_fragments(message, source_text):
    goals, status, diagnostics = service._sanitize_customer_goals(
        [
            _raw_goal(
                message,
                source_text,
                semantic_key="dimension_or_material_question",
                start=999,
            )
        ],
        message=message,
    )

    assert status == "valid"
    assert diagnostics == []
    assert len(goals) == 1
    assert message[
        goals[0]["source_span_start"]:goals[0]["source_span_end"]
    ] == source_text


def test_source_text_not_found_fails_closed():
    message = "当前只问材质"
    raw = _raw_goal(
        "另一条消息里问尺寸",
        "问尺寸",
        semantic_key="dimensions",
    )

    goals, status, diagnostics = service._sanitize_customer_goals(
        [raw],
        message=message,
    )

    assert goals == []
    assert status == "invalid"
    assert diagnostics == ["source_text_not_found"]


def test_source_text_multiple_matches_fails_closed_without_offset_guessing():
    message = "尺寸和尺寸都要确认"
    raw = _raw_goal(
        message,
        "尺寸",
        semantic_key="",
        claim_type="dimensions",
    )

    goals, status, diagnostics = service._sanitize_customer_goals(
        [raw],
        message=message,
    )

    assert goals == []
    assert status == "invalid"
    assert diagnostics == ["source_text_multiple_matches"]


def test_source_text_from_history_fails_closed():
    current = "当前只问材质"
    historical = "之前还问过安装"
    raw = _raw_goal(
        historical,
        "问过安装",
        semantic_key="",
        claim_type="installation",
    )

    goals, status, diagnostics = service._sanitize_customer_goals(
        [raw],
        message=current,
        history_texts=[historical],
    )

    assert goals == []
    assert status == "invalid"
    assert diagnostics == ["source_text_from_wrong_turn"]


def test_partially_overlapping_exact_spans_are_allowed():
    message = "dimensions and space fit"
    first_text = "dimensions and space"
    second_text = "space fit"

    goals, status, diagnostics = service._sanitize_customer_goals(
        [
            _raw_goal(
                message,
                first_text,
                semantic_key="",
                claim_type="dimensions",
            ),
            _raw_goal(
                message,
                second_text,
                semantic_key="space_fit_advice",
            ),
        ],
        message=message,
    )

    assert status == "valid"
    assert diagnostics == []
    assert len(goals) == 2
    assert {
        (goal["source_span_start"], goal["source_span_end"])
        for goal in goals
    } == {
        (message.index(first_text), message.index(first_text) + len(first_text)),
        (message.index(second_text), message.index(second_text) + len(second_text)),
    }


def test_same_semantic_key_with_different_provenance_stays_independent():
    message = "first request and second request"
    goals, status, diagnostics = service._sanitize_customer_goals(
        [
            _raw_goal(
                message,
                "first request",
                semantic_key="same_diagnostic",
            ),
            _raw_goal(
                message,
                "second request",
                semantic_key="same_diagnostic",
            ),
        ],
        message=message,
    )

    assert status == "valid"
    assert diagnostics == []
    assert len({goal["goal_ref"] for goal in goals}) == 2


def test_provider_owned_span_and_public_identity_injection_fail_closed():
    message = "installation request"
    injected = _raw_goal(
        message,
        message,
        semantic_key="",
        claim_type="installation",
    )
    injected["source_span_start"] = 0
    injected["source_span_end"] = len(message)
    injected["goal_ref"] = "public-goal-ref"
    injected["source_turn_uid"] = "turn-" + ("f" * 20)

    schema, provenance = service._validate_raw_llm_result(
        {
            "goals": [injected],
        },
        message=message,
    )

    assert "source_span_out_of_range" not in {
        item["reason_code"] for item in provenance
    }
    assert {
        item["reason_code"] for item in schema
    } == {"goal_extra_field"}


def test_input_order_does_not_change_goal_identity_set():
    message = "先问材质，再问尺寸"
    raw_goals = [
        _raw_goal(
            message,
            "问材质",
            semantic_key="",
            claim_type="material",
        ),
        _raw_goal(
            message,
            "问尺寸",
            semantic_key="",
            claim_type="dimensions",
        ),
    ]

    forward, forward_status, _ = service._sanitize_customer_goals(
        raw_goals,
        message=message,
    )
    reverse, reverse_status, _ = service._sanitize_customer_goals(
        list(reversed(raw_goals)),
        message=message,
    )

    assert forward_status == reverse_status == "valid"
    assert {goal["goal_ref"] for goal in forward} == {
        goal["goal_ref"] for goal in reverse
    }


def test_server_recomputes_exact_slice_hash_and_rejects_mutation():
    message = "material request"
    goals, status, diagnostics = service._sanitize_customer_goals(
        [
            _raw_goal(
                message,
                message,
                semantic_key="",
                claim_type="material",
            )
        ],
        message=message,
    )
    mutated = deepcopy(goals)
    mutated[0]["source_text_sha256"] = "0" * 64

    valid, reasons = service._validate_canonical_customer_goals(
        mutated,
        message=message,
    )

    assert status == "valid"
    assert diagnostics == []
    assert valid is False
    assert "customer_goal_source_text_digest_invalid" in reasons
    assert "customer_goal_identity_mismatch" in reasons


@pytest.mark.parametrize("status", ["invalid", "degraded"])
def test_non_authoritative_understanding_clears_claims_and_legacy_fallback(
    status,
):
    result = {
        "query_fact_type": "material",
        "risk_hint": "medium",
        "secondary_fact_types": [],
        "customer_goals": [{
            "goal_ref": "goal-diagnostic-only",
            "goal_kind": "customer_goal",
            "claim_type": "material",
        }],
        "goal_understanding_status": status,
        "goal_understanding_diagnostics": [
            "duplicate_goal_provenance",
            "later_reason",
        ],
    }

    understanding = _turn_understanding_from_result(
        {"customer_message": "material request"},
        result,
    )
    formal = _formal_understanding({
        "customer_message": "material request",
        "query_fact_type": "material",
        "turn_understanding": understanding,
    })

    assert understanding["requested_claims"] == []
    assert formal["requested_claims"] == []
    assert formal["goal_understanding_diagnostics"][0] == (
        "duplicate_goal_provenance"
    )


def test_requested_claim_count_mismatch_invalidates_whole_turn():
    duplicated_ref = {
        "goal_ref": "goal-duplicate",
        "goal_kind": "customer_goal",
        "claim_type": "material",
    }

    understanding = _turn_understanding_from_result(
        {"customer_message": "two goals"},
        {
            "query_fact_type": "material",
            "risk_hint": "medium",
            "secondary_fact_types": [],
            "customer_goals": [
                duplicated_ref,
                dict(duplicated_ref),
            ],
            "goal_understanding_status": "valid",
            "goal_understanding_diagnostics": [],
        },
    )

    assert understanding["goal_understanding_status"] == "invalid"
    assert understanding["requested_claims"] == []
    assert understanding["goal_understanding_diagnostics"] == [
        "requested_claim_count_mismatch"
    ]


def test_no_customer_goal_produces_explicit_empty_claims():
    understanding = _turn_understanding_from_result(
        {"customer_message": "service action only"},
        {
            "query_fact_type": "",
            "risk_hint": "medium",
            "secondary_fact_types": [],
            "customer_goals": [{
                "goal_ref": "goal-action",
                "goal_kind": "service_action",
                "claim_type": "",
            }],
            "goal_understanding_status": "valid",
            "goal_understanding_diagnostics": [],
        },
    )

    assert understanding["goal_understanding_status"] == "valid"
    assert understanding["requested_claims"] == []
