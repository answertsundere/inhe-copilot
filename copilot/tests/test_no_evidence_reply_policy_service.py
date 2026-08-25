from app.services.no_evidence_reply_policy_service import (
    apply_no_evidence_reply_policy,
    build_no_evidence_reply_policy,
    contains_unsupported_media_promise,
    get_sendable_media_asset_types,
    has_attached_sendable_media_asset,
    has_sendable_media_asset,
    media_delivery_claim_issues,
    should_apply_no_evidence_policy,
)
from app.services.customer_facing_safe_handoff_service import CUSTOMER_FACING_INTERNAL_REDLINE_TERMS


def _assert_customer_facing_safe_handoff(reply: str):
    for term in CUSTOMER_FACING_INTERNAL_REDLINE_TERMS:
        assert term not in reply
    assert "核对" in reply or "核实" in reply
    assert "准确回复" in reply or "处理方案" in reply or "为准" in reply


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
    assert "安装资料" in result["reply"]
    assert "核对" in result["reply"]
    assert "当前位置拍给我" in result["reply"]
    assert "准确回复" in result["reply"]
    _assert_customer_facing_safe_handoff(result["reply"])
    assert "我把视频发您" not in result["reply"]
    assert "下面发您" not in result["reply"]
    assert "可以发安装视频" not in result["reply"]


def test_order_identifier_from_graph_prevents_reasking_for_order_context():
    response = {
        "suggested_reply": "亲，麻烦您发一下商品链接、订单截图或款式图，我帮您核对对应安装资料。",
        "query_fact_type": "installation",
        "requires_human_review": True,
        "evidence_debug": {
            "query_fact_type": "installation",
            "order_product_identity": {
                "status": "not_found",
                "identifier": "opaque-order-identifier",
                "identifier_type": "unknown_identifier",
            },
        },
        "recommended_assets": [],
        "reply_blocks": [],
    }

    updated = apply_no_evidence_reply_policy(response, {"current_query": "如何安装"})

    inputs = updated["evidence_debug"]["no_evidence_reply_policy_inputs"]
    assert inputs["has_order_context"] is True
    assert inputs["order_lookup_status"] == "not_found"
    assert updated["answer_trace"]["no_evidence_reply_policy"]["reply_strategy"] == "verify_installation_asset_before_send"
    assert "订单截图" not in updated["suggested_reply"]
    assert updated["requires_human_review"] is True
    assert updated.get("can_send") is not True


def test_no_evidence_policy_clears_stale_direct_answer_diagnostics():
    response = {
        "suggested_reply": "The material is PP.",
        "query_fact_type": "cleaning_care",
        "requires_human_review": False,
        "evidence_debug": {
            "query_fact_type": "cleaning_care",
            "selected_evidence": [{"fact_type": "material", "attribute_key": "material"}],
            "evidence_sufficient": True,
            "direct_answer_supported": True,
            "answer_relevance_passed": True,
        },
    }
    context = {
        "turn_understanding": {
            "turn_actionability": "actionable_question",
            "query_fact_type": "cleaning_care",
        },
        "product_name": "demo product",
    }

    updated = apply_no_evidence_reply_policy(response, context)

    assert updated["generation_mode"] == "no_evidence_reply_policy"
    assert updated["requires_human_review"] is True
    assert updated["evidence_debug"]["evidence_sufficient"] is False
    assert updated["evidence_debug"]["direct_answer_supported"] is False
    assert updated["evidence_debug"]["answer_relevance_passed"] is False


def test_installation_with_sendable_asset_can_reference_delivery():
    result = _policy(
        query_fact_type="installation",
        has_sendable_media_asset=True,
        sendable_media_asset_types=["install_video"],
    )

    assert result["requires_human_review"] is False
    assert result["reply_strategy"] == "send_supported_installation_asset"
    assert "发您参考" in result["reply"]
    assert result["forbidden_claims"] == []


def test_installation_with_non_install_media_asset_requires_review():
    result = _policy(
        query_fact_type="installation",
        has_sendable_media_asset=True,
        sendable_media_asset_types=["sku_image"],
    )

    assert result["requires_human_review"] is True
    assert result["reply_strategy"] == "verify_installation_asset_before_send"
    assert result["reason"]


