"""
test_execution_debug — Phase 1A 测试

覆盖:
1. API 返回完整 execution_debug 顶层结构
2. routing 有 final_intent
3. tool_calls 能区分 planned 与 executed
4. JST成功/失败/超时正确记录
5. RAG retrieved/used/rejected 正确区分
6. citations 不由 LLM 伪造
7. guards 正确记录 fallback
8. total_ms 使用真实请求耗时
9. versions 不为空
10. 敏感信息不泄漏
"""

import json
import pytest
from unittest.mock import patch, MagicMock

from app.services.execution_debug_builder import (
    build_execution_debug,
    _mask_sensitive,
    _mask_id,
    _build_tool_calls,
    _build_rag,
    _build_citations,
    _build_guards,
    _build_timing,
    _build_outcome,
    _build_versions,
    _build_routing,
    _build_generation,
)
from app.models.reply import ReplySuggestion


# ========== Fixtures ==========

def _sample_graph_result():
    """典型 LangGraph 执行结果。"""
    return {
        "customer_message": "帮我查一下订单",
        "intent": "logistics_eta",
        "risk_level": "low",
        "customer_emotion": "焦急",
        "suggested_reply": "亲，您的订单已发货，快递单号 SF1234，预计明天到。",
        "response_strategy": "logistics_with_order",
        "answer_mode": "logistics_fact_answer",
        "generation_mode": "rule_based",
        "llm_used": False,
        "requires_human_review": False,
        "router_source": "tool_registry",
        "router_reason": "platform_trade_id identified",
        "router_confidence": 0.95,
        "matched_product_name": "刺猬桌面书架",
        "order_status": "shipped",
        "identifier_type": "platform_trade_id",
        "used_fact_tool": "jst_lookup_outbound_tool",
        "used_endpoint": "/open/orders/out/simple",
        "allowed_source_types": ["faq", "product_facts"],
        "rag_retrieval_mode": "hybrid",
        "used_knowledge_entry_ids": [812],
        "used_knowledge_titles": ["六号防摔枕材质"],
        "slots": {"product_name": "刺猬桌面书架", "sku_name": "YH115K06B01S03"},
        "safety_contract": {"passed": True},
        "hallucination_guard": {"passed": True, "unsupported_terms": [], "fallback_used": False},
        "live_order": {
            "o_id": "123",
            "status": "shipped",
            "logistics_company": "顺丰",
            "l_id": "SF1234",
        },
        "logistics_trace": {
            "status": "in_transit",
            "carrier": "顺丰",
            "tracking_no": "SF1234",
        },
        "evidence": {
            "order_facts": [{"fact": "订单已发货", "source_type": "jst_sales_out", "confidence": "high"}],
            "logistics_facts": [{"fact": "顺丰 SF1234", "source_type": "jst_logistics", "confidence": "high"}],
            "product_facts": [{"fact": "材质: PP塑料", "source_type": "product_facts", "confidence": "high"}],
            "policy_facts": [],
            "sop_evidence": [],
            "template_evidence": [],
            "faq_evidence": [],
            "unknowns": [],
            "conflicts": [],
        },
        "knowledge_evidence": [
            {
                "entry_id": 812,
                "chunk_id": "c812_1",
                "title": "六号防摔枕材质是什么？能洗吗？",
                "source_type": "faq",
                "chunk_text": "六号防摔枕采用PP塑料，可水洗。",
                "score": 0.82,
                "rerank_score": 0.86,
                "confidence": "high",
            },
        ],
        "retrieved_chunks": [
            {
                "entry_id": 812,
                "chunk_id": "c812_1",
                "title": "六号防摔枕材质是什么？能洗吗？",
                "source_type": "faq",
                "chunk_text": "六号防摔枕采用PP塑料，可水洗。",
                "score": 0.82,
                "rerank_score": 0.86,
            },
            {
                "entry_id": 999,
                "chunk_id": "c999_1",
                "title": "不相关条目",
                "source_type": "faq",
                "chunk_text": "这个不应该被采用。",
                "score": 0.3,
                "rejection_reasons": ["low_score"],
            },
        ],
        "tool_results": {
            "jst_lookup_outbound_tool": {
                "found": True,
                "o_id": "123",
                "status": "shipped",
                "logistics_company": "顺丰",
                "l_id": "SF1234",
                "endpoint": "/open/orders/out/simple",
            },
        },
        "tool_traces": [
            {
                "node": "tool_executor",
                "tool_name": "jst_lookup_outbound_tool",
                "status": "success",
                "duration_ms": 483,
                "provider": "tool_registry",
                "input_summary": {"outer_so_id": "5116887975001001001"},
                "output_summary": {"found": True, "o_id": "123"},
                "can_create_fact_types": ["order_facts", "logistics_facts"],
            },
        ],
        "tool_plan": [
            {"tool_name": "jst_lookup_outbound_tool", "inputs": {"outer_so_id": "5116887975001001001"}},
        ],
        "trace_steps": [
            {"node": "normalize_input", "step": "normalize_input", "status": "success", "duration_ms": 1},
            {"node": "detect_intent", "status": "success", "duration_ms": 2},
            {"node": "risk_check", "status": "success", "duration_ms": 1},
            {"node": "tool_planner", "status": "success", "duration_ms": 5},
            {"node": "tool_executor", "status": "success", "duration_ms": 483, "tools_executed": 1},
            {"node": "evidence_builder", "status": "success", "duration_ms": 3},
            {"node": "hallucination_guard", "status": "success", "duration_ms": 1, "passed": True},
            {"node": "factual_guard", "status": "success", "duration_ms": 1, "passed": True},
            {"node": "quality_guard", "status": "success", "duration_ms": 1, "passed": True},
            {"node": "human_review_gate", "status": "success", "duration_ms": 0},
        ],
        "evidence_debug": {
            "answer_mode": "logistics_fact_answer",
            "generation_mode": "rule_based",
            "jst_duration_ms": 483,
            "rag_duration_ms": 38,
            "llm_duration_ms": 0,
            "llm_used": False,
            "used_knowledge_entry_ids": [812],
            "used_knowledge_titles": ["六号防摔枕材质"],
        },
        "guard_warnings": [],
        "allowed_tools": ["jst_lookup_outbound_tool"],
        "required_tools": ["jst_lookup_outbound_tool"],
        "forbidden_tools": [],
    }


