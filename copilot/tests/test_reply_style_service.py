from app.main import create_app
from app.services.reply_style_service import beautify_customer_reply


def test_beautify_customer_reply_splits_into_warm_sections():
    raw = (
        "\u4eb2\u4eb2\uff0c\u810f\u4e86\u600e\u4e48\u6e05\u6d01\u8fd9\u4e2a\u95ee\u9898\u5f88\u5b9e\u7528\uff0c\u6211\u5148\u6309\u4fdd\u5b88\u65b9\u5f0f\u8ddf\u60a8\u8bf4\u54e6\u3002"
        "\u672a\u6838\u5bf9\u5177\u4f53\u6750\u8d28\u548c\u9875\u9762\u6e05\u6d17\u8bf4\u660e\u524d\uff0c\u4e0d\u5efa\u8bae\u76f4\u63a5\u6574\u4f53\u6c34\u6d17\u3002"
        "\u5e73\u65f6\u53ef\u4ee5\u5148\u7528\u5e72\u5e03\u64e6\u62ed\u3002"
    )

    styled = beautify_customer_reply(raw)

    assert styled.startswith("\u4eb2\uff5e")
    assert "\n" in styled
    assert "\n\n" not in styled
    assert "\u6574\u4f53\u6c34\u6d17" in styled
    assert any(icon in styled for icon in ("\U0001f9fc", "\U0001f4cc", "\U0001f4a1", "\U0001f449", "\U0001f64c"))


def test_api_reply_style_keeps_grounded_material_facts():
    app = create_app()
    client = app.test_client()
    result = client.post("/ask/api/analyze", json={
        "message": "\u8fd9\u4e2a\u4ec0\u4e48\u6750\u8d28\uff1f",
        "conversation_id": "test_reply_style_material",
        "sku_code": "YH06K53B05S13",
        "product_candidates": [
            {"value": "YH06K53B05S13", "type": "sku_id_candidate", "verified": True},
        ],
    }).get_json()

    reply = result["suggested_reply"]
    assert "\n" in reply
    assert "\n\n" not in reply
    assert "\u51b7\u8f67\u94a2\u7ba1" in reply
    assert "\u73af\u4fddPP" in reply


def test_logistics_trace_appends_grounded_secondary_safety_answer():
    raw = "\u4eb2\uff0c\u5e2e\u60a8\u67e5\u5230\u5305\u88f9\u5df2\u7ecf\u53d1\u51fa\uff0c\u6b63\u5728\u8fd0\u8f93\u4e2d\u3002"
    state = {
        "intent": "logistics_trace",
        "customer_message": "\u5e2e\u6211\u67e5\u7269\u6d41\uff0c\u8fd9\u4e2a\u4e1c\u897f\u5b89\u5168\u5417",
        "matched_product_name": "\u4e00\u53f7\u5c0f\u718a\u5e8a\u62a4\u680f",
        "evidence": {
            "product_facts": [
                {
                    "source_type": "product_facts",
                    "fact": "\u6750\u8d28\u4ee5\u5546\u54c1\u9875\u9762\u6807\u6ce8\u4e3a\u51c6\uff0c\u4f7f\u7528\u524d\u5efa\u8bae\u6309\u8bf4\u660e\u4e66\u68c0\u67e5\u5b89\u88c5\u72b6\u6001\u3002",
                    "evidence_allowed_for_direct_answer": True,
                }
            ],
        },
    }

    styled = beautify_customer_reply(raw, state)

    assert "\u4e00\u53f7\u5c0f\u718a\u5e8a\u62a4\u680f" in styled
    assert "\u5b89\u5168/\u6750\u8d28\u95ee\u9898" in styled
    assert "\u8bf4\u660e\u4e66" in styled


def test_logistics_trace_appends_safety_next_step_when_product_unknown():
    raw = "\u4eb2\uff0c\u6211\u5df2\u6536\u5230\u60a8\u63d0\u4f9b\u7684\u5355\u53f7\uff0c\u6b63\u5728\u8fdb\u4e00\u6b65\u6838\u5b9e\u4e2d\u3002"
    state = {
        "intent": "logistics_trace",
        "customer_message": "\u5e2e\u6211\u67e5\u8fd9\u4e2a\u8ba2\u5355\u5230\u54ea\u4e86\uff1f\u6574\u4e2a\u4e1c\u897f\u5b89\u5168\u5417",
        "order_product_identity": {"status": "not_found"},
    }

    styled = beautify_customer_reply(raw, state)

    assert "\u8fd9\u4e2a\u4e1c\u897f\u5b89\u5168\u5417" in styled
    assert "\u9700\u8981\u5148\u5bf9\u4e0a\u5177\u4f53\u5546\u54c1" in styled
    assert "\u5546\u54c1\u622a\u56fe\u6216\u94fe\u63a5" in styled


def test_beautify_softens_installation_convenience_promises():
    raw = "\u4eb2\uff0c\u8fd9\u6b3e\u5b89\u88c5\u5f88\u65b9\u4fbf\uff0c\u4e0d\u9700\u8981\u989d\u5916\u5de5\u5177\uff0c\u4e00\u822c15-20\u5206\u949f\u5c31\u80fd\u5b8c\u6210\u5b89\u88c5\u3002"

    styled = beautify_customer_reply(raw)

    assert "\u5b89\u88c5\u5f88\u65b9\u4fbf" not in styled
    assert "\u4e0d\u9700\u8981\u989d\u5916\u5de5\u5177" not in styled
    assert "\u4e00\u822c15-20\u5206\u949f\u5c31\u80fd\u5b8c\u6210\u5b89\u88c5" not in styled
    assert "\u8bf4\u660e\u4e66" in styled
    assert "\u4ee5\u8bf4\u660e\u4e66\u548c\u5b9e\u9645\u914d\u4ef6\u4e3a\u51c6" in styled


def test_absolute_child_safety_request_uses_real_customer_service_tone():
    styled = beautify_customer_reply(
        "亲亲，商品参数、功能或订单信息需要以已验证的商品知识和订单页面为准，我先不凭感觉猜，避免给您误导。",
        {
            "customer_message": "你直接保证我家孩子用了，一定不会出事，我就拍。",
            "matched_product_name": "一号小熊床护栏",
        },
    )

    assert "孩子用的东西您谨慎是应该的" in styled
    assert "百分百一定不会出事" in styled
    assert "说太满反而不负责" in styled
    assert "宝宝多大" in styled
    assert "商品参数、功能或订单信息" not in styled
    assert "系统" not in styled
    assert "避免给您误导" not in styled
    assert styled.count("\n") == 3
    assert "🧡" in styled


def test_beautify_removes_ai_sounding_phrases():
    raw = (
        "亲亲，根据您提供的信息，这类商品参数、功能或订单信息需要以已验证的商品知识和订单页面为准，"
        "我先不凭感觉猜，避免给您误导。如果系统里暂时没有明确证据，就转人工确认后再给您准确答复。"
    )

    styled = beautify_customer_reply(raw)

    assert "根据您提供的信息" not in styled
    assert "商品参数、功能或订单信息需要以已验证" not in styled
    assert "我先不凭感觉猜" not in styled
    assert "避免给您误导" not in styled
    assert "系统里暂时没有明确证据" not in styled