def test_unsupported_installation_wall_fix_reply_is_rewritten_without_fact_type():
    response = {
        "suggested_reply": (
            "\u4eb2\uff5e\u60a8\u770b\u5230\u7684\u87ba\u4e1d\u5b54\u662f\u7528\u6765\u56fa\u5b9a\u4e66\u67b6\u5230\u5899\u4e0a\u7684\uff0c"
            "\u9632\u6b62\u503e\u5012\u3002\u5982\u679c\u5e8a\u57ab\u8584\u538b\u4e0d\u4f4f\uff0c"
            "\u5efa\u8bae\u7528\u87ba\u4e1d\u5b54\u6253\u5899\u56fa\u5b9a\u4f1a\u66f4\u5b89\u5168\u3002"
        ),
        "requires_human_review": True,
        "reply_blocks": [],
        "recommended_assets": [],
    }

    updated = apply_no_evidence_reply_policy(
        response,
        {"current_query": "\u6211\u770b\u5230\u4e0b\u9762\u662f\u6709\u87ba\u4e1d\u5b54\u7684"},
    )

    assert updated["generation_mode"] == "no_evidence_reply_policy"
    assert updated["query_fact_type"] == "installation"
    assert updated["requires_human_review"] is True
    if "sendable_reply" in updated:
        assert updated["sendable_reply"] == ""
    assert "\u81a8\u80c0\u87ba\u4e1d" not in updated["suggested_reply"]
    assert "\u6253\u5899\u56fa\u5b9a" not in updated["suggested_reply"]
    assert "\u9632\u6b62\u503e\u5012" not in updated["suggested_reply"]
    assert "\u5b89\u88c5\u8d44\u6599" in updated["suggested_reply"]
    assert "\u6838\u5bf9" in updated["suggested_reply"]


def test_supported_installation_image_block_is_not_rewritten_as_no_evidence():
    response = {
        "suggested_reply": (
            "\u4eb2\uff0c\u8fd9\u5f20\u5b89\u88c5\u56fe\u4e0a\u6807\u7684\u4f4d\u7f6e\u662f\u56fa\u5b9a\u7528\u7684\uff0c"
            "\u60a8\u53ef\u4ee5\u5148\u5bf9\u7167\u56fe\u4e0a\u87ba\u4e1d\u5b54\u4f4d\u770b\u4e00\u4e0b\u3002"
        ),
        "requires_human_review": False,
        "reply_blocks": [{
            "type": "image",
            "asset_type": "pack_guide_image",
            "asset_url": "https://asset.example/install.png",
        }],
        "recommended_assets": [],
    }

    updated = apply_no_evidence_reply_policy(
        response,
        {"current_query": "\u6211\u770b\u5230\u4e0b\u9762\u662f\u6709\u87ba\u4e1d\u5b54\u7684"},
    )

    assert updated.get("generation_mode") != "no_evidence_reply_policy"
    assert updated["suggested_reply"] == response["suggested_reply"]


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
    assert "\u8fd9\u6b3e\u5546\u54c1" in result["reply"]
    assert "\u5b89\u88c5\u8d44\u6599" in result["reply"]
    assert "\u51c6\u786e\u56de\u590d" in result["reply"]
    _assert_customer_facing_safe_handoff(result["reply"])


def test_installation_tutorial_request_with_only_diagram_requires_handoff():
    result = _policy(
        query_fact_type="installation",
        has_sendable_media_asset=True,
        sendable_media_asset_types=["install_image"],
        customer_message="\u4f60\u597d \u6709\u5b89\u88c5\u6559\u7a0b\u5417",
    )

    assert result["requires_human_review"] is True
    assert result["reply_strategy"] == "review_installation_diagram_without_video"
    assert "\u5b89\u88c5\u8d44\u6599" in result["reply"]
    _assert_customer_facing_safe_handoff(result["reply"])


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
    assert result["answer_trace"]["no_evidence_reply_policy"]["reply_strategy"] == "verify_installation_asset_before_send"
    assert "\u5b89\u88c5\u8d44\u6599" in result["suggested_reply"]
    _assert_customer_facing_safe_handoff(result["suggested_reply"])


def test_installation_video_promise_with_unattached_diagram_requires_handoff():
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
    assert result["requires_human_review"] is True
    assert result["answer_trace"]["no_evidence_reply_policy"]["reply_strategy"] == "verify_installation_asset_before_send"
    assert "安装资料" in result["suggested_reply"]
    assert "准确回复" in result["suggested_reply"]
    _assert_customer_facing_safe_handoff(result["suggested_reply"])
    assert "我把安装视频发您" not in result["suggested_reply"]


