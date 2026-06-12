from app.main import create_app
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
        "\u9002\u5408\u591a\u5927\u5b9d\u5b9d\uff1f": "age_range",
        "\u53ef\u4ee5\u5f00\u53d1\u7968\u5417\uff1f": "invoice_policy",
        "\u53ef\u4ee5\u7533\u8bf7\u4ef7\u4fdd\u5417\uff1f": "price_protection",
    }
    for message, expected in cases.items():
        result = classify_query_fact_type(message, "product_question")
        assert result["query_fact_type"] == expected


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
