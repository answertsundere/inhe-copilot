from app.services.final_answer_auditor import audit_final_answer


def test_final_auditor_corrects_mismatched_reply_with_generic_rule():
    response = {
        "intent": "product_question",
        "display_product_name": "\u82f1\u79be\u9632\u5939\u6ed1\u95e8\u6536\u7eb3\u67b6",
        "suggested_reply": "\u4eb2\uff5e\u8fd9\u6b3e\u5355\u5c42\u627f\u91cd\u7ea615-30kg\uff0c\u653e\u4e66\u7c4d\u73a9\u5177\u90fd\u591f\u7528\u3002",
        "requires_human_review": False,
        "context_used": {
            "product_context_pack": {
                "generic_rules": [
                    {
                        "rule_key": "placement_scene_dry_area_v1",
                        "title": "\u6446\u653e\u573a\u666f\u4fdd\u5b88\u5efa\u8bae",
                        "fact_type": "placement_scene",
                        "risk_level": "low",
                        "auto_reply_allowed": True,
                        "score": 10.0,
                        "reply_template": (
                            "\u4eb2\uff5e{product_display}\u653e\u5728\u5367\u5ba4\u3001\u5ba2\u5385\u3001\u4e66\u623f"
                            "\u8fd9\u7c7b\u65e5\u5e38\u6536\u7eb3\u533a\u57df\u4e00\u822c\u662f\u53ef\u4ee5\u53c2\u8003\u7684\u3002"
                        ),
                    }
                ],
                "evidence_pack": {
                    "matched_generic_rules": [
                        {"rule_key": "placement_scene_dry_area_v1", "fact_type": "placement_scene", "score": 10.0}
                    ]
                },
            }
        },
        "evidence_debug": {"query_fact_type": "placement_scene"},
    }

    audited = audit_final_answer(response, customer_message="\u5367\u5ba4\u53ef\u4ee5\u7528\u5417")

    assert audited["final_answer_audit"]["passed"] is False
    assert audited["final_answer_audit"]["correction_source"] == "generic_service_rule"
    assert audited["requires_human_review"] is False
    assert "\u5367\u5ba4" in audited["suggested_reply"]
    assert "\u627f\u91cd" not in audited["suggested_reply"]
