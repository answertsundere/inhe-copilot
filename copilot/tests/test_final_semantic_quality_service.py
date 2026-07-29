import json

import pytest

from app.services.final_semantic_quality_service import (
    _canonicalize_finding_codes,
    apply_semantic_fit_result,
    audit_customer_reply_semantic_fit,
    finding_ownership_matrix,
)


class _FakeMessage:
    def __init__(self, content):
        self.content = content


class _FakeChoice:
    def __init__(self, content, *, finish_reason="stop"):
        self.message = _FakeMessage(content)
        self.finish_reason = finish_reason


class _FakeResponse:
    def __init__(self, content, *, finish_reason="stop"):
        self.choices = [_FakeChoice(content, finish_reason=finish_reason)]


class _CountingClient:
    api_key = "test"
    model = "fake"

    def __init__(self, *, content=None, error=None, finish_reason="stop"):
        self.content = content
        self.error = error
        self.finish_reason = finish_reason
        self.call_count = 0
        self.last_kwargs = None

    def create_chat_completion(self, **kwargs):
        self.call_count += 1
        self.last_kwargs = kwargs
        if self.error is not None:
            raise self.error
        return _FakeResponse(
            self.content,
            finish_reason=self.finish_reason,
        )


class _FakeCompletions:
    def __init__(self, content):
        self.content = content

    def create(self, **kwargs):
        return _FakeResponse(self.content)


class _FakeChat:
    def __init__(self, content):
        self.completions = _FakeCompletions(content)


class _FakeClient:
    api_key = "test-key"
    model = "test-model"

    def __init__(self, content):
        self.client = type("Client", (), {"chat": _FakeChat(content)})()

    def create_chat_completion(self, **kwargs):
        return self.client.chat.completions.create(**kwargs)


def _model_first_atomic_response(*, inference: bool = False):
    second_status = "supported" if inference else "unresolved"
    second_basis = "bounded_inference" if inference else "none"
    second_kind = "allowed_inference" if inference else "unresolved"
    second_evidence = ["material-direct"] if inference else []
    return {
        "suggested_reply": (
            "这款主体材质为ABS塑料加硅胶。\n"
            + (
                "日常轻微滑落一般不用过度担心，但高处或反复跌落不能保证。"
                if inference
                else "目前无法确认能否保证摔不坏。"
            )
        ),
        "requires_human_review": True,
        "can_send": False,
        "model_first_answer_composer": {
            "status": "accepted",
            "clauses": [
                {
                    "clause_ref": "C1",
                    "goal_ref": "goal-material",
                    "clause_kind": "supported_fact",
                    "text": "这款主体材质为ABS塑料加硅胶。",
                    "evidence_uids": ["material-direct"],
                },
                {
                    "clause_ref": "C2",
                    "goal_ref": "goal-durability",
                    "clause_kind": second_kind,
                    "text": (
                        "日常轻微滑落一般不用过度担心，但高处或反复跌落不能保证。"
                        if inference
                        else "目前无法确认能否保证摔不坏。"
                    ),
                    "evidence_uids": second_evidence,
                    "inference_policy_refs": (
                        ["domain-policy:household@v1:minor-drop-guidance"]
                        if inference
                        else []
                    ),
                    "scope_qualifier": (
                        "ordinary_minor_accidental_drop"
                        if inference
                        else ""
                    ),
                    "inference_risk_level": "medium" if inference else "",
                    "maximum_risk_level": "medium" if inference else "",
                    "inference_review_only": inference,
                    "required_qualifiers": (
                        ["no_absolute_guarantee"] if inference else []
                    ),
                    "prohibited_extensions": (
                        ["child_safety"] if inference else []
                    ),
                },
            ],
        },
        "minimal_decision_context": {
            "product_identity": {"resolved": True},
            "admitted_evidence": [{
                "evidence_uid": "material-direct",
                "fact_type": "material",
                "content": "主体材质为ABS塑料加硅胶。",
            }],
            "claim_resolutions": [
                {
                    "claim_uid": "goal-material",
                    "goal_kind": "customer_goal",
                    "claim_type": "material",
                    "status": "supported",
                    "support_basis": "direct_evidence",
                    "evidence_uids": ["material-direct"],
                },
                {
                    "claim_uid": "goal-durability",
                    "goal_kind": "customer_goal",
                    "claim_type": "durability",
                    "status": second_status,
                    "support_basis": second_basis,
                    "evidence_uids": second_evidence,
                    "inference_policy_refs": (
                        ["domain-policy:household@v1:minor-drop-guidance"]
                        if inference
                        else []
                    ),
                    "scope_qualifier": (
                        "ordinary_minor_accidental_drop"
                        if inference
                        else ""
                    ),
                    "inference_risk_level": "medium" if inference else "",
                    "maximum_risk_level": "medium" if inference else "",
                    "inference_review_only": inference,
                    "required_qualifiers": (
                        ["no_absolute_guarantee"] if inference else []
                    ),
                    "prohibited_extensions": (
                        ["child_safety"] if inference else []
                    ),
                },
            ],
            "bounded_inference_policies": (
                [{
                    "policy_ref": (
                        "domain-policy:household@v1:minor-drop-guidance"
                    ),
                    "maximum_risk_level": "medium",
                }]
                if inference
                else []
            ),
        },
        "evidence_debug": {
            "query_fact_type": "material",
            "admitted_answer_context": {
                "direct_product_facts": [{
                    "evidence_uid": "material-direct",
                    "source_type": "product_facts",
                    "evidence_role": "product_fact_direct",
                    "claim_types_supported": ["material"],
                    "text": "主体材质为ABS塑料加硅胶。",
                }],
                "direct_policy_facts": [],
                "unresolved_claims": (
                    []
                    if inference
                    else [{
                        "claim_uid": "goal-durability",
                        "claim_type": "durability",
                        "status": "unresolved",
                    }]
                ),
            },
        },
    }


def _atomic_judge_payload(*, inference: bool = False):
    from app.services.final_semantic_quality_service import (
        _atomic_semantic_contract,
    )

    contract = _atomic_semantic_contract(
        _model_first_atomic_response(inference=inference)
    )
    return {
        "schema_version": "unified-textual-audit-v1",
        "goal_reviews": [
            {
                "goal_ref": item["goal_ref"],
                "clause_ref": item["clause_ref"],
                "clause_kind": item["clause_kind"],
                "textual_status": "accepted",
                "finding_codes": [],
            }
            for item in contract
        ],
        "global_finding_codes": [],
    }


