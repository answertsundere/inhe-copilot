from app.services.final_answer_auditor import _expected_topics, _is_visual_media_answer, audit_final_answer
from app.services.customer_facing_safe_handoff_service import CUSTOMER_FACING_INTERNAL_REDLINE_TERMS


class _FakeMessage:
    def __init__(self, content):
        self.content = content


class _FakeChoice:
    def __init__(self, content):
        self.message = _FakeMessage(content)


class _FakeResponse:
    def __init__(self, content):
        self.choices = [_FakeChoice(content)]


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


def test_expected_topics_prefer_explicit_accessory_availability_over_stale_installation_intent():
    topics = _expected_topics(
        "\u8fd9\u4e2a\u914d\u4ef6\u6709\u5356\u5417",
        {
            "intent": "installation",
            "evidence_debug": {"query_fact_type": "accessory_availability"},
        },
    )

    assert "accessory_availability" in topics
    assert "installation" not in topics


def test_final_answer_auditor_allows_no_evidence_controlled_accessory_handoff():
    response = {
        "intent": "installation",
        "suggested_reply": "\u4eb2\uff0c\u6211\u6309\u8fd9\u6b3e\u5e2e\u60a8\u6838\u5bf9\u8fd9\u4e2a\u914d\u4ef6\u662f\u5426\u80fd\u5355\u72ec\u8865\u4e70/\u552e\u5356\u3002",
        "requires_human_review": True,
        "answer_mode": "no_evidence_controlled_reply",
        "evidence_debug": {
            "answer_mode": "no_evidence_clarification",
            "query_fact_type": "accessory_availability",
            "product_context_pack_summary": {
                "evidence_pack": {
                    "query_fact_type": "accessory_availability",
                    "answerability": "missing_product_fact",
                    "missing_fields": ["accessory_availability"],
                }
            },
        },
    }

    audited = audit_final_answer(
        response,
        customer_message="\u8fd9\u4e2a\u914d\u4ef6\u6709\u5356\u5417",
    )

    assert audited["final_answer_audit"]["passed"] is True
    assert audited.get("generation_mode") != "final_answer_audit_fallback"


def test_final_answer_auditor_allows_no_evidence_controlled_placement_handoff():
    response = {
        "intent": "product_question",
        "suggested_reply": "亲，这个摆放位置需要按这款商品的材质、结构和使用环境核对后再确认。我先帮您核对，避免直接说能晒、能放导致口径不准确。",
        "requires_human_review": True,
        "answer_mode": "no_evidence_controlled_reply",
        "answer_trace": {
            "query_fact_type": "placement_scene",
            "required_fact_types": ["placement_scene"],
            "no_evidence_reply_policy": {
                "reply_strategy": "verify_placement_scene_for_known_product",
                "requires_human_review": True,
            },
        },
        "evidence_debug": {
            "answer_mode": "no_evidence_controlled_reply",
            "query_fact_type": "placement_scene",
            "selected_evidence": [],
            "product_context_pack_summary": {
                "evidence_pack": {
                    "query_fact_type": "placement_scene",
                    "answerability": "missing_product_fact",
                    "missing_fields": ["placement_scene"],
                }
            },
        },
    }

    audited = audit_final_answer(
        response,
        customer_message="可以放在飘窗上晒吗",
    )

    assert audited["final_answer_audit"]["passed"] is True
    assert audited["final_answer_audit"]["no_evidence_controlled_accepted"] is True
    assert audited.get("generation_mode") != "final_answer_audit_fallback"


def test_final_answer_auditor_blocks_structure_function_answered_as_scene():
    response = {
        "intent": "product_question",
        "suggested_reply": "亲，这款可以放在卧室或客厅，建议摆在干燥平整的位置。",
        "requires_human_review": False,
        "evidence_debug": {"query_fact_type": "structure_function"},
    }

    audited = audit_final_answer(response, customer_message="侧板可以翻下来吗")

    assert audited["final_answer_audit"]["passed"] is False
    assert any(
        issue in audited["final_answer_audit"]["issues"]
        for issue in ("wrong_topic:structure_function->placement_scene", "answer_not_about_customer_question")
    )
    assert audited["requires_human_review"] is True


