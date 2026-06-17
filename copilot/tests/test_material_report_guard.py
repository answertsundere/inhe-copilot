from app.main import create_app


SKU = "YH06K53B05S13"


def _post(message: str) -> dict:
    app = create_app()
    client = app.test_client()
    return client.post("/ask/api/analyze", json={
        "message": message,
        "conversation_id": f"test_material_report_guard_{hash(message) & 0xFFFFFFFF}",
        "sku_code": SKU,
        "product_candidates": [
            {"value": SKU, "type": "sku_id_candidate", "verified": True},
        ],
        "copilot_context": {
            "product_candidates": [
                {"value": SKU, "type": "sku_id_candidate", "verified": True},
            ],
        },
    }).get_json()


def test_material_safety_uses_verified_material_evidence_when_sku_is_known():
    result = _post("\u8fd9\u4e2a\u6750\u8d28\u5b89\u5168\u5417\uff1f\u4f1a\u4e0d\u4f1a\u5bb9\u6613\u53d7\u6f6e\uff1f")

    reply = result["suggested_reply"]
    assert result["intent"] == "material_safety"
    assert result["requires_human_review"] is True
    assert "\u51b7\u8f67\u94a2\u7ba1" in reply
    assert "\u73af\u4fddPP" in reply
    assert "\u65e0\u7eba\u5e03" in reply


def test_formaldehyde_report_query_does_not_use_unrelated_faq():
    result = _post("\u6ca1\u6709\u7532\u919b\u7684\u68c0\u67e5\u62a5\u544a\u5417\uff1f")

    reply = result["suggested_reply"]
    assert result["intent"] == "material_safety"
    assert result["requires_human_review"] is True
    assert "\u7532\u919b" in reply
    assert "\u68c0\u6d4b\u62a5\u544a" in reply or "\u68c0\u67e5\u62a5\u544a" in reply
    assert "\u627f\u91cd" not in reply
    assert "15-30kg" not in reply
    assert "\u52a0\u7c97\u94a2\u7ba1" not in reply
