from app.services.real_context_product_identity_service import (
    augment_copilot_context_with_real_identity,
    build_conversation_media_reference,
    build_real_context_product_identity,
)
from app.services.eval_sanitizer_service import hash_sensitive, sanitize_obj, sanitize_product_title


def test_builds_product_candidates_from_product_and_order_context():
    context = {
        "real_context": {
            "product": {
                "item_id": "1234567890",
                "item_id_hash": hash_sensitive("1234567890"),
                "product_url": "https://item.taobao.com/item.htm?id=1234567890",
                "product_title": "儿童书架收纳柜",
                "sku_code": "YH88K01B02S03",
            },
            "order": {
                "order_product_title": "儿童书架收纳柜-订单款",
                "order_sku_code": "YH88K01B02S03",
            },
        }
    }

    identity = build_real_context_product_identity(context)

    by_type = {item["type"]: item for item in identity["product_candidates"]}
    assert identity["display_product_name"] == "儿童书架收纳柜"
    assert identity["has_resolved_product_context"] is True
    assert by_type["sku_code"]["value"] == "YH88K01B02S03"
    assert by_type["i_id"]["value"] == "YH88K01"
    assert by_type["platform_product_id"]["value"] == "1234567890"
    assert by_type["platform_item_id_hash"]["value"] == hash_sensitive("1234567890")
    assert by_type["product_url"]["value"].startswith("https://item.taobao.com/")
    assert by_type["product_title"]["product_name"] == "儿童书架收纳柜"
    assert by_type["order_product_title"]["product_name"] == "儿童书架收纳柜-订单款"
    assert "order_id" not in identity["identity_sources"]


def test_order_product_title_is_used_when_product_title_is_absent():
    identity = build_real_context_product_identity({
        "order_product_title": "售后订单里的置物架",
        "order_sku_code": "YH77K03B01S02",
    })

    assert identity["display_product_name"] == "售后订单里的置物架"
    assert any(item["type"] == "order_product_title" for item in identity["product_candidates"])
    assert any(item["type"] == "sku_code" for item in identity["product_candidates"])


def test_augment_context_merges_candidates_and_keeps_historical_media_separate():
    context = {
        "product_candidates": [{"type": "manual", "value": "手动候选"}],
        "product_name": "页面标题",
        "media_context": {
            "video_urls": ["https://example.com/install.mp4"],
            "image_urls": ["https://example.com/detail.jpg"],
        },
    }

    augmented = augment_copilot_context_with_real_identity(context)
    media_ref = build_conversation_media_reference(augmented)

    assert augmented["display_product_name"] == "页面标题"
    assert any(item["value"] == "手动候选" for item in augmented["product_candidates"])
    assert media_ref["evidence_role"] == "conversation_media_reference"
    assert media_ref["sendable"] is False
    assert media_ref["media_context_count"] == 2


def test_augment_context_preserves_structured_order_id_for_local_tools_only():
    platform_order_id = "6926666820903533935"
    raw_phone = "13812345678"

    augmented = augment_copilot_context_with_real_identity({
        "platform_order_id": platform_order_id,
        "customer_phone": raw_phone,
    })

    assert augmented["platform_order_id"] == platform_order_id
    assert augmented["customer_phone"] != raw_phone


def test_repository_scope_scoring_accepts_structured_scope_candidates():
    from app.repositories.knowledge_chunk_repository import _compute_scope_score

    score = _compute_scope_score(
        {
            "sku_scope": [{"sku_code": "YH88K01B02S03"}],
            "product_scope": [{"value": "儿童书架收纳柜"}],
            "title": "儿童书架收纳柜安装说明",
        },
        sku_name="YH88K01B02S03",
        product_name="儿童书架收纳柜",
    )

    assert score > 0


def test_product_title_sanitizer_does_not_redact_room_words_as_address():
    title = "\u82f1\u79be\u9632\u5939\u6ed1\u95e8\u6536\u7eb3\u67b6\u6574\u7406\u5ba2\u5385\u96f6\u98df\u684c\u9762\u513f\u7ae5\u73a9\u5177\u5367\u5ba4\u53ef\u62fc\u642d\u50a8\u7269\u62bd\u5c49"

    assert sanitize_product_title(title) == title
    sanitized = sanitize_obj({
        "product_title": title,
        "product_candidates": [{"type": "product_candidate", "value": title}],
    })

    assert sanitized["product_title"] == title
    assert sanitized["product_candidates"][0]["value"] == title
    assert "[ADDRESS_REDACTED]" not in sanitized["product_title"]


def test_real_context_identity_preserves_qianniu_product_title():
    title = "\u82f1\u79be\u9632\u5939\u6ed1\u95e8\u6536\u7eb3\u67b6\u6574\u7406\u5ba2\u5385\u96f6\u98df\u684c\u9762\u513f\u7ae5\u73a9\u5177\u5367\u5ba4\u53ef\u62fc\u642d\u50a8\u7269\u62bd\u5c49"

    identity = build_real_context_product_identity({
        "product_title": title,
        "product_candidates": [{"type": "product_candidate", "value": title}],
    })

    assert identity["product_title"] == title
    assert identity["display_product_name"] == title
    assert identity["product_candidates"][0]["value"] == title
    assert "[ADDRESS_REDACTED]" not in str(identity)