def test_installation_context_pack_media_count_without_reply_block_requires_handoff():
    response = {
        "suggested_reply": "亲，我先把安装示意图/说明书发您参考。",
        "query_fact_type": "installation",
        "evidence_debug": {
            "query_fact_type": "installation",
            "selected_evidence": [{"fact_type": "installation"}],
        },
        "context_used": {
            "product_context_pack": {
                "stats": {"sendable_media_asset_count": 1},
                "recommended_assets": [{
                    "asset_type": "install_image",
                    "asset_url": "https://asset.example/install.png",
                    "auto_send_level": "auto",
                }],
            },
        },
    }
    context = {
        "turn_understanding": {"turn_actionability": "actionable_question", "query_fact_type": "installation"},
        "real_context_summary": {"has_product_context": True, "has_media_context": True},
    }

    result = apply_no_evidence_reply_policy(response, context)

    assert result["requires_human_review"] is True
    assert result["answer_trace"]["no_evidence_reply_policy"]["reply_strategy"] == "verify_installation_asset_before_send"
    assert "安装资料" in result["suggested_reply"]
    _assert_customer_facing_safe_handoff(result["suggested_reply"])


def test_installation_attached_diagram_block_can_send_diagram_reply():
    response = {
        "suggested_reply": "亲，我把安装视频发您参考，您先看一下。",
        "query_fact_type": "installation",
        "evidence_debug": {
            "query_fact_type": "installation",
            "selected_evidence": [{"fact_type": "installation"}],
        },
        "reply_blocks": [
            {"type": "text", "content": "亲，我先把安装示意图发您参考。"},
            {
                "type": "image",
                "asset_type": "install_image",
                "url": "https://asset.example/install.png",
                "send_mode": "auto_when_platform_connected",
            },
        ],
    }
    context = {
        "turn_understanding": {"turn_actionability": "actionable_question", "query_fact_type": "installation"},
        "real_context_summary": {"has_product_context": True, "has_media_context": True},
    }

    result = apply_no_evidence_reply_policy(response, context)

    assert result["requires_human_review"] is False
    assert result["answer_trace"]["no_evidence_reply_policy"]["reply_strategy"] == "send_installation_diagram_without_video"


def test_accessory_usage_without_evidence_asks_for_accessory_photo_without_inventing_usage():
    result = _policy(query_fact_type="accessory_usage", has_media_context=False)

    assert result["requires_human_review"] is True
    assert result["reply_strategy"] == "verify_accessory_usage_with_photo"
    assert "结构" in result["reply"]
    assert "配件规格" in result["reply"]
    assert "说明书" in result["reply"]
    assert "准确回复" in result["reply"]
    _assert_customer_facing_safe_handoff(result["reply"])


def test_aftersales_mismatch_reply_uses_aftersales_check_action():
    result = _policy(query_fact_type="aftersales", has_media_context=True)

    assert result["requires_human_review"] is True
    assert result["reply_strategy"] == "aftersales_mismatch_check"
    assert "先别着急" in result["reply"]
    assert "当前订单" in result["reply"]
    assert "售后问题" in result["reply"]
    assert "相关说明页" in result["reply"]
    assert "问题位置" in result["reply"]


def test_return_pickup_without_evidence_requires_order_aftersales_check():
    result = _policy(
        query_fact_type="return_pickup",
        has_product_context=True,
        has_order_context=False,
        customer_message="\u4e3a\u4ec0\u4e48\u6ca1\u6709\u4e0a\u95e8\u53d6\u4ef6",
    )

    assert result["requires_human_review"] is True
    assert result["reply_strategy"] == "return_pickup_check"
    assert result["needs_followup"] is True
    assert "\u552e\u540e\u5355" in result["reply"]
    assert "\u53d6\u4ef6\u65b9\u5f0f" in result["reply"]
    assert "\u8ba2\u5355" in result["reply"]
    assert "\u4e0b\u4e00\u6b65\u5904\u7406\u65b9\u6848" in result["reply"]
    for forbidden in ("\u4e00\u5b9a\u4f1a\u4e0a\u95e8\u53d6\u4ef6", "\u9a6c\u4e0a\u4e0a\u95e8\u53d6\u4ef6", "\u7acb\u5373\u9000\u6b3e", "\u76f4\u63a5\u8865\u53d1", "\u4e00\u5b9a\u8d54\u4ed8"):
        assert forbidden not in result["reply"]
    _assert_customer_facing_safe_handoff(result["reply"])