def test_final_answer_auditor_blocks_structure_compatibility_answered_as_space():
    response = {
        "intent": "product_question",
        "suggested_reply": "亲，这款能不能放下主要看您家预留位置的宽度、进深和高度，旁边也要留走动空间。",
        "requires_human_review": False,
        "evidence_debug": {"query_fact_type": "structure_function"},
    }

    audited = audit_final_answer(response, customer_message="三面围栏，想补第四面，这款能用吗")

    assert audited["final_answer_audit"]["passed"] is False
    assert any(
        issue in audited["final_answer_audit"]["issues"]
        for issue in ("wrong_topic:structure_function->space_fit", "answer_not_about_customer_question")
    )
    assert audited["requires_human_review"] is True


def test_final_answer_auditor_allows_damaged_aftersales_handoff():
    response = {
        "intent": "aftersales",
        "suggested_reply": "亲，收到。麻烦您拍一下破损位置、配件整体和外包装，我这边按订单核实后给您处理补发、换件或售后方案。",
        "requires_human_review": True,
        "evidence_debug": {"query_fact_type": "aftersales_policy"},
    }

    audited = audit_final_answer(response, customer_message="板子裂了")

    assert audited["final_answer_audit"]["passed"] is True
    assert audited["suggested_reply"] == response["suggested_reply"]


def test_final_answer_auditor_dimension_fallback_does_not_promise_media_without_block():
    response = {
        "intent": "product_question",
        "product_name": "\u6d4b\u8bd5\u6536\u7eb3\u67dc",
        "suggested_reply": "\u4eb2\uff0c\u8fd9\u6b3e\u6750\u8d28\u633a\u7ed3\u5b9e\u7684\u3002",
        "requires_human_review": False,
        "evidence_debug": {"query_fact_type": "dimensions"},
        "reply_blocks": [],
        "recommended_assets": [],
    }

    audited = audit_final_answer(response, customer_message="\u8fd9\u6b3e\u591a\u9ad8")

    assert audited["final_answer_audit"]["passed"] is False
    assert audited["requires_human_review"] is True
    assert "\u4e0b\u9762\u53d1" not in audited["suggested_reply"]
    assert "\u5546\u54c1\u56fe/\u5c3a\u5bf8\u56fe" not in audited["suggested_reply"]
    assert "\u6838\u5bf9" in audited["suggested_reply"]


def test_final_answer_auditor_blocks_media_promise_without_reply_blocks():
    response = {
        "intent": "product_question",
        "product_name": "\u6d4b\u8bd5\u4e66\u67b6",
        "suggested_reply": (
            "\u4eb2\uff0c\u5b89\u88c5\u53ef\u4ee5\u53c2\u8003\u8bf4\u660e\u4e66\u4e0a\u7684\u6b65\u9aa4\u54e6\u3002"
            "\u53e6\u5916\uff0c\u4e0b\u9762\u56fe\u7247/\u89c6\u9891\u53ef\u53c2\u8003\uff0c"
            "\u6211\u8fd9\u8fb9\u518d\u53d1\u60a8\u5bf9\u5e94\u7684\u5b89\u88c5\u56fe\u6216\u89c6\u9891\u3002"
        ),
        "requires_human_review": False,
        "evidence_debug": {
            "query_fact_type": "installation",
            "answer_mode": "no_evidence_controlled_reply",
        },
        "answer_trace": {
            "query_fact_type": "installation",
            "no_evidence_reply_policy": {
                "reply_strategy": "verify_installation_asset_before_send",
                "requires_human_review": True,
            },
        },
        "recommended_assets": [{
            "asset_type": "pack_guide_image",
            "asset_url": "https://asset.example/install.png",
            "auto_send_level": "auto",
        }],
        "reply_blocks": [],
    }

    audited = audit_final_answer(response, customer_message="\u9632\u5012\u5de5\u5177\u600e\u4e48\u7528")

    assert audited["final_answer_audit"]["passed"] is False
    assert "unsupported_media_claim" in audited["final_answer_audit"]["issues"]
    assert audited["requires_human_review"] is True
    assert "\u4e0b\u9762\u56fe\u7247/\u89c6\u9891\u53ef\u53c2\u8003" not in audited["suggested_reply"]


