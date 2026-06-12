import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.agent.nodes.generate_reply import generate_reply
from app.agent.nodes.build_response import build_response
from app.agent.nodes.gold_csr_reply_builder import gold_csr_reply_builder
from app.agent.nodes.hallucination_guard import hallucination_guard


def _faq_state(message, entry_id, title, content, product_name=""):
    chunk = {
        "chunk_id": f"chunk-{entry_id}",
        "entry_id": entry_id,
        "title": title,
        "source_type": "faq",
        "intent": "product_question",
        "score": 0.92,
        "chunk_text": content,
        "confidence": "low",
        "reference_only": False,
        "needs_human_review": False,
    }
    return {
        "customer_message": message,
        "normalized_message": message,
        "intent": "product_question",
        "risk_level": "low",
        "matched_product_name": product_name,
        "filtered_evidence": [chunk],
        "knowledge_evidence": [chunk],
        "evidence": {
            "product_facts": [],
            "faq_evidence": [
                {
                    "fact": content,
                    "source_type": "faq",
                    "confidence": "low",
                    "reference_only": False,
                }
            ],
            "policy_facts": [],
            "sop_evidence": [],
            "template_evidence": [],
            "unknowns": [],
            "conflicts": [],
        },
        "knowledge": [{"title": title, "content": content}],
        "trace_steps": [],
    }


def test_six_anti_fall_pillow_uses_exact_faq_without_llm():
    content = "六号防摔枕材质是什么？能洗吗？面料可以清洗，清洗后自然晾干即可。"
    state = _faq_state(
        "六号防摔枕材质是什么？能洗吗？",
        812,
        "六号防摔枕材质是什么？能洗吗？",
        content,
        "六号防摔枕",
    )

    result = generate_reply(state)
    guarded = hallucination_guard({**state, **result})

    assert result["answer_mode"] == "exact_faq_answer"
    assert result["llm_used"] is False
    assert result["generation_mode"] == "rule_based"
    assert 812 in result["used_knowledge_entry_ids"]
    assert guarded["hallucination_guard"]["passed"] is True
    reply = guarded["suggested_reply"]
    assert content in reply
    assert "优质填充棉" not in reply
    assert "记忆棉" not in reply
    assert "枕芯采用" not in reply


def test_lion_bib_keeps_faq_facts_only():
    content = "一号狮子围兜采用防水面料，日常湿布一擦即可，也可以水冲后晾干；底部有接漏袋。"
    state = _faq_state(
        "一号狮子围兜防水吗？",
        701,
        "一号狮子围兜防水吗？",
        content,
        "一号狮子围兜",
    )

    result = generate_reply(state)
    guarded = hallucination_guard({**state, **result})
    reply = guarded["suggested_reply"]

    assert result["answer_mode"] == "exact_faq_answer"
    assert "防水面料" in reply
    assert "湿布一擦" in reply
    assert "水冲" in reply
    assert "晾干" in reply
    assert "接漏袋" in reply
    assert guarded["hallucination_guard"]["passed"] is True


def test_faq_age_answer_is_not_rewritten_by_factual_guard():
    from app.agent.nodes.factual_guard import factual_guard

    content = "亲，这款枕头适合1岁以上的宝宝使用，高度设计符合婴幼儿颈椎发育特点。注意1岁以内的宝宝不建议使用枕头，以确保呼吸通畅和安全～"
    state = _faq_state(
        "这款十一号防摔枕适合多大宝宝？",
        813,
        "这款十一号防摔枕适合多大宝宝？",
        content,
        "十一号防摔枕",
    )

    result = generate_reply(state)
    guarded = hallucination_guard({**state, **result})
    checked = factual_guard({**state, **result, **guarded})

    assert result["answer_mode"] == "exact_faq_answer"
    assert "适合1岁以上" in checked["suggested_reply"]
    assert "高度设计" in checked["suggested_reply"]
    assert "商品链接" not in checked["suggested_reply"]
    assert checked["guard_warnings"] == []


def test_gold_csr_does_not_overwrite_locked_faq_answer():
    state = {
        "suggested_reply": "亲亲，关于您咨询的一号狮子围兜：一号狮子围兜采用防水面料。",
        "answer_mode": "exact_faq_answer",
        "response_strategy_plan": {"reply_goal": "answer_product_fact"},
        "trace_steps": [],
    }

    result = gold_csr_reply_builder(state)

    assert result["suggested_reply"] == state["suggested_reply"]
    assert result["gold_csr_applied"] is False


def test_gold_csr_clarifies_when_product_identity_is_unclear_even_if_rag_matched():
    state = {
        "suggested_reply": "亲亲，关于您咨询的实木：某个商品采用实木材质。",
        "answer_mode": "exact_faq_answer",
        "response_strategy_plan": {"reply_goal": "clarify_product_identity"},
        "trace_steps": [],
    }

    result = gold_csr_reply_builder(state)

    assert result["gold_csr_applied"] is True
    assert result["answer_mode"] == "no_evidence_clarification"
    assert "商品链接" in result["suggested_reply"]
    assert "SKU" in result["suggested_reply"]


