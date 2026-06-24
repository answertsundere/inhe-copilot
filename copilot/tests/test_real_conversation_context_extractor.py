from app.services.real_conversation_context_extractor import (
    build_agent_context_from_real_context,
    extract_real_context,
    merge_real_context,
    summarize_real_context,
)


def test_extracts_presales_product_detail_context():
    context = extract_real_context(
        "当前用户来自 商品详情页\nhttps://item.taobao.com/item.htm?id=123456789&spm=a1\n儿童书架收纳柜",
        {"product_title": "儿童书架收纳柜"},
    )

    assert context["conversation_type"] == "presales"
    assert context["source_page"] == "product_detail"
    assert context["product"]["item_id"] == "123456789"
    assert context["product"]["product_url"] == "https://item.taobao.com/item.htm?id=123456789"
    assert context["product"]["product_title"] == "儿童书架收纳柜"
    assert "spm=" not in context["product"]["product_url"]

    agent_context = build_agent_context_from_real_context(context)
    assert agent_context["item_id"] == "123456789"
    assert agent_context["product_url"] == "https://item.taobao.com/item.htm?id=123456789"
    assert agent_context["source_page"] == "product_detail"


def test_extracts_aftersales_order_context_without_exposing_full_order_id():
    context = extract_real_context(
        "订单号 123456789012345 当前用户来自 订单123456789012345",
        {"order_product_title": "儿童书架收纳柜", "sku_code": "SKU-A1"},
    )

    assert context["conversation_type"] == "aftersales"
    assert context["source_page"] == "order_detail"
    assert context["order"]["order_id_hash"]
    assert context["order"]["order_id_masked"].startswith("123***")
    assert context["order"]["order_id"] != "123456789012345"
    assert context["order"]["order_product_title"] == "儿童书架收纳柜"
    assert context["order"]["order_sku_code"] == "SKU-A1"

    summary = summarize_real_context(context)
    assert summary["has_order_context"] is True
    assert summary["order_id_masked"] == context["order"]["order_id_masked"]
    assert "123456789012345" not in str(summary)


def test_extracts_media_references_without_signed_query_or_content_claims():
    context = extract_real_context(
        "https://demo.oss-cn-hangzhou.aliyuncs.com/install.mp4?Expires=1&Signature=secret\n"
        "https://img.alicdn.com/imgextra/i1/example.jpg?token=secret",
        {"message_type": "video"},
    )

    assert context["media"]["video_urls"] == ["https://demo.oss-cn-hangzhou.aliyuncs.com/install.mp4"]
    assert context["media"]["image_urls"] == ["https://img.alicdn.com/imgextra/i1/example.jpg"]
    assert "Signature=" not in str(context)
    assert "token=secret" not in str(context)

    agent_context = build_agent_context_from_real_context(context)
    assert agent_context["media_context"]["video_urls"]
    assert agent_context["media_context"]["image_urls"]


def test_merges_context_across_followup_turns():
    first = extract_real_context(
        "当前用户来自 商品详情页 https://detail.tmall.com/item.htm?id=987654321",
        {"product_title": "儿童床护栏"},
    )
    followup = extract_real_context("柜子的有吗")
    merged = merge_real_context(first, followup)

    assert merged["conversation_type"] == "presales"
    assert merged["source_page"] == "product_detail"
    assert merged["product"]["item_id"] == "987654321"
    assert summarize_real_context(merged)["has_product_context"] is True
