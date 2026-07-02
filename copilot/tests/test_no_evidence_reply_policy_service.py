from app.services.no_evidence_reply_policy_service import (
    apply_no_evidence_reply_policy,
    build_no_evidence_reply_policy,
    contains_unsupported_media_promise,
    get_sendable_media_asset_types,
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


def test_installation_with_diagram_but_no_video_uses_diagram_reply():
    result = _policy(
        query_fact_type="installation",
        has_sendable_media_asset=True,
        sendable_media_asset_types=["install_image"],
    )

    assert result["requires_human_review"] is False
    assert result["reply_strategy"] == "send_installation_diagram_without_video"
    assert "当前这款商品" in result["reply"]
    assert "暂时没有可直接发送的安装视频" in result["reply"]
    assert "安装示意图" in result["reply"]
    assert "拍一下当前安装位置" in result["reply"]
    assert "安装视频/说明书" not in result["reply"]


def test_installation_video_request_with_only_diagram_requires_handoff():
    result = _policy(
        query_fact_type="installation",
        has_sendable_media_asset=True,
        sendable_media_asset_types=["install_image"],
        customer_message="\u6709\u7ec4\u88c5\u89c6\u9891\u5417",
    )

    assert result["requires_human_review"] is True
    assert result["reply_strategy"] == "review_installation_diagram_without_video"
    assert "\u5f53\u524d\u8fd9\u6b3e\u5546\u54c1" in result["reply"]
    assert "\u4e0d\u76f4\u63a5\u627f\u8bfa\u6709\u5b89\u88c5\u89c6\u9891" in result["reply"]
    assert "\u8f6c\u4eba\u5de5" in result["reply"]


def test_installation_tutorial_request_with_only_diagram_requires_handoff():
    result = _policy(
        query_fact_type="installation",
        has_sendable_media_asset=True,
        sendable_media_asset_types=["install_image"],
        customer_message="\u4f60\u597d \u6709\u5b89\u88c5\u6559\u7a0b\u5417",
    )

    assert result["requires_human_review"] is True
    assert result["reply_strategy"] == "review_installation_diagram_without_video"
    assert "\u4e0d\u76f4\u63a5\u627f\u8bfa\u6709\u5b89\u88c5\u89c6\u9891" in result["reply"]


def test_apply_policy_rewrites_video_request_when_only_diagram_is_available():
    response = {
        "suggested_reply": "\u4eb2\uff0c\u6211\u5148\u628a\u5b89\u88c5\u56fe\u53d1\u60a8\u53c2\u8003\u3002",
        "query_fact_type": "installation",
        "requires_human_review": False,
        "evidence_debug": {
            "query_fact_type": "installation",
            "selected_evidence": [{"fact_type": "installation"}],
            "semantic_query": {"current_query": "\u6709\u7ec4\u88c5\u89c6\u9891\u5417"},
        },
        "recommended_assets": [{
            "asset_type": "install_image",
            "asset_url": "https://asset.example/install.png",
            "auto_send_level": "auto",
        }],
    }
    context = {
        "turn_understanding": {"turn_actionability": "actionable_question", "query_fact_type": "installation"},
        "product_name": "demo product",
    }

    result = apply_no_evidence_reply_policy(response, context)

    assert result["requires_human_review"] is True
    assert result["generation_mode"] == "no_evidence_reply_policy"
    assert result["answer_trace"]["no_evidence_reply_policy"]["reply_strategy"] == "review_installation_diagram_without_video"
    assert "\u8f6c\u4eba\u5de5" in result["suggested_reply"]


def test_installation_video_promise_is_rewritten_when_only_diagram_is_sendable():
    response = {
        "suggested_reply": "亲，我把安装视频发您参考，您先看一下。",
        "query_fact_type": "installation",
        "evidence_debug": {"query_fact_type": "installation", "selected_evidence": []},
        "recommended_assets": [{
            "asset_type": "install_image",
            "asset_url": "https://asset.example/install.png",
            "auto_send_level": "auto",
        }],
    }
    context = {
        "turn_understanding": {"turn_actionability": "actionable_question", "query_fact_type": "installation"},
        "real_context_summary": {"has_product_context": True, "has_media_context": True},
    }

    result = apply_no_evidence_reply_policy(response, context)

    assert result["generation_mode"] == "no_evidence_reply_policy"
    assert result["requires_human_review"] is False
    assert result["answer_trace"]["no_evidence_reply_policy"]["reply_strategy"] == "send_installation_diagram_without_video"
    assert "暂时没有可直接发送的安装视频" in result["suggested_reply"]
    assert "我把安装视频发您" not in result["suggested_reply"]


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
    assert "先别着急" in result["reply"]
    assert "当前订单" in result["reply"]
    assert "售后问题" in result["reply"]
    assert "资料截图" in result["reply"]
    assert "问题位置" in result["reply"]
    assert "实物照片" in result["reply"]
    assert "转人工" in result["reply"]
    assert "直接退款" not in result["reply"]
    assert "直接补发" not in result["reply"]


def test_promotion_without_evidence_checks_activity_rules_not_product_detail():
    result = _policy(query_fact_type='promotion', has_product_context=True, has_media_context=False)

    assert result['requires_human_review'] is True
    assert result['reply_strategy'] == 'verify_current_activity_rule'
    assert '优惠券' in result['reply']
    assert '满减' in result['reply']
    assert '下单页面' in result['reply']
    assert '商品详情需要确认' not in result['reply']
    assert '内部价' not in result['reply']


def test_price_negotiation_without_evidence_uses_activity_rule_handoff():
    for fact_type in ('promotion_policy', 'price_negotiation'):
        result = _policy(query_fact_type=fact_type, has_product_context=True, has_media_context=False)
        assert result['requires_human_review'] is True
        assert result['reply_strategy'] == 'verify_current_activity_rule'
        assert '优惠券' in result['reply']
        assert '下单页面' in result['reply']
        assert '内部价' not in result['reply']


def test_dimensions_with_known_product_context_does_not_request_product_link_again():
    result = _policy(query_fact_type="dimensions", has_product_context=True)

    assert result["requires_human_review"] is True
    assert result["reply_strategy"] == "verify_dimensions_for_known_product"
    assert "已经看到当前商品信息" in result["reply"]
    assert "尺寸图/商品资料" in result["reply"]
    assert "商品链接" not in result["reply"]
    assert "SKU" not in result["reply"]


def test_placement_scene_without_evidence_uses_manual_verification():
    result = _policy(query_fact_type='placement_scene', has_product_context=True, has_media_context=False)

    assert result['requires_human_review'] is True
    assert result['reply_strategy'] == 'verify_placement_scene_for_known_product'
    assert '床垫厚度' in result['reply']
    assert '特殊床架' in result['reply']
    assert '拍一下床边位置' in result['reply']


def test_unsupported_media_promise_with_real_chinese_terms_is_rewritten():
    response = {
        "suggested_reply": "亲～具体尺寸建议参考下面发您的商品图/尺寸图。",
        "query_fact_type": "dimensions",
        "requires_human_review": False,
        "evidence_debug": {"query_fact_type": "dimensions", "selected_evidence": []},
        "answer_trace": {"query_fact_type": "dimensions", "required_fact_types": ["dimensions"]},
        "recommended_assets": [],
    }
    context = {
        "turn_understanding": {
            "turn_actionability": "actionable_question",
            "query_fact_type": "dimensions",
        },
        "product_name": "demo product",
        "media_context": {},
    }

    result = apply_no_evidence_reply_policy(response, context)

    assert result["requires_human_review"] is True
    assert result["generation_mode"] == "no_evidence_reply_policy"
    assert "下面发您" not in result["suggested_reply"]
    assert "商品图/尺寸图" not in result["suggested_reply"]
    assert result["answer_trace"]["no_evidence_reply_policy"]["reply_strategy"] == "verify_dimensions_for_known_product"


def test_gross_weight_with_known_product_context_does_not_answer_dimensions_or_capacity():
    result = _policy(query_fact_type="gross_weight", has_product_context=True)

    assert result["requires_human_review"] is True
    assert result["reply_strategy"] == "verify_gross_weight_for_known_product"
    assert "\u6bdb\u91cd" in result["reply"]
    assert "\u5305\u88c5\u91cd\u91cf" in result["reply"]
    assert "\u5c3a\u5bf8" not in result["reply"]
    assert "\u627f\u91cd" not in result["reply"]
    assert "\u5546\u54c1\u94fe\u63a5" not in result["reply"]


def test_accessory_availability_with_known_product_context_does_not_answer_installation():
    result = _policy(query_fact_type="accessory_availability", has_product_context=True)

    assert result["requires_human_review"] is True
    assert result["reply_strategy"] == "verify_accessory_availability_for_known_product"
    assert "\u914d\u4ef6" in result["reply"]
    assert any(term in result["reply"] for term in ("\u5355\u72ec", "\u8865\u4e70", "\u552e\u5356"))
    assert "\u5b89\u88c5\u8d44\u6599" not in result["reply"]
    assert "\u600e\u4e48\u88c5" not in result["reply"]
    assert "\u5546\u54c1\u94fe\u63a5" not in result["reply"]


def test_space_fit_with_known_product_context_mentions_reserved_space():
    result = _policy(query_fact_type='space_fit', has_product_context=True)

    assert result['requires_human_review'] is True
    assert result['reply_strategy'] == 'verify_space_fit_for_known_product'
    assert '能不能放下' in result['reply']
    assert '预留位置' in result['reply']
    assert '长、宽、高' in result['reply']
    assert '商品链接' not in result['reply']


def test_space_fit_with_sendable_media_asset_can_reference_delivery():
    result = _policy(
        query_fact_type="space_fit",
        has_product_context=True,
        has_sendable_media_asset=True,
        sendable_media_asset_types=["size_chart"],
    )

    assert result["requires_human_review"] is False
    assert result["reply_strategy"] == "send_supported_space_fit_asset"
    assert result["reason"] == "sendable_media_asset_available"


def test_space_fit_with_non_size_media_asset_stays_human_review():
    result = _policy(
        query_fact_type="space_fit",
        has_product_context=True,
        has_sendable_media_asset=True,
        sendable_media_asset_types=["product_photo"],
    )

    assert result["requires_human_review"] is True
    assert result["reply_strategy"] == "verify_space_fit_for_known_product"
    assert result["reason"] == "no_approved_usable_media_asset_matched"
    assert "预留位置" in result["reply"]


def test_structure_function_with_known_product_context_safe_handoff():
    result = _policy(query_fact_type="structure_function", has_product_context=True)

    assert result["requires_human_review"] is True
    assert result["reply_strategy"] == "verify_structure_function_for_known_product"
    assert "结构" in result["reply"]
    assert "配件规格" in result["reply"]
    assert "补配" in result["reply"] or "加装" in result["reply"]
    assert "是否可补、是否适配" in result["reply"]
    assert "卧室" not in result["reply"]
    assert "客厅" not in result["reply"]
    assert "预留位置" not in result["reply"]


def test_damaged_aftersales_with_order_context_asks_for_damage_photos_not_product_link():
    result = _policy(
        query_fact_type="aftersales",
        has_product_context=True,
        has_order_context=True,
        customer_message="板子裂了",
    )

    assert result["requires_human_review"] is True
    assert result["reply_strategy"] == "aftersales_damaged_item_check"
    assert "先别着急" in result["reply"]
    assert "当前订单" in result["reply"]
    assert "问题位置" in result["reply"]
    assert "外包装" in result["reply"]
    assert "转人工核实" in result["reply"]
    assert "处理方案" in result["reply"]
    assert "直接补发" not in result["reply"]
    assert "直接退款" not in result["reply"]
    assert "商品链接" not in result["reply"]


def test_damaged_aftersales_without_context_requests_order_or_product_info():
    result = _policy(
        query_fact_type="aftersales",
        has_product_context=False,
        has_order_context=False,
        customer_message="配件坏了怎么办",
    )

    assert result["requires_human_review"] is True
    assert result["reply_strategy"] == "request_context_for_damaged_aftersales"
    assert "先别着急" in result["reply"]
    assert "订单" in result["reply"]
    assert "商品" in result["reply"]
    assert "问题位置" in result["reply"]
    assert "转人工核实" in result["reply"]


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


def test_sendable_media_asset_types_reads_installation_image_assets():
    assert get_sendable_media_asset_types({
        "recommended_assets": [{
            "asset_type": "install_image",
            "asset_url": "https://asset.example/install.png",
            "auto_send_level": "auto",
        }]
    }) == {"install_image"}


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


def test_gold_installation_diagram_reply_matches_supervisor_wording():
    result = _policy(
        query_fact_type="installation",
        has_sendable_media_asset=True,
        sendable_media_asset_types=["install_image"],
    )

    assert result["requires_human_review"] is False
    assert result["reply_strategy"] == "send_installation_diagram_without_video"
    assert "暂时没有可直接发送的安装视频" in result["reply"]
    assert "安装示意图/说明书" in result["reply"]
    assert "对照图纸" in result["reply"]


def test_gold_stability_reply_for_fixed_or_load_capacity_questions():
    result = _policy(query_fact_type="load_capacity", has_product_context=True)

    assert result["requires_human_review"] is True
    assert result["reply_strategy"] == "verify_stability_or_load_capacity"
    assert "按说明书安装" in result["reply"]
    assert "防倒件" in result["reply"]
    assert "商品截图" in result["reply"]


def test_gold_internal_space_reply_for_inside_space_question():
    result = _policy(
        query_fact_type="dimensions",
        has_product_context=True,
        customer_message="这里面是什么样的空间？",
    )

    assert result["requires_human_review"] is True
    assert result["reply_strategy"] == "verify_dimensions_for_known_product"
    assert "内部空间" in result["reply"]
    assert "玩具" in result["reply"]
    assert "衣服" in result["reply"]


def test_gold_structure_function_reply_for_left_right_installation():
    result = _policy(query_fact_type="structure_function", has_product_context=True)

    assert result["requires_human_review"] is True
    assert result["reply_strategy"] == "verify_structure_function_for_known_product"
    assert "孔位" in result["reply"]
    assert "说明书" in result["reply"]
    assert "侧板/护栏/挡板" in result["reply"]
    assert "避免装错方向" in result["reply"]


def test_gold_promotion_reply_mentions_coupon_and_activity_boundary():
    result = _policy(query_fact_type="promotion", has_product_context=True)

    assert result["requires_human_review"] is True
    assert result["reply_strategy"] == "verify_current_activity_rule"
    assert "优惠券" in result["reply"]
    assert "满减" in result["reply"]
    assert "下单页面" in result["reply"]


def test_gold_bed_fit_reply_mentions_mattress_and_photo_check():
    result = _policy(query_fact_type="placement_scene", has_product_context=True)

    assert result["requires_human_review"] is True
    assert result["reply_strategy"] == "verify_placement_scene_for_known_product"
    assert "床垫厚度" in result["reply"]
    assert "特殊床架" in result["reply"]
    assert "拍一下床边位置" in result["reply"]
