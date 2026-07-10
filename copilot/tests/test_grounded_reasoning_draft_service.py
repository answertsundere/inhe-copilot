import pytest

from app.services.grounded_reasoning_draft_service import (
    GroundedReasoningDraftService,
    build_grounded_reasoning_draft,
    has_forbidden_claim_violation,
    has_internal_jargon_draft,
    has_mojibake_draft,
    has_unsupported_media_claim,
    used_answer_memory_as_fact,
)


def _run_post_processor(kwargs, response):
    post_processor = kwargs.get("response_post_processor")
    return post_processor(response) if callable(post_processor) else response


@pytest.fixture()
def client():
    import app.models.kb_tables  # noqa: F401
    from app.db import init_db
    from app.main import create_app

    init_db()
    flask_app = create_app()
    flask_app.config["TESTING"] = True
    return flask_app.test_client()


def _assert_shadow_contract(draft):
    assert draft["shadow_only"] is True
    assert draft["used_for_final_reply"] is False
    assert draft["can_change_can_send"] is False
    assert has_mojibake_draft(draft) is False
    assert has_internal_jargon_draft(draft) is False
    assert used_answer_memory_as_fact(draft) is False


def test_child_safety_uses_structure_boundary_without_age_or_absolute_safety_claim():
    draft = build_grounded_reasoning_draft(
        customer_message="家里有两岁宝宝，这个会不会夹手或者有安全隐患？",
        query_fact_type="pinch_safety",
        selected_evidence=[
            {
                "evidence_role": "product_fact_direct",
                "fact_type": "structure_function",
                "content": "柜门为滑门结构，使用时需要沿轨道推拉。",
                "can_direct_answer": True, "gate_status": "allowed", "review_status": "verified", "sku_code": "SKU-A",
            }
            ],
        product_identity={"sku_code": "SKU-A"},
        answer_memory_guidance={"action_hints": ["先回应宝宝安全关切，再提醒按结构说明核对。"]},
    )

    _assert_shadow_contract(draft)
    assert draft["requires_human_review"] is True
    assert "滑门结构" in draft["grounded_draft"]
    assert "适合2周岁" not in draft["grounded_draft"]
    assert "适合两岁" not in draft["grounded_draft"]
    assert "不会夹手" not in draft["grounded_draft"]
    assert has_forbidden_claim_violation(draft) is False
    assert draft["used_facts"][0]["source"] == "selected_evidence"


def test_material_safety_mentions_material_but_not_non_toxic_or_certificate_claim():
    draft = build_grounded_reasoning_draft(
        customer_message="宝宝咬了一下会不会中毒？",
        query_fact_type="material_safety",
        selected_evidence=[
                {"evidence_role": "product_fact_direct", "fact_type": "material", "content": "主体材质：PP。", "can_direct_answer": True, "gate_status": "allowed", "review_status": "verified", "sku_code": "SKU-A"}
            ],
        product_identity={"sku_code": "SKU-A"},
        answer_memory_guidance={"action_hints": ["误咬场景先让客户检查破损和误吞。"]},
    )

    _assert_shadow_contract(draft)
    assert draft["requires_human_review"] is True
    assert "PP" in draft["grounded_draft"]
    assert "掉屑" in draft["grounded_draft"]
    assert "破损" in draft["grounded_draft"]
    assert "误吞" in draft["grounded_draft"]
    assert "无毒" not in draft["grounded_draft"]
    assert "有证书" not in draft["grounded_draft"]
    assert has_forbidden_claim_violation(draft) is False


def test_installation_screw_guides_photo_without_replacement_or_video_promise():
    draft = build_grounded_reasoning_draft(
        customer_message="螺丝拧紧还掉怎么办？",
        query_fact_type="installation",
        selected_evidence=[
            {"source_type": "installation_guide", "fact_type": "installation", "content": "螺丝需对准孔位后拧紧。"}
        ],
        reply_blocks=[],
    )

    _assert_shadow_contract(draft)
    assert draft["requires_human_review"] is True
    assert "孔位" in draft["grounded_draft"]
    assert "拍一下" in draft["grounded_draft"]
    assert "补发" not in draft["grounded_draft"]
    assert "发视频" not in draft["grounded_draft"]
    assert has_unsupported_media_claim(draft, []) is False


def test_installation_video_only_promised_when_reply_block_has_video():
    draft = build_grounded_reasoning_draft(
        customer_message="有没有安装视频？",
        query_fact_type="installation",
        selected_evidence=[
            {"source_type": "installation_guide", "fact_type": "installation", "content": "安装步骤说明。"}
        ],
        reply_blocks=[{"type": "video", "url": "https://example.test/install.mp4"}],
    )

    _assert_shadow_contract(draft)
    assert "视频可以先参考" in draft["grounded_draft"]
    assert has_unsupported_media_claim(draft, [{"type": "video", "url": "https://example.test/install.mp4"}]) is False


