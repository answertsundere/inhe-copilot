from app.services.product_context_pack_service import _media_fact_customer_text


def test_media_fact_text_is_customer_facing_for_dimensions():
    text = _media_fact_customer_text("dimensions", "图片")

    assert "尺寸" in text
    assert "宽度" in text
    assert "进深" in text
    assert "已匹配" not in text
    assert "素材" not in text
    assert "asset" not in text.lower()
    assert "核对后再发" not in text