def _mutated_atomic_payload(mutation):
    payload = _atomic_judge_payload()
    checks = payload["goal_reviews"]
    first = checks[0]
    if mutation == "top_level_extra":
        payload["extra"] = True
    elif mutation == "top_level_missing":
        payload.pop("global_finding_codes")
    elif mutation == "schema_version":
        payload["schema_version"] = "unknown"
    elif mutation == "goal_reviews_type":
        payload["goal_reviews"] = {}
    elif mutation == "global_finding_codes_type":
        payload["global_finding_codes"] = {}
    elif mutation == "global_issue_duplicate":
        payload["global_finding_codes"] = ["semantic_mismatch", "semantic_mismatch"]
    elif mutation == "global_issue_invalid":
        payload["global_finding_codes"] = ["unknown_issue"]
    elif mutation == "segment_type":
        checks[0] = "invalid"
    elif mutation == "segment_extra_field":
        first["extra"] = True
    elif mutation == "segment_missing_field":
        first.pop("textual_status")
    elif mutation == "duplicate_reference":
        checks[1] = dict(first)
    elif mutation == "unknown_goal":
        first["goal_ref"] = "unknown-goal"
    elif mutation == "unknown_clause":
        first["clause_ref"] = "unknown-clause"
    elif mutation == "clause_kind":
        first["clause_kind"] = "unknown"
    elif mutation == "textual_status":
        first["textual_status"] = True
    elif mutation == "issue_codes_type":
        first["finding_codes"] = {}
    elif mutation == "issue_code_duplicate":
        first.update({
            "textual_status": "rejected",
            "finding_codes": ["unsupported_claim", "unsupported_claim"],
        })
    elif mutation == "issue_code_invalid":
        first["finding_codes"] = ["unknown_issue"]
    elif mutation == "status_finding_mismatch":
        first.update({
            "textual_status": "rejected",
            "finding_codes": [],
        })
    elif mutation == "missing_segment":
        checks.pop()
    elif mutation == "duplicate_segment":
        checks.append(dict(first))
    elif mutation == "array_root":
        return []
    else:
        raise AssertionError(f"Unknown mutation: {mutation}")
    return payload


def test_final_semantic_fit_uses_llm_judge_to_block_wrong_answer(monkeypatch):
    from app import config
    from app.llm import client as llm_client

    monkeypatch.setattr(config, "COPILOT_FINAL_AUDIT_LLM_ENABLED", True)
    monkeypatch.setattr(
        llm_client,
        "get_llm_client",
        lambda: _FakeClient(
            '{"passed": false, "issues": ["answered_space_fit_as_load_capacity"], "reason": "Customer asks fit/space but reply answers load capacity."}'
        ),
    )
    response = {
        "suggested_reply": "亲～这款单层均匀承重约15-30kg，放书和玩具都够用。",
        "requires_human_review": False,
        "evidence_debug": {
            "semantic_query": {"primary_fact_type": "space_fit"},
            "product_context_pack_summary": {
                "evidence_pack": {
                    "answerability": "direct_answer",
                    "query_fact_type": "space_fit",
                    "matched_facts": [
                        {
                            "fact_type": "space_fit",
                            "preview": "尺寸图可参考预留宽度、进深和高度。",
                "direct_answer_allowed": True,
                "material_provenance": "structured_product_record",
                        }
                    ],
                }
            },
        },
    }

    result = audit_customer_reply_semantic_fit(
        response,
        customer_message="卧室空间比较小，这个放得下吗？",
    )

    assert result["passed"] is False
    assert result["mode"] == "llm_semantic_fit"
    assert "answered_space_fit_as_load_capacity" in result["issues"]


@pytest.mark.parametrize(
    "content",
    [
        "",
        "not-json",
        json.dumps({"passed": True, "issues": []}),
        json.dumps({
            "passed": True,
            "issues": [],
            "reason": "ok",
            "extra": "not allowed",
        }),
        json.dumps({
            "passed": False,
            "issues": ["unknown_issue"],
            "reason": "blocked",
        }),
        json.dumps({
            "passed": True,
            "issues": ["semantic_mismatch"],
            "reason": "contradictory",
        }),
    ],
)
def test_model_first_semantic_fit_fails_closed_on_invalid_schema(
    monkeypatch,
    content,
):
    client = _CountingClient(content=content)
    monkeypatch.setattr("app.llm.client.get_llm_client", lambda: client)

    result = audit_customer_reply_semantic_fit(
        _model_first_atomic_response(),
        customer_message="这款是什么材质，耐摔吗？",
    )

    assert client.call_count == 1
    assert result["passed"] is False
    assert result["issues"] == ["semantic_judge_schema_invalid"]


@pytest.mark.parametrize(
    ("mutation", "expected_category"),
    [
        ("top_level_extra", "top_level_fields_invalid"),
        ("top_level_missing", "top_level_fields_invalid"),
        ("schema_version", "schema_version_invalid"),
        ("goal_reviews_type", "goal_reviews_type_invalid"),
        ("global_finding_codes_type", "global_finding_codes_type_invalid"),
        ("global_issue_invalid", "global_issue_code_invalid"),
        ("segment_type", "segment_type_invalid"),
        ("segment_extra_field", "segment_fields_invalid"),
        ("segment_missing_field", "segment_fields_invalid"),
        ("duplicate_reference", "duplicate_segment_reference"),
        ("unknown_goal", "unknown_segment_reference"),
        ("unknown_clause", "unknown_segment_reference"),
        ("clause_kind", "clause_kind_mismatch"),
        ("textual_status", "textual_status_invalid"),
        ("issue_codes_type", "finding_codes_type_invalid"),
        ("issue_code_invalid", "issue_code_invalid"),
        ("status_finding_mismatch", "textual_status_finding_mismatch"),
        ("missing_segment", "segment_reference_set_incomplete"),
        ("duplicate_segment", "duplicate_segment_reference"),
        ("array_root", "free_text_response"),
    ],
)
def test_atomic_semantic_audit_mutations_fail_closed_with_exact_diagnostics(
    monkeypatch,
    mutation,
    expected_category,
):
    client = _CountingClient(
        content=json.dumps(_mutated_atomic_payload(mutation))
    )
    monkeypatch.setattr("app.llm.client.get_llm_client", lambda: client)

    result = audit_customer_reply_semantic_fit(
        _model_first_atomic_response(),
        customer_message="这款是什么材质，耐摔吗？",
    )

    assert client.call_count == 1
    assert result["passed"] is False
    assert result["issues"] == ["semantic_judge_schema_invalid"]
    assert result["validation_diagnostics"]["category"] == expected_category
    assert result["provider_diagnostics"]["model_call_count"] == 1
    assert result["provider_diagnostics"]["retry_count"] == 0
    assert result["provider_diagnostics"]["repair_count"] == 0