# ========== Test 1: 完整顶层结构 ==========

class TestExecutionDebugSchema:
    def test_full_top_level_structure(self):
        result = _sample_graph_result()
        ed = build_execution_debug(result, request_duration_ms=600)

        expected_keys = [
            "request", "versions", "routing", "tool_calls",
            "rag", "citations", "generation", "guards", "timing", "outcome",
        ]
        for key in expected_keys:
            assert key in ed, f"Missing top-level key: {key}"

    def test_request_has_required_fields(self):
        result = _sample_graph_result()
        ed = build_execution_debug(result, request_id="req-001", message_id="msg-001",
                                   conversation_id="conv-001", scenario="after_sale")
        req = ed["request"]
        assert req["request_id"] == "req-001"
        assert req["message_id"] == "msg-001"
        assert req["conversation_id"] == "conv-001"
        assert req["scenario"] == "after_sale"

    def test_request_id_stable(self):
        result = _sample_graph_result()
        ed = build_execution_debug(result, request_id="fixed-id")
        assert ed["request"]["request_id"] == "fixed-id"


# ========== Test 2: routing 有 final_intent ==========

class TestRouting:
    def test_routing_has_final_intent(self):
        result = _sample_graph_result()
        ed = build_execution_debug(result)
        routing = ed["routing"]
        assert routing["final_intent"] == "logistics_eta"
        assert routing["risk_level"] == "low"
        assert routing["selected_route"] == "logistics_with_order"
        assert routing["answer_mode"] == "logistics_fact_answer"
        assert routing["need_human_review"] is False

    def test_routing_shows_intent_journey(self):
        result = _sample_graph_result()
        result["parallel_understanding"] = {"intent": "general"}
        result["decision_fusion"] = {"final_intent": "logistics_eta"}
        ed = build_execution_debug(result)
        routing = ed["routing"]
        assert routing["old_intent"] == "general"
        assert routing["fusion_final_intent"] == "logistics_eta"


# ========== Test 3: tool_calls 区分 planned 与 executed ==========

class TestToolCalls:
    def test_planned_and_executed(self):
        result = _sample_graph_result()
        ed = build_execution_debug(result)
        tc = ed["tool_calls"]
        assert len(tc) >= 1
        # The executed tool should have status "success"
        outbound = [t for t in tc if t["tool_name"] == "jst_lookup_outbound_tool"]
        assert len(outbound) == 1
        assert outbound[0]["status"] == "success"
        assert outbound[0]["found"] is True
        assert outbound[0]["duration_ms"] == 483

    def test_planned_not_executed_shows_skipped(self):
        result = _sample_graph_result()
        # Add a planned tool that wasn't executed
        result["tool_plan"] = result["tool_plan"] + [
            {"tool_name": "rag_search_tool", "inputs": {"query": "test"}}
        ]
        result["tool_traces"] = []  # No traces = nothing executed
        result["tool_results"] = {}

        calls = _build_tool_calls([], {}, result)
        not_executed = [c for c in calls if c["status"] in ("skipped", "planned")]
        assert len(not_executed) >= 1
        ne_names = [c["tool_name"] for c in not_executed]
        assert "rag_search_tool" in ne_names


