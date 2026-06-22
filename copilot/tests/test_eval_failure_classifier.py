from app.services.eval_failure_classifier import classify_eval_failure


def test_wrong_tool_called_maps_to_tool_policy():
    result = classify_eval_failure(
        {"case_uid": "c1"},
        {"evidence_debug": {"tool_policy_trace": {"allowed_tools": ["jst_lookup_order_tool"]}}},
        "must_not_call_tools",
        "jst_lookup_order_tool",
        ["jst_lookup_order_tool"],
    )

    assert result["failure_type"] == "wrong_tool_called"
    assert result["suggested_fix_area"] == "tool_policy"
    assert any(path.endswith("tool_policy_gate.py") for path in result["suggested_files"])


def test_internal_term_leak_maps_to_semantic_compiler():
    result = classify_eval_failure(
        {"case_uid": "c2"},
        {"suggested_reply": "内部 RAG 命中"},
        "must_not_contain",
        "RAG",
        "RAG",
    )

    assert result["failure_type"] == "internal_term_leak"
    assert result["suggested_fix_area"] == "semantic_compiler"


def test_missing_evidence_maps_to_product_or_media_data():
    product = classify_eval_failure({"case_uid": "c3"}, {"evidence_debug": {}}, "must_have_evidence_type", "rag", {})
    media = classify_eval_failure(
        {"case_uid": "c4"},
        {"evidence_debug": {"needs_visual_asset": True}},
        "must_have_evidence_type",
        "media",
        {},
    )

    assert product["failure_type"] == "missing_evidence"
    assert product["suggested_fix_area"] == "product_card_data"
    assert media["suggested_fix_area"] == "media_asset_data"