def test_final_answer_auditor_blocks_unsupported_installation_wall_fix_claim_without_evidence():
    response = {
        "intent": "product_question",
        "product_name": "\u6d4b\u8bd5\u4e66\u67b6",
        "suggested_reply": (
            "\u4eb2\uff5e\u60a8\u770b\u5230\u7684\u87ba\u4e1d\u5b54\u662f\u7528\u6765\u56fa\u5b9a\u4e66\u67b6\u7684\uff0c"
            "\u9632\u6b62\u503e\u5012\u3002\u5982\u679c\u5bb6\u91cc\u6709\u5c0f\u5b69\uff0c"
            "\u5efa\u8bae\u7528\u81a8\u80c0\u87ba\u4e1d\u56fa\u5b9a\u5728\u5899\u4e0a\uff0c\u8fd9\u6837\u66f4\u5b89\u5168\u3002"
            "\u60a8\u65b9\u4fbf\u62cd\u4e00\u4e0b\u87ba\u4e1d\u5b54\u7684\u4f4d\u7f6e\u5417\uff1f\u6211\u5e2e\u60a8\u786e\u8ba4\u5177\u4f53\u600e\u4e48\u5b89\u88c5\u3002"
        ),
        "requires_human_review": True,
        "evidence_debug": {
            "query_fact_type": "installation",
            "answer_mode": "no_evidence_controlled_reply",
        },
        "answer_trace": {
            "query_fact_type": "installation",
            "no_evidence_reply_policy": {
                "reply_strategy": "verify_installation_asset_before_send",
                "requires_human_review": True,
            },
        },
        "reply_blocks": [],
        "recommended_assets": [],
    }

    audited = audit_final_answer(response, customer_message="\u8fd9\u4e2a\u87ba\u4e1d\u5b54\u600e\u4e48\u56fa\u5b9a")

    assert audited["final_answer_audit"]["passed"] is False
    assert "unsupported_installation_structure_claim" in audited["final_answer_audit"]["issues"]
    assert audited["requires_human_review"] is True
    assert "\u81a8\u80c0\u87ba\u4e1d" not in audited["suggested_reply"]
    assert "\u56fa\u5b9a\u5728\u5899" not in audited["suggested_reply"]
    assert "\u9632\u6b62\u503e\u5012" not in audited["suggested_reply"]
    assert "\u5b89\u88c5\u8d44\u6599" in audited["suggested_reply"]
    assert "\u6838\u5bf9" in audited["suggested_reply"]


def test_final_answer_auditor_allows_installation_guidance_with_attached_install_asset():
    response = {
        "intent": "product_question",
        "product_name": "\u6d4b\u8bd5\u4e66\u67b6",
        "suggested_reply": (
            "\u4eb2\uff0c\u8fd9\u5f20\u5b89\u88c5\u56fe\u4e0a\u6807\u7684\u4f4d\u7f6e\u662f\u56fa\u5b9a\u7528\u7684\uff0c"
            "\u60a8\u53ef\u4ee5\u5148\u5bf9\u7167\u56fe\u4e0a\u87ba\u4e1d\u5b54\u4f4d\u770b\u4e00\u4e0b\u3002"
        ),
        "requires_human_review": False,
        "evidence_debug": {
            "query_fact_type": "installation",
            "evidence_sufficient": True,
            "selected_evidence": [{"fact_type": "installation"}],
        },
        "reply_blocks": [{
            "type": "image",
            "asset_type": "pack_guide_image",
            "asset_url": "https://asset.example/install.png",
        }],
        "recommended_assets": [],
    }

    audited = audit_final_answer(response, customer_message="\u8fd9\u4e2a\u87ba\u4e1d\u5b54\u600e\u4e48\u56fa\u5b9a")

    assert audited["final_answer_audit"]["passed"] is True
    assert "unsupported_installation_structure_claim" not in audited["final_answer_audit"]["issues"]
    assert audited["suggested_reply"] == response["suggested_reply"]


