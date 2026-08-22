from app.agent.nodes.generate_reply import _odor_reply, _real_product_facts, _render_exact_faq, _render_product_facts


def test_odor_product_facts_prioritize_specific_no_odor_evidence():
    state = {
        "query_fact_type": "odor",
        "evidence": {
            "product_facts": [
                {
                    "entry_id": "kbproduct:1",
                    "chunk_id": "kbproduct:1:odor",
                    "source_type": "product_facts",
                    "fact": "\u6c14\u5473\u8bf4\u660e: \u65b0\u54c1\u5bc6\u5c01\u5305\u88c5\u6253\u5f00\u540e\u53ef\u80fd\u4f1a\u6709\u8f7b\u5fae\u5305\u88c5\u6216\u8fd0\u8f93\u6c14\u5473\u3002",
                    "evidence_fact_type": "odor",
                    "evidence_allowed_for_direct_answer": True,
                    "direct_answer_allowed": True,
                    "score": 20,
                }
            ]
        },
        "knowledge_evidence": [
            {
                "entry_id": "kbqa:1403",
                "chunk_id": "kbqa:1403:0",
                "source_type": "faq",
                "chunk_text": "\u6750\u8d28\u8bf4\u660e: \u91c7\u7528\u98df\u54c1\u7ea7HDPE/PP\u73af\u4fdd\u6750\u6599\uff0c\u65e0\u6bd2\u65e0\u5473\u3002",
                "evidence_fact_type": "odor",
                "evidence_allowed_for_direct_answer": True,
                "direct_answer_allowed": True,
                "score": 2,
            }
        ],
    }

    facts = _real_product_facts(state)

    assert facts
    assert facts[0]["entry_id"] == "kbqa:1403"
    assert "\u65e0\u6bd2\u65e0\u5473" in facts[0]["chunk_text"]


def test_odor_reply_uses_specific_odor_sentence_before_other_material_details():
    state = {
        "query_fact_type": "odor",
        "evidence": {
            "product_facts": [
                {
                    "entry_id": "kbqa:1403",
                    "source_type": "faq",
                    "chunk_text": (
                        "\u4eb2\u8bf7\u653e\u5fc3\uff0c\u6211\u4eec\u91c7\u7528\u7684\u662f"
                        "\u98df\u54c1\u7ea7HDPE/PP\u73af\u4fdd\u6750\u6599\uff0c"
                        "\u901a\u8fc7\u56fd\u5bb63C\u8ba4\u8bc1\uff0c\u65e0\u6bd2\u65e0\u5473\uff0c"
                        "\u4e0d\u542bBPA\u7b49\u6709\u5bb3\u7269\u8d28\u3002"
                        "\u8868\u9762\u5149\u6ed1\u65e0\u6bdb\u523a\uff0c\u4e0d\u4f1a\u5212\u4f24\u5b9d\u5b9d\u5a07\u5ae9\u7684\u76ae\u80a4\u3002"
                    ),
                    "evidence_fact_type": "odor",
                    "evidence_allowed_for_direct_answer": True,
                    "direct_answer_allowed": True,
                    "score": 10,
                }
            ]
        },
    }

    reply = _render_product_facts(state, "\u4e00\u53f7\u5c0f\u718a\u5e8a\u62a4\u680f")

    assert "\u5173\u4e8e\u8fd9\u6b3e\u300c\u4e00\u53f7\u5c0f\u718a\u5e8a\u62a4\u680f\u300d\u7684\u6c14\u5473" in reply
    assert "\u65e0\u6bd2\u65e0\u5473" in reply
    assert "\u5546\u54c1\u8d44\u6599\u5e93" not in reply
    assert "\u72b6\u6001: published" not in reply
    assert reply.index("\u65e0\u6bd2\u65e0\u5473") < reply.index("\u8868\u9762\u5149\u6ed1") if "\u8868\u9762\u5149\u6ed1" in reply else True


def test_exact_faq_odor_reply_does_not_move_non_odor_sentence_first():
    faq = {
        "entry_id": "kbqa:1403",
        "source_type": "faq",
        "fact": (
            "\u4eb2\u8bf7\u653e\u5fc3\uff0c\u6211\u4eec\u91c7\u7528\u7684\u662f"
            "\u98df\u54c1\u7ea7HDPE/PP\u73af\u4fdd\u6750\u6599\uff0c"
            "\u901a\u8fc7\u56fd\u5bb63C\u8ba4\u8bc1\uff0c\u65e0\u6bd2\u65e0\u5473\uff0c"
            "\u4e0d\u542bBPA\u7b49\u6709\u5bb3\u7269\u8d28\u3002"
            "\u8868\u9762\u5149\u6ed1\u65e0\u6bdb\u523a\uff0c\u4e0d\u4f1a\u5212\u4f24\u5b9d\u5b9d\u5a07\u5ae9\u7684\u76ae\u80a4\u3002"
        ),
        "evidence_fact_type": "odor",
    }

    reply = _render_exact_faq(faq, "\u4e00\u53f7\u5c0f\u718a\u5e8a\u62a4\u680f", {"query_fact_type": "odor"})

    assert "\u5173\u4e8e\u8fd9\u6b3e\u300c\u4e00\u53f7\u5c0f\u718a\u5e8a\u62a4\u680f\u300d\u7684\u6c14\u5473" in reply
    assert "\u65e0\u6bd2\u65e0\u5473" in reply
    assert not reply.splitlines()[1].startswith("\u8868\u9762\u5149\u6ed1")


def test_exact_product_hub_dimension_reply_keeps_attribute_label_with_value():
    state = {
        "query_fact_type": "dimensions",
        "evidence": {
            "product_facts": [
                {
                    "entry_id": "product_data_hub:dimension-1",
                    "chunk_id": "product_data_hub:dimension-1",
                    "source_type": "product_facts",
                    "protocol_source_type": "product_data_hub",
                    "title": "尺寸",
                    "chunk_text": "36.5x22cm",
                    "evidence_fact_type": "dimensions",
                    "evidence_allowed_for_direct_answer": True,
                    "direct_answer_allowed": True,
                }
            ]
        },
    }

    reply = _render_product_facts(state, "测试商品")

    assert "尺寸：36.5x22cm" in reply


def test_odor_fallback_is_customer_facing_without_verify_handoff():
    reply = _odor_reply({"query_fact_type": "odor"})

    assert "通风" in reply
    assert "暂停使用" in reply
    assert "拍照" in reply or "视频" in reply
    assert "绝对没有" not in reply
    assert "0甲醛" not in reply
    assert "核实" not in reply
    assert "确认清楚" not in reply
    assert "转人工" not in reply
