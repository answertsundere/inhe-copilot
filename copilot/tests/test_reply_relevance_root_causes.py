"""Regression tests for upstream causes of irrelevant replies."""

import pytest
import importlib

from app.agent.graph import _route_after_knowledge_scope
from app.agent.nodes.evidence_builder import _profile_fact_text, evidence_builder
from app.agent.nodes.generate_reply import _real_product_facts
from app.agent.nodes.response_strategy_router import response_strategy_router
from app.agent.nodes.router_validation import router_validation
from app.models.reply import ReplySuggestion
from app.services.fact_type_service import classify_query_fact_type


@pytest.mark.parametrize(
    ("intent", "message"),
    [
        ("invoice", "这个订单可以开电子发票吗？"),
        ("price_protection", "这个订单还能申请价保吗？"),
        ("promotion_query", "现在拍这个有什么优惠吗？"),
        ("stock_query", "这个今天拍还有货吗？"),
    ],
)
def test_product_context_does_not_override_policy_intent(intent, message):
    result = router_validation({
        "normalized_message": message,
        "intent": intent,
        "router_decision": {"intent": intent},
        "router_source": "rule",
        "matched_product_name": "一号小熊床护栏",
        "product_candidates": [{"value": "一号小熊床护栏"}],
        "slots": {},
        "trace_steps": [],
    })

    assert result["intent"] == intent


def test_book_count_is_classified_as_load_capacity():
    result = classify_query_fact_type("可以放多少本绘本？", "product_question")

    assert result["query_fact_type"] == "load_capacity"


def test_pinched_child_is_classified_as_safety_fact():
    result = classify_query_fact_type("宝宝用的时候被夹到了，你们这个是不是有质量问题？", "aftersales")

    assert result["query_fact_type"] == "pinch_safety"


def test_pressure_bend_question_is_classified_as_load_capacity():
    result = classify_query_fact_type("可以放很多绘本和玩具吗？会不会压弯？", "product_question")

    assert result["query_fact_type"] == "load_capacity"


def test_profile_installation_does_not_fall_back_to_capacity():
    text, missing = _profile_fact_text(
        {
            "product_name": "3号云屋收纳柜",
            "specs": {
                "weight": "8.58",
                "load_capacity": "",
                "install_method": "",
            },
        },
        "installation",
        "我要安装视频",
    )

    assert text == ""
    assert "安装方式" in missing
    assert "承重/容量" not in text
    assert "8.58" not in text


def test_profile_load_capacity_never_uses_product_weight():
    text, missing = _profile_fact_text(
        {
            "product_name": "水龙头延长器",
            "specs": {
                "weight": "0.15",
                "load_capacity": "",
            },
        },
        "load_capacity",
        "可以放多少本绘本？",
    )

    assert text == ""
    assert "承重/容量" in missing
    assert "0.15" not in text


def test_product_card_load_capacity_never_uses_product_weight():
    text, missing = _profile_fact_text(
        {
            "product_name": "九号防夹滑门收纳柜",
            "specs": {
                "weight": "2.65",
                "load_capacity": "",
            },
        },
        "load_capacity",
        "可以放很多绘本和玩具吗？会不会压弯？",
        source="product_cards",
    )

    assert text == ""
    assert "承重/容量" in missing
    assert "2.65" not in text


def test_gift_missing_with_order_does_not_ask_for_order_screenshot():
    from app.agent.nodes.generate_reply import _gift_missing_reply

    reply = _gift_missing_reply({
        "order_id": "6926666820903533935",
        "evidence": {"order_facts": [{"order_id": "6926666820903533935"}]},
    })

    assert "按这笔订单" in reply or "按当前订单" in reply
    assert "订单截图" not in reply
    assert "活动页面" in reply


def test_pinched_aftersales_reply_uses_order_and_product_context():
    from app.agent.nodes.generate_reply import _aftersales_reply

    reply = _aftersales_reply({
        "normalized_message": "宝宝用的时候被夹到了，你们这个是不是有质量问题？",
        "order_id": "6926666820903533935",
        "query_fact_type": "safety_small_parts",
        "order_product_identity": {
            "matched_product_name": "九号防夹滑门收纳柜",
        },
    })

    assert "九号防夹滑门收纳柜" in reply
    assert "6926666820903533935" in reply
    assert "暂停" in reply
    assert "稍等" in reply
    assert "订单号" not in reply


def test_blocked_product_fact_is_not_renderable():
    facts = _real_product_facts({
        "query_fact_type": "installation",
        "evidence": {
            "product_facts": [
                {
                    "source_type": "product_facts",
                    "fact": "承重/容量: 8.58",
                    "evidence_fact_type": "installation",
                    "evidence_allowed_for_direct_answer": False,
                    "reference_only": True,
                },
            ],
        },
    })

    assert facts == []