def test_final_answer_auditor_blocks_wall_fix_prescription_without_direct_verified_evidence():
    response = {
        "intent": "product_question",
        "i_id": "IID-A",
        "suggested_reply": "亲，可以用膨胀螺丝固定到墙上，这样更稳固安全。",
        "requires_human_review": True,
        "evidence_debug": {
            "query_fact_type": "installation",
            "evidence_sufficient": True,
            "selected_evidence": [{"fact_type": "installation"}],
        },
        "reply_blocks": [{
            "type": "image",
            "url": "https://asset.example/guide.png",
            "asset_type": "pack_guide_image",
            "i_id": "IID-A",
        }],
    }

    audited = audit_final_answer(response, customer_message="这个孔位怎么固定")

    assert audited["final_answer_audit"]["passed"] is False
    assert "unsupported_installation_structure_claim" in audited["final_answer_audit"]["issues"]
    assert "膨胀螺丝" not in audited["suggested_reply"]


def test_final_answer_auditor_allows_verified_direct_wall_fix_manual_evidence():
    response = {
        "intent": "product_question",
        "i_id": "IID-A",
        "suggested_reply": "亲，说明书要求使用膨胀螺丝固定到墙面，请按图示孔位操作。",
        "requires_human_review": True,
        "evidence_debug": {
            "query_fact_type": "installation",
            "selected_evidence": [{
                "fact_type": "installation",
                "evidence_role": "installation_manual",
                "verification_status": "reviewed",
                "i_id": "IID-A",
                "content": "说明书要求使用膨胀螺丝固定到墙面，防止倾倒。",
            }],
        },
        "reply_blocks": [],
    }

    audited = audit_final_answer(response, customer_message="这个孔位怎么固定")

    assert audited["final_answer_audit"]["passed"] is True
    assert audited["suggested_reply"] == response["suggested_reply"]


def test_final_answer_auditor_rejects_ineligible_or_unscoped_wall_fix_evidence():
    base = {
        "fact_type": "installation",
        "evidence_role": "installation_manual",
        "verification_status": "reviewed",
        "i_id": "IID-A",
        "content": "说明书要求使用膨胀螺丝固定到墙面，防止倾倒。",
    }
    variants = [
        {**base, "reference_only": True},
        {**base, "gate_status": "blocked"},
        {**base, "direct_answer_allowed": False},
        {**base, "i_id": "IID-B"},
        {key: value for key, value in base.items() if key != "i_id"},
    ]
    for evidence in variants:
        response = {
            "i_id": "IID-A",
            "suggested_reply": "亲，可以用膨胀螺丝固定到墙上，这样更稳固安全。",
            "requires_human_review": True,
            "evidence_debug": {"query_fact_type": "installation", "selected_evidence": [evidence]},
        }
        audited = audit_final_answer(response, customer_message="这个孔位怎么固定")
        assert "unsupported_installation_structure_claim" in audited["final_answer_audit"]["issues"]


def test_final_answer_auditor_uses_llm_semantic_judge(monkeypatch):
    from app import config
    from app.llm import client as llm_client

    monkeypatch.setattr(config, "COPILOT_FINAL_AUDIT_LLM_ENABLED", True)
    monkeypatch.setattr(
        llm_client,
        "get_llm_client",
        lambda: _FakeClient(
            '{"passed": false, "issues": ["semantic_mismatch"], "reason": "客户问气味，但回复只讲防潮和材质，没有回答气味。"}'
        ),
    )
    response = {
        "intent": "product_question",
        "suggested_reply": "亲～这款主要采用冷轧钢管和环保PP材质，长期潮湿环境下可能有生锈风险。",
        "requires_human_review": False,
        "evidence_debug": {"query_fact_type": "material"},
    }

    audited = audit_final_answer(response, customer_message="材质有气味吗")

    assert audited["final_answer_audit"]["passed"] is False
    assert audited["final_answer_audit"]["mode"] == "llm_semantic_consistency_with_hard_safety"
    assert "llm:semantic_mismatch" in audited["final_answer_audit"]["issues"]
    assert audited["requires_human_review"] is True


