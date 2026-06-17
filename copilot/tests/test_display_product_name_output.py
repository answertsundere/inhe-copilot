from app.services.customer_reply_polisher import polish_customer_reply
from app.services.final_answer_auditor import audit_final_answer


PLATFORM_TITLE = "英禾防夹滑门收纳架整理客厅零食桌面儿童玩具卧室可拼搭储物抽屉"
INTERNAL_NAME = "九号防夹滑门收纳柜"


def test_polisher_replaces_internal_name_with_platform_title():
    response = {
        "product_name": INTERNAL_NAME,
        "matched_product_name": INTERNAL_NAME,
        "suggested_reply": f"亲～您担心「{INTERNAL_NAME}」的气味问题很正常，建议先通风后使用。",
    }

    result = polish_customer_reply(
        response,
        customer_message="有没有味道",
        copilot_context={"display_product_name": PLATFORM_TITLE},
    )

    assert INTERNAL_NAME not in result["suggested_reply"]
    assert PLATFORM_TITLE in result["suggested_reply"]
    assert result["display_product_name"] == PLATFORM_TITLE


def test_final_answer_auditor_fallback_uses_platform_title():
    response = {
        "product_name": INTERNAL_NAME,
        "matched_product_name": INTERNAL_NAME,
        "suggested_reply": f"亲～关于「{INTERNAL_NAME}」的小零件/电池安全，我先帮您核对。",
        "evidence_debug": {"query_fact_type": "pinch_safety"},
    }

    result = audit_final_answer(
        response,
        customer_message="这个会不会夹手？",
        copilot_context={"platform_product_title": PLATFORM_TITLE},
    )

    assert result["final_answer_audit"]["passed"] is False
    assert INTERNAL_NAME not in result["suggested_reply"]
    assert PLATFORM_TITLE in result["suggested_reply"]


def test_safety_fallback_is_customer_facing_not_internal_process():
    response = {
        "product_name": INTERNAL_NAME,
        "matched_product_name": INTERNAL_NAME,
        "suggested_reply": f"亲～关于「{INTERNAL_NAME}」的小零件/电池安全，我先帮您核对。",
        "evidence_debug": {"query_fact_type": "pinch_safety"},
    }

    result = audit_final_answer(
        response,
        customer_message="家里有宝宝，这个会不会夹手？",
        copilot_context={"display_product_name": PLATFORM_TITLE},
    )

    reply = result["suggested_reply"]
    assert "夹手" in reply
    assert "宝宝" in reply
    assert "确认清楚后" not in reply
    assert "系统" not in reply
    assert "资料库" not in reply