@pytest.mark.parametrize(
    "mutation",
    ["global_issue_duplicate", "issue_code_duplicate"],
)
def test_atomic_semantic_audit_canonicalizes_duplicate_findings(
    monkeypatch,
    mutation,
):
    client = _CountingClient(
        content=json.dumps(_mutated_atomic_payload(mutation))
    )
    monkeypatch.setattr("app.llm.client.get_llm_client", lambda: client)

    result = audit_customer_reply_semantic_fit(
        _model_first_atomic_response(),
        customer_message="这款是什么材质，耐摔吗？",
    )

    assert client.call_count == 1
    assert result["passed"] is False
    assert result["normalization_status"] == "canonicalized"
    if mutation == "issue_code_duplicate":
        finding = result["canonical_goal_findings"][0]
    else:
        finding = result["canonical_global_findings"]
    assert finding["primary_finding_code"] in {
        "semantic_mismatch",
        "unsupported_claim",
    }
    assert finding["raw_finding_codes"] == (
        ["unsupported_claim", "unsupported_claim"]
        if mutation == "issue_code_duplicate"
        else ["semantic_mismatch", "semantic_mismatch"]
    )


def test_finding_ownership_matrix_covers_all_allowed_codes():
    matrix = finding_ownership_matrix()

    codes = [item["raw_finding_code"] for item in matrix]
    assert len(codes) == len(set(codes)) == 21
    assert {
        "factual_fidelity",
        "unresolved_boundary",
        "goal_coverage",
        "conversation_continuity",
        "unsupported_completion",
        "relevance",
        "communication_quality",
    } == {item["canonical_family"] for item in matrix}
    assert all(item["blocking"] is True for item in matrix)
    by_code = {
        item["raw_finding_code"]: item
        for item in matrix
    }
    assert by_code["unsupported_claim"]["canonical_root_code"] == (
        "unsupported_claim"
    )
    assert by_code["unsupported_claim"]["canonical_subtype"] == (
        "generic"
    )
    assert by_code["unsupported_product_claim"][
        "canonical_root_code"
    ] == "unsupported_claim"
    assert by_code["unsupported_product_claim"][
        "canonical_subtype"
    ] == "product_claim"


@pytest.mark.parametrize(
    "raw_codes",
    [
        ["unsupported_claim", "semantic_mismatch"],
        ["semantic_mismatch", "unsupported_claim"],
        [
            "unsupported_claim",
            "semantic_mismatch",
            "unsupported_claim",
        ],
    ],
)
def test_finding_canonicalizer_stabilizes_supported_root_with_secondary(
    raw_codes,
):
    before = list(raw_codes)

    normalized, issue = _canonicalize_finding_codes(raw_codes)

    assert issue == ""
    assert raw_codes == before
    assert normalized["blocking"] is True
    assert normalized["primary_finding_family"] == "factual_fidelity"
    assert normalized["primary_finding_code"] == "unsupported_claim"
    assert normalized["secondary_finding_codes"] == [
        "semantic_mismatch"
    ]
    assert normalized["raw_finding_codes"] == before
    assert normalized["canonical_findings"] == [{
        "finding_family": "factual_fidelity",
        "finding_code": "unsupported_claim",
        "canonical_root_code": "unsupported_claim",
        "raw_finding_codes": ["unsupported_claim"],
        "canonical_subtypes": ["generic"],
        "blocking": True,
        "secondary_finding_codes": ["semantic_mismatch"],
    }]


@pytest.mark.parametrize(
    ("raw_codes", "expected_subtypes"),
    [
        (["unsupported_claim"], ["generic"]),
        (["unsupported_product_claim"], ["product_claim"]),
        (
            [
                "unsupported_claim",
                "unsupported_product_claim",
            ],
            ["generic", "product_claim"],
        ),
        (
            [
                "unsupported_product_claim",
                "unsupported_claim",
                "unsupported_product_claim",
            ],
            ["generic", "product_claim"],
        ),
    ],
)
def test_unsupported_claim_aliases_share_only_the_approved_root(
    raw_codes,
    expected_subtypes,
):
    normalized, issue = _canonicalize_finding_codes(raw_codes)

    assert issue == ""
    assert normalized["blocking"] is True
    assert normalized["primary_finding_family"] == "factual_fidelity"
    assert normalized["primary_finding_code"] == "unsupported_claim"
    assert normalized["primary_canonical_root_code"] == (
        "unsupported_claim"
    )
    assert normalized["primary_canonical_subtypes"] == expected_subtypes
    assert normalized["raw_finding_codes"] == raw_codes
    assert {
        item["raw_finding_code"]
        for item in normalized["raw_finding_details"]
    } == set(raw_codes)
    assert len(normalized["canonical_findings"]) == 1


def test_product_claim_alias_with_semantic_secondary_keeps_root():
    normalized, issue = _canonicalize_finding_codes([
        "semantic_mismatch",
        "unsupported_product_claim",
    ])

    assert issue == ""
    assert normalized["primary_finding_code"] == "unsupported_claim"
    assert normalized["primary_canonical_subtypes"] == ["product_claim"]
    assert normalized["secondary_finding_codes"] == [
        "semantic_mismatch"
    ]


def test_finding_canonicalizer_does_not_invent_unsupported_root():
    normalized, issue = _canonicalize_finding_codes(
        ["semantic_mismatch"]
    )

    assert issue == ""
    assert normalized["primary_finding_family"] == "relevance"
    assert normalized["primary_finding_code"] == "semantic_mismatch"
    assert normalized["secondary_finding_codes"] == []


def test_finding_canonicalizer_preserves_independent_roots():
    normalized, issue = _canonicalize_finding_codes([
        "unsupported_claim",
        "unresolved_claim_asserted",
        "semantic_mismatch",
    ])

    assert issue == ""
    assert {
        item["finding_code"]
        for item in normalized["canonical_findings"]
    } == {"unsupported_claim", "unresolved_claim_asserted"}
    assert normalized["primary_finding_code"] == (
        "unresolved_claim_asserted"
    )


@pytest.mark.parametrize(
    ("raw_codes", "expected_issue"),
    [
        (["unknown_issue"], "finding_code_unknown"),
        (
            [
                "missing_evidence_without_human_review",
                "unnecessary_handoff",
            ],
            "finding_code_conflict",
        ),
    ],
)
def test_finding_canonicalizer_rejects_unknown_or_conflicting_codes(
    raw_codes,
    expected_issue,
):
    normalized, issue = _canonicalize_finding_codes(raw_codes)

    assert normalized is None
    assert issue == expected_issue


