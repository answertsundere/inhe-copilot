from app.services.no_evidence_reply_policy_service import (
    apply_no_evidence_reply_policy,
    build_no_evidence_reply_policy,
    contains_unsupported_media_promise,
    has_sendable_media_asset,
)


def _policy(**overrides):
    data = {
        "query_fact_type": "installation",
        "turn_actionability": "actionable_question",
        "conversation_type": "mixed",
        "source_page": "order_detail",
        "has_product_context": True,
        "has_order_context": False,
        "has_media_context": True,
        "has_sendable_media_asset": False,
        "missing_reason": "no_approved_usable_media_asset_matched",
        "real_context_summary": {},
    }
    data.update(overrides)
    return build_no_evidence_reply_policy(data)


def test_installation_without_sendable_asset_requires_verified_material_before_send():
    result = _policy(query_fact_type="installation", has_product_context=True, has_sendable_media_asset=False)

    assert result["requires_human_review"] is True
    assert result["reply_strategy"] == "verify_installation_asset_before_send"
    assert "对应安装资料" in result["reply"]
    assert "防止资料和款式不对应" in result["reply"]
    assert "把当前位置拍给我" in result["reply"]
    assert "我把视频发您" not in result["reply"]
    assert "下面发您" not in result["reply"]
    assert "可以发安装视频" not in result["reply"]


def test_installation_with_sendable_asset_can_reference_delivery():
    result = _policy(query_fact_type="installation", has_sendable_media_asset=True)

    assert result["requires_human_review"] is False
    assert result["reply_strategy"] == "send_supported_installation_asset"
    assert "发您参考" in result["reply"]
    assert result["forbidden_claims"] == []


def test_accessory_usage_without_evidence_asks_for_accessory_photo_without_inventing_usage():
    result = _policy(query_fact_type="accessory_usage", has_media_context=False)

    assert result["requires_human_review"] is True
    assert result["reply_strategy"] == "verify_accessory_usage_with_photo"
    assert "配件图确认" in result["reply"]
    assert "配件和说明书位置拍一下" in result["reply"]
    assert "少件或配件不匹配" in result["reply"]


def test_aftersales_mismatch_reply_uses_aftersales_check_action():
    result = _policy(query_fact_type="aftersales", has_media_context=True)

    assert result["requires_human_review"] is True
    assert result["reply_strategy"] == "aftersales_mismatch_check"
    assert "资料和实物可能不一致" in result["reply"]
    assert "售后核对" in result["reply"]
    assert "资料截图和实物照片" in result["reply"]


def test_promotion_without_evidence_checks_activity_rules_not_product_detail():
    result = _policy(query_fact_type="promotion", has_product_context=True, has_media_context=False)

    assert result["requires_human_review"] is True
    assert result["reply_strategy"] == "verify_current_activity_rule"
    assert "活动/福利" in result["reply"]
    assert "下单时间和页面规则" in result["reply"]
    assert "商品详情需要确认" not in result["reply"]
    assert "内部价" not in result["reply"]


def test_dimensions_with_known_product_context_does_not_request_product_link_again():
    result = _policy(query_fact_type="dimensions", has_product_context=True)

    assert result["requires_human_review"] is True
    assert result["reply_strategy"] == "verify_dimensions_for_known_product"
    assert "已经看到当前商品信息" in result["reply"]
    assert "尺寸图/商品资料" in result["reply"]
    assert "商品链接" not in result["reply"]
    assert "SKU" not in result["reply"]


def test_space_fit_with_known_product_context_mentions_reserved_space():
    result = _policy(query_fact_type="space_fit", has_product_context=True)

    assert result["requires_human_review"] is True
    assert result["reply_strategy"] == "verify_space_fit_for_known_product"
    assert "放得下" in result["reply"]
    assert "预留位置" in result["reply"]
    assert "宽度、进深、高度" in result["reply"]
    assert "商品链接" not in result["reply"]


def test_dimensions_without_product_context_can_request_minimal_product_identity():
    result = _policy(query_fact_type="dimensions", has_product_context=False)

    assert result["requires_human_review"] is True
    assert result["reply_strategy"] == "request_product_context_for_dimensions"
    assert "商品链接" in result["reply"]
    assert "SKU" in result["reply"]