def test_return_pickup_with_order_context_still_requires_human_review_without_promise():
    result = _policy(
        query_fact_type="return_pickup",
        has_product_context=True,
        has_order_context=True,
        customer_message="\u5feb\u9012\u63fd\u6536\u600e\u4e48\u8fd8\u6ca1\u6765",
    )

    assert result["requires_human_review"] is True
    assert result["reply_strategy"] == "return_pickup_check"
    assert result["needs_followup"] is False
    assert "\u5f53\u524d\u8ba2\u5355" in result["reply"]
    assert "\u5feb\u9012\u63fd\u6536" in result["reply"]
    assert "\u60a8\u628a\u8ba2\u5355" not in result["reply"]
    assert "\u4e00\u5b9a\u4f1a\u4e0a\u95e8\u53d6\u4ef6" not in result["reply"]
    assert "处理方案" in result["reply"]
    _assert_customer_facing_safe_handoff(result["reply"])
    assert "直接退款" not in result["reply"]
    assert "直接补发" not in result["reply"]


def test_promotion_without_evidence_checks_activity_rules_not_product_detail():
    result = _policy(query_fact_type='promotion', has_product_context=True, has_media_context=False)

    assert result['requires_human_review'] is True
    assert result['reply_strategy'] == 'verify_current_activity_rule'
    assert '优惠券' in result['reply']
    assert '满减' in result['reply']
    assert '下单页' in result['reply']
    assert '核对' in result['reply']
    _assert_customer_facing_safe_handoff(result['reply'])
    assert '商品详情需要确认' not in result['reply']
    assert '内部价' not in result['reply']


def test_price_negotiation_without_evidence_uses_activity_rule_handoff():
    for fact_type in ('promotion_policy', 'price_negotiation'):
        result = _policy(query_fact_type=fact_type, has_product_context=True, has_media_context=False)
        assert result['requires_human_review'] is True
        assert result['reply_strategy'] == 'verify_current_activity_rule'
        assert '优惠券' in result['reply']
        assert '下单页' in result['reply']
        assert '核对' in result['reply']
        _assert_customer_facing_safe_handoff(result['reply'])
        assert '内部价' not in result['reply']


def test_dimensions_with_known_product_context_does_not_request_product_link_again():
    result = _policy(query_fact_type="dimensions", has_product_context=True)

    assert result["requires_human_review"] is True
    assert result["reply_strategy"] == "verify_dimensions_for_known_product"
    assert "尺寸/规格" in result["reply"]
    assert "资料" in result["reply"]
    assert "预留位置" in result["reply"]
    _assert_customer_facing_safe_handoff(result["reply"])
    assert "商品链接" not in result["reply"]
    assert "SKU" not in result["reply"]


def test_placement_scene_without_evidence_uses_manual_verification():
    result = _policy(query_fact_type='placement_scene', has_product_context=True, has_media_context=False)

    assert result['requires_human_review'] is True
    assert result['reply_strategy'] == 'verify_placement_scene_for_known_product'
    assert '准备放的位置环境' in result['reply']
    assert '现场环境' in result['reply']
    _assert_customer_facing_safe_handoff(result['reply'])
    assert '床垫厚度' not in result['reply']
    assert '特殊床架' not in result['reply']


def test_load_capacity_without_evidence_uses_safe_non_numeric_fallback():
    result = _policy(query_fact_type='load_capacity', has_product_context=True, has_media_context=False)

    assert result['requires_human_review'] is True
    assert result['reply_strategy'] == 'verify_stability_or_load_capacity'
    assert '承重和稳定性' in result['reply']
    assert '分散摆放' in result['reply']
    assert '准确回复' in result['reply']
    _assert_customer_facing_safe_handoff(result['reply'])
    assert '压不弯' not in result['reply']


def test_material_safety_without_evidence_uses_document_based_fallback():
    result = _policy(query_fact_type='material', has_product_context=True, has_media_context=False)

    assert result['requires_human_review'] is True
    assert result['reply_strategy'] == 'verify_material_safety_for_known_product'
    assert '材质' in result['reply']
    assert '检测说明' in result['reply']
    assert '核对' in result['reply']
    assert '避免说错' in result['reply']
    assert '准确回复' in result['reply']
    assert '确认清楚' not in result['reply']
    assert '订单号' not in result['reply']
    _assert_customer_facing_safe_handoff(result['reply'])
    assert '无毒' in result['forbidden_claims']
    assert '有检测报告' in result['forbidden_claims']


def test_material_safety_without_product_context_requests_product_not_order():
    result = _policy(query_fact_type='certification_report', has_product_context=False, has_order_context=False)

    assert result['requires_human_review'] is True
    assert result['reply_strategy'] == 'request_product_context_for_material_safety'
    assert '商品截图' in result['reply']
    assert 'SKU' in result['reply']
    assert '订单号' not in result['reply']
    assert '有证书' in result['forbidden_claims']