def test_aftersales_required_tool_routes_to_tool_planner_before_rag():
    assert _route_after_knowledge_scope({
        "response_strategy": "aftersales",
        "required_tools": ["jst_lookup_outbound_tool"],
        "tool_results": {},
    }) == "tool_planner"


def test_aftersales_with_order_requires_jst_lookup():
    result = response_strategy_router({
        "customer_message": "宝宝用的时候被夹到了，你们这个是不是有质量问题？",
        "normalized_message": "宝宝用的时候被夹到了，你们这个是不是有质量问题？",
        "intent": "aftersales",
        "risk_level": "medium",
        "query_fact_type": "safety_small_parts",
        "order_id": "6926666820903533935",
        "slots": {
            "identifier_type": "platform_trade_id",
            "platform_trade_id": "6926666820903533935",
        },
        "trace_steps": [],
    })

    assert result["response_strategy"] == "aftersales"
    assert "jst_lookup_outbound_tool" in result["required_tools"]
    assert "product_facts" in result["allowed_source_types"]
    assert "faq" in result["allowed_source_types"]


def test_aftersales_does_not_repeat_already_attempted_tool():
    assert _route_after_knowledge_scope({
        "response_strategy": "aftersales",
        "required_tools": ["jst_lookup_outbound_tool"],
        "tool_results": {"jst_lookup_outbound_tool": {"found": False}},
    }) == "rag_retrieve"


def test_product_category_conflict_blocks_rag_before_generation():
    result = response_strategy_router({
        "customer_message": "可以放多少本绘本？",
        "normalized_message": "可以放多少本绘本？",
        "intent": "product_question",
        "risk_level": "low",
        "matched_product_name": "1号快乐鲸鱼水龙头延长器",
        "order_product_identity": {
            "status": "resolved",
            "matched_product_name": "1号快乐鲸鱼水龙头延长器",
            "category_l3": "水龙头延长器",
        },
        "slots": {},
        "trace_steps": [],
    })

    assert result["response_strategy"] == "clarification"
    assert result["should_query_knowledge"] is False
    assert result["required_tools"] == []
    assert result["product_context_validation"]["mismatch"] is True


def test_tool_registry_rag_results_still_pass_the_fact_gate():
    result = evidence_builder({
        "intent": "installation",
        "query_fact_type": "installation",
        "tool_results": {
            "rag_search_tool": {
                "chunks": [{
                    "source_type": "product_facts",
                    "chunk_text": "\u627f\u91cd/\u5bb9\u91cf: 8.58",
                    "fact_type": "load_capacity",
                    "entry_status": "published",
                    "score": 0.9,
                    "rerank_score": 0.9,
                    "metadata": {"auto_reply_allowed": True},
                }],
            },
        },
        "trace_steps": [],
    })

    fact = result["evidence"]["product_facts"][0]
    assert fact["direct_answer_allowed"] is False
    assert "wrong_fact_type" in fact["gate_reasons"]
    assert _real_product_facts(result) == []


def test_risky_installation_evidence_is_sanitized_not_discarded():
    result = evidence_builder({
        "intent": "installation",
        "query_fact_type": "installation",
        "tool_results": {
            "rag_search_tool": {
                "chunks": [{
                    "source_type": "installation_guide",
                    "chunk_text": "\u5b89\u88c5\u5f88\u65b9\u4fbf\uff0c\u4e0d\u9700\u8981\u989d\u5916\u5de5\u5177\u3002",
                    "fact_type": "installation",
                    "entry_status": "published",
                    "score": 0.9,
                    "rerank_score": 0.9,
                    "metadata": {"auto_reply_allowed": True},
                }],
            },
        },
        "trace_steps": [],
    })

    fact = result["evidence"]["product_facts"][0]
    assert fact["sanitization_applied"] is True
    assert fact["direct_answer_allowed"] is True
    assert "\u5b89\u88c5\u5f88\u65b9\u4fbf" not in fact["fact"]
    assert "\u4e0d\u9700\u8981\u989d\u5916\u5de5\u5177" not in fact["fact"]