# ========== Test 4: JST 成功/失败/超时 ==========

class TestJSTStatus:
    def test_jst_success(self):
        result = _sample_graph_result()
        ed = build_execution_debug(result)
        jst_calls = [t for t in ed["tool_calls"] if t["tool_name"].startswith("jst_lookup")]
        assert any(t["status"] == "success" and t["found"] for t in jst_calls)

    def test_jst_error(self):
        result = _sample_graph_result()
        result["tool_traces"] = [
            {
                "node": "tool_executor",
                "tool_name": "jst_lookup_outbound_tool",
                "status": "error",
                "duration_ms": 3000,
                "provider": "tool_registry",
                "input_summary": {},
                "error_code": "ConnectionError",
                "summary": "ConnectionError",
            }
        ]
        result["tool_results"] = {"jst_lookup_outbound_tool": {"error": "connection failed"}}
        ed = build_execution_debug(result)
        jst = [t for t in ed["tool_calls"] if t["tool_name"] == "jst_lookup_outbound_tool"]
        assert len(jst) == 1
        assert jst[0]["status"] == "error"
        assert jst[0]["found"] is False

    def test_jst_timeout(self):
        result = _sample_graph_result()
        result["tool_traces"] = [
            {
                "node": "tool_executor",
                "tool_name": "jst_lookup_order_tool",
                "status": "error",
                "duration_ms": 5000,
                "provider": "tool_registry",
                "input_summary": {},
                "error_code": "timeout",
                "summary": "timeout",
            }
        ]
        result["tool_results"] = {}
        ed = build_execution_debug(result)
        jst = [t for t in ed["tool_calls"] if t["tool_name"] == "jst_lookup_order_tool"]
        assert len(jst) == 1
        assert jst[0]["status"] == "error"
        assert jst[0]["error_code"] == "timeout"


# ========== Test 5: RAG retrieved/used/rejected ==========

class TestRAG:
    def test_rag_retrieved_used_rejected(self):
        result = _sample_graph_result()
        ed = build_execution_debug(result)
        rag = ed["rag"]
        assert rag["retrieval_mode"] == "hybrid"
        assert rag["metrics"]["retrieved_count"] >= 1
        assert rag["metrics"]["used_count"] >= 1
        assert rag["metrics"]["rejected_count"] >= 1

    def test_rag_no_results(self):
        result = _sample_graph_result()
        result["retrieved_chunks"] = []
        result["knowledge_evidence"] = []
        result["filtered_evidence"] = []
        result["used_knowledge_entry_ids"] = []
        ed = build_execution_debug(result)
        rag = ed["rag"]
        assert rag["metrics"]["retrieved_count"] == 0
        assert rag["metrics"]["used_count"] == 0


# ========== Test 6: citations 不由 LLM 伪造 ==========

class TestCitations:
    def test_citations_are_code_generated(self):
        result = _sample_graph_result()
        ed = build_execution_debug(result)
        for c in ed["citations"]:
            # Citation IDs should follow K<entry_id> or TOOL_<idx> pattern
            cid = c["citation_id"]
            assert cid.startswith("K") or cid.startswith("K_") or cid.startswith("T_") or cid.startswith("TOOL_"), f"Unexpected citation format: {cid}"

    def test_no_llm_generated_citation_ids(self):
        result = _sample_graph_result()
        ed = build_execution_debug(result)
        for c in ed["citations"]:
            # Should not have random-looking IDs that don't follow our patterns
            cid = c["citation_id"]
            assert not cid.startswith("cit_"), "LLM-generated citation detected"
            assert not cid.startswith("ref_"), "LLM-generated citation detected"

    def test_knowledge_citation_has_entry_id(self):
        result = _sample_graph_result()
        ed = build_execution_debug(result)
        k_citations = [c for c in ed["citations"] if c["citation_type"] == "knowledge"]
        # Should have citation for entry 812
        assert any(c["source_id"] == 812 for c in k_citations)

    def test_tool_citation(self):
        result = _sample_graph_result()
        ed = build_execution_debug(result)
        tool_citations = [c for c in ed["citations"] if c["citation_type"] == "tool_fact"]
        assert len(tool_citations) >= 1
        assert "order_status" in tool_citations[0]["fact_types"]


# ========== Test 7: guards 正确记录 fallback ==========