def test_child_suitability_without_evidence_requires_review_and_no_safety_promise():
    result = _policy(query_fact_type='age_range', has_product_context=True, has_media_context=False)

    assert result['requires_human_review'] is True
    assert result['reply_strategy'] == 'verify_child_suitability_for_known_product'
    assert '宝宝适用和安全' in result['reply']
    assert '适用年龄' in result['reply']
    assert '核对' in result['reply']
    assert '避免说错' in result['reply']
    _assert_customer_facing_safe_handoff(result['reply'])
    assert '适合0-6岁' not in result['reply']
    assert '保护宝宝安全' not in result['reply']
    assert '适合0-6岁' in result['forbidden_claims']
    assert '保护宝宝安全' in result['forbidden_claims']


def test_child_suitability_without_product_context_requests_product_not_order():
    result = _policy(query_fact_type='child_safety', has_product_context=False, has_order_context=False)

    assert result['requires_human_review'] is True
    assert result['reply_strategy'] == 'request_product_context_for_child_suitability'
    assert '商品截图' in result['reply']
    assert 'SKU' in result['reply']
    assert '订单号' not in result['reply']
    assert '绝对安全' in result['forbidden_claims']


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


def test_installation_media_promise_without_reply_blocks_is_rewritten():
    response = {
        "suggested_reply": (
            "亲，防倒工具的安装可以参考说明书上的步骤哦。"
            "另外，下面图片/视频可参考，我这边再发您对应的安装图或视频。"
        ),
        "query_fact_type": "installation",
        "requires_human_review": False,
        "evidence_debug": {
            "query_fact_type": "installation",
            "selected_evidence": [{"fact_type": "installation", "content": "安装说明可参考说明书步骤。"}],
        },
        "answer_trace": {"query_fact_type": "installation", "required_fact_types": ["installation"]},
        "recommended_assets": [],
        "reply_blocks": [],
    }
    context = {
        "turn_understanding": {"turn_actionability": "actionable_question", "query_fact_type": "installation"},
        "product_name": "demo product",
        "media_context": {},
    }

    result = apply_no_evidence_reply_policy(response, context)

    assert result["requires_human_review"] is True
    assert result["generation_mode"] == "no_evidence_reply_policy"
    assert result["answer_trace"]["no_evidence_reply_policy"]["reply_strategy"] == "verify_installation_asset_before_send"
    assert "下面图片/视频可参考" not in result["suggested_reply"]
    assert "再发您对应的安装图或视频" not in result["suggested_reply"]
    assert "安装资料" in result["suggested_reply"]
    _assert_customer_facing_safe_handoff(result["suggested_reply"])


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
    assert '预留位置' in result['reply']
    assert '宽、深、高' in result['reply']
    _assert_customer_facing_safe_handoff(result['reply'])
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
    _assert_customer_facing_safe_handoff(result["reply"])


def test_space_fit_sku_image_with_size_title_counts_as_space_fit_asset():
    result = _policy(
        query_fact_type="space_fit",
        has_product_context=True,
        has_sendable_media_asset=True,
        sendable_media_asset_types=["sku_image", "space_fit_image"],
    )

    assert result["requires_human_review"] is False
    assert result["reply_strategy"] == "send_supported_space_fit_asset"


def test_structure_function_with_known_product_context_safe_handoff():
    result = _policy(query_fact_type="structure_function", has_product_context=True)

    assert result["requires_human_review"] is True
    assert result["reply_strategy"] == "verify_structure_function_for_known_product"
    assert "结构" in result["reply"]
    assert "配件规格" in result["reply"]
    assert "孔位" in result["reply"]
    assert "侧板/护栏/挡板" in result["reply"]
    _assert_customer_facing_safe_handoff(result["reply"])
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
    assert "核实" in result["reply"]
    assert "处理方案" in result["reply"]
    _assert_customer_facing_safe_handoff(result["reply"])
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
    assert "核实" in result["reply"]
    _assert_customer_facing_safe_handoff(result["reply"])


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
    assert contains_unsupported_media_promise("亲，下面图片/视频可参考。", False) is True
    assert contains_unsupported_media_promise("亲，我这边再发您对应的安装图或视频。", False) is True
    assert contains_unsupported_media_promise("亲，我把视频发您参考。", True) is False
    assert has_sendable_media_asset({"recommended_assets": [{"asset_url": "https://asset.example/video.mp4", "auto_send_level": "auto"}]}) is True
    assert has_attached_sendable_media_asset({"recommended_assets": [{"asset_url": "https://asset.example/video.mp4", "auto_send_level": "auto"}]}) is False
    assert has_attached_sendable_media_asset({"reply_blocks": [{"type": "image", "url": "https://asset.example/install.png"}]}) is True
    assert has_sendable_media_asset({"recommended_assets": [{"asset_url": "https://asset.example/video.mp4", "auto_send_level": "review"}]}) is False


