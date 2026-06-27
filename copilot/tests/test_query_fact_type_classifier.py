from app.main import create_app
from app.services import semantic_fact_type_service
from app.services.fact_type_service import classify_query_fact_type


def test_query_fact_type_classifier_high_frequency_fields():
    cases = {
        "\u8fd9\u4e2a\u4ec0\u4e48\u6750\u8d28\uff1f": "material",
        "\u6ca1\u6709\u7532\u919b\u7684\u68c0\u67e5\u62a5\u544a\u5417\uff1f": "certification_report",
        "\u57fa\u7840\u6b3e\u548c\u5347\u7ea7\u6b3e\u5dee\u4ec0\u4e48": "variant_compare",
        "\u8fd9\u4e2a\u627f\u91cd\u591a\u5c11\uff1f": "load_capacity",
        "\u8fd9\u4e2a\u7ed9\u5b9d\u5b9d\u7528\u7edd\u5bf9\u4e0d\u4f1a\u5012\u5427\uff1f": "stability",
        "\u8fd9\u4e2a\u9632\u503e\u5012\u5417\uff1f": "stability",
        "\u8fd9\u4e2a\u7a33\u4e0d\u7a33\uff1f": "stability",
        "\u8fd9\u4e2a\u4f1a\u4e0d\u4f1a\u5939\u624b\u6216\u8005\u6709\u5b89\u5168\u9690\u60a3\uff1f": "pinch_safety",
        "\u8fd9\u4e2a\u5c0f\u96f6\u4ef6\u4f1a\u4e0d\u4f1a\u88ab\u5b9d\u5b9d\u8bef\u541e\uff1f": "safety_small_parts",
        "\u9002\u5408\u591a\u5927\u5b9d\u5b9d\uff1f": "age_range",
        "\u53ef\u4ee5\u5f00\u53d1\u7968\u5417\uff1f": "invoice_policy",
        "\u53ef\u4ee5\u7533\u8bf7\u4ef7\u4fdd\u5417\uff1f": "price_protection",
        "\u8fd9\u662f\u53ef\u62c6\u5378\u7684\u5417\uff1f": "detachable",
        "\u4ea7\u54c1\u6709\u6c14\u5473\u5417": "odor",
        "\u8fd9\u4e2a\u6709\u5473\u513f\u5417": "odor",
        "\u6750\u8d28\u6709\u6c14\u5473\u5417": "odor",
        "\u652f\u4ed8\u5b9d\u6253\u6b3e\u591a\u4e45\u80fd\u5230\u8d26": "aftersales_policy",
        "\u6dd8\u5b9d\u5c0f\u989d\u6253\u6b3e\u4e00\u822c\u591a\u4e45": "aftersales_policy",
        "\u6bdb\u91cd\u591a\u5c11": "gross_weight",
        "\u5546\u54c1\u6bdb\u91cd\u591a\u5c11": "gross_weight",
        "\u8fd9\u4e2a\u591a\u91cd": "gross_weight",
        "\u5c0f\u7bee\u5b50\u914d\u4ef6\u6709\u5356\u5417": "accessory_availability",
        "\u914d\u4ef6\u80fd\u5355\u72ec\u4e70\u5417": "accessory_availability",
    }
    for message, expected in cases.items():
        result = classify_query_fact_type(message, "product_question")
        assert result["query_fact_type"] == expected


def test_accessory_installation_question_is_not_availability():
    result = classify_query_fact_type("\u8fd9\u4e2a\u914d\u4ef6\u600e\u4e48\u88c5", "product_question")

    assert result["query_fact_type"] in {"installation", "accessory_usage"}
    assert result["query_fact_type"] != "accessory_availability"


def test_promotion_terms_are_not_misrouted_to_aftersales():
    for message in ("有没有福利", "有什么优惠", "晒图返多少"):
        result = classify_query_fact_type(message, "product_question")
        assert result["query_fact_type"] == "promotion_policy"
        assert result.get("secondary_fact_types", []) == []


def test_aftersales_promotion_multi_intent_keeps_promotion_secondary():
    result = classify_query_fact_type("退货后晒图福利还给吗", "product_question")

    assert result["query_fact_type"] == "aftersales_policy"
    assert "promotion_policy" in result.get("secondary_fact_types", [])


