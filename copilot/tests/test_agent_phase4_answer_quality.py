from app.agent.nodes.build_response import build_response
from app.agent.nodes.generate_reply import generate_reply
from app.agent.nodes.gold_csr_reply_builder import gold_csr_reply_builder
from app.agent.nodes.post_generation_grounding_guard import post_generation_grounding_guard
from app.services.semantic_fact_type_service import classify_query_fact_type_llm_first
from app.services.final_answer_auditor import audit_final_answer
from app.services.final_semantic_quality_service import audit_customer_reply_semantic_fit


def _bad_text_tokens():
    return [
        chr(code)
        for code in (
            0x95BA,
            0x940E,
            0x95B8,
            0x940F,
            0x95C1,
            0x6FE0,
            0x7F01,
            0x6FE1,
            0x93C9,
            0x7039,
            0x9359,
        )
    ] + ["\ufffd"]


def _assert_customer_reply_clean(reply: str):
    assert not any(token in reply for token in _bad_text_tokens())
    assert not any(token in reply for token in ("系统", "知识库", "RAG", "fact_type", "query_fact_type"))


def _fact(fact_type, text, source_type="product_facts"):
    return {
        "chunk_id": f"chunk-{fact_type}",
        "entry_id": f"entry-{fact_type}",
        "source_type": source_type,
        "title": f"{fact_type} fact",
        "chunk_text": text,
        "fact": text,
        "evidence_fact_type": fact_type,
        "fact_type": fact_type,
        "score": 0.95,
        "evidence_allowed_for_direct_answer": True,
        "direct_answer_allowed": True,
        "evidence_allowed_for_exact_answer": True,
    }


def _state(message, primary, secondary=None, evidence_items=None, *, intent="product_question", risk_level="low", product_pack=None):
    secondary = secondary or []
    evidence_items = evidence_items or []
    return {
        "customer_message": message,
        "normalized_message": message,
        "intent": intent,
        "risk_level": risk_level,
        "query_fact_type": primary,
        "query_fact_type_label": primary,
        "secondary_fact_types": secondary,
        "query_understanding": {
            "original_message": message,
            "normalized_message": message,
            "retrieval_query": message,
            "intent": intent,
            "sub_intents": [],
            "query_fact_type": primary,
            "secondary_fact_types": secondary,
        },
        "filtered_evidence": evidence_items,
        "knowledge_evidence": evidence_items,
        "product_context_pack": product_pack or {},
        "evidence": {
            "product_facts": evidence_items,
            "faq_evidence": [],
            "policy_facts": [],
            "template_evidence": [],
            "sop_evidence": [],
        },
        "trace_steps": [],
    }


def test_material_and_stock_shipping_are_naturally_merged():
    result = generate_reply(_state(
        "宝宝能用吗，今天能发吗？",
        "material",
        ["stock_shipping"],
        [_fact("material", "材质为冷轧钢管、环保PP和无纺布，建议按页面检测说明正常使用。")],
    ))

    reply = result["suggested_reply"]
    _assert_customer_reply_clean(reply)
    assert "宝宝" in reply
    assert any(token in reply for token in ("冷轧钢", "钢管", "环保PP", "无纺布"))
    assert any(token in reply for token in ("发货", "库存", "下单时间", "仓库"))
    assert "绝对安全" not in reply
    assert "一定今天发" not in reply
    trace = result["answer_composition_trace"]
    assert set(trace["covered_fact_types"]) == {"material", "stock_shipping"}
    assert trace["fallback_used_by_fact_type"]["material"] is False
    assert trace["fallback_used_by_fact_type"]["stock_shipping"] is True


def test_baby_can_use_plus_shipping_routes_to_material_not_age(monkeypatch):
    from app import config

    monkeypatch.setattr(config, "COPILOT_FACT_TYPE_LLM_ENABLED", False)

    result = classify_query_fact_type_llm_first({
        "customer_message": "宝宝能用吗，今天能发吗？",
        "normalized_message": "宝宝能用吗，今天能发吗？",
        "intent": "stock_query",
    })

    assert result["query_fact_type"] == "stock_shipping"
    assert "material" in result["secondary_fact_types"]
    assert "age_range" not in result["secondary_fact_types"]