def test_media_delivery_claim_requires_each_attached_media_type():
    response = {
        "query_fact_type": "installation",
        "i_id": "IID-A",
        "reply_blocks": [{
            "type": "image",
            "url": "https://asset.example/guide.png",
            "asset_type": "pack_guide_image",
            "media_purpose": "packing_list_image",
            "i_id": "IID-A",
        }],
    }

    issues = media_delivery_claim_issues(
        response,
        "亲，下面图片/视频可参考。",
    )

    assert issues == ["missing_attached_video_block"]

    assert media_delivery_claim_issues(
        response,
        "如果安装有问题，我们可以发安装视频给您参考。",
    ) == ["missing_attached_video_block"]
    assert media_delivery_claim_issues(
        response,
        "目前无法发安装视频给您参考。",
    ) == []


def test_media_delivery_claim_rejects_catalog_only_wrong_role_and_identity():
    catalog_only = {
        "query_fact_type": "installation",
        "recommended_assets": [{
            "asset_type": "install_image",
            "asset_url": "https://asset.example/guide.png",
            "auto_send_level": "auto",
        }],
        "reply_blocks": [],
    }
    wrong_role = {
        "query_fact_type": "installation",
        "reply_blocks": [{
            "type": "image",
            "url": "https://asset.example/product.png",
            "asset_type": "sku_image",
        }],
    }
    wrong_identity = {
        "query_fact_type": "installation",
        "i_id": "IID-A",
        "reply_blocks": [{
            "type": "image",
            "url": "https://asset.example/guide.png",
            "asset_type": "install_image",
            "i_id": "IID-B",
        }],
    }
    missing_identity = {
        "query_fact_type": "installation",
        "i_id": "IID-A",
        "reply_blocks": [{
            "type": "image",
            "url": "https://asset.example/guide.png",
            "asset_type": "install_image",
        }],
    }

    assert media_delivery_claim_issues(catalog_only, "亲，下面图片可参考。") == ["missing_attached_image_block"]
    assert media_delivery_claim_issues(wrong_role, "亲，下面图片可参考。") == ["installation_image_role_mismatch"]
    assert media_delivery_claim_issues(wrong_identity, "亲，下面图片可参考。") == ["image_block_identity_mismatch"]
    assert media_delivery_claim_issues(missing_identity, "亲，下面图片可参考。") == ["image_block_identity_mismatch"]


def test_dimension_delivery_requires_size_role_and_exact_identity():
    base = {
        "query_fact_type": "dimensions",
        "i_id": "IID-A",
        "reply_blocks": [{
            "type": "image",
            "url": "https://asset.example/size.png",
            "asset_type": "size_image",
            "media_purpose": "dimension_reference",
            "i_id": "IID-A",
            "status": "approved",
            "usable_for_agent": True,
        }],
    }

    assert media_delivery_claim_issues(base, "亲，下面图片可参考。") == []

    ordinary_photo = {
        **base,
        "reply_blocks": [{
            **base["reply_blocks"][0],
            "asset_type": "sku_image",
            "media_purpose": "appearance_image",
            "title": "尺寸参考图",
        }],
    }
    assert media_delivery_claim_issues(ordinary_photo, "亲，下面图片可参考。") == [
        "dimensions_image_role_or_identity_mismatch"
    ]

    missing_identity = {
        **base,
        "reply_blocks": [{key: value for key, value in base["reply_blocks"][0].items() if key != "i_id"}],
    }
    assert media_delivery_claim_issues(missing_identity, "亲，下面图片可参考。") == [
        "dimensions_image_role_or_identity_mismatch"
    ]


def test_sendable_media_asset_types_reads_installation_image_assets():
    assert get_sendable_media_asset_types({
        "recommended_assets": [{
            "asset_type": "install_image",
            "asset_url": "https://asset.example/install.png",
            "auto_send_level": "auto",
        }]
    }) == {"install_image"}


def test_sendable_media_asset_types_requires_a_declared_dimension_media_role():
    assert get_sendable_media_asset_types({
        "recommended_assets": [{
            "asset_type": "size_image",
            "asset_title": "Product specification image",
            "asset_url": "https://asset.example/size.png",
            "auto_send_level": "auto",
        }]
    }) == {"size_image", "space_fit_image"}