def test_atomic_semantic_audit_keeps_findings_on_separate_goals(
    monkeypatch,
):
    payload = _atomic_judge_payload()
    payload["goal_reviews"][0].update({
        "textual_status": "rejected",
        "finding_codes": ["unsupported_claim"],
    })
    payload["goal_reviews"][1].update({
        "textual_status": "rejected",
        "finding_codes": ["semantic_mismatch"],
    })
    client = _CountingClient(content=json.dumps(payload))
    monkeypatch.setattr("app.llm.client.get_llm_client", lambda: client)

    result = audit_customer_reply_semantic_fit(
        _model_first_atomic_response(),
        customer_message="这款是什么材质，耐摔吗？",
    )

    assert result["passed"] is False
    assert [
        item["primary_finding_code"]
        for item in result["canonical_goal_findings"]
    ] == ["unsupported_claim", "semantic_mismatch"]


def test_unsupported_aliases_on_different_goals_remain_separate(
    monkeypatch,
):
    payload = _atomic_judge_payload()
    payload["goal_reviews"][0].update({
        "textual_status": "rejected",
        "finding_codes": ["unsupported_claim"],
    })
    payload["goal_reviews"][1].update({
        "textual_status": "rejected",
        "finding_codes": ["unsupported_product_claim"],
    })
    client = _CountingClient(content=json.dumps(payload))
    monkeypatch.setattr("app.llm.client.get_llm_client", lambda: client)

    result = audit_customer_reply_semantic_fit(
        _model_first_atomic_response(),
        customer_message="这款是什么材质，耐摔吗？",
    )

    assert result["passed"] is False
    findings = result["canonical_goal_findings"]
    assert len(findings) == 2
    assert [item["goal_ref"] for item in findings] == [
        "goal_01",
        "goal_02",
    ]
    assert [item["primary_finding_code"] for item in findings] == [
        "unsupported_claim",
        "unsupported_claim",
    ]
    assert [item["primary_canonical_subtypes"] for item in findings] == [
        ["generic"],
        ["product_claim"],
    ]


def test_atomic_semantic_audit_prefers_goal_attribution_over_global_duplicate(
    monkeypatch,
):
    payload = _atomic_judge_payload()
    payload["goal_reviews"][0].update({
        "textual_status": "rejected",
        "finding_codes": ["unsupported_claim"],
    })
    payload["global_finding_codes"] = ["unsupported_claim"]
    client = _CountingClient(content=json.dumps(payload))
    monkeypatch.setattr("app.llm.client.get_llm_client", lambda: client)

    result = audit_customer_reply_semantic_fit(
        _model_first_atomic_response(),
        customer_message="这款是什么材质，耐摔吗？",
    )

    assert result["passed"] is False
    assert result["canonical_goal_findings"][0][
        "primary_finding_code"
    ] == "unsupported_claim"
    assert result["canonical_global_findings"]["canonical_findings"] == []
    assert result["canonical_global_findings"][
        "secondary_finding_codes"
    ] == ["unsupported_claim"]
    assert result["canonical_global_findings"][
        "raw_finding_codes"
    ] == ["unsupported_claim"]


def test_finding_canonicalization_is_hash_stable_and_input_immutable():
    first_input = [
        "semantic_mismatch",
        "unsupported_claim",
        "unsupported_claim",
    ]
    second_input = list(reversed(first_input))
    first_before = json.dumps(first_input)
    second_before = json.dumps(second_input)

    first, first_issue = _canonicalize_finding_codes(first_input)
    second, second_issue = _canonicalize_finding_codes(second_input)

    assert first_issue == second_issue == ""
    assert json.dumps(first_input) == first_before
    assert json.dumps(second_input) == second_before
    stable_fields = (
        "blocking",
        "primary_finding_family",
        "primary_finding_code",
        "secondary_finding_codes",
        "canonical_findings",
    )
    first_stable = {
        key: first[key]
        for key in stable_fields
    }
    second_stable = {
        key: second[key]
        for key in stable_fields
    }
    assert first_stable == second_stable
    assert json.dumps(
        first_stable,
        sort_keys=True,
        separators=(",", ":"),
    ) == json.dumps(
        second_stable,
        sort_keys=True,
        separators=(",", ":"),
    )


@pytest.mark.parametrize("fence", ["```json\n{}\n```", "```\n{}\n```"])
def test_atomic_semantic_audit_accepts_one_complete_json_fence(
    monkeypatch,
    fence,
):
    payload = json.dumps(_atomic_judge_payload())
    content = fence.format(payload)
    client = _CountingClient(content=content)
    monkeypatch.setattr("app.llm.client.get_llm_client", lambda: client)

    result = audit_customer_reply_semantic_fit(
        _model_first_atomic_response(),
        customer_message="这款是什么材质，耐摔吗？",
    )

    assert result["passed"] is True
    assert result["provider_diagnostics"]["response_envelope"] == (
        "single_json_fence"
    )
    assert result["provider_diagnostics"]["envelope_unwrap_count"] == 1
    assert result["provider_diagnostics"]["json_repair_count"] == 0


@pytest.mark.parametrize(
    ("content", "expected_category"),
    [
        ("analysis\n" + json.dumps(_atomic_judge_payload()), "free_text_response"),
        (
            "```json\n"
            + json.dumps(_atomic_judge_payload())
            + "\n```\n```json\n{}\n```",
            "json_envelope_invalid",
        ),
        ("```json\n{\"schema_version\":", "json_envelope_invalid"),
    ],
)
def test_atomic_semantic_audit_rejects_unbounded_or_incomplete_envelopes(
    monkeypatch,
    content,
    expected_category,
):
    client = _CountingClient(content=content)
    monkeypatch.setattr("app.llm.client.get_llm_client", lambda: client)

    result = audit_customer_reply_semantic_fit(
        _model_first_atomic_response(),
        customer_message="这款是什么材质，耐摔吗？",
    )

    assert result["passed"] is False
    assert result["issues"] == ["semantic_judge_schema_invalid"]
    assert result["validation_diagnostics"]["category"] == expected_category
    assert result["provider_diagnostics"]["repair_count"] == 0
    assert result["provider_diagnostics"]["retry_count"] == 0


