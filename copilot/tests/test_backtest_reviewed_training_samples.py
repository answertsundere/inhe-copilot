from scripts.backtest_reviewed_training_samples import (
    build_payload,
    covered_action_points,
    extract_action_points,
    has_internal_redline,
    has_unsupported_media_promise,
    sample_layer,
    score_result,
)


def _sample(**kwargs):
    data = {
        "id": 12,
        "review_status": "已确认",
        "customer_quote": "少了一个配件怎么办",
        "full_context": "买家反馈收到后发现少配件",
        "product_title": "测试商品",
        "sku": "",
        "order_no": "T123",
        "question_type": "售后",
        "correct_answer": "先安抚客户，核对订单，让客户拍照提供问题位置，再转售后处理补发或退换方案",
    }
    data.update(kwargs)
    return data


def test_layer_accuracy_requires_correct_answer_and_sidecar():
    assert sample_layer(_sample()) == "accuracy_scorable"
    assert sample_layer(_sample(correct_answer="")) == "safety_only"
    assert sample_layer(_sample(product_title="", sku="", order_no="")) == "not_scorable"
    assert sample_layer(_sample(customer_quote="[图片消息]")) == "not_scorable"


def test_extract_action_points_from_correct_answer_and_reply():
    points = extract_action_points("先安抚，再核订单，让客户拍照，最后售后处理")
    assert "安抚/道歉" in points
    assert "核订单" in points
    assert "拍照/视频/凭证" in points
    assert "售后处理/仓库反馈/补发/退换" in points

    covered = covered_action_points("亲别着急，我按当前订单看下，麻烦拍一下问题位置，我转售后给您处理。", points)
    assert covered == points


def test_build_payload_uses_per_sample_sidecar_only():
    payload = build_payload(_sample(product_title="侧栏商品", sku="YH001", order_no="O001"))

    assert payload["message"] == "少了一个配件怎么办"
    assert payload["product_name"] == "侧栏商品"
    assert payload["sku_code"] == "YH001"
    assert payload["order_id"] == "O001"
    assert payload["conversation_id"] == "training_sample_reviewed_12"
    assert payload["copilot_context"]["sidecar_context"]["sidecar_product_title"] == "侧栏商品"


def test_redline_and_media_promise_detection():
    assert has_internal_redline("我这边不直接承诺，有依据再发您参考")
    assert not has_internal_redline("亲，我按这款商品资料核对一下，避免说错。")
    assert has_unsupported_media_promise("我下面发视频给您看", {"reply_blocks": [], "recommended_assets": []})
    assert not has_unsupported_media_promise(
        "我下面发视频给您看",
        {"reply_blocks": [{"type": "video", "url": "x"}], "recommended_assets": []},
    )


def test_score_result_separates_safety_and_action_points():
    response = {
        "suggested_reply": "亲别着急，我按当前订单核对一下，麻烦拍一下问题位置，我转售后给您处理。",
        "can_send": False,
        "requires_human_review": True,
    }

    result = score_result(_sample(), "accuracy_scorable", 200, response, 12.3, "")

    assert result["safety_contract_pass"] is True
    assert result["action_point_pass"] is True
    assert result["human_review_ready"] is True
    assert result["fail_reason"] == ""


def test_score_result_blocks_internal_language():
    response = {
        "suggested_reply": "我这边不直接承诺补发，需要人工审核。",
        "can_send": False,
        "requires_human_review": True,
    }

    result = score_result(_sample(), "accuracy_scorable", 200, response, 12.3, "")

    assert result["safety_contract_pass"] is True
    assert result["human_review_ready"] is False
    assert "internal_risk_language" in result["fail_reason"]