def test_deictic_followup_asks_for_position_without_expanding_product_facts():
    result = _policy(
        query_fact_type="",
        turn_actionability="deictic_followup",
        has_product_context=True,
        has_media_context=False,
        missing_reason="context_insufficient",
    )

    assert result["requires_human_review"] is False
    assert result["needs_followup"] is True
    assert result["reply_strategy"] == "clarify_context"
    assert "对应位置圈一下" in result["reply"]
    assert "商品链接" not in result["reply"]
    assert "SKU" not in result["reply"]
    assert "尺寸" not in result["reply"]
    assert "材质" not in result["reply"]
    assert "承重" not in result["reply"]


def test_media_promise_gate_uses_actual_sendable_status():
    assert contains_unsupported_media_promise("亲，我把视频发您参考。", False) is True
    assert contains_unsupported_media_promise("亲，我把视频发您参考。", True) is False
    assert has_sendable_media_asset({"recommended_assets": [{"asset_url": "https://asset.example/video.mp4", "auto_send_level": "auto"}]}) is True
    assert has_sendable_media_asset({"recommended_assets": [{"asset_url": "https://asset.example/video.mp4", "auto_send_level": "review"}]}) is False


def test_apply_policy_replaces_unsupported_media_promise_after_rewrite():
    response = {
        "suggested_reply": "亲，我把视频发您参考，您先看一下。",
        "query_fact_type": "installation",
        "evidence_debug": {"query_fact_type": "installation", "selected_evidence": []},
        "recommended_assets": [],
    }
    context = {
        "turn_understanding": {"turn_actionability": "actionable_question", "query_fact_type": "installation"},
        "real_context_summary": {"has_product_context": True, "has_media_context": True},
    }

    result = apply_no_evidence_reply_policy(response, context)

    assert result["requires_human_review"] is True
    assert result["generation_mode"] == "no_evidence_reply_policy"
    assert "对应安装资料" in result["suggested_reply"]
    assert "我把视频发您" not in result["suggested_reply"]
    assert "发您参考" not in result["suggested_reply"]


def test_installation_media_request_without_sendable_asset_applies_even_with_selected_evidence():
    response = {
        "suggested_reply": "亲～这个问题我先帮您按这款商品核对一下，您稍等一下，我这边确认后再回复您。",
        "query_fact_type": "installation",
        "customer_message": "麻烦发下安装资料",
        "evidence_debug": {"selected_evidence": [{"fact_type": "installation", "content": "暂无安装视频"}]},
        "recommended_assets": [],
    }
    context = {
        "turn_understanding": {"turn_actionability": "actionable_question", "query_fact_type": "installation"},
        "real_context_summary": {"has_product_context": True, "has_media_context": False},
    }

    result = apply_no_evidence_reply_policy(response, context)

    assert result["generation_mode"] == "no_evidence_reply_policy"
    assert result["requires_human_review"] is True
    assert result["answer_trace"]["no_evidence_reply_policy"]["reply_strategy"] == "verify_installation_asset_before_send"
    assert "按这款商品核对一下" not in result["suggested_reply"]
    assert "确认后再回复" not in result["suggested_reply"]


def test_aftersales_mismatch_request_applies_even_with_selected_evidence():
    response = {
        "suggested_reply": "亲～这个问题我先帮您按这款商品核对一下，您稍等一下，我这边确认后再回复您。",
        "query_fact_type": "aftersales",
        "customer_message": "资料和实物不一致",
        "evidence_debug": {"selected_evidence": [{"fact_type": "installation", "content": "安装资料"}]},
    }
    context = {
        "turn_understanding": {"turn_actionability": "actionable_question", "query_fact_type": "aftersales"},
        "real_context_summary": {"has_product_context": True, "has_media_context": True},
    }

    result = apply_no_evidence_reply_policy(response, context)

    assert result["generation_mode"] == "no_evidence_reply_policy"
    assert result["answer_trace"]["no_evidence_reply_policy"]["reply_strategy"] == "aftersales_mismatch_check"
    assert "按这款商品核对一下" not in result["suggested_reply"]


def test_final_fallback_policy_recovers_order_context_from_response():
    response = {
        "suggested_reply": "亲～这款商品这个问题我先帮您按这款商品核对一下，您稍等一下，我这边确认后再回复您。",
        "query_fact_type": "installation",
        "evidence_debug": {"query_fact_type": "installation", "selected_evidence": []},
        "real_context": {"has_order_context": True, "has_product_context": False, "has_media_context": True},
        "recommended_assets": [],
    }

    result = apply_no_evidence_reply_policy(response, None)

    assert result["generation_mode"] == "no_evidence_reply_policy"
    assert result["answer_trace"]["no_evidence_reply_policy"]["reply_strategy"] == "verify_installation_asset_before_send"
    assert "商品链接" not in result["suggested_reply"]
