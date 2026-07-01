from app.services.real_conversation_sidecar_context_service import build_sidecar_context


def test_presales_product_title_is_complete_sidecar_product_context():
    result = build_sidecar_context(
        turn_metadata={"sidecar_product_title": "儿童收纳柜"},
        turn_understanding={"query_fact_type": "gross_weight", "should_score": True},
        buyer_message="毛重多少",
    )

    assert result["sidecar_context_quality"] == "complete"
    assert result["has_sidecar_product_context"] is True
    assert result["has_sidecar_order_context"] is False
    assert result["missing_context_fields"] == []
    assert result["product_candidates"][0]["product_name"] == "儿童收纳柜"
    assert result["product_candidates"][0]["verified"] is False


def test_top_level_real_context_product_title_is_sidecar_context():
    result = build_sidecar_context(
        real_context={"product_title": "Sidecar Product Title"},
        turn_understanding={"query_fact_type": "gross_weight", "should_score": True},
        buyer_message="gross weight?",
    )

    assert result["sidecar_context_quality"] == "complete"
    assert result["has_sidecar_product_context"] is True
    assert result["product_title"] == "Sidecar Product Title"
    assert result["product_candidates"][0]["type"] == "product_title"


def test_sidecar_sku_creates_verified_product_candidate():
    result = build_sidecar_context(
        turn_metadata={"sidecar_product_title": "儿童收纳柜", "sidecar_sku_code": "YH01K99B01"},
        turn_understanding={"query_fact_type": "installation", "should_score": True},
        buyer_message="怎么安装",
    )

    sku_candidate = next(item for item in result["product_candidates"] if item["type"] == "sku_code")
    title_candidate = next(item for item in result["product_candidates"] if item["type"] == "product_title")
    assert sku_candidate["verified"] is True
    assert title_candidate["verified"] is True
    assert result["sidecar_context_quality"] == "complete"


def test_aftersales_order_context_is_complete_but_product_only_is_partial():
    complete = build_sidecar_context(
        turn_metadata={"sidecar_order_id": "1234567890123", "sidecar_product_title": "儿童收纳柜"},
        turn_understanding={"query_fact_type": "aftersales", "should_score": True},
        buyer_message="少了一个配件",
    )
    partial = build_sidecar_context(
        turn_metadata={"sidecar_product_title": "儿童收纳柜"},
        turn_understanding={"query_fact_type": "aftersales", "should_score": True},
        buyer_message="少了一个配件",
    )

    assert complete["sidecar_context_quality"] == "complete"
    assert complete["has_sidecar_order_context"] is True
    assert partial["sidecar_context_quality"] == "partial"
    assert partial["missing_context_fields"] == ["order"]


def test_platform_identity_only_is_supplemental_not_complete_context():
    result = build_sidecar_context(
        real_context={
            "product": {
                "item_id_hash": "hash-item",
                "product_url": "https://item.taobao.com/item.htm?id=123",
            },
            "order": {},
        },
        turn_understanding={"query_fact_type": "dimensions", "should_score": True},
        buyer_message="尺寸多少",
    )

    assert result["sidecar_context_quality"] == "missing"
    assert result["has_sidecar_product_context"] is False
    assert result["supplemental_platform_identity"]["item_id_hash"] == "hash-item"
    assert result["missing_context_fields"] == ["product"]