def test_dimensions_and_visual_asset_do_not_drift_to_load_or_material():
    product_pack = {
        "recommended_assets": [{
            "asset_id": "asset-size",
            "asset_type": "image",
            "asset_title": "尺寸图",
        }],
    }
    result = generate_reply(_state(
        "尺寸多大，有没有图？",
        "dimensions",
        ["visual_asset"],
        [_fact("dimensions", "尺寸为长60cm、宽30cm、高90cm。")],
        product_pack=product_pack,
    ))

    reply = result["suggested_reply"]
    _assert_customer_reply_clean(reply)
    assert "尺寸" in reply
    assert any(token in reply for token in ("60cm", "长60", "宽30", "高90"))
    assert any(token in reply for token in ("图", "图片", "尺寸图"))
    assert "承重" not in reply
    assert "材质" not in reply


def test_space_fit_does_not_answer_as_load_or_moisture():
    result = generate_reply(_state(
        "卧室空间比较小，大概要多少空间才放得下？",
        "space_fit",
        [],
        [],
    ))

    reply = result["suggested_reply"]
    _assert_customer_reply_clean(reply)
    assert any(token in reply for token in ("长宽高", "占地", "预留", "空间"))
    assert "承重" not in reply
    assert "防潮" not in reply
    assert "生锈" not in reply


def test_unscoped_faq_is_not_used_as_direct_space_fit_fact():
    result = generate_reply(_state(
        "卧室空间比较小，大概要多少空间才放得下？",
        "space_fit",
        [],
        [_fact("dimensions", "这款折叠脸盆有大号和小号可选，折叠设计非常节省空间。", "faq")],
    ))

    reply = result["suggested_reply"]
    _assert_customer_reply_clean(reply)
    assert "折叠脸盆" not in reply
    assert any(token in reply for token in ("长宽高", "占地", "预留", "空间"))


def test_gold_csr_preserves_composed_answer_when_it_covers_required_fact_type():
    generated = generate_reply(_state(
        "卧室空间比较小，大概要多少空间才放得下？",
        "space_fit",
        [],
        [],
    ))
    generated.pop("answer_composition_trace", None)

    result = gold_csr_reply_builder({
        **_state("卧室空间比较小，大概要多少空间才放得下？", "space_fit", []),
        **generated,
        "response_strategy_plan": {"reply_goal": "clarify_product_identity"},
    })

    assert result["gold_csr_applied"] is False
    assert "发一下商品链接" not in result["suggested_reply"]
    assert any(token in result["suggested_reply"] for token in ("长宽高", "占地", "预留", "空间"))


def test_placement_scene_is_not_only_material():
    result = generate_reply(_state(
        "这个在卧室可以用吗？",
        "placement_scene",
        [],
        [],
    ))

    reply = result["suggested_reply"]
    _assert_customer_reply_clean(reply)
    assert "卧室" in reply
    assert any(token in reply for token in ("平整", "干燥", "通风", "通行"))
    assert "承重" not in reply


def test_aftersales_plus_installation_answers_aftersales_first():
    result = generate_reply(_state(
        "少了配件，安装不了怎么办？",
        "aftersales_policy",
        ["installation"],
        [_fact("installation", "安装前需要先核对配件是否齐全。", "installation_guide")],
        intent="aftersales",
        risk_level="medium",
    ))

    reply = result["suggested_reply"]
    _assert_customer_reply_clean(reply)
    assert any(token in reply for token in ("少件", "缺配件", "售后"))
    assert "安装" in reply
    assert reply.find("售后") < reply.find("安装")
    assert "硬装" in reply or "配件" in reply


def test_wrong_item_return_explains_aftersales_before_photo_request():
    result = generate_reply(_state(
        "你们发错了，我想退，怎么弄？",
        "aftersales_policy",
        [],
        [],
        intent="aftersales",
        risk_level="medium",
    ))

    reply = result["suggested_reply"]
    _assert_customer_reply_clean(reply)
    assert "售后" in reply
    assert "退货" in reply
    assert "拍" in reply
    assert reply.find("售后") < reply.find("拍")
    assert reply.find("退货") < reply.find("拍")
    assert "订单截图" not in reply