def test_sendable_media_asset_types_does_not_promote_size_named_sku_image():
    assert get_sendable_media_asset_types({
        "recommended_assets": [{
            "asset_type": "sku_image",
            "asset_title": "Size marked product image",
            "asset_url": "https://asset.example/size.png",
            "auto_send_level": "auto",
        }]
    }) == {"sku_image"}


def test_sendable_media_asset_types_does_not_treat_plain_sku_image_as_space_fit():
    assert get_sendable_media_asset_types({
        "recommended_assets": [{
            "asset_type": "sku_image",
            "asset_title": "Product appearance",
            "asset_url": "https://asset.example/product.png",
            "auto_send_level": "auto",
        }]
    }) == {"sku_image"}


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
    assert "安装资料" in result["suggested_reply"]
    assert "准确回复" in result["suggested_reply"]
    assert "我把视频发您" not in result["suggested_reply"]
    assert "发您参考" not in result["suggested_reply"]
    _assert_customer_facing_safe_handoff(result["suggested_reply"])


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
    assert "安装资料" in result["suggested_reply"]
    assert "准确回复" in result["suggested_reply"]
    assert "下面发您" not in result["suggested_reply"]
    _assert_customer_facing_safe_handoff(result["suggested_reply"])


def test_installation_direct_evidence_summary_prevents_false_no_evidence_handoff():
    response = {
        "suggested_reply": "亲，这个贴纸按安装说明贴在对应标记位置就可以，装的时候先对齐孔位再固定。",
        "query_fact_type": "installation",
        "customer_message": "贴纸贴哪",
        "evidence_debug": {
            "query_fact_type": "installation",
            "knowledge_evidence_summary": [
                {
                    "source_type": "product_facts",
                    "query_fact_type": "installation",
                    "evidence_fact_type": "installation",
                    "gate_status": "allowed",
                    "direct_answer_allowed": True,
                    "evidence_allowed_for_exact_answer": True,
                    "chunk_preview": "安装说明：贴纸贴在对应标记位置。",
                }
            ],
        },
        "recommended_assets": [],
    }
    context = {
        "turn_understanding": {"turn_actionability": "actionable_question", "query_fact_type": "installation"},
        "real_context_summary": {"has_product_context": True, "has_media_context": True},
    }

    result = apply_no_evidence_reply_policy(response, context)

    assert result.get("generation_mode") != "no_evidence_reply_policy"
    assert result["suggested_reply"] == response["suggested_reply"]


