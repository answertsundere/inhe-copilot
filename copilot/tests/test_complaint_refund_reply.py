from app.agent.nodes.generate_reply import generate_reply
from app.agent.nodes.reply_relevance_guard import reply_relevance_guard
from app.services.final_answer_auditor import audit_final_answer
from app.services.grounding_validation_service import validate_reply_grounding


def test_refund_complaint_with_order_does_not_request_irrelevant_photos():
    msg = "\u4e0d\u7ed9\u6211\u9000\u6b3e\u6211\u5c31\u6295\u8bc9\u3002"

    result = generate_reply({
        "normalized_message": msg,
        "customer_message": msg,
        "intent": "complaint",
        "answer_mode": "sop_human_review_answer",
        "risk_level": "high",
        "order_id": "6926666820903533935",
        "slots": {"platform_order_id": "6926666820903533935"},
        "trace_steps": [],
    })

    reply = result["suggested_reply"]
    assert "\u9000\u6b3e" in reply
    assert "\u8ba2\u5355\u4fe1\u606f" in reply
    assert "\u7a0d\u7b49" in reply
    assert "\u5b9e\u7269" not in reply
    assert "\u5916\u7bb1" not in reply
    assert "\u9762\u5355" not in reply
    assert "\u7167\u7247" not in reply
    assert result["answer_mode"] == "sop_human_review_answer"


def test_grounding_allows_refund_process_tracking_language():
    reply = (
        "\u4eb2\uff5e\u6211\u8fd9\u8fb9\u5df2\u7ecf\u770b\u5230\u60a8\u7ed9\u7684\u8ba2\u5355\u4fe1\u606f\u3002\n"
        "\u6211\u5148\u6838\u5bf9\u5f53\u524d\u8ba2\u5355\u7684\u552e\u540e\u8bb0\u5f55\u3001"
        "\u9000\u6b3e\u8fdb\u5ea6\u548c\u5e73\u53f0\u53ef\u5904\u7406\u8def\u5f84\uff0c\u9ebb\u70e6\u60a8\u7a0d\u7b49\u4e00\u4e0b\u3002"
    )
    result = validate_reply_grounding({
        "suggested_reply": reply,
        "intent": "complaint",
        "evidence": {},
        "filtered_evidence": [],
        "knowledge_evidence": [],
    })

    assert result["passed"] is True


def test_grounding_still_blocks_actual_refund_promise():
    result = validate_reply_grounding({
        "suggested_reply": "\u4eb2\uff5e\u5df2\u7ecf\u9000\u6b3e\u4e86\uff0c\u8bf7\u60a8\u6ce8\u610f\u67e5\u6536\u3002",
        "intent": "complaint",
        "evidence": {},
        "filtered_evidence": [],
        "knowledge_evidence": [],
    })

    assert result["passed"] is False
    assert any(c["fact_type"] == "aftersales_promise" for c in result["unsupported_claims"])


def test_relevance_guard_keeps_refund_complaint_handoff_with_order():
    msg = "\u4e0d\u7ed9\u6211\u9000\u6b3e\u6211\u5c31\u6295\u8bc9\u3002"
    reply = (
        "\u4eb2\uff5e\u6211\u7406\u89e3\u60a8\u7740\u6025\u60f3\u628a\u9000\u6b3e\u95ee\u9898\u5904\u7406\u597d\uff0c"
        "\u8fd9\u4e2a\u6211\u4f1a\u4f18\u5148\u5e2e\u60a8\u8ddf\u8fdb\u3002\n"
        "\u6211\u8fd9\u8fb9\u5df2\u7ecf\u770b\u5230\u60a8\u7ed9\u7684\u8ba2\u5355\u4fe1\u606f\uff0c"
        "\u4f1a\u76f4\u63a5\u6309\u8fd9\u7b14\u8ba2\u5355\u5e2e\u60a8\u6838\u5bf9\u3002\n"
        "\u6211\u5148\u6838\u5bf9\u5f53\u524d\u8ba2\u5355\u7684\u552e\u540e\u8bb0\u5f55\u3001"
        "\u9000\u6b3e\u8fdb\u5ea6\u548c\u5e73\u53f0\u53ef\u5904\u7406\u8def\u5f84\uff0c"
        "\u9ebb\u70e6\u60a8\u7a0d\u7b49\u4e00\u4e0b\u3002"
    )

    result = reply_relevance_guard({
        "normalized_message": msg,
        "customer_message": msg,
        "suggested_reply": reply,
        "intent": "complaint",
        "risk_level": "high",
        "order_id": "6926666820903533935",
        "slots": {"platform_order_id": "6926666820903533935"},
        "trace_steps": [],
    })

    assert result["reply_relevance_guard"]["passed"] is True
    assert result["suggested_reply"] == reply


def test_final_audit_allows_no_need_to_repeat_order_id_text(monkeypatch):
    monkeypatch.setattr(
        "app.config.COPILOT_FINAL_AUDIT_LLM_ENABLED",
        False,
        raising=False,
    )
    msg = "\u4e0d\u7ed9\u6211\u9000\u6b3e\u6211\u5c31\u6295\u8bc9\u3002"
    response = {
        "suggested_reply": (
            "\u4eb2\uff5e\u6211\u7406\u89e3\u60a8\u7740\u6025\u60f3\u628a\u9000\u6b3e\u95ee\u9898\u5904\u7406\u597d\u3002\n"
            "\u6211\u8fd9\u8fb9\u5df2\u7ecf\u770b\u5230\u60a8\u7ed9\u7684\u8ba2\u5355\u4fe1\u606f\uff0c"
            "\u4e0d\u7528\u60a8\u91cd\u590d\u63d0\u4f9b\u8ba2\u5355\u53f7\u3002\n"
            "\u6211\u5148\u6838\u5bf9\u552e\u540e\u8bb0\u5f55\u548c\u9000\u6b3e\u8fdb\u5ea6\uff0c\u9ebb\u70e6\u60a8\u7a0d\u7b49\u3002"
        ),
        "order_id": "6926666820903533935",
        "intent": "complaint",
        "evidence_debug": {"query_fact_type": "aftersales_policy"},
    }

    audited = audit_final_answer(
        response,
        customer_message=msg,
        copilot_context={"order_id": "6926666820903533935"},
    )

    assert audited["final_answer_audit"]["passed"] is True
