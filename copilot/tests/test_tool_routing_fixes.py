"""
Tests for tool routing, product resolution, and RAG scope fixes.

These tests reproduce the reported bugs:
A. Installation strategy missing rag_search_tool
B. Single low-confidence candidate treated as ambiguous → all tools killed
C. response_strategy_router overrides decision_fusion required_tools
D. RAG scope missing product_id/sku_id
E. System asks for already-provided information
F. Route invariants: required ∩ forbidden = ∅, required ⊆ allowed
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
import unittest.mock as mock


# ---------------------------------------------------------------------------
# A. Installation strategy must include rag_search_tool
# ---------------------------------------------------------------------------

class TestInstallationStrategyTools:
    """installation strategy must require product_resolver_tool AND rag_search_tool"""

    def _route(self, intent="installation", **kwargs):
        from app.agent.nodes.response_strategy_router import response_strategy_router
        state = {
            "intent": intent,
            "risk_level": kwargs.get("risk_level", "low"),
            "slots": {
                "identifier_type": kwargs.get("identifier_type", ""),
                "platform_trade_id": kwargs.get("platform_trade_id", ""),
                "order_id": kwargs.get("order_id", ""),
                "tracking_no": kwargs.get("tracking_no", ""),
                "possible_numeric_id": "",
                "product_name": kwargs.get("product_name", ""),
            },
            "is_logistics_time_commitment": False,
            "order_product_identity": kwargs.get("order_product_identity", {}),
            "trace_steps": [],
        }
        return response_strategy_router(state)

    def test_installation_requires_product_resolver(self):
        result = self._route()
        assert "product_resolver_tool" in result["required_tools"], \
            f"installation must require product_resolver_tool, got {result['required_tools']}"

    def test_installation_requires_rag_search(self):
        """Bug: installation only requires product_resolver_tool, missing rag_search_tool"""
        result = self._route()
        assert "rag_search_tool" in result["required_tools"], \
            f"installation must require rag_search_tool, got {result['required_tools']}"

    def test_installation_allowed_includes_rag(self):
        result = self._route()
        assert "rag_search_tool" in result["allowed_tools"]

    def test_installation_source_types_include_installation_guide(self):
        result = self._route()
        assert "installation_guide" in result["allowed_source_types"]

    def test_installation_source_types_include_product_facts(self):
        result = self._route()
        assert "product_facts" in result["allowed_source_types"]

    def test_installation_with_order_id_includes_jst_tool(self):
        """When installation has an order_id, the correct JST tool should be allowed/required"""
        result = self._route(identifier_type="platform_trade_id", platform_trade_id="5116887975001001001")
        assert "jst_lookup_outbound_tool" in result["required_tools"]
        assert "product_resolver_tool" in result["required_tools"]
        assert "rag_search_tool" in result["required_tools"]


# ---------------------------------------------------------------------------
# B. Single low-confidence candidate must NOT kill all tools
# ---------------------------------------------------------------------------

class TestSingleCandidateNotAmbiguous:
    """A single product candidate with low confidence should not block all tools"""

    def _make_identity(self, status="ambiguous", source="sidecar_product_name", candidates=None):
        return {
            "status": status,
            "source": source,
            "identifier": "test",
            "identifier_type": "product_name",
            "reason": "low_confidence_single_match",
            "confidence": 0.3,
            "candidates": candidates or [{"name": "A2号收纳柜", "sku_id": "YH06K39B02S06", "i_id": "YH06K39"}],
        }

    def test_single_candidate_ambiguous_does_not_kill_tools(self):
        """When there's only 1 candidate, even if ambiguous, tools should NOT be fully forbidden"""
        from app.agent.nodes.response_strategy_router import response_strategy_router
        identity = self._make_identity(candidates=[
            {"name": "A2号收纳柜", "sku_id": "YH06K39B02S06", "i_id": "YH06K39"}
        ])
        state = {
            "intent": "product_question",
            "risk_level": "low",
            "slots": {"identifier_type": "", "platform_trade_id": "", "order_id": "", "tracking_no": "",
                      "possible_numeric_id": "", "product_name": ""},
            "is_logistics_time_commitment": False,
            "order_product_identity": identity,
            "trace_steps": [],
        }
        result = response_strategy_router(state)
        # Tools should NOT be completely empty
        assert len(result["required_tools"]) > 0 or len(result["allowed_tools"]) > 0, \
            "Single candidate should not kill all tools"

    def test_two_candidates_ambiguous_kills_tools(self):
        """When there are 2+ different candidates, tools should be killed for clarification"""
        from app.agent.nodes.response_strategy_router import response_strategy_router
        identity = self._make_identity(candidates=[
            {"name": "A2号收纳柜", "sku_id": "YH06K39B02S06", "i_id": "YH06K39"},
            {"name": "B3号书架", "sku_id": "YH04K22B01S01", "i_id": "YH04K22"},
        ])
        state = {
            "intent": "product_question",
            "risk_level": "low",
            "slots": {"identifier_type": "", "platform_trade_id": "", "order_id": "", "tracking_no": "",
                      "possible_numeric_id": "", "product_name": ""},
            "is_logistics_time_commitment": False,
            "order_product_identity": identity,
            "trace_steps": [],
        }
        result = response_strategy_router(state)
        # Two different candidates → clarification
        assert result["required_tools"] == []
        assert result["answer_mode"] == "no_evidence_clarification"


