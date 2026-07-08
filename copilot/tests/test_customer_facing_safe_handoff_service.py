from app.services.customer_facing_safe_handoff_service import (
    CUSTOMER_FACING_INTERNAL_REDLINE_TERMS,
    apply_customer_facing_safe_handoff,
    customer_facing_safe_handoff_reply,
)
from app.services.customer_reply_polisher import polish_customer_reply


def _assert_no_internal_redline(reply: str):
    for term in CUSTOMER_FACING_INTERNAL_REDLINE_TERMS:
        assert term not in reply


def test_material_safety_handoff_is_customer_facing_without_unsafe_claims():
    policy = {
        "requires_human_review": True,
        "reply_strategy": "verify_material_safety_for_known_product",
        "reply": "我这边不直接说无毒或有证书，有依据再发您参考。",
        "forbidden_claims": ["无毒", "有证书", "绝对安全"],
    }

    result = apply_customer_facing_safe_handoff(policy, {"query_fact_type": "material"})
    reply = result["reply"]

    assert result["requires_human_review"] is True
    assert result["forbidden_claims"] == policy["forbidden_claims"]
    assert "材质" in reply
    assert "检测说明" in reply
    assert "避免说错" in reply
    assert "准确回复" in reply
    assert "无毒" not in reply
    assert "有证书" not in reply
    _assert_no_internal_redline(reply)


def test_child_safety_handoff_is_natural_without_age_or_safety_promise():
    reply = customer_facing_safe_handoff_reply("age_range")

    assert "宝宝适用" in reply
    assert "适用年龄" in reply
    assert "核对" in reply
    assert "避免说错" in reply
    assert "适合0-6岁" not in reply
    assert "保护宝宝安全" not in reply
    _assert_no_internal_redline(reply)


def test_safe_handoff_does_not_expose_redacted_identifier_as_product_name():
    reply = customer_facing_safe_handoff_reply(
        "load_capacity",
        inputs={"product_title": "[LONG_ID_REDACTED:228d73b3a4]"},
    )

    assert "[LONG_ID_REDACTED" not in reply
    assert "这款商品" in reply
    assert "承重" in reply
    assert "结构说明" in reply
    assert "分散摆放" in reply
    _assert_no_internal_redline(reply)


def test_context_request_policy_is_not_overwritten_by_safe_handoff_copy():
    policy = {
        "requires_human_review": True,
        "reply_strategy": "request_product_context_for_material_safety",
        "reply": "亲，麻烦您发一下商品截图或SKU，我帮您核对材质说明。",
    }

    result = apply_customer_facing_safe_handoff(policy, {"query_fact_type": "material"})

    assert result["reply"] == policy["reply"]
    assert "商品截图" in result["reply"]
    assert "SKU" in result["reply"]


def test_polisher_translates_internal_safe_handoff_language_to_customer_copy():
    response = {
        "suggested_reply": (
            "亲，我这边不直接说无毒或有证书；您要确认材质、气味或检测证明的话，"
            "我按当前商品资料核对，有依据再发您参考。"
        ),
        "requires_human_review": True,
        "evidence_debug": {"query_fact_type": "material"},
    }

    polished = polish_customer_reply(response, customer_message="这个材质有毒吗")
    reply = polished["suggested_reply"]

    assert polished["requires_human_review"] is True
    assert "材质" in reply
    assert "检测说明" in reply
    assert "避免说错" in reply
    assert "准确回复" in reply
    _assert_no_internal_redline(reply)
