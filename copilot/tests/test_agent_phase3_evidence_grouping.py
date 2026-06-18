from app.agent.nodes.generate_reply import generate_reply
from app.services.evidence_grouping_service import group_evidence_by_fact_type
from app.services.final_answer_auditor import audit_final_answer


def _state(message, primary, secondary, evidence_items=None, product_pack=None):
    return {
        "customer_message": message,
        "normalized_message": message,
        "intent": "product_question",
        "risk_level": "low",
        "query_fact_type": primary,
        "secondary_fact_types": secondary,
        "query_understanding": {
            "original_message": message,
            "normalized_message": message,
            "retrieval_query": message,
            "intent": "product_question",
            "sub_intents": [],
            "query_fact_type": primary,
            "secondary_fact_types": secondary,
        },
        "filtered_evidence": evidence_items or [],
        "knowledge_evidence": evidence_items or [],
        "product_context_pack": product_pack or {},
        "evidence": {
            "product_facts": evidence_items or [],
            "faq_evidence": [],
            "policy_facts": [],
        },
        "trace_steps": [],
    }


def _fact(fact_type, text, source_type="product_facts"):
    return {
        "chunk_id": f"chunk-{fact_type}",
        "entry_id": f"entry-{fact_type}",
        "source_type": source_type,
        "chunk_text": text,
        "fact": text,
        "evidence_fact_type": fact_type,
        "fact_type": fact_type,
        "score": 0.95,
        "evidence_allowed_for_direct_answer": True,
        "direct_answer_allowed": True,
        "evidence_allowed_for_exact_answer": True,
    }


def test_grouping_and_reply_cover_material_plus_shipping():
    state = _state(
        "宝宝能用吗，今天能发吗？",
        "material",
        ["stock_shipping"],
        [_fact("material", "材质为环保PP和钢管，建议按页面检测说明核对宝宝使用安全。")],
    )

    result = generate_reply(state)

    grouping = result["evidence_grouping"]
    assert set(grouping["coverage"]["required_fact_types"]) == {"material", "stock_shipping"}
    assert {g["fact_type"] for g in grouping["groups"]} == {"material", "stock_shipping"}
    reply = result["suggested_reply"]
    assert any(token in reply for token in ("材质", "安全", "宝宝"))
    assert any(token in reply for token in ("发货", "库存", "下单页", "今天"))
    assert "绝对安全" not in reply
    assert "一定今天发" not in reply


def test_grouping_and_reply_cover_waterproof_plus_shipping():
    state = _state(
        "这个防水吗，什么时候发货？",
        "material",
        ["stock_shipping"],
        [_fact("material", "面料有防水说明，日常脏了可以用湿布擦拭。")],
    )

    result = generate_reply(state)

    reply = result["suggested_reply"]
    assert "防水" in reply or "湿布" in reply
    assert any(token in reply for token in ("发货", "库存", "下单页"))
    assert result["evidence_grouping"]["coverage"]["missing_fact_types"] == []


def test_grouping_and_reply_cover_dimensions_plus_visual_asset():
    product_pack = {
        "recommended_assets": [{
            "asset_id": "asset-size-1",
            "asset_type": "image",
            "asset_title": "尺寸图",
            "product_name": "测试商品",
        }],
    }
    state = _state(
        "尺寸多大？有没有图？",
        "dimensions",
        ["visual_asset"],
        [_fact("dimensions", "尺寸为长60cm、宽30cm、高90cm。")],
        product_pack,
    )

    result = generate_reply(state)

    grouping = result["evidence_grouping"]
    visual_group = next(g for g in grouping["groups"] if g["fact_type"] == "visual_asset")
    assert visual_group["selected_evidence"][0]["asset_id"] == "asset-size-1"
    reply = result["suggested_reply"]
    assert "尺寸" in reply or "60cm" in reply
    assert any(token in reply for token in ("图", "图片", "素材"))
    assert "承重" not in reply
    assert "材质" not in reply


def test_grouping_and_reply_cover_aftersales_plus_installation():
    state = _state(
        "少了配件，安装不了怎么办？",
        "aftersales_policy",
        ["installation"],
        [_fact("installation", "安装前需要先核对配件是否齐全。", "installation_guide")],
    )

    result = generate_reply(state)

    reply = result["suggested_reply"]
    assert any(token in reply for token in ("售后", "补发", "少件", "缺配件"))
    assert "安装" in reply
    assert "只按安装教程" in reply or "配件不齐" in reply


def test_missing_one_sub_intent_keeps_supported_shipping_answer():
    state = _state(
        "这个适合一岁宝宝吗？今天能发吗？",
        "age_range",
        ["stock_shipping"],
        [],
    )

    result = generate_reply(state)

    grouping = result["evidence_grouping"]
    assert "age_range" in grouping["coverage"]["missing_fact_types"]
    reply = result["suggested_reply"]
    assert any(token in reply for token in ("适龄", "适合", "一岁", "宝宝"))
    assert any(token in reply for token in ("发货", "库存", "下单页", "今天"))
    assert "一定适合" not in reply
    assert "一定今天发" not in reply


def test_final_auditor_blocks_missing_multi_intent_coverage():
    response = {
        "intent": "product_question",
        "suggested_reply": "亲，这款材质为环保PP，宝宝使用建议按页面说明核对。",
        "requires_human_review": False,
        "evidence_debug": {
            "query_fact_type": "material",
            "evidence_grouping": {
                "coverage": {
                    "required_fact_types": ["material", "stock_shipping"],
                    "covered_fact_types": ["material", "stock_shipping"],
                    "missing_fact_types": [],
                },
                "groups": [],
            },
            "multi_intent_answer_plan": [
                {"fact_type": "material", "covered_by_existing_reply": True, "reply_part": ""},
                {"fact_type": "stock_shipping", "covered_by_existing_reply": False, "reply_part": ""},
            ],
        },
    }

    audited = audit_final_answer(response, customer_message="宝宝能用吗，今天能发吗？")

    assert audited["final_answer_audit"]["passed"] is False
    assert "stock_shipping" in audited["final_answer_audit"]["missing_fact_types"]


def test_grouping_service_marks_missing_and_supported_fact_types_separately():
    grouping = group_evidence_by_fact_type(
        {
            "evidence": {},
            "knowledge_evidence": [],
            "filtered_evidence": [],
            "rejected_evidence": [],
            "product_context_pack": {},
        },
        {
            "query_fact_type": "age_range",
            "secondary_fact_types": ["stock_shipping"],
        },
    )

    assert grouping["coverage"]["required_fact_types"] == ["age_range", "stock_shipping"]
    assert "age_range" in grouping["coverage"]["missing_fact_types"]
    assert "stock_shipping" in grouping["coverage"]["covered_fact_types"]