# ---------------------------------------------------------------------------
# C. Route invariants
# ---------------------------------------------------------------------------

class TestRouteInvariants:
    """required_tools ∩ forbidden_tools must be empty; required ⊆ allowed"""

    def _route(self, intent, risk_level="low", identifier_type="", **kwargs):
        from app.agent.nodes.response_strategy_router import response_strategy_router
        state = {
            "intent": intent,
            "risk_level": risk_level,
            "slots": {
                "identifier_type": identifier_type,
                "platform_trade_id": kwargs.get("platform_trade_id", ""),
                "order_id": kwargs.get("order_id", ""),
                "tracking_no": kwargs.get("tracking_no", ""),
                "possible_numeric_id": "",
                "product_name": "",
            },
            "is_logistics_time_commitment": False,
            "order_product_identity": kwargs.get("order_product_identity", {}),
            "trace_steps": [],
        }
        return response_strategy_router(state)

    @pytest.mark.parametrize("intent,risk_level,identifier_type", [
        ("product_question", "low", ""),
        ("installation", "low", ""),
        ("installation", "low", "platform_trade_id"),
        ("logistics_eta", "low", "platform_trade_id"),
        ("logistics_eta", "low", "internal_order_id"),
        ("logistics_eta", "low", "tracking_no"),
        ("complaint", "high", ""),
        ("aftersales", "low", ""),
        ("general", "low", ""),
    ])
    def test_required_not_in_forbidden(self, intent, risk_level, identifier_type):
        result = self._route(intent, risk_level, identifier_type)
        required = set(result["required_tools"])
        forbidden = set(result["forbidden_tools"])
        overlap = required & forbidden
        assert overlap == set(), \
            f"{intent}: required ∩ forbidden = {overlap}"

    @pytest.mark.parametrize("intent,risk_level,identifier_type", [
        ("product_question", "low", ""),
        ("installation", "low", ""),
        ("installation", "low", "platform_trade_id"),
        ("logistics_eta", "low", "platform_trade_id"),
        ("complaint", "high", ""),
        ("aftersales", "low", ""),
    ])
    def test_required_subset_of_allowed(self, intent, risk_level, identifier_type):
        result = self._route(intent, risk_level, identifier_type)
        required = set(result["required_tools"])
        allowed = set(result["allowed_tools"])
        missing = required - allowed
        assert missing == set(), \
            f"{intent}: required not in allowed: {missing}"

    @pytest.mark.parametrize("intent", ["product_question", "installation"])
    def test_product_installation_require_resolver_and_rag(self, intent):
        result = self._route(intent)
        assert "product_resolver_tool" in result["required_tools"], \
            f"{intent} must require product_resolver_tool"
        assert "rag_search_tool" in result["required_tools"], \
            f"{intent} must require rag_search_tool"


