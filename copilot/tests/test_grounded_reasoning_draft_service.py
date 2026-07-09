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
                "source_type": "product_facts",
                "fact_type": "structure_function",
                "content": "柜门为滑门结构，使用时需要沿轨道推拉。",
            }
        ],
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
            {"source_type": "product_facts", "fact_type": "material", "content": "主体材质：PP。"}
        ],
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
        return {
            "intent": "product_question",
            "suggested_reply": "Need review.",
            "requires_human_review": True,
            "can_send": False,
            "sendable_reply": "",
            "selected_evidence": [{"fact_type": "installation", "content": "安装说明"}],
            "evidence_debug": {"query_fact_type": "installation"},
            "answer_trace": {"query_fact_type": "installation"},
        }

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