def test_answer_memory_contributes_hints_but_not_used_facts():
    draft = build_grounded_reasoning_draft(
        customer_message="有没有安装教程？",
        query_fact_type="installation",
        selected_evidence=[],
        answer_memory_guidance={
            "action_hints": ["围绕安装步骤和卡住的位置组织回复。"],
            "matched_memories": [{"approved_answer": "历史答案不能当事实"}],
        },
    )

    _assert_shadow_contract(draft)
    assert draft["answer_memory_action_hints"] == ["围绕安装步骤和卡住的位置组织回复。"]
    assert draft["used_facts"] == []
    assert used_answer_memory_as_fact(draft) is False


def test_evidence_admission_rejects_non_factual_or_incompatible_candidates():
    draft = build_grounded_reasoning_draft(
        customer_message="这个多重？",
        query_fact_type="gross_weight",
        product_identity={"sku_code": "SKU-A"},
        selected_evidence=[
            {"evidence_role": "product_fact_direct", "fact_type": "gross_weight", "attribute_key": "gross_weight", "content": "包装毛重 10kg", "can_direct_answer": True, "gate_status": "allowed", "review_status": "verified", "sku_code": "SKU-A"},
            {"source_type": "service_action", "fact_type": "gross_weight", "content": "请人工核对"},
            {"source_type": "media_reference", "fact_type": "gross_weight", "content": "图片资料"},
            {"evidence_role": "product_fact_direct", "fact_type": "dimensions", "content": "宽 80cm", "can_direct_answer": True, "gate_status": "allowed", "review_status": "verified", "sku_code": "SKU-A"},
            {"evidence_role": "product_fact_direct", "fact_type": "gross_weight", "attribute_key": "gross_weight", "content": "包装毛重 12kg", "can_direct_answer": True, "gate_status": "allowed", "review_status": "verified", "sku_code": "SKU-A"},
            {"evidence_role": "product_fact_direct", "fact_type": "gross_weight", "content": "包装毛重 10kg", "can_direct_answer": True, "gate_status": "allowed", "review_status": "verified", "sku_code": "SKU-B"},
        ],
    )

    assert draft["used_facts"] == []
    assert {item["reason"] for item in draft["rejected_evidence"]} >= {
        "ineligible_role_or_gate",
        "fact_type_incompatible",
        "conflicting_evidence",
        "product_identity_mismatch",
    }
    assert draft["requires_human_review"] is True


def test_forbidden_claims_from_shadow_guidance_are_checked_without_changing_reply():
    draft = {"grounded_draft": "这款安全无毒。", "forbidden_claims": ["安全无毒"]}

    assert has_forbidden_claim_violation(draft) is True


@pytest.mark.parametrize(
    "text",
    [
        "不能确认是否无毒。",
        "暂无无毒依据。",
        "无毒这一点无法确认。",
        "这不代表无毒。",
        "目前没有检测报告依据。",
    ],
)
def test_forbidden_claims_allow_negated_or_uncertain_statements(text):
    assert has_forbidden_claim_violation(
        {"grounded_draft": text, "forbidden_claims": ["无毒", "有检测报告"]}
    ) is False


def _direct_fact(*, fact_type, attribute_key, value, content=None, **overrides):
    fact = {
        "evidence_role": "product_fact_direct",
        "fact_type": fact_type,
        "attribute_key": attribute_key,
        "value": value,
        "content": content or str(value),
        "can_direct_answer": True,
        "gate_status": "allowed",
        "review_status": "verified",
        "sku_code": "SKU-A",
    }
    fact.update(overrides)
    return fact


def _grounded_with_facts(facts, *, fact_type="gross_weight", identity=None):
    return build_grounded_reasoning_draft(
        customer_message="请核对这个属性。",
        query_fact_type=fact_type,
        product_identity=identity or {"sku_code": "SKU-A"},
        selected_evidence=list(facts),
    )


@pytest.mark.parametrize("count", [2, 3, 4])
def test_numeric_conflicts_reject_the_entire_group_independent_of_order(count):
    facts = [
        _direct_fact(
            fact_type="gross_weight",
            attribute_key="gross_weight",
            value=f"{10 + index}kg",
            content=f"包装毛重 {10 + index}kg",
        )
        for index in range(count)
    ]

    for ordered in (facts, list(reversed(facts)), [facts[index] for index in range(0, count, 2)] + [facts[index] for index in range(1, count, 2)]):
        draft = _grounded_with_facts(ordered)
        assert draft["used_facts"] == []
        rejected = [item for item in draft["rejected_evidence"] if item["reason"] == "conflicting_evidence"]
        assert len(rejected) == count
        assert {item["original_value"] for item in rejected} == {f"{10 + index}kg" for index in range(count)}


