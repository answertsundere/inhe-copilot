from app.services.final_answer_auditor import audit_final_answer


def test_final_answer_auditor_accepts_customer_facing_odor_reply():
    response = {
        "intent": "product_question",
        "product_name": "\u4e00\u53f7\u5c0f\u718a\u5e8a\u62a4\u680f",
        "suggested_reply": (
            "\u4eb2\uff5e\n"
            "\u8fd9\u6b3e\u6750\u8d28\u8bf4\u660e\u91cc\u5199\u5230\u662f\u73af\u4fddPP\u6750\u6599\uff0c\u65e0\u6bd2\u65e0\u5473\u3002\n"
            "\u65b0\u54c1\u5bc6\u5c01\u5305\u88c5\u6253\u5f00\u540e\u5982\u679c\u6709\u8f7b\u5fae\u5305\u88c5\u6c14\u5473\uff0c"
            "\u653e\u5728\u901a\u98ce\u5904\u6563\u4e00\u4e0b\u5c31\u53ef\u4ee5\u3002"
        ),
        "requires_human_review": False,
        "evidence_debug": {"query_fact_type": "odor"},
    }

    audited = audit_final_answer(
        response,
        customer_message="\u4ea7\u54c1\u6709\u6c14\u5473\u5417",
    )

    assert audited["final_answer_audit"]["passed"] is True
    assert audited["requires_human_review"] is False