def test_atomic_semantic_prompt_counts_direct_unresolved_declaration_as_answer(
    monkeypatch,
):
    client = _CountingClient(content=json.dumps(_atomic_judge_payload()))
    monkeypatch.setattr("app.llm.client.get_llm_client", lambda: client)

    result = audit_customer_reply_semantic_fit(
        _model_first_atomic_response(),
        customer_message="这款是什么材质，耐摔吗？",
    )

    system_prompt = client.last_kwargs["messages"][0]["content"]
    assert result["passed"] is True
    assert "cannot be confirmed or guaranteed answers" in system_prompt
    assert "without asserting the fact" in system_prompt


@pytest.mark.parametrize("error", [TimeoutError("late"), RuntimeError("provider")])
def test_model_first_semantic_fit_fails_closed_when_judge_unavailable(
    monkeypatch,
    error,
):
    client = _CountingClient(error=error)
    monkeypatch.setattr("app.llm.client.get_llm_client", lambda: client)

    result = audit_customer_reply_semantic_fit(
        _model_first_atomic_response(),
        customer_message="这款是什么材质，耐摔吗？",
    )

    assert client.call_count == 1
    assert result["passed"] is False
    assert result["issues"] == ["semantic_judge_unavailable"]
    assert result["validation_diagnostics"]["category"] == "provider_error"
    assert result["provider_diagnostics"]["provider_latency_ms"] is None


def test_atomic_semantic_audit_accepts_supported_and_unresolved_segments(
    monkeypatch,
):
    client = _CountingClient(content=json.dumps(_atomic_judge_payload()))
    monkeypatch.setattr("app.llm.client.get_llm_client", lambda: client)

    result = audit_customer_reply_semantic_fit(
        _model_first_atomic_response(),
        customer_message="这款是什么材质，耐摔吗？",
    )

    assert client.call_count == 1
    assert result["passed"] is True
    assert result["issues"] == []
    assert result["schema_version"] == "unified-textual-audit-v1"
    assert len(result["goal_reviews"]) == 2
    assert all(
        item["textual_status"] == "accepted"
        for item in result["goal_reviews"]
    )


def test_atomic_semantic_audit_accepts_policy_bounded_inference(monkeypatch):
    client = _CountingClient(
        content=json.dumps(_atomic_judge_payload(inference=True))
    )
    monkeypatch.setattr("app.llm.client.get_llm_client", lambda: client)

    result = audit_customer_reply_semantic_fit(
        _model_first_atomic_response(inference=True),
        customer_message="这款是什么材质，日常不小心滑落容易坏吗？",
    )

    assert client.call_count == 1
    assert result["passed"] is True
    assert result["issues"] == []
    assert any(
        item["clause_kind"] == "allowed_inference"
        for item in result["goal_reviews"]
    )


@pytest.mark.parametrize(
    ("mutate", "expected_issue"),
    [
        (
            lambda payload: payload["goal_reviews"][0].update({
                "textual_status": "rejected",
                "finding_codes": ["unsupported_claim"],
            }),
            "unsupported_claim",
        ),
        (
            lambda payload: payload["goal_reviews"][1].update({
                "textual_status": "rejected",
                "finding_codes": ["unresolved_claim_asserted"],
            }),
            "unresolved_claim_asserted",
        ),
        (
            lambda payload: payload["goal_reviews"][1].update({
                "textual_status": "rejected",
                "finding_codes": ["inference_scope_exceeded"],
            }),
            "inference_scope_exceeded",
        ),
        (
            lambda payload: payload["goal_reviews"][1].update({
                "textual_status": "rejected",
                "finding_codes": ["query_reply_mismatch"],
            }),
            "query_reply_mismatch",
        ),
    ],
)
def test_atomic_semantic_audit_derives_failure_from_atomic_fields(
    monkeypatch,
    mutate,
    expected_issue,
):
    payload = _atomic_judge_payload()
    mutate(payload)
    client = _CountingClient(content=json.dumps(payload))
    monkeypatch.setattr("app.llm.client.get_llm_client", lambda: client)

    result = audit_customer_reply_semantic_fit(
        _model_first_atomic_response(),
        customer_message="这款是什么材质，耐摔吗？",
    )

    assert client.call_count == 1
    assert result["passed"] is False
    assert expected_issue in result["issues"]


@pytest.mark.parametrize(
    "finding_code",
    [
        "historical_agent_fact_used",
        "known_context_re_requested",
        "unsupported_service_action_completion",
        "unsupported_media_claim",
        "omitted_customer_goal",
        "repeated_generic_reply",
        "internal_language_exposure",
    ],
)
def test_atomic_semantic_audit_derives_global_findings_locally(
    monkeypatch,
    finding_code,
):
    payload = _atomic_judge_payload()
    payload["global_finding_codes"] = [finding_code]
    client = _CountingClient(content=json.dumps(payload))
    monkeypatch.setattr("app.llm.client.get_llm_client", lambda: client)

    result = audit_customer_reply_semantic_fit(
        _model_first_atomic_response(),
        customer_message="这款是什么材质，耐摔吗？",
    )

    assert client.call_count == 1
    assert result["passed"] is False
    assert result["issues"] == [finding_code]
    assert result["goal_reviews"] == payload["goal_reviews"]


@pytest.mark.parametrize(
    "mutate",
    [
        lambda payload: payload["goal_reviews"].pop(),
        lambda payload: payload["goal_reviews"].append(
            dict(payload["goal_reviews"][0])
        ),
        lambda payload: payload["goal_reviews"][0].update({
            "goal_ref": "unknown-goal",
        }),
        lambda payload: payload["goal_reviews"][0].update({
            "clause_ref": "unknown-clause",
        }),
        lambda payload: payload["goal_reviews"][0].update({
            "finding_codes": ["unknown_issue"],
        }),
        lambda payload: payload.update({
            "passed": True,
            "reason": "Pass.",
        }),
    ],
)
def test_atomic_semantic_audit_rejects_invalid_references_and_schema(
    monkeypatch,
    mutate,
):
    payload = _atomic_judge_payload()
    mutate(payload)
    client = _CountingClient(content=json.dumps(payload))
    monkeypatch.setattr("app.llm.client.get_llm_client", lambda: client)

    result = audit_customer_reply_semantic_fit(
        _model_first_atomic_response(),
        customer_message="这款是什么材质，耐摔吗？",
    )

    assert client.call_count == 1
    assert result["passed"] is False
    assert result["issues"] == ["semantic_judge_schema_invalid"]