def test_final_answer_auditor_llm_blocks_space_question_answered_as_load(monkeypatch):
    from app import config
    from app.llm import client as llm_client

    monkeypatch.setattr(config, "COPILOT_FINAL_AUDIT_LLM_ENABLED", True)
    monkeypatch.setattr(
        llm_client,
        "get_llm_client",
        lambda: _FakeClient(
            '{"passed": false, "issues": ["answered_space_fit_as_load_capacity"], "reason": "客户问空间是否放得下，回复却只回答承重。"}'
        ),
    )
    response = {
        "intent": "product_question",
        "suggested_reply": "\u4eb2\uff5e\u8fd9\u6b3e\u5355\u5c42\u5747\u5300\u627f\u91cd\u7ea615-30kg\uff0c\u653e\u4e66\u7c4d\u73a9\u5177\u90fd\u591f\u7528\u3002",
        "requires_human_review": False,
        "evidence_debug": {"query_fact_type": "space_fit"},
    }

    audited = audit_final_answer(response, customer_message="\u5367\u5ba4\u7a7a\u95f4\u6bd4\u8f83\u5c0f\uff0c\u8fd9\u4e2a\u653e\u7684\u4e0b\u5417")

    assert audited["final_answer_audit"]["passed"] is False
    assert "llm:answered_space_fit_as_load_capacity" in audited["final_answer_audit"]["issues"]
    assert audited["requires_human_review"] is True


def test_final_answer_auditor_blocks_child_age_safety_claims_to_handoff():
    response = {
        "intent": "product_question",
        "product_name": "测试儿童书架",
        "suggested_reply": "亲亲，这款适合0-6岁的宝宝使用，圆角设计也能保护宝宝安全。",
        "requires_human_review": False,
        "evidence_debug": {"query_fact_type": "age_range"},
    }

    audited = audit_final_answer(response, customer_message="有没有适合2周岁宝宝的")

    assert audited["final_answer_audit"]["passed"] is False
    assert audited["requires_human_review"] is True
    assert "宝宝适用" in audited["suggested_reply"]
    assert "适用年龄" in audited["suggested_reply"]
    assert "核对" in audited["suggested_reply"]
    assert "避免说错" in audited["suggested_reply"]
    assert "准确回复" in audited["suggested_reply"]
    for term in CUSTOMER_FACING_INTERNAL_REDLINE_TERMS:
        assert term not in audited["suggested_reply"]
    assert "适合0-6岁" not in audited["suggested_reply"]
    assert "保护宝宝安全" not in audited["suggested_reply"]


def test_final_answer_auditor_blocks_pinch_answered_as_battery():
    response = {
        "intent": "product_question",
        "suggested_reply": "亲，您问的是「九号防夹滑门收纳柜」的小零件/电池安全，我先帮您核对。",
        "requires_human_review": False,
        "evidence_debug": {
            "query_fact_type": "pinch_safety",
            "query_fact_type_label": "夹手/结构安全",
        },
    }

    audited = audit_final_answer(
        response,
        customer_message="家里有两岁宝宝，这个会不会夹手或者有安全隐患？",
    )

    assert audited["final_answer_audit"]["passed"] is False
    assert "pinch_safety_answered_as_small_parts_battery" in audited["final_answer_audit"]["issues"]
    assert audited["requires_human_review"] is True
    assert "夹手" in audited["suggested_reply"]
    assert "小零件/电池安全" not in audited["suggested_reply"]