class TestGuards:
    def test_guards_list(self):
        result = _sample_graph_result()
        ed = build_execution_debug(result)
        guard_names = [g["guard_name"] for g in ed["guards"]]
        assert "risk_check" in guard_names
        assert "hallucination_guard" in guard_names

    def test_hallucination_guard_fallback(self):
        result = _sample_graph_result()
        result["hallucination_guard"] = {
            "passed": False,
            "unsupported_terms": ["记忆棉"],
            "fallback_used": True,
        }
        result["answer_mode"] = "exact_faq_answer"
        result["trace_steps"].append(
            {"node": "hallucination_guard", "status": "blocked", "duration_ms": 1}
        )
        ed = build_execution_debug(result)
        hg = [g for g in ed["guards"] if g["guard_name"] == "hallucination_guard"][0]
        assert hg["passed"] is False
        assert hg["details"]["unsupported_terms"] == ["记忆棉"]
        assert hg["details"]["fallback_used"] is True


# ========== Test 8: total_ms 使用真实请求耗时 ==========

class TestTiming:
    def test_total_ms_from_request_duration(self):
        result = _sample_graph_result()
        ed = build_execution_debug(result, request_duration_ms=617)
        assert ed["timing"]["total_ms"] == 617

    def test_total_ms_not_sum_of_parts(self):
        result = _sample_graph_result()
        ed = build_execution_debug(result, request_duration_ms=1000)
        timing = ed["timing"]
        # total_ms should be 1000 (the actual wall-clock), not a sum
        assert timing["total_ms"] == 1000

    def test_node_durations_populated(self):
        result = _sample_graph_result()
        ed = build_execution_debug(result)
        nd = ed["timing"]["node_durations"]
        assert "normalize_input" in nd
        assert nd["normalize_input"] > 0


# ========== Test 9: versions 不为空 ==========

class TestVersions:
    def test_versions_not_empty(self):
        result = _sample_graph_result()
        ed = build_execution_debug(result)
        v = ed["versions"]
        assert v["graph_version"]
        assert v["prompt_version"]
        assert v["routing_config_version"]
        assert v["model_name"]
        assert v["tool_registry_version"]
        assert v["app_version"]

    def test_versions_from_config(self):
        from app.config import GRAPH_VERSION, PROMPT_VERSION
        result = _sample_graph_result()
        ed = build_execution_debug(result)
        assert ed["versions"]["graph_version"] == GRAPH_VERSION
        assert ed["versions"]["prompt_version"] == PROMPT_VERSION


# ========== Test 10: 敏感信息不泄漏 ==========

class TestSensitiveData:
    def test_phone_number_masked(self):
        assert "****" in _mask_sensitive("13812345678")

    def test_no_api_key_in_result(self):
        result = _sample_graph_result()
        ed = build_execution_debug(result)
        json_str = json.dumps(ed, ensure_ascii=False)
        assert "JUSHUITAN_APP_KEY" not in json_str
        assert "JUSHUITAN_APP_SECRET" not in json_str
        assert "JUSHUITAN_ACCESS_TOKEN" not in json_str
        # Check no API key pattern
        assert "COPILOT_LLM_API_KEY" not in json_str

    def test_order_id_masking_configurable(self):
        with patch("app.services.execution_debug_builder.MASK_ORDER_IDS", True):
            assert "****" in _mask_id("5116887975001001001", True)

    def test_order_id_not_masked_by_default(self):
        assert _mask_id("5116887975001001001", False) == "5116887975001001001"

    def test_tool_input_no_full_api_response(self):
        result = _sample_graph_result()
        ed = build_execution_debug(result)
        for tc in ed["tool_calls"]:
            # tool input_summary should not contain raw JST response
            assert "access_token" not in json.dumps(tc.get("input_summary", {}))

    def test_request_candidates_masked_by_config(self):
        with patch("app.services.execution_debug_builder.MASK_ORDER_IDS", True):
            result = _sample_graph_result()
            copilot_ctx = {
                "order_candidates": [{"value": "5116887975001001001", "type": "platform_trade_id"}],
            }
            ed = build_execution_debug(result, copilot_context=copilot_ctx)
            # When masking is on, order IDs in candidates should be masked
            for oc in ed["request"]["order_candidates"]:
                if oc["value"]:
                    assert "****" in oc["value"]


# ========== Integration: ReplySuggestion ==========

class TestReplySuggestionWithExecutionDebug:
    def test_from_dict_with_execution_debug(self):
        data = {
            "intent": "general",
            "suggested_reply": "test",
            "execution_debug": {"request": {"request_id": "r1"}, "versions": {}},
        }
        suggestion = ReplySuggestion.from_dict(data)
        assert suggestion.execution_debug["request"]["request_id"] == "r1"

    def test_to_dict_includes_execution_debug(self):
        suggestion = ReplySuggestion(
            intent="general",
            suggested_reply="test",
            execution_debug={"request": {"request_id": "r1"}},
        )
        d = suggestion.to_dict()
        assert "execution_debug" in d

    def test_to_dict_omits_empty_execution_debug(self):
        suggestion = ReplySuggestion(intent="general", suggested_reply="test")
        d = suggestion.to_dict()
        assert "execution_debug" not in d