def test_atomic_semantic_audit_is_stable_when_output_order_changes(monkeypatch):
    forward = _atomic_judge_payload()
    reverse = _atomic_judge_payload()
    reverse["goal_reviews"].reverse()
    clients = iter([
        _CountingClient(content=json.dumps(forward)),
        _CountingClient(content=json.dumps(reverse)),
    ])
    monkeypatch.setattr(
        "app.llm.client.get_llm_client",
        lambda: next(clients),
    )
    response = _model_first_atomic_response()

    first = audit_customer_reply_semantic_fit(
        response,
        customer_message="这款是什么材质，耐摔吗？",
    )
    second = audit_customer_reply_semantic_fit(
        response,
        customer_message="这款是什么材质，耐摔吗？",
    )

    first_semantic = {
        key: value
        for key, value in first.items()
        if key != "provider_diagnostics"
    }
    second_semantic = {
        key: value
        for key, value in second.items()
        if key != "provider_diagnostics"
    }
    assert first_semantic == second_semantic
    assert (
        first["provider_diagnostics"]["response_sha256"]
        != second["provider_diagnostics"]["response_sha256"]
    )


def test_legacy_semantic_fit_remains_fail_soft_when_judge_unavailable(monkeypatch):
    client = _CountingClient(error=TimeoutError("late"))
    monkeypatch.setattr("app.llm.client.get_llm_client", lambda: client)

    result = audit_customer_reply_semantic_fit(
        {
            "suggested_reply": "这款是ABS材质。",
            "requires_human_review": True,
        },
        customer_message="这款是什么材质？",
    )

    assert client.call_count == 1
    assert result["passed"] is True
    assert result["mode"] == "deterministic"


def test_model_first_semantic_failure_keeps_delivery_fail_closed():
    response = {
        "suggested_reply": "这款是ABS材质，目前无法确认耐摔程度。",
        "sendable_reply": "stale",
        "can_send": True,
        "requires_human_review": False,
        "model_first_answer_composer": {"status": "accepted"},
    }
    result = {
        "checked": True,
        "passed": False,
        "issues": ["semantic_judge_unavailable"],
        "reason": "Semantic judge is unavailable.",
        "mode": "llm_semantic_fit",
    }

    updated = apply_semantic_fit_result(response, result)

    assert updated["can_send"] is False
    assert updated["sendable_reply"] == ""
    assert updated["requires_human_review"] is True


def test_final_semantic_fit_blocks_missing_evidence_without_human_review(monkeypatch):
    from app import config

    monkeypatch.setattr(config, "COPILOT_FINAL_AUDIT_LLM_ENABLED", False)
    response = {
        "suggested_reply": "亲～这款可以拆卸，日常移动很方便。",
        "requires_human_review": False,
        "evidence_debug": {
            "semantic_query": {"primary_fact_type": "detachable"},
            "product_context_pack_summary": {
                "evidence_pack": {
                    "answerability": "missing_product_fact",
                    "query_fact_type": "detachable",
                    "missing_fields": ["detachable"],
                    "matched_facts": [],
                }
            },
        },
    }

    result = audit_customer_reply_semantic_fit(
        response,
        customer_message="这个可以拆卸吗？",
    )

    assert result["passed"] is False
    assert "missing_evidence_without_human_review" in result["issues"]


def test_final_semantic_fit_blocks_gross_weight_answered_with_capacity(monkeypatch):
    from app import config

    monkeypatch.setattr(config, "COPILOT_FINAL_AUDIT_LLM_ENABLED", False)
    response = {
        "suggested_reply": "\u4eb2\uff0c\u8fd9\u6b3e\u5355\u5c42\u627f\u91cd\u7ea620kg\uff0c\u653e\u4e66\u548c\u73a9\u5177\u90fd\u591f\u7528\u3002",
        "requires_human_review": False,
        "evidence_debug": {"query_fact_type": "gross_weight"},
    }

    result = audit_customer_reply_semantic_fit(
        response,
        customer_message="\u8fd9\u4e2a\u591a\u91cd\uff1f",
    )

    assert result["passed"] is False
    assert "gross_weight_answered_with_load_capacity" in result["issues"]


def test_final_semantic_fit_blocks_gross_weight_answered_with_dimensions(monkeypatch):
    from app import config

    monkeypatch.setattr(config, "COPILOT_FINAL_AUDIT_LLM_ENABLED", False)
    response = {
        "suggested_reply": "\u4eb2\uff0c\u8fd9\u6b3e\u5bbd80cm\u3001\u6df140cm\u3001\u9ad890cm\uff0c\u60a8\u53ef\u4ee5\u5148\u91cf\u4e00\u4e0b\u9884\u7559\u4f4d\u7f6e\u3002",
        "requires_human_review": False,
        "evidence_debug": {"query_fact_type": "gross_weight"},
    }

    result = audit_customer_reply_semantic_fit(
        response,
        customer_message="\u5546\u54c1\u6bdb\u91cd\u591a\u5c11\uff1f",
    )

    assert result["passed"] is False
    assert "gross_weight_answered_with_dimensions_or_capacity" in result["issues"]


def test_final_semantic_fit_blocks_accessory_availability_answered_with_installation(monkeypatch):
    from app import config

    monkeypatch.setattr(config, "COPILOT_FINAL_AUDIT_LLM_ENABLED", False)
    response = {
        "suggested_reply": "\u4eb2\uff0c\u8fd9\u4e2a\u914d\u4ef6\u6309\u8bf4\u660e\u4e66\u7684\u5b89\u88c5\u6b65\u9aa4\u5148\u5361\u4e0a\u4fa7\u677f\u5c31\u53ef\u4ee5\u3002",
        "requires_human_review": False,
        "evidence_debug": {"query_fact_type": "accessory_availability"},
    }

    result = audit_customer_reply_semantic_fit(
        response,
        customer_message="\u914d\u4ef6\u80fd\u5355\u72ec\u4e70\u5417\uff1f",
    )

    assert result["passed"] is False
    assert "accessory_availability_answered_with_installation" in result["issues"]


def test_final_semantic_fit_blocks_installation_answered_with_product_facts(monkeypatch):
    from app import config

    monkeypatch.setattr(config, "COPILOT_FINAL_AUDIT_LLM_ENABLED", False)
    response = {
        "suggested_reply": "\u4eb2\uff0c\u8fd9\u6b3e\u5bbd80cm\uff0c\u6750\u8d28\u662fPP\uff0c\u5355\u5c42\u627f\u91cd\u7ea610kg\uff0c\u9002\u5408\u65e5\u5e38\u6536\u7eb3\u3002",
        "requires_human_review": False,
        "evidence_debug": {"query_fact_type": "installation"},
    }

    result = audit_customer_reply_semantic_fit(
        response,
        customer_message="\u6709\u7ec4\u88c5\u89c6\u9891\u5417\uff1f",
    )

    assert result["passed"] is False
    assert "installation_answered_with_unrelated_product_fact" in result["issues"]