# ---------------------------------------------------------------------------
# D. plan_tools invariant: ambiguous guard only for multi-candidate
# ---------------------------------------------------------------------------

class TestPlanToolsAmbiguousGuard:
    """plan_tools should only skip tools when truly ambiguous (multiple candidates)"""

    def test_single_candidate_does_not_skip_tools(self):
        from app.agent.tools.executor import plan_tools
        state = {
            "normalized_message": "怎么让它自动感应",
            "intent": "product_question",
            "slots": {"identifier_type": "", "platform_trade_id": "", "order_id": "", "tracking_no": ""},
            "allowed_tools": ["product_resolver_tool", "rag_search_tool", "template_select_tool"],
            "required_tools": ["product_resolver_tool", "rag_search_tool"],
            "forbidden_tools": [],
            "allowed_source_types": ["product_facts", "faq"],
            "order_product_identity": {
                "source": "sidecar_product_name",
                "status": "ambiguous",
                "candidates": [{"name": "A2号收纳柜", "sku_id": "YH06K39B02S06", "i_id": "YH06K39"}],
            },
            "trace_steps": [],
        }
        with mock.patch("app.agent.tools.executor._try_llm_tool_selection", return_value=None):
            result = plan_tools(state)
        assert len(result["tool_plan"]) > 0, "Single candidate should not skip all tools"

    def test_multi_candidate_skips_tools(self):
        from app.agent.tools.executor import plan_tools
        state = {
            "normalized_message": "怎么让它自动感应",
            "intent": "product_question",
            "slots": {"identifier_type": "", "platform_trade_id": "", "order_id": "", "tracking_no": ""},
            "allowed_tools": ["product_resolver_tool", "rag_search_tool", "template_select_tool"],
            "required_tools": ["product_resolver_tool", "rag_search_tool"],
            "forbidden_tools": [],
            "allowed_source_types": ["product_facts", "faq"],
            "order_product_identity": {
                "source": "sidecar_product_name",
                "status": "ambiguous",
                "candidates": [
                    {"name": "A2号收纳柜", "i_id": "YH06K39"},
                    {"name": "B3号书架", "i_id": "YH04K22"},
                ],
            },
            "trace_steps": [],
        }
        with mock.patch("app.agent.tools.executor._try_llm_tool_selection", return_value=None):
            result = plan_tools(state)
        assert len(result["tool_plan"]) == 0, "Multi-candidate ambiguous should skip all tools"


# ---------------------------------------------------------------------------
# E. RAG scope includes product_id and sku_id
# ---------------------------------------------------------------------------

class TestRAGScopeIncludesIdentifiers:
    """RAG scope should include product_id and sku_id from order_product_identity"""

    def test_rag_retrieve_uses_product_id_in_scope(self):
        from app.agent.nodes.rag_retrieve import rag_retrieve
        state = {
            "should_query_knowledge": True,
            "normalized_message": "怎么让它自动感应",
            "customer_message": "怎么让它自动感应",
            "intent": "product_question",
            "allowed_source_types": ["product_facts", "faq"],
            "matched_product_name": "A2号收纳柜",
            "product_candidates": [
                {"name": "A2号收纳柜", "sku_id": "YH06K39B02S06", "i_id": "YH06K39"},
            ],
            "slots": {"sku_code": "YH06K39B02S06"},
            "trace_steps": [],
        }

        with mock.patch("app.retrieval.retriever_factory.get_retriever") as mock_factory:
            mock_retriever = mock.MagicMock()
            mock_retriever.retrieve.return_value = []
            mock_factory.return_value = mock_retriever

            rag_retrieve(state)

            call_args = mock_retriever.retrieve.call_args
            product_scope = call_args.kwargs.get("product_scope") or call_args[1].get("product_scope", [])
            sku_scope = call_args.kwargs.get("sku_scope") or call_args[1].get("sku_scope", [])

            # Product scope should include the product name
            assert "A2号收纳柜" in product_scope
            # SKU scope should include the sku_id
            assert "YH06K39B02S06" in sku_scope