def test_final_answer_auditor_allows_matching_pinch_handoff():
    response = {
        "intent": "product_question",
        "suggested_reply": "亲，您担心的是「九号防夹滑门收纳柜」滑门会不会夹手对吗？我先帮您按对应款式核实清楚。",
        "requires_human_review": True,
        "evidence_debug": {"query_fact_type": "pinch_safety"},
    }

    audited = audit_final_answer(
        response,
        customer_message="家里有两岁宝宝，这个会不会夹手或者有安全隐患？",
    )

    assert audited["final_answer_audit"]["passed"] is True
    assert audited["suggested_reply"] == response["suggested_reply"]


def test_final_answer_auditor_blocks_material_safety_claim_from_composition_only():
    response = {
        "intent": "material_safety",
        "i_id": "IID-A",
        "suggested_reply": "亲，这款是PP材质，宝宝接触也安全，您放心使用。",
        "requires_human_review": False,
        "evidence_debug": {
            "query_fact_type": "material_safety",
            "selected_evidence": [{
                "evidence_uid": "composition-only",
                "evidence_role": "product_fact_direct",
                "fact_type": "material",
                "content": "主体材质为PP。",
                "verification_status": "reviewed",
                "gate_status": "allowed",
                "direct_answer_allowed": True,
                "i_id": "IID-A",
            }],
        },
    }

    audited = audit_final_answer(response, customer_message="宝宝会咬，这个材质安全吗？")

    assert audited["requires_human_review"] is True
    assert "unsupported_high_risk_claim:material_safety" in audited["final_answer_audit"]["issues"]
    assert "放心使用" not in audited["suggested_reply"]
    assert audited["can_send"] is False
    assert audited["sendable_reply"] == ""
    assert audited["reply_status"] == "needs_human_review"


def test_final_answer_auditor_allows_material_safety_only_with_matching_direct_evidence():
    response = {
        "intent": "material_safety",
        "i_id": "IID-A",
        "suggested_reply": "亲，这款的材质安全说明可按对应检测资料查看。",
        "requires_human_review": False,
        "evidence_debug": {
            "query_fact_type": "material_safety",
            "selected_evidence": [{
                "evidence_uid": "safety-direct",
                "evidence_role": "product_fact_direct",
                "fact_type": "material_safety",
                "supported_claim_types": ["material_safety"],
                "content": "该款材质安全说明以对应检测资料为准。",
                "verification_status": "reviewed",
                "gate_status": "allowed",
                "direct_answer_allowed": True,
                "i_id": "IID-A",
            }],
        },
    }

    audited = audit_final_answer(response, customer_message="这个材质安全吗？")

    assert "unsupported_high_risk_claim:material_safety" not in audited["final_answer_audit"]["issues"]


def test_final_answer_auditor_blocks_pinch_answered_as_generic_material():
    response = {
        "intent": "product_question",
        "suggested_reply": "亲，您问的材质和安全点我先按这款商品帮您再核实一下。",
        "requires_human_review": True,
        "evidence_debug": {"query_fact_type": "pinch_safety"},
    }

    audited = audit_final_answer(
        response,
        customer_message="家里有两岁宝宝，这个会不会夹手或者有安全隐患？",
    )

    assert audited["final_answer_audit"]["passed"] is False
    assert "夹手" in audited["suggested_reply"]
    assert "材质和安全点" not in audited["suggested_reply"]


def test_final_answer_auditor_blocks_internal_language():
    response = {
        "intent": "product_question",
        "suggested_reply": "亲，系统里目前没有这款商品的已审核资料，我先转人工。",
        "requires_human_review": False,
        "evidence_debug": {"query_fact_type": "material"},
    }

    audited = audit_final_answer(response, customer_message="这个材质安全吗？")

    assert audited["final_answer_audit"]["passed"] is False
    assert "internal_system_language" in audited["final_answer_audit"]["issues"]
    assert "系统里" not in audited["suggested_reply"]
    assert "已审核资料" not in audited["suggested_reply"]