def test_installation_faq_extra_tool_variant_is_sanitized():
    result = evidence_builder({
        "intent": "installation",
        "query_fact_type": "installation",
        "tool_results": {
            "rag_search_tool": {
                "chunks": [{
                    "source_type": "faq",
                    "chunk_text": "\u4e0d\u9700\u8981\u989d\u5916\u51c6\u5907\u5de5\u5177\u3002",
                    "fact_type": "installation",
                    "entry_status": "published",
                    "score": 0.9,
                    "rerank_score": 0.9,
                    "metadata": {"auto_reply_allowed": True},
                }],
            },
        },
        "trace_steps": [],
    })

    fact = result["evidence"]["faq_evidence"][0]
    assert fact["sanitization_applied"] is True
    assert "\u4e0d\u9700\u8981\u989d\u5916\u51c6\u5907\u5de5\u5177" not in fact["fact"]


def test_tool_registry_rag_chunks_are_not_counted_twice():
    chunk = {
        "chunk_id": "chunk-1",
        "entry_id": "entry-1",
        "source_type": "faq",
        "chunk_text": "\u6309\u8bf4\u660e\u4e66\u6b65\u9aa4\u5b89\u88c5\u3002",
        "fact_type": "installation",
        "query_fact_type": "installation",
        "evidence_fact_type": "installation",
        "entry_status": "published",
        "score": 0.9,
        "rerank_score": 0.9,
        "gate_status": "allowed",
        "gate_reasons": [],
        "reference_only": False,
        "evidence_allowed_for_exact_answer": True,
        "evidence_allowed_for_direct_answer": True,
    }
    result = evidence_builder({
        "intent": "installation",
        "query_fact_type": "installation",
        "knowledge_evidence": [chunk],
        "tool_results": {"rag_search_tool": {"chunks": [chunk]}},
        "trace_steps": [],
    })

    assert len(result["evidence"]["faq_evidence"]) == 1


def test_known_local_product_does_not_wait_for_jst_name_lookup(monkeypatch):
    resolver = importlib.import_module("app.agent.nodes.order_product_resolver")
    local_identity = {
        "status": "resolved",
        "source": "sidecar_product_name",
        "identifier": "3\u53f7\u4e91\u5c4b\u6536\u7eb3\u67dc",
        "identifier_type": "product_name",
        "matched_product_name": "3\u53f7\u4e91\u5c4b\u6536\u7eb3\u67dc",
        "confidence": 1.0,
    }
    monkeypatch.setattr(
        resolver,
        "_resolve_product_name_from_local",
        lambda state: local_identity,
    )

    def unexpected_jst_lookup(state):
        raise AssertionError("JST name lookup should be a fallback")

    monkeypatch.setattr(resolver, "_resolve_product_name_via_jst", unexpected_jst_lookup)
    result = resolver.order_product_resolver({
        "conversation_id": "local-first-regression",
        "matched_product_name": "3\u53f7\u4e91\u5c4b\u6536\u7eb3\u67dc",
        "product_candidates": [{
            "value": "3\u53f7\u4e91\u5c4b\u6536\u7eb3\u67dc",
        }],
        "slots": {},
        "trace_steps": [],
    })

    assert result["order_product_identity"]["status"] == "resolved"
    assert result["order_product_identity"]["source"] == "sidecar_product_name"


def test_pure_tracking_request_defers_lookup_to_identifier_router(monkeypatch):
    resolver = importlib.import_module("app.agent.nodes.order_product_resolver")

    def unexpected_lookup(*args, **kwargs):
        raise AssertionError("product resolver must not query JST for pure logistics")

    monkeypatch.setattr(
        "app.integrations.jst.live_query.lookup_order_by_identifier",
        unexpected_lookup,
    )
    result = resolver.order_product_resolver({
        "intent": "logistics_trace",
        "customer_message": "SF0229477422177 \u5230\u54ea\u4e86",
        "normalized_message": "SF0229477422177 \u5230\u54ea\u4e86",
        "tracking_no": "SF0229477422177",
        "slots": {
            "tracking_no": "SF0229477422177",
            "identifier_type": "tracking_no",
        },
        "trace_steps": [],
    })

    assert "order_product_identity" not in result
    assert result["trace_steps"][-1]["status"] == "skipped"
    assert "identifier tool router" in result["trace_steps"][-1]["summary"]


def test_reply_model_keeps_runtime_debug_contract():
    result = ReplySuggestion.from_dict({
        "suggested_reply": "ok",
        "answer_mode": "exact_faq_answer",
        "generation_mode": "rule_based",
        "llm_used": False,
        "used_knowledge_entry_ids": ["812"],
        "used_knowledge_titles": ["faq"],
        "used_fact_tools": ["rag_search_tool"],
        "product_context_validation": {"mismatch": False},
    }).to_dict()

    assert result["answer_mode"] == "exact_faq_answer"
    assert result["used_knowledge_entry_ids"] == ["812"]
    assert result["used_fact_tools"] == ["rag_search_tool"]
    assert result["product_context_validation"]["mismatch"] is False