def test_odor_fallback_has_no_internal_terms_or_absolute_promise():
    result = generate_reply(_state(
        "这个有味道吗？",
        "odor",
        [],
        [],
        intent="odor_question",
    ))

    reply = result["suggested_reply"]
    _assert_customer_reply_clean(reply)
    assert "味" in reply
    assert "通风" in reply
    assert "保证无味" not in reply
    assert "绝对无味" not in reply


def test_odor_composition_does_not_quote_policy_redline_as_product_fact():
    result = generate_reply(_state(
        "这个有味道吗？",
        "odor",
        ["material"],
        [_fact(
            "odor",
            "以下承诺在回复中绝对不能出现：气味会在通风后消散/产品符合安全标准。",
            "aftersales_policy",
        )],
        intent="odor_question",
    ))

    reply = result["suggested_reply"]
    _assert_customer_reply_clean(reply)
    assert "以下承诺" not in reply
    assert "绝对不能出现" not in reply
    assert "气味" in reply or "味道" in reply
    assert "通风" in reply


def test_complaint_reply_has_apology_aftersales_and_no_compensation_promise():
    result = generate_reply(_state(
        "这个质量太差了，再不处理我就投诉你们。",
        "aftersales_policy",
        [],
        [],
        intent="complaint",
        risk_level="high",
    ))

    reply = result["suggested_reply"]
    _assert_customer_reply_clean(reply)
    assert any(token in reply for token in ("添麻烦", "抱歉", "不好意思"))
    assert any(token in reply for token in ("售后", "处理", "核对"))
    assert "一定赔" not in reply
    assert "直接赔" not in reply


def test_final_auditor_still_blocks_answer_a_to_b():
    response = {
        "intent": "product_question",
        "suggested_reply": "亲，这款单层均匀承重约15-30kg，放书籍玩具都够用。",
        "requires_human_review": False,
        "evidence_debug": {"query_fact_type": "space_fit"},
    }

    audited = audit_final_answer(response, customer_message="卧室空间比较小，这个放得下吗？")

    assert audited["final_answer_audit"]["passed"] is False
    assert audited["requires_human_review"] is True


def test_final_auditor_allows_safe_composition_fallback_for_space_fit():
    reply = "亲亲，卧室空间比较小的话，重点看商品长宽高、占地和开合/取放预留空间；您可以量一下预留位置的长宽高，我按对应款式帮您判断。"
    response = {
        "intent": "product_question",
        "suggested_reply": reply,
        "requires_human_review": False,
        "evidence_debug": {
            "query_fact_type": "space_fit",
            "answer_composition_trace": {
                "covered_fact_types": ["space_fit"],
                "missing_fact_types": [],
                "fallback_used_by_fact_type": {"space_fit": True},
                "answer_sections": [{"fact_type": "space_fit", "source": "fallback", "text": reply}],
            },
            "product_context_pack_summary": {
                "evidence_pack": {
                    "query_fact_type": "space_fit",
                    "answerability": "missing_product_fact",
                },
            },
        },
    }

    audited = audit_final_answer(response, customer_message="卧室空间比较小，这个放得下吗？")

    assert audited["final_answer_audit"]["passed"] is True


def test_final_auditor_does_not_let_llm_override_safe_composition(monkeypatch):
    from app import config
    from app.services import final_answer_auditor as auditor

    monkeypatch.setattr(config, "COPILOT_FINAL_AUDIT_LLM_ENABLED", True)
    monkeypatch.setattr(
        auditor,
        "_semantic_llm_audit",
        lambda *args, **kwargs: {"passed": False, "issues": ["semantic_mismatch"], "reason": "fake false negative"},
    )
    reply = "亲亲，卧室空间比较小的话，重点看商品长宽高、占地和开合/取放预留空间；您可以量一下预留位置的长宽高，我按对应款式帮您判断。"
    response = {
        "intent": "product_question",
        "suggested_reply": reply,
        "requires_human_review": False,
        "evidence_debug": {
            "query_fact_type": "space_fit",
            "answer_composition_trace": {
                "covered_fact_types": ["space_fit"],
                "missing_fact_types": [],
                "fallback_used_by_fact_type": {"space_fit": True},
                "answer_sections": [{"fact_type": "space_fit", "source": "fallback", "text": reply}],
            },
        },
    }

    audited = audit_final_answer(response, customer_message="卧室空间比较小，这个放得下吗？")

    assert audited["final_answer_audit"]["passed"] is True