def test_product_question_without_evidence_asks_for_identifier():
    state = {
        "customer_message": "这个儿童书架是不是实木的？",
        "normalized_message": "这个儿童书架是不是实木的？",
        "intent": "product_question",
        "risk_level": "low",
        "evidence": {"product_facts": [], "faq_evidence": [], "unknowns": []},
        "filtered_evidence": [],
        "knowledge_evidence": [],
        "trace_steps": [],
    }

    result = generate_reply(state)
    reply = result["suggested_reply"]

    assert result["answer_mode"] == "no_evidence_clarification"
    assert result["llm_used"] is False
    assert "商品链接" in reply
    assert "截图" in reply
    assert "订单号" in reply
    assert "实木" not in reply
    assert "商品详情页未标注" not in reply


def test_product_question_without_evidence_acknowledges_resolved_product_identity():
    state = {
        "customer_message": "这款适合多大宝宝？",
        "normalized_message": "这款适合多大宝宝？",
        "intent": "product_question",
        "risk_level": "low",
        "answer_mode": "no_evidence_clarification",
        "order_product_identity": {
            "status": "resolved",
            "matched_product_name": "二号飞鱼划水玩具",
            "i_id": "YH78K02",
            "source": "jst_product_name_query",
        },
        "evidence": {"product_facts": [], "faq_evidence": [], "unknowns": []},
        "filtered_evidence": [],
        "knowledge_evidence": [],
        "trace_steps": [],
    }

    result = generate_reply(state)
    reply = result["suggested_reply"]

    assert "二号飞鱼划水玩具" in reply
    assert "商品链接" not in reply
    assert "截图" not in reply
    assert "SKU" not in reply
    assert "核实" in reply


def test_hallucination_guard_blocks_unsupported_product_terms():
    state = {
        "suggested_reply": "亲亲，这款防摔枕枕芯采用优质填充棉和记忆棉。",
        "answer_mode": "policy_answer",
        "generation_mode": "llm_grounded",
        "intent": "product_question",
        "evidence": {"product_facts": [], "faq_evidence": [], "unknowns": []},
        "filtered_evidence": [],
        "knowledge_evidence": [],
        "trace_steps": [],
    }

    result = hallucination_guard(state)

    assert result["answer_mode"] == "no_evidence_clarification"
    assert result["generation_mode"] == "llm_fallback_blocked"
    assert result["hallucination_guard"]["passed"] is False
    assert result["hallucination_guard"]["fallback_used"] is True
    assert "填充棉" in result["hallucination_guard"]["unsupported_terms"]
    assert "记忆棉" in result["hallucination_guard"]["unsupported_terms"]
    assert "商品链接" in result["suggested_reply"]


def test_legacy_policy_mode_resolves_to_policy_grounded_answer():
    state = {
        "customer_message": "超过七天还能退吗？",
        "normalized_message": "超过七天还能退吗？",
        "intent": "refund",
        "answer_mode": "policy",
        "risk_level": "low",
        "evidence": {
            "policy_facts": [
                {"fact": "售后政策需以订单状态和平台规则核实后处理。", "source_type": "policy"}
            ],
            "product_facts": [],
            "faq_evidence": [],
            "unknowns": [],
        },
        "filtered_evidence": [],
        "knowledge_evidence": [],
        "trace_steps": [],
    }

    result = generate_reply(state)

    assert result["answer_mode"] == "policy_grounded_answer"


def test_evidence_debug_exposes_grounded_generation_fields():
    state = {
        "suggested_reply": "亲亲，关于您咨询的问题：FAQ 原文。",
        "answer_mode": "exact_faq_answer",
        "generation_mode": "rule_based",
        "llm_used": False,
        "hallucination_guard": {
            "passed": True,
            "unsupported_terms": [],
            "fallback_used": False,
        },
        "used_knowledge_entry_ids": [812],
        "used_knowledge_titles": ["六号防摔枕材质是什么？能洗吗？"],
        "evidence": {"faq_evidence": [{"fact": "FAQ 原文。", "source_type": "faq"}]},
        "trace_steps": [],
    }

    result = build_response(state)
    debug = result["evidence_debug"]

    assert debug["answer_mode"] == "exact_faq_answer"
    assert debug["generation_mode"] == "rule_based"
    assert debug["llm_used"] is False
    assert debug["hallucination_guard"]["passed"] is True
    assert debug["hallucination_guard"]["unsupported_terms"] == []
    assert debug["hallucination_guard"]["fallback_used"] is False
    assert debug["used_knowledge_entry_ids"] == [812]
    assert debug["used_knowledge_titles"] == ["六号防摔枕材质是什么？能洗吗？"]