def test_api_exposes_query_fact_type_debug():
    app = create_app()
    client = app.test_client()

    result = client.post("/ask/api/analyze", json={
        "message": "\u6ca1\u6709\u7532\u919b\u7684\u68c0\u67e5\u62a5\u544a\u5417\uff1f",
        "conversation_id": "test_query_fact_type_debug",
        "sku_code": "YH06K53B05S13",
        "product_candidates": [
            {"value": "YH06K53B05S13", "type": "sku_id_candidate", "verified": True},
        ],
    }).get_json()

    debug = result["evidence_debug"]
    assert debug["query_fact_type"] == "certification_report"
    assert debug["query_fact_type_label"]
    assert result["requires_human_review"] is True


def test_api_final_audit_blocks_pinch_as_battery_topic():
    app = create_app()
    client = app.test_client()

    result = client.post("/ask/api/analyze", json={
        "message": "\u5bb6\u91cc\u6709\u4e24\u5c81\u5b9d\u5b9d\uff0c\u8fd9\u4e2a\u4f1a\u4e0d\u4f1a\u5939\u624b\u6216\u8005\u6709\u5b89\u5168\u9690\u60a3\uff1f",
        "product_title": "\u82f1\u79be\u9632\u5939\u6ed1\u95e8\u6536\u7eb3\u67b6\u6574\u7406\u5ba2\u5385\u96f6\u98df\u684c\u9762\u513f\u7ae5\u73a9\u5177\u5367\u5ba4\u53ef\u62fc\u642d\u50a8\u7269\u62bd\u5c49",
        "conversation_id": "test_api_final_audit_pinch_safety",
    }).get_json()

    debug = result["evidence_debug"]
    assert debug["query_fact_type"] == "pinch_safety"
    assert result["final_answer_audit"]["passed"] is False
    assert result["final_answer_audit"]["fallback_used"] is True
    assert "\u5939\u624b" in result["suggested_reply"]
    assert "\u5c0f\u96f6\u4ef6/\u7535\u6c60\u5b89\u5168" not in result["suggested_reply"]


def test_llm_fact_type_classification_can_override_rule_hint(monkeypatch):
    monkeypatch.setattr(semantic_fact_type_service.config, "COPILOT_FACT_TYPE_LLM_ENABLED", True)
    monkeypatch.setattr(
        semantic_fact_type_service,
        "_classify_with_llm",
        lambda state, message, intent: {
            "query_fact_type": "odor",
            "confidence": 0.9,
            "matched_terms": [],
            "source": "llm",
            "reason": "semantic focus is odor",
            "risk_hint": "",
            "secondary_fact_types": ["material"],
        },
    )

    result = semantic_fact_type_service.classify_query_fact_type_llm_first({
        "normalized_message": "\u6750\u8d28\u6709\u6c14\u5473\u5417",
        "intent": "product_question",
    })

    assert result["query_fact_type"] == "odor"
    assert result["source"] == "llm"
    assert result["secondary_fact_types"] == ["material"]


def test_llm_fact_type_space_fit_is_not_overridden_by_rule_hint(monkeypatch):
    monkeypatch.setattr(semantic_fact_type_service.config, "COPILOT_FACT_TYPE_LLM_ENABLED", True)
    monkeypatch.setattr(
        semantic_fact_type_service,
        "_classify_with_llm",
        lambda state, message, intent: {
            "query_fact_type": "space_fit",
            "confidence": 0.92,
            "matched_terms": [],
            "source": "llm",
            "reason": "customer asks whether the room has enough space",
            "risk_hint": "low",
            "secondary_fact_types": ["dimensions"],
        },
    )

    result = semantic_fact_type_service.classify_query_fact_type_llm_first({
        "normalized_message": "\u5367\u5ba4\u653e\u7684\u4e0b\u5417\uff0c\u7a7a\u95f4\u53ef\u80fd\u6bd4\u8f83\u5c0f",
        "intent": "product_question",
    })

    assert result["query_fact_type"] == "space_fit"
    assert result["source"] == "llm"