def test_equivalent_mass_values_are_deduplicated_with_provenance():
    facts = [
        _direct_fact(fact_type="gross_weight", attribute_key="gross_weight", value="10kg"),
        _direct_fact(fact_type="gross_weight", attribute_key="gross_weight", value="10.0公斤"),
        _direct_fact(fact_type="gross_weight", attribute_key="gross_weight", value="10000克"),
    ]

    draft = _grounded_with_facts(facts)

    assert len(draft["used_facts"]) == 1
    assert draft["used_facts"][0]["normalized_value"] == "mass_g:1E+4"
    assert sum(item["reason"] == "duplicate_evidence" for item in draft["rejected_evidence"]) == 2


def test_attribute_slots_keep_width_height_and_weight_concepts_separate():
    dimensions = _grounded_with_facts(
        [
            _direct_fact(fact_type="dimensions", attribute_key="width", value="80cm", content="宽80cm"),
            _direct_fact(fact_type="dimensions", attribute_key="height", value="120cm", content="高120cm"),
        ],
        fact_type="dimensions",
    )
    weight = _grounded_with_facts(
        [
            _direct_fact(fact_type="gross_weight", attribute_key="gross_weight", value="10kg"),
            _direct_fact(fact_type="load_capacity", attribute_key="load_capacity", value="10kg"),
        ],
        fact_type="",
    )

    assert {item["attribute_key"] for item in dimensions["used_facts"]} == {"width", "height"}
    assert not any(item["reason"] == "conflicting_evidence" for item in dimensions["rejected_evidence"])
    assert {item["attribute_key"] for item in weight["used_facts"]} == {"gross_weight", "load_capacity"}


def test_same_width_with_different_values_is_not_silently_deduplicated():
    draft = _grounded_with_facts(
        [
            _direct_fact(fact_type="dimensions", attribute_key="width", value="80cm"),
            _direct_fact(fact_type="dimensions", attribute_key="width", value="120cm"),
        ],
        fact_type="dimensions",
    )

    assert draft["used_facts"] == []
    assert [item["reason"] for item in draft["rejected_evidence"]] == [
        "conflicting_evidence",
        "conflicting_evidence",
    ]


def test_missing_attribute_key_is_warning_not_rejection():
    fact = _direct_fact(
        fact_type="gross_weight",
        attribute_key="",
        value="10kg",
        content="包装毛重10kg",
    )
    draft = _grounded_with_facts([fact])

    assert len(draft["used_facts"]) == 1
    assert draft["rejected_evidence"] == []
    assert draft["admission_warnings"][0]["reason"] == "conflict_check_skipped"


def test_unparseable_candidate_does_not_bypass_comparable_conflict_group():
    draft = _grounded_with_facts([
        _direct_fact(fact_type="gross_weight", attribute_key="gross_weight", value="10kg"),
        _direct_fact(fact_type="gross_weight", attribute_key="gross_weight", value="12kg"),
        _direct_fact(fact_type="gross_weight", attribute_key="gross_weight", value="approximately ten"),
    ])

    assert all(item["normalized_value"] == "" for item in draft["used_facts"])
    assert {item["reason"] for item in draft["rejected_evidence"]} == {"conflicting_evidence"}
    assert draft["admission_warnings"][0]["reason"] == "conflict_check_skipped"


def test_incomparable_mass_unit_domains_are_not_reported_as_numeric_conflict():
    draft = _grounded_with_facts(
        [
            _direct_fact(fact_type="gross_weight", attribute_key="gross_weight", value="2斤"),
            _direct_fact(fact_type="gross_weight", attribute_key="gross_weight", value="1kg"),
        ]
    )

    assert draft["used_facts"] == []
    assert {item["reason"] for item in draft["rejected_evidence"]} == {"incomparable_unit_domain"}


def test_product_fact_requires_a_shared_identity_namespace():
    cross_namespace = _direct_fact(
        fact_type="gross_weight",
        attribute_key="gross_weight",
        value="10kg",
        sku_code="SKU-X",
    )
    draft = _grounded_with_facts([cross_namespace], identity={"i_id": "IID-A"})

    assert draft["used_facts"] == []
    assert draft["rejected_evidence"][0]["reason"] == "product_identity_namespace_missing"