def test_final_semantic_fit_does_not_accept_recommended_asset_without_reply_block(monkeypatch):
    from app import config

    monkeypatch.setattr(config, "COPILOT_FINAL_AUDIT_LLM_ENABLED", False)
    response = {
        "suggested_reply": "\u4eb2\uff0c\u4e0b\u9762\u56fe\u7247/\u89c6\u9891\u53ef\u53c2\u8003\uff0c\u6211\u518d\u53d1\u60a8\u5bf9\u5e94\u7684\u5b89\u88c5\u56fe\u6216\u89c6\u9891\u3002",
        "requires_human_review": False,
        "recommended_assets": [{
            "asset_type": "pack_guide_image",
            "asset_url": "https://asset.example/install.png",
            "auto_send_level": "auto",
        }],
        "reply_blocks": [],
        "evidence_debug": {
            "query_fact_type": "installation",
            "product_context_pack_summary": {
                "evidence_pack": {
                    "answerability": "missing_product_fact",
                    "query_fact_type": "installation",
                    "missing_fields": ["installation"],
                    "matched_facts": [],
                }
            },
        },
    }

    result = audit_customer_reply_semantic_fit(
        response,
        customer_message="\u9632\u5012\u5de5\u5177\u600e\u4e48\u7528",
    )

    assert result["passed"] is False
    assert "unsupported_media_claim" in result["issues"]


def test_final_semantic_fit_rejects_combined_media_claim_when_only_image_is_attached(monkeypatch):
    from app import config

    monkeypatch.setattr(config, "COPILOT_FINAL_AUDIT_LLM_ENABLED", False)
    response = {
        "suggested_reply": "亲，下面图片/视频可参考。",
        "requires_human_review": True,
        "reply_blocks": [{
            "type": "image",
            "url": "https://asset.example/guide.png",
            "asset_type": "pack_guide_image",
        }],
        "evidence_debug": {
            "query_fact_type": "installation",
            "answer_mode": "no_evidence_controlled_reply",
            "no_evidence_reply_policy": {"reply_strategy": "verify_installation_asset_before_send"},
        },
        "answer_trace": {
            "query_fact_type": "installation",
            "no_evidence_reply_policy": {"reply_strategy": "verify_installation_asset_before_send"},
        },
    }

    result = audit_customer_reply_semantic_fit(
        response,
        customer_message="有安装资料吗",
    )

    assert result["passed"] is False


def test_final_semantic_fit_allows_installation_handoff_about_materials(monkeypatch):
    from app import config

    monkeypatch.setattr(config, "COPILOT_FINAL_AUDIT_LLM_ENABLED", False)
    response = {
        "suggested_reply": (
            "\u4eb2\uff0c\u6211\u5148\u6309\u5f53\u524d\u8fd9\u6b3e\u5546\u54c1\u7684\u5b89\u88c5\u8d44\u6599\u6838\u5bf9\u3002"
            "\u5982\u679c\u6ca1\u6709\u660e\u786e\u5b89\u88c5\u89c6\u9891\uff0c\u4e0d\u4f1a\u76f4\u63a5\u627f\u8bfa\u89c6\u9891\uff1b"
            "\u60a8\u53ef\u4ee5\u628a\u5361\u4f4f\u7684\u4f4d\u7f6e\u62cd\u7167\u53d1\u6765\uff0c\u6211\u8fd9\u8fb9\u8f6c\u4eba\u5de5\u5e2e\u60a8\u786e\u8ba4\u3002"
        ),
        "requires_human_review": True,
        "evidence_debug": {"query_fact_type": "installation"},
    }

    result = audit_customer_reply_semantic_fit(
        response,
        customer_message="\u6709\u7ec4\u88c5\u89c6\u9891\u5417\uff1f",
    )

    assert result["passed"] is True


def test_final_semantic_fit_accepts_controlled_no_evidence_installation_handoff(monkeypatch):
    from app import config

    monkeypatch.setattr(config, "COPILOT_FINAL_AUDIT_LLM_ENABLED", False)
    response = {
        "suggested_reply": (
            "\u4eb2\uff0c\u5b89\u88c5\u8d44\u6599\u6211\u5e2e\u60a8\u6309\u8fd9\u6b3e\u6838\u5bf9\u4e00\u4e0b\u3002"
            "\u60a8\u5982\u679c\u5361\u5728\u54ea\u4e00\u6b65\uff0c\u4e5f\u53ef\u4ee5\u628a\u5f53\u524d\u4f4d\u7f6e\u62cd\u7ed9\u6211\uff0c\u6211\u4e00\u8d77\u770b\uff1b"
            "\u6211\u786e\u8ba4\u540e\u7ed9\u60a8\u51c6\u786e\u56de\u590d\u3002"
        ),
        "requires_human_review": True,
        "answer_trace": {
            "query_fact_type": "installation",
            "no_evidence_reply_policy": {
                "reply_strategy": "verify_installation_asset_before_send",
                "requires_human_review": True,
            },
        },
        "evidence_debug": {
            "answer_mode": "no_evidence_controlled_reply",
            "query_fact_type": "installation",
        },
    }

    result = audit_customer_reply_semantic_fit(
        response,
        customer_message="\u9632\u5012\u5de5\u5177\u600e\u4e48\u7528\uff1f",
    )

    assert result["passed"] is True
    assert result["reason"] == "Controlled no-evidence handoff reply accepted deterministically."


def test_material_semantic_fallback_does_not_present_keyword_hits_as_product_facts():
    from app.services.final_semantic_quality_service import apply_semantic_fit_result

    response = {
        "suggested_reply": "亲，这款防潮还可以。",
        "display_product_name": "英禾防夹滑门收纳架整理客厅零食桌面儿童玩具卧室可拼搭储物抽屉",
        "requires_human_review": True,
        "evidence_debug": {
            "query_fact_type": "material",
            "filtered_evidence_summary": [
                {
                    "evidence_fact_type": "material",
                    "chunk_preview": "这款产品主要采用冷轧钢管/环保PP/无纺布等材质，金属部分经过防锈喷涂处理，具有一定的防潮能力。",
                }
            ],
        },
    }

    updated = apply_semantic_fit_result(
        response,
        {
            "checked": True,
            "passed": False,
            "issues": ["material_safety_incomplete"],
            "reason": "material safety was not fully answered",
        },
    )

    reply = updated["suggested_reply"]
    assert updated["requires_human_review"] is True
    assert "材质、安全和防潮说明" in reply
    assert "里面有材质和防潮相关说明" not in reply
    assert "转人工" not in reply
    assert "口径" not in reply
    assert "复核" not in reply
    assert "英禾防夹滑门收纳架" not in reply