# ---------------------------------------------------------------------------
# F. Already-provided info not re-requested
# ---------------------------------------------------------------------------

class TestNoReRequestKnownInfo:
    """generate_reply should not ask for info already in state"""

    def test_with_sku_does_not_ask_for_sku(self):
        from app.agent.nodes.generate_reply import _resolve_answer_mode
        state = {
            "intent": "product_question",
            "answer_mode": "product_answer",
            "knowledge_evidence": [],
            "filtered_evidence": [],
            "retrieved_chunks": [],
            "slots": {"sku_code": "YH06K39B02S06", "product_name": "A2号收纳柜"},
            "matched_product_name": "A2号收纳柜",
            "order_product_identity": {
                "status": "resolved",
                "sku_id": "YH06K39B02S06",
                "i_id": "YH06K39",
            },
            "trace_steps": [],
        }
        mode = _resolve_answer_mode(state)
        # When there's no evidence, it should say "no evidence for this product"
        # not "please provide SKU"
        if mode == "no_evidence_clarification":
            # The clarification should acknowledge the known product
            from app.agent.nodes.generate_reply import generate_reply
            result = generate_reply(state)
            reply = result.get("suggested_reply", "")
            assert "YH06K39" not in reply or "已识别" in reply or "已找到" in reply or "已经" in reply, \
                f"Should not ask for SKU when already known: {reply}"


# ---------------------------------------------------------------------------
# G. Installation chain goes through tool_planner
# ---------------------------------------------------------------------------

class TestInstallationUsesToolPlanner:
    """Installation strategy should route through tool_planner → tool_executor → rag"""

    def test_installation_has_rag_in_required(self):
        """Direct check: installation required_tools includes rag_search_tool"""
        from app.agent.nodes.response_strategy_router import response_strategy_router
        state = {
            "intent": "installation",
            "risk_level": "low",
            "slots": {
                "identifier_type": "platform_trade_id",
                "platform_trade_id": "5116887975001001001",
                "order_id": "",
                "tracking_no": "",
                "possible_numeric_id": "",
                "product_name": "感应灯",
            },
            "is_logistics_time_commitment": False,
            "order_product_identity": {},
            "trace_steps": [],
        }
        result = response_strategy_router(state)
        assert "rag_search_tool" in result["required_tools"]
        assert "product_resolver_tool" in result["required_tools"]
        assert "jst_lookup_outbound_tool" in result["required_tools"]

    def test_installation_plan_includes_rag(self):
        """plan_tools with installation state should include rag_search_tool in plan"""
        from app.agent.tools.executor import plan_tools
        state = {
            "normalized_message": "怎么让它自动感应",
            "intent": "installation",
            "slots": {
                "identifier_type": "platform_trade_id",
                "platform_trade_id": "5116887975001001001",
                "order_id": "",
                "tracking_no": "",
            },
            "allowed_tools": [
                "jst_lookup_outbound_tool", "product_resolver_tool",
                "rag_search_tool", "template_select_tool",
            ],
            "required_tools": ["jst_lookup_outbound_tool", "product_resolver_tool", "rag_search_tool"],
            "forbidden_tools": ["jst_lookup_order_tool", "jst_lookup_tracking_tool"],
            "allowed_source_types": ["installation_guide", "product_facts", "faq"],
            "matched_product_name": "",
            "product_candidates": [],
            "trace_steps": [],
        }
        with mock.patch("app.agent.tools.executor._try_llm_tool_selection", return_value=None):
            result = plan_tools(state)
        tool_names = [c["tool_name"] for c in result["tool_plan"]]
        assert "rag_search_tool" in tool_names, f"rag_search_tool missing from plan: {tool_names}"
        assert "product_resolver_tool" in tool_names
        assert "jst_lookup_outbound_tool" in tool_names