def test_global_direct_faq_does_not_require_product_identity():
    faq = {
        "evidence_role": "faq_direct",
        "fact_type": "gross_weight",
        "attribute_key": "gross_weight",
        "content": "重量以商品页面规格为准。",
        "can_direct_answer": True,
        "gate_status": "allowed",
        "review_status": "reviewed",
        "fact_scope": "global",
    }
    draft = _grounded_with_facts([faq], identity={"i_id": "IID-A"})

    assert len(draft["used_facts"]) == 1


def test_product_fact_cannot_use_global_scope_to_bypass_identity():
    fact = _direct_fact(
        fact_type="gross_weight",
        attribute_key="gross_weight",
        value="10kg",
        sku_code="",
        fact_scope="global",
    )
    draft = _grounded_with_facts([fact], identity={})

    assert draft["used_facts"] == []
    assert draft["rejected_evidence"][0]["reason"] == "product_identity_missing"


def test_shadow_local_fact_type_fallback_covers_high_value_unclassified_questions():
    bite = build_grounded_reasoning_draft(
        customer_message="宝宝咬了一下会不会中毒？",
        selected_evidence=[{"fact_type": "material", "content": "主体材质：PP"}],
    )
    pinch = build_grounded_reasoning_draft(customer_message="会不会夹脚？")
    visual = build_grounded_reasoning_draft(customer_message="看图是两层还是三层？")
    weight = build_grounded_reasoning_draft(
        customer_message="这个多重？",
        selected_evidence=[{"fact_type": "gross_weight", "content": "包装毛重约 10kg"}],
    )

    assert bite["query_fact_type"] == "material_safety"
    assert "误吞" in bite["grounded_draft"]
    assert pinch["query_fact_type"] == "pinch_safety"
    assert visual["query_fact_type"] == "structure"
    assert weight["query_fact_type"] == "gross_weight"
    assert "包装毛重" in weight["grounded_draft"]


def test_attach_shadow_draft_does_not_change_response_contract():
    response = {
        "suggested_reply": "原回复",
        "sendable_reply": "",
        "can_send": False,
        "requires_human_review": True,
        "selected_evidence": [{"fact_type": "material", "content": "主体材质：PP"}],
        "evidence_debug": {"query_fact_type": "material"},
        "answer_trace": {"query_fact_type": "material"},
    }

    updated = GroundedReasoningDraftService().attach_shadow_draft(
        response,
        customer_message="这个材质安全吗？",
        answer_memory_guidance={"action_hints": ["先按资料核对材质。"]},
    )

    assert updated["suggested_reply"] == "原回复"
    assert updated["can_send"] is False
    assert updated["sendable_reply"] == ""
    assert updated["requires_human_review"] is True
    assert updated["selected_evidence"] == [{"fact_type": "material", "content": "主体材质：PP"}]
    assert updated["grounded_reasoning_draft"]["used_for_final_reply"] is False
    assert updated["evidence_debug"]["grounded_reasoning_draft"]["can_change_can_send"] is False


def test_analyze_grounded_reasoning_shadow_is_env_gated(client, monkeypatch):
    import app.services.analysis_execution_service as execution_service

    def fake_execute_analysis(**kwargs):
        return _run_post_processor(kwargs, {
            "intent": "product_question",
            "suggested_reply": "Need review.",
            "requires_human_review": True,
            "can_send": False,
            "sendable_reply": "",
            "selected_evidence": [{"fact_type": "installation", "content": "安装说明"}],
            "evidence_debug": {"query_fact_type": "installation"},
            "answer_trace": {"query_fact_type": "installation"},
        })

    monkeypatch.setattr(execution_service, "execute_analysis", fake_execute_analysis)
    monkeypatch.delenv("COPILOT_GROUNDED_REASONING_SHADOW_ENABLED", raising=False)
    response = client.post(
        "/api/analyze",
        json={"message": "有没有安装视频？", "product_name": "测试商品", "conversation_id": "pytest_grounded_disabled"},
    )
    data = response.get_json()
    assert response.status_code == 200
    assert "grounded_reasoning_draft" not in data

    monkeypatch.setenv("COPILOT_GROUNDED_REASONING_SHADOW_ENABLED", "true")
    response = client.post(
        "/api/analyze",
        json={"message": "有没有安装视频？", "product_name": "测试商品", "conversation_id": "pytest_grounded_enabled"},
    )
    data = response.get_json()
    assert response.status_code == 200
    assert data["can_send"] is False
    assert data["sendable_reply"] == ""
    assert data["grounded_reasoning_draft"]["shadow_only"] is True
    assert data["grounded_reasoning_draft"]["can_change_can_send"] is False
    assert data["answer_trace"]["grounded_reasoning_draft"]["used_for_final_reply"] is False