def test_final_semantic_fit_blocks_structure_function_answered_with_scene(monkeypatch):
    from app import config

    monkeypatch.setattr(config, "COPILOT_FINAL_AUDIT_LLM_ENABLED", False)
    response = {
        "suggested_reply": "亲，这款可以放卧室、客厅，建议旁边留出走动空间。",
        "requires_human_review": False,
        "evidence_debug": {"query_fact_type": "structure_function"},
    }

    result = audit_customer_reply_semantic_fit(
        response,
        customer_message="侧板可以翻下来吗？",
    )

    assert result["passed"] is False
    assert "structure_function_answered_with_scene_or_space" in result["issues"]


def test_final_semantic_fit_blocks_structure_compatibility_answered_with_space(monkeypatch):
    from app import config

    monkeypatch.setattr(config, "COPILOT_FINAL_AUDIT_LLM_ENABLED", False)
    response = {
        "suggested_reply": "亲，这款能不能放下主要看您家预留位置的宽度、进深和高度，旁边也要留走动空间。",
        "requires_human_review": False,
        "evidence_debug": {"query_fact_type": "structure_function"},
    }

    result = audit_customer_reply_semantic_fit(
        response,
        customer_message="三面围栏，想补第四面，这款能用吗",
    )

    assert result["passed"] is False
    assert "structure_function_answered_with_scene_or_space" in result["issues"]


def test_final_semantic_fit_allows_damaged_aftersales_handoff(monkeypatch):
    from app import config

    monkeypatch.setattr(config, "COPILOT_FINAL_AUDIT_LLM_ENABLED", False)
    response = {
        "suggested_reply": "亲，收到。麻烦您拍一下断裂/破损位置、配件整体和外包装，我这边核实后给您处理补发、换件或售后方案。",
        "requires_human_review": True,
        "evidence_debug": {"query_fact_type": "aftersales_policy"},
    }

    result = audit_customer_reply_semantic_fit(
        response,
        customer_message="这个断了",
    )

    assert result["passed"] is True


def test_apply_semantic_fit_result_replaces_bad_reply():
    response = {
        "suggested_reply": "bad answer",
        "display_product_name": "英禾防夹滑门收纳架整理客厅零食桌面儿童玩具卧室可拼搭储物抽屉",
        "requires_human_review": False,
    }
    result = {
        "checked": True,
        "passed": False,
        "issues": ["semantic_mismatch"],
        "reason": "bad",
        "mode": "llm_semantic_fit",
    }

    updated = apply_semantic_fit_result(response, result)

    assert updated["requires_human_review"] is True
    assert updated["generation_mode"] == "final_semantic_fit_fallback"
    assert "bad answer" != updated["suggested_reply"]
    assert updated["final_semantic_fit_audit"]["fallback_used"] is True


def test_final_semantic_fit_allows_direct_evidence_answer(monkeypatch):
    from app import config

    monkeypatch.setattr(config, "COPILOT_FINAL_AUDIT_LLM_ENABLED", False)
    response = {
        "suggested_reply": "亲～这款尺寸可以参考下面的尺寸图，建议对照家里预留位置的宽度、进深和高度。",
        "requires_human_review": False,
        "evidence_debug": {
            "semantic_query": {"primary_fact_type": "space_fit"},
            "product_context_pack_summary": {
                "evidence_pack": {
                    "answerability": "direct_answer",
                    "query_fact_type": "space_fit",
                    "matched_facts": [
                        {
                            "fact_type": "space_fit",
                            "preview": "尺寸图可参考预留宽度、进深和高度。",
                            "direct_answer_allowed": True,
                        }
                    ],
                }
            },
        },
    }

    result = audit_customer_reply_semantic_fit(
        response,
        customer_message="卧室空间比较小，这个放得下吗？",
    )

    assert result["passed"] is True


def test_semantic_payload_contains_only_admitted_direct_facts():
    from app.services.final_semantic_quality_service import _semantic_payload

    response = {
        "suggested_reply": "主体材质为PP。",
        "selected_evidence": [{
            "evidence_uid": "direct",
            "source_type": "product_facts",
            "evidence_role": "product_fact_direct",
            "fact_type": "material",
            "attribute_key": "material",
            "content": "主体材质为PP。",
            "sku_code": "SKU-A",
            "fact_review_status": "verified",
                "gate_status": "allowed",
                "direct_answer_allowed": True,
                "material_provenance": "structured_product_record",
            }],
        "context_used": {
            "product_context_pack": {
                "matched_facts": [{
                    "evidence_uid": "reference",
                    "source_type": "faq",
                    "evidence_role": "faq_direct",
                    "fact_type": "material",
                    "preview": "待核实材质",
                    "reference_only": True,
                    "direct_answer_allowed": False,
                }],
                "generic_rules": [{
                    "evidence_uid": "generic",
                    "source_type": "generic_rule",
                    "evidence_role": "service_action",
                    "content": "转人工核对。",
                }],
            }
        },
        "answer_memory_guidance": {"answer_text": "历史客服说安全。"},
        "grounded_reasoning_draft": {"used_facts": [{"evidence_uid": "shadow"}]},
        "evidence_debug": {"query_fact_type": "material"},
    }

    payload = _semantic_payload(response, "什么材质？", {"sku_code": "SKU-A"})

    assert [item["evidence_uid"] for item in payload["admitted_direct_facts"]] == ["direct"]
    serialized = str(payload)
    assert "reference" not in serialized
    assert "generic" not in serialized
    assert "历史客服说安全" not in serialized
    assert "shadow" not in serialized


def test_semantic_payload_preserves_model_first_review_and_reasoning_contract():
    from app.services.final_semantic_quality_service import _semantic_payload

    response = _model_first_atomic_response(inference=True)
    response["final_answer_audit"] = {
        "passed": True,
        "issues": [],
        "model_call_count": 0,
    }

    payload = _semantic_payload(
        response,
        "这款是什么材质，耐摔吗？",
        {"sku_code": "SKU-A"},
    )

    assert payload["schema_version"] == "unified-textual-audit-input-v1"
    assert payload["deterministic_final_contract"] == {
        "passed": True,
        "issues": [],
        "model_call_count": 0,
    }
    assert len(payload["canonical_truth"]["candidate_clauses"]) == 2
    assert payload["canonical_truth"]["evidence"][0]["evidence_ref"] == "E1"
    serialized = json.dumps(payload, ensure_ascii=False)
    assert "material-direct" not in serialized
    assert "model_first_candidate_contract" not in payload