def test_installation_media_request_still_requires_attached_asset_with_direct_evidence_summary():
    response = {
        "suggested_reply": "亲～这个问题我先帮您按这款商品核对一下，您稍等一下，我这边确认后再回复您。",
        "query_fact_type": "installation",
        "customer_message": "麻烦发下安装资料",
        "evidence_debug": {
            "knowledge_evidence_summary": [
                {
                    "source_type": "product_facts",
                    "query_fact_type": "installation",
                    "evidence_fact_type": "installation",
                    "gate_status": "allowed",
                    "direct_answer_allowed": True,
                    "evidence_allowed_for_exact_answer": True,
                    "chunk_preview": "安装说明可参考说明书步骤。",
                }
            ],
        },
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


def test_installation_structure_modification_uses_handoff_not_diagram_send():
    result = _policy(
        query_fact_type="installation",
        has_sendable_media_asset=True,
        sendable_media_asset_types=["install_image"],
        customer_message="这款能不能只装中间部分，两边拆掉会不会影响稳固？",
    )

    assert result["requires_human_review"] is True
    assert result["reply_strategy"] == "verify_structure_function_for_known_product"
    assert "核对" in result["reply"]
    assert "侧板/护栏/挡板" in result["reply"]
    _assert_customer_facing_safe_handoff(result["reply"])


def test_installation_diagram_request_still_can_use_diagram_when_not_modification():
    result = _policy(
        query_fact_type="installation",
        has_sendable_media_asset=True,
        sendable_media_asset_types=["install_image"],
        customer_message="安装步骤怎么看？",
    )

    assert result["requires_human_review"] is False
    assert result["reply_strategy"] == "send_installation_diagram_without_video"


def test_installation_accessory_package_question_uses_handoff_without_confusing_usage():
    result = _policy(
        query_fact_type="installation",
        has_sendable_media_asset=True,
        sendable_media_asset_types=["install_image"],
        customer_message="这款有没有配螺丝刀？",
    )

    assert result["requires_human_review"] is True
    assert result["reply_strategy"] == "verify_accessory_usage_with_photo"
    assert "配件规格" in result["reply"]
    _assert_customer_facing_safe_handoff(result["reply"])


def test_installation_accessory_package_uses_context_customer_message():
    response = {
        "suggested_reply": "亲，这个细节可以参考下面发您的图片或视频。",
        "evidence_debug": {"query_fact_type": "installation", "selected_evidence": []},
        "context_used": {
            "product_context_pack": {
                "stats": {"sendable_media_asset_count": 1},
                "recommended_assets": [{
                    "asset_url": "https://asset.example/install.png",
                    "asset_type": "install_image",
                    "auto_send_level": "auto",
                }],
            }
        },
    }
    context = {
        "customer_message": "这款有没有配螺丝刀？",
        "turn_understanding": {"turn_actionability": "actionable_question", "query_fact_type": "installation"},
        "product_name": "测试商品",
    }

    result = apply_no_evidence_reply_policy(response, context)

    assert result["generation_mode"] == "no_evidence_reply_policy"
    assert result["answer_trace"]["no_evidence_reply_policy"]["reply_strategy"] == "verify_accessory_usage_with_photo"
    assert result.get("can_send") is not True


def test_installation_tool_usage_request_is_not_package_missing_question():
    result = _policy(
        query_fact_type="installation",
        has_sendable_media_asset=True,
        sendable_media_asset_types=["install_image"],
        customer_message="螺丝刀怎么用？",
    )

    assert result["reply_strategy"] == "send_installation_diagram_without_video"


def test_gold_stability_reply_for_fixed_or_load_capacity_questions():
    result = _policy(query_fact_type="load_capacity", has_product_context=True)

    assert result["requires_human_review"] is True
    assert result["reply_strategy"] == "verify_stability_or_load_capacity"
    assert "承重和稳定性" in result["reply"]
    assert "分散摆放" in result["reply"]
    assert "核对" in result["reply"]
    _assert_customer_facing_safe_handoff(result["reply"])


def test_gold_internal_space_reply_for_inside_space_question():
    result = _policy(
        query_fact_type="dimensions",
        has_product_context=True,
        customer_message="这里面是什么样的空间？",
    )

    assert result["requires_human_review"] is True
    assert result["reply_strategy"] == "verify_dimensions_for_known_product"
    assert "内部空间" in result["reply"]
    assert "核对" in result["reply"]
    assert "准确回复" in result["reply"]


def test_gold_structure_function_reply_for_left_right_installation():
    result = _policy(query_fact_type="structure_function", has_product_context=True)

    assert result["requires_human_review"] is True
    assert result["reply_strategy"] == "verify_structure_function_for_known_product"
    assert "孔位" in result["reply"]
    assert "侧板/护栏/挡板" in result["reply"]
    assert "避免" in result["reply"]
    _assert_customer_facing_safe_handoff(result["reply"])


def test_gold_promotion_reply_mentions_coupon_and_activity_boundary():
    result = _policy(query_fact_type="promotion", has_product_context=True)

    assert result["requires_human_review"] is True
    assert result["reply_strategy"] == "verify_current_activity_rule"
    assert "优惠券" in result["reply"]
    assert "满减" in result["reply"]
    assert "下单页" in result["reply"]


def test_gold_placement_scene_reply_mentions_environment_and_photo_check():
    result = _policy(query_fact_type="placement_scene", has_product_context=True)

    assert result["requires_human_review"] is True
    assert result["reply_strategy"] == "verify_placement_scene_for_known_product"
    assert "准备放的位置环境" in result["reply"]
    _assert_customer_facing_safe_handoff(result["reply"])
    assert "现场环境" in result["reply"]
    assert "床垫厚度" not in result["reply"]


def test_material_composition_cannot_authorize_cleaning_or_moisture_instructions():
    response = {
        "suggested_reply": "\u4eb2\uff0c\u53ef\u4ee5\u6c34\u6d17\u3002",
        "selected_evidence": [{
            "fact_type": "material",
            "attribute_key": "material",
            "direct_answer_allowed": True,
        }],
    }
    inputs = {"query_fact_type": "cleaning_care", "turn_actionability": "actionable_question"}

    assert should_apply_no_evidence_policy(response, inputs) is True


def test_identity_scoped_direct_care_evidence_can_satisfy_the_care_contract():
    response = {
        "suggested_reply": "\u4eb2\uff0c\u8bf7\u6309\u5546\u54c1\u8bf4\u660e\u6e05\u6d01\u3002",
        "selected_evidence": [{
            "fact_type": "cleaning_care",
            "attribute_key": "cleaning_care",
            "direct_answer_allowed": True,
        }],
    }
    inputs = {"query_fact_type": "cleaning_care", "turn_actionability": "actionable_question"}

    assert should_apply_no_evidence_policy(response, inputs) is False