def test_final_answer_auditor_rewrites_odor_internal_or_wrong_reply():
    response = {
        "intent": "odor_question",
        "product_name": "测试收纳柜",
        "suggested_reply": "亲，系统里没有这款商品的已审核资料，我不能凭感觉说有没有味道，先转人工。",
        "requires_human_review": False,
        "evidence_debug": {"query_fact_type": "odor"},
    }

    audited = audit_final_answer(response, customer_message="产品有味道吗？")

    assert audited["final_answer_audit"]["passed"] is False
    assert audited["requires_human_review"] is True
    assert "气味" in audited["suggested_reply"]
    assert "通风" in audited["suggested_reply"]
    assert "拍照" in audited["suggested_reply"] or "视频" in audited["suggested_reply"]
    assert "系统" not in audited["suggested_reply"]
    assert "资料库" not in audited["suggested_reply"]
    assert "凭感觉" not in audited["suggested_reply"]
    assert "绝对没有" not in audited["suggested_reply"]
    assert "核实" not in audited["suggested_reply"]
    assert "确认清楚" not in audited["suggested_reply"]
    assert "转人工" not in audited["suggested_reply"]

def test_final_answer_auditor_blocks_direct_answer_when_product_card_fact_missing():
    response = {
        "intent": "product_question",
        "suggested_reply": "\u4eb2\uff0c\u8fd9\u6b3e\u662f\u53ef\u4ee5\u62c6\u5378\u7684\uff0c\u65e5\u5e38\u4f7f\u7528\u5f88\u65b9\u4fbf\u3002",
        "requires_human_review": False,
        "product_context_pack": {
            "evidence_pack": {
                "answerability": "missing_product_fact",
                "query_fact_type": "detachable",
                "missing_fields": ["detachable"],
                "matched_facts": [],
            }
        },
        "evidence_debug": {"query_fact_type": "detachable"},
    }

    audited = audit_final_answer(response, customer_message="\u8fd9\u4e2a\u53ef\u4ee5\u62c6\u5378\u5417")

    assert audited["final_answer_audit"]["passed"] is False
    assert "product_card_missing_fact_answered_as_direct" in audited["final_answer_audit"]["issues"]
    assert audited["requires_human_review"] is True


def test_final_answer_auditor_allows_handoff_when_product_card_fact_missing():
    response = {
        "intent": "product_question",
        "suggested_reply": "\u4eb2\uff0c\u8fd9\u4e2a\u62c6\u88c5\u7ec6\u8282\u6211\u5148\u5e2e\u60a8\u6838\u5b9e\u6e05\u695a\uff0c\u60a8\u7a0d\u7b49\u4e00\u4e0b\u3002",
        "requires_human_review": True,
        "product_context_pack": {
            "evidence_pack": {
                "answerability": "missing_product_fact",
                "query_fact_type": "detachable",
                "missing_fields": ["detachable"],
                "matched_facts": [],
            }
        },
        "evidence_debug": {"query_fact_type": "detachable"},
    }

    audited = audit_final_answer(response, customer_message="\u8fd9\u4e2a\u53ef\u4ee5\u62c6\u5378\u5417")

    assert audited["final_answer_audit"]["passed"] is True


def test_visual_media_fallback_requires_attached_identity_matched_dimension_block():
    base = {
        "query_fact_type": "dimensions",
        "i_id": "ITEM-A",
        "suggested_reply": "亲，下面尺寸图您可以参考。",
        "reply_blocks": [{
            "type": "image",
            "asset_type": "size_image",
            "media_purpose": "dimension_reference",
            "i_id": "ITEM-A",
            "asset_url": "https://asset.example/size.png",
            "status": "approved",
            "usable_for_agent": True,
        }],
    }

    assert _is_visual_media_answer(base, base["suggested_reply"], {"dimensions"}) is True
    assert _is_visual_media_answer(
        {**base, "reply_blocks": [{
            **base["reply_blocks"][0],
            "asset_type": "sku_image",
            "media_purpose": "appearance_image",
        }]},
        base["suggested_reply"],
        {"dimensions"},
    ) is False
    assert _is_visual_media_answer(
        {**base, "reply_blocks": []},
        base["suggested_reply"],
        {"dimensions"},
    ) is False