def test_post_generation_grounding_skips_safe_composition_fallback():
    generated = generate_reply(_state(
        "卧室空间比较小，大概要多少空间才放得下？",
        "space_fit",
        [],
        [],
    ))

    result = post_generation_grounding_guard({**_state(
        "卧室空间比较小，大概要多少空间才放得下？",
        "space_fit",
        [],
    ), **generated})

    assert result["post_generation_grounding"]["passed"] is True
    assert result["post_generation_grounding"]["judge_mode"] == "answer_composition_fallback_skip"
    assert "长宽高" in generated["suggested_reply"]


def test_final_semantic_fit_allows_safe_composition_fallback(monkeypatch):
    from app import config

    monkeypatch.setattr(config, "COPILOT_FINAL_AUDIT_LLM_ENABLED", False)
    reply = "亲亲，卧室空间比较小的话，重点看商品长宽高、占地和开合/取放预留空间；您可以量一下预留位置的长宽高，我按对应款式帮您判断。"
    result = audit_customer_reply_semantic_fit(
        {
            "intent": "product_question",
            "suggested_reply": reply,
            "requires_human_review": False,
            "evidence_debug": {
                "query_fact_type": "space_fit",
                "answer_composition_trace": {
                    "covered_fact_types": ["space_fit"],
                    "missing_fact_types": [],
                    "fallback_used_by_fact_type": {"space_fit": True},
                    "answer_sections": [{"fact_type": "space_fit", "source": "fallback", "text": reply}],
                },
                "product_context_pack_summary": {
                    "evidence_pack": {
                        "query_fact_type": "space_fit",
                        "answerability": "missing_product_fact",
                    },
                },
            },
        },
        customer_message="卧室空间比较小，这个放得下吗？",
    )

    assert result["passed"] is True


def test_build_response_exposes_answer_composition_trace():
    generated = generate_reply(_state(
        "宝宝能用吗，今天能发吗？",
        "material",
        ["stock_shipping"],
        [_fact("material", "材质为冷轧钢管、环保PP和无纺布。")],
    ))

    response = build_response({**_state("宝宝能用吗，今天能发吗？", "material", ["stock_shipping"]), **generated})

    trace = response["evidence_debug"]["answer_composition_trace"]
    assert set(trace["covered_fact_types"]) == {"material", "stock_shipping"}
    assert response["evidence_debug"]["answer_composition_trace"]["answer_sections"]


def test_build_response_restores_composed_reply_from_trace_when_state_reply_drifted():
    state = _state("卧室空间比较小，大概要多少空间才放得下？", "space_fit", [])
    state.update({
        "suggested_reply": "亲，这款折叠脸盆有大号和小号可选，折叠设计非常节省空间。",
        "answer_composition_trace": {
            "covered_fact_types": ["space_fit"],
            "missing_fact_types": [],
            "fallback_used_by_fact_type": {"space_fit": True},
            "answer_sections": [{
                "fact_type": "space_fit",
                "source": "fallback",
                "text": "卧室空间比较小的话，重点看商品长宽高、占地和开合/取放预留空间；您可以量一下预留位置的长宽高，我按对应款式帮您判断。",
            }],
        },
    })

    response = build_response(state)

    assert "折叠脸盆" not in response["suggested_reply"]
    assert "长宽高" in response["suggested_reply"]
    assert "预留" in response["suggested_reply"]


def test_phase4_output_has_no_internal_terms():
    result = generate_reply(_state(
        "宝宝能用吗，今天能发吗？",
        "material",
        ["stock_shipping"],
        [_fact("material", "材质为环保PP。")],
    ))

    _assert_customer_reply_clean(result["suggested_reply"])
