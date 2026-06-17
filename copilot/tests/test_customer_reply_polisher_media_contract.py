from app.services.customer_reply_polisher import polish_customer_reply


def test_polisher_rewrites_internal_media_workflow_language_for_size_image():
    response = {
        "suggested_reply": (
            "亲～「英禾防夹滑门收纳架整理客厅零食桌面儿童玩具卧室可拼搭储物抽屉」"
            "这个点如果需要看安装步骤、尺寸或配件位置，我可以帮您对照对应商品的图片/视频资料。"
            "如果当前款式没有匹配到可发送的资料，我会先按对应款式核对后再发您，避免发错。"
        ),
        "evidence_debug": {"query_fact_type": "dimensions"},
        "recommended_assets": [{
            "asset_type": "sku_image",
            "asset_url": "https://example.com/size.png",
        }],
    }

    polished = polish_customer_reply(
        response,
        customer_message="可以直接告诉我们产品的大小吗",
    )
    reply = polished["suggested_reply"]

    assert "匹配到可发送" not in reply
    assert "可发送的资料" not in reply
    assert "核对后再发" not in reply
    assert "避免发错" not in reply
    assert "图/视频资料" not in reply
    assert "安装步骤、尺寸或配件位置" not in reply
    assert "尺寸" in reply
    assert "图片" in reply
    assert "宽度" in reply
    assert "进深" in reply
    assert polished["customer_reply_polish"]["applied"] is True

