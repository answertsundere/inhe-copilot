"""
Tests for the full chain fixes:
1. response_strategy_router must not unconditionally clear tools
2. resolve_product_identity must use already-resolved identity
3. response_strategy_planner must not re-ask known info
4. product_resolver_tool must reuse resolved identity
5. RAG must use stable identifiers
6. Route invariants must hold

These tests reproduce the real bugs reported in production:
- Case 1: Product title with single candidate wrongly blocked
- Case 2: Installation + platform_trade_id + SKU → no tools
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
import unittest.mock as mock


# ============================================================================
# A. Product title scenario: single candidate should not be ambiguous
# ============================================================================

class TestProductTitleSingleCandidate:
    """Case A: 千牛完整商品标题 → single candidate → must NOT block tools"""

    def _make_sidecar_identity(self, status, candidates, source="sidecar_product_name"):
        return {
            "status": status,
            "source": source,
            "identifier": "英禾喂养台多功能收纳柜玩具柜婴儿用品带抽屉落地分格组合储物柜",
            "identifier_type": "product_name",
            "confidence": 0.35,
            "candidates": candidates,
        }

    def test_single_candidate_low_conf_not_ambiguous_in_router(self):
        """When order_product_identity has status=resolved with low_confidence,
        response_strategy_router must NOT block all tools."""
        from app.agent.nodes.response_strategy_router import response_strategy_router
        identity = self._make_sidecar_identity(
            status="resolved",
            candidates=[{"name": "A2号收纳柜", "sku_id": "YH06K39B02S06", "i_id": "YH06K39"}],
        )
        identity["low_confidence"] = True
        identity["reason"] = "low_confidence_single_match"
        state = {
            "intent": "product_question",
            "risk_level": "low",
            "slots": {"identifier_type": "", "platform_trade_id": "", "order_id": "",
                      "tracking_no": "", "possible_numeric_id": "", "product_name": ""},
            "is_logistics_time_commitment": False,
            "order_product_identity": identity,
            "trace_steps": [],
        }
        result = response_strategy_router(state)
        # Must NOT clear all tools
        assert "product_resolver_tool" in result["required_tools"], \
            f"product_question must require product_resolver_tool, got required={result['required_tools']}"
        assert "rag_search_tool" in result["required_tools"], \
            f"product_question must require rag_search_tool, got required={result['required_tools']}"
        # Invariant: required ∩ forbidden = ∅
        assert not (set(result["required_tools"]) & set(result["forbidden_tools"])), \
            f"required ∩ forbidden overlap: {set(result['required_tools']) & set(result['forbidden_tools'])}"

    def test_single_candidate_ambiguous_not_killing_tools(self):
        """Even if order_product_resolver mistakenly marks single candidate as ambiguous,
        response_strategy_router should not kill ALL tools (only product_resolver)."""
        from app.agent.nodes.response_strategy_router import response_strategy_router
        identity = self._make_sidecar_identity(
            status="ambiguous",
            candidates=[{"name": "A2号收纳柜", "sku_id": "YH06K39B02S06", "i_id": "YH06K39"}],
        )
        identity["reason"] = "ambiguous_sidecar_product_name"
        state = {
            "intent": "product_question",
            "risk_level": "low",
            "slots": {"identifier_type": "", "platform_trade_id": "", "order_id": "",
                      "tracking_no": "", "possible_numeric_id": "", "product_name": ""},
            "is_logistics_time_commitment": False,
            "order_product_identity": identity,
            "trace_steps": [],
        }
        result = response_strategy_router(state)
        # Single candidate ambiguous → should still allow some tools, not block everything
        # At minimum, required_tools should not be empty for product_question
        assert len(result["required_tools"]) > 0 or len(result["allowed_tools"]) > 0, \
            f"Single candidate should not block ALL tools. required={result['required_tools']}, allowed={result['allowed_tools']}"


# ============================================================================
# B. Platform trade ID + installation scenario
# ============================================================================

class TestPlatformTradeIdInstallation:
    """Case B: platform_trade_id + SKU + installation → must execute tools"""

    def test_installation_with_platform_trade_id_includes_jst(self):
        """When intent=installation and platform_trade_id exists,
        jst_lookup_outbound_tool must be in required_tools."""
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
        assert "jst_lookup_outbound_tool" in result["required_tools"], \
            f"installation + platform_trade_id must require jst_lookup_outbound_tool, got {result['required_tools']}"
        assert "product_resolver_tool" in result["required_tools"]
        assert "rag_search_tool" in result["required_tools"]
        # Invariant
        assert not (set(result["required_tools"]) & set(result["forbidden_tools"]))

    def test_installation_with_resolved_identity_keeps_tools(self):
        """Installation with already-resolved product identity must still run tools."""
        from app.agent.nodes.response_strategy_router import response_strategy_router
        identity = {
            "status": "resolved",
            "source": "jst_order_items",
            "matched_product_name": "感应灯",
            "sku_id": "YHXXXK01B01S01",
            "i_id": "YHXXXK01",
            "confidence": 0.95,
        }
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
            "order_product_identity": identity,
            "trace_steps": [],
        }
        result = response_strategy_router(state)
        assert "rag_search_tool" in result["required_tools"]
        assert "product_resolver_tool" in result["required_tools"]


# ============================================================================
# C. SKU exact match
# ============================================================================

class TestSKUExactMatch:
    """Case C: SKU exact match should resolve and not be ambiguous"""

    def test_sku_exact_in_order_product_resolver(self):
        """When SKU is provided, order_product_resolver should resolve it."""
        from app.agent.nodes.order_product_resolver import order_product_resolver
        state = {
            "customer_message": "怎么让它自动感应",
            "normalized_message": "怎么让它自动感应",
            "conversation_id": "test-sku",
            "slots": {
                "sku_code": "YHXXXK01B01S01",
                "sku_id": "YHXXXK01B01S01",
                "product_name": "感应灯",
                "identifier_type": "platform_trade_id",
                "platform_trade_id": "5116887975001001001",
                "order_id": "",
                "tracking_no": "",
                "possible_numeric_id": "",
            },
            "copilot_context": {},
            "conversation_context": {},
            "product_candidates": [],
            "trace_steps": [],
        }
        with mock.patch("app.agent.nodes.order_product_resolver._resolve_direct_product_code") as mock_resolve:
            mock_resolve.return_value = {
                "status": "resolved",
                "source": "sidecar_product_code",
                "identifier": "YHXXXK01B01S01",
                "identifier_type": "sku_id",
                "internal_product_name": "感应灯",
                "matched_product_name": "感应灯",
                "sku_id": "YHXXXK01B01S01",
                "i_id": "YHXXXK01",
                "confidence": 0.98,
                "reason": "matched_by_sidecar_product_code",
                "item_count": 0,
                "candidates": ["感应灯", "YHXXXK01B01S01", "YHXXXK01"],
            }
            result = order_product_resolver(state)

        identity = result.get("order_product_identity", {})
        assert identity.get("status") == "resolved", \
            f"SKU exact match should resolve, got status={identity.get('status')}"
        assert identity.get("sku_id") == "YHXXXK01B01S01"
        assert result.get("matched_product_name") == "感应灯"
        # Slots should be populated
        slots = result.get("slots", {})
        assert slots.get("sku_code") == "YHXXXK01B01S01"
        assert slots.get("product_name") == "感应灯"


# ============================================================================
# D. Single low-confidence candidate
# ============================================================================

class TestSingleLowConfidenceCandidate:
    """Case D: Single candidate with low confidence should NOT be treated as ambiguous"""

    def test_low_conf_single_candidate_is_resolved(self):
        """When _resolve_product_name_from_local finds only one distinct product,
        it should return status=resolved with low_confidence=True, not ambiguous."""
        from app.agent.nodes.order_product_resolver import _resolve_product_name_from_local
        state = {
            "customer_message": "为什么只能手动摆呢，我没找到，怎么让它自动感应",
            "normalized_message": "为什么只能手动摆呢，我没找到，怎么让它自动感应",
            "copilot_context": {
                "product_candidates": [
                    {"value": "英禾喂养台多功能收纳柜玩具柜婴儿用品带抽屉落地分格组合储物柜",
                     "type": "product_name"},
                ],
            },
            "product_candidates": [],
            "conversation_context": {},
            "trace_steps": [],
        }
        # Mock the local product database to return one product
        with mock.patch("app.main.get_product_knowledge_repo") as mock_pk, \
             mock.patch("app.main.get_product_repo") as mock_prod:
            mock_pk.return_value = mock.MagicMock(_cards=[
                {
                    "product_name": "A2号收纳柜",
                    "i_id": "YH06K39",
                    "sku_summary": {"sku_list": [{"sku_id": "YH06K39B02S06", "sku_name": "A2号收纳柜"}]},
                },
            ])
            mock_prod.return_value = mock.MagicMock(skus={})
            result = _resolve_product_name_from_local(state)

        assert result is not None
        # Should be resolved (single candidate), not ambiguous
        assert result.get("status") == "resolved", \
            f"Single candidate should be resolved, not {result.get('status')}: {result.get('reason')}"
        # Should NOT claim "multiple products"
        assert "多个" not in str(result.get("reason", "")), \
            f"Single candidate should not claim multiple products: {result.get('reason')}"

    def test_low_conf_single_candidate_allows_tools_in_router(self):
        """When order_product_identity is resolved with low_confidence,
        response_strategy_router should allow tools to proceed."""
        from app.agent.nodes.response_strategy_router import response_strategy_router
        identity = {
            "status": "resolved",
            "source": "sidecar_product_name",
            "identifier": "英禾喂养台多功能收纳柜玩具柜婴儿用品带抽屉落地分格组合储物柜",
            "identifier_type": "product_name",
            "internal_product_name": "A2号收纳柜",
            "matched_product_name": "A2号收纳柜",
            "sku_id": "YH06K39B02S06",
            "i_id": "YH06K39",
            "confidence": 0.35,
            "reason": "low_confidence_single_match",
            "low_confidence": True,
            "item_count": 1,
            "candidates": [{"name": "A2号收纳柜", "sku_id": "YH06K39B02S06", "i_id": "YH06K39"}],
        }
        state = {
            "intent": "product_question",
            "risk_level": "low",
            "slots": {"identifier_type": "", "platform_trade_id": "", "order_id": "",
                      "tracking_no": "", "possible_numeric_id": "", "product_name": "A2号收纳柜"},
            "is_logistics_time_commitment": False,
            "order_product_identity": identity,
            "trace_steps": [],
        }
        result = response_strategy_router(state)
        assert "product_resolver_tool" in result["required_tools"], \
            f"Low-confidence resolved should still allow tools. required={result['required_tools']}"
        assert "rag_search_tool" in result["required_tools"]


# ============================================================================
# E. Multi-candidate truly ambiguous
# ============================================================================

class TestMultiCandidateAmbiguous:
    """Case E: Multiple truly different candidates → clarification, not wrong-scope answer"""

    def test_two_different_products_are_ambiguous(self):
        """When there are 2+ distinct i_id candidates, should be ambiguous."""
        from app.agent.nodes.response_strategy_router import response_strategy_router
        identity = {
            "status": "ambiguous",
            "source": "sidecar_product_name",
            "identifier": "收纳柜",
            "identifier_type": "product_name",
            "reason": "ambiguous_sidecar_product_name",
            "confidence": 0.0,
            "candidates": [
                {"name": "A2号收纳柜", "sku_id": "YH06K39B02S06", "i_id": "YH06K39"},
                {"name": "B5号收纳柜", "sku_id": "YH05K12B01S01", "i_id": "YH05K12"},
            ],
        }
        state = {
            "intent": "product_question",
            "risk_level": "low",
            "slots": {"identifier_type": "", "platform_trade_id": "", "order_id": "",
                      "tracking_no": "", "possible_numeric_id": "", "product_name": ""},
            "is_logistics_time_commitment": False,
            "order_product_identity": identity,
            "trace_steps": [],
        }
        result = response_strategy_router(state)
        # Should go to clarification
        assert result["response_strategy"] == "clarification"
        assert result["answer_mode"] == "no_evidence_clarification"


# ============================================================================
# F. RAG no data scenario
# ============================================================================

class TestRAGNoData:
    """Case F: Tools resolve product but RAG returns 0 → must explain, not re-ask"""

    def test_rag_no_data_with_resolved_product(self):
        """When product is resolved but RAG has 0 results, should not re-ask for SKU."""
        from app.agent.nodes.rag_retrieve import rag_retrieve
        state = {
            "should_query_knowledge": True,
            "normalized_message": "怎么让它自动感应",
            "customer_message": "怎么让它自动感应",
            "intent": "installation",
            "allowed_source_types": ["installation_guide", "product_facts", "faq"],
            "matched_product_name": "感应灯",
            "product_candidates": [{"name": "感应灯", "sku_id": "YHXXXK01B01S01", "i_id": "YHXXXK01"}],
            "slots": {"sku_code": "YHXXXK01B01S01", "sku_name": "感应灯"},
            "order_product_identity": {
                "status": "resolved",
                "sku_id": "YHXXXK01B01S01",
                "i_id": "YHXXXK01",
            },
            "trace_steps": [],
        }
        with mock.patch("app.retrieval.retriever_factory.get_retriever") as mock_factory:
            mock_retriever = mock.MagicMock()
            mock_retriever.retrieve.return_value = []
            mock_factory.return_value = mock_retriever

            result = rag_retrieve(state)

        # RAG was executed (not skipped)
        assert result.get("retrieved_chunks") == []
        # Trace should show it was executed, not skipped
        traces = result.get("trace_steps", [])
        rag_trace = next((t for t in traces if t.get("node") == "rag_retrieve"), {})
        assert rag_trace.get("status") == "success", \
            f"RAG should be executed, not skipped. Got status={rag_trace.get('status')}"


# ============================================================================
# G. RAG with data scenario
# ============================================================================

class TestRAGWithData:
    """Case G: Published+ready knowledge should be correctly retrieved"""

    def test_rag_uses_sku_and_iid_in_scope(self):
        """RAG scope should include sku_id and i_id from order_product_identity."""
        from app.agent.nodes.rag_retrieve import rag_retrieve
        state = {
            "should_query_knowledge": True,
            "normalized_message": "怎么让它自动感应",
            "customer_message": "怎么让它自动感应",
            "intent": "product_question",
            "allowed_source_types": ["product_facts", "faq"],
            "matched_product_name": "感应灯",
            "product_candidates": [],
            "slots": {"sku_code": "YHXXXK01B01S01", "sku_name": "感应灯"},
            "order_product_identity": {
                "status": "resolved",
                "sku_id": "YHXXXK01B01S01",
                "i_id": "YHXXXK01",
            },
            "trace_steps": [],
        }
        with mock.patch("app.retrieval.retriever_factory.get_retriever") as mock_factory:
            mock_retriever = mock.MagicMock()
            mock_retriever.retrieve.return_value = []
            mock_factory.return_value = mock_retriever

            rag_retrieve(state)

            call_kwargs = mock_retriever.retrieve.call_args
            product_scope = call_kwargs.kwargs.get("product_scope") or call_kwargs[1].get("product_scope", [])
            sku_scope = call_kwargs.kwargs.get("sku_scope") or call_kwargs[1].get("sku_scope", [])

            # Must include product name
            assert "感应灯" in product_scope, f"product_scope missing name: {product_scope}"
            # Must include SKU and i_id
            assert "YHXXXK01B01S01" in sku_scope, f"sku_scope missing sku_id: {sku_scope}"

    def test_rag_keeps_facts_for_all_authoritative_requested_fact_types(self):
        from app.agent.nodes.rag_retrieve import _prefer_matching_fact_type

        results = [
            {"chunk_id": "dimensions", "fact_type": "dimensions"},
            {"chunk_id": "material", "fact_type": "material"},
            {"chunk_id": "unrequested", "fact_type": "load_capacity"},
        ]

        selected = _prefer_matching_fact_type(
            results,
            "dimensions",
            requested_fact_types=["dimensions", "material_composition"],
        )

        assert [item["chunk_id"] for item in selected] == ["dimensions", "material"]


# ============================================================================
# H. Route invariants for all strategies
# ============================================================================

class TestAllRouteInvariants:
    """required ∩ forbidden = ∅; required ⊆ allowed for all major strategies"""

    def _route(self, intent, **kwargs):
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

    @pytest.mark.parametrize("intent", [
        "product_question", "installation", "logistics_eta",
        "aftersales", "complaint", "general",
    ])
    def test_required_not_in_forbidden(self, intent):
        result = self._route(intent, risk_level="high" if intent == "complaint" else "low")
        required = set(result["required_tools"])
        forbidden = set(result["forbidden_tools"])
        overlap = required & forbidden
        assert overlap == set(), \
            f"{intent}: required ∩ forbidden = {overlap}"

    @pytest.mark.parametrize("intent", [
        "product_question", "installation", "logistics_eta",
        "aftersales", "complaint",
    ])
    def test_required_subset_of_allowed(self, intent):
        result = self._route(intent, risk_level="high" if intent == "complaint" else "low",
                             identifier_type="platform_trade_id" if intent == "logistics_eta" else "")
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


# ============================================================================
# I. resolve_product_identity uses already-resolved identity
# ============================================================================

class TestResolveProductIdentityUsesResolved:
    """resolve_product_identity must check order_product_identity before keyword matching"""

    def test_uses_already_resolved_identity(self):
        """When order_product_identity is resolved, resolve_product_identity should use it."""
        from app.agent.nodes.resolve_product_identity import resolve_product_identity
        state = {
            "normalized_message": "怎么让它自动感应",
            "customer_message": "怎么让它自动感应",
            "intent": "product_question",
            "slots": {"order_id": "", "possible_numeric_id": "", "product_name": "感应灯"},
            "matched_product_name": "感应灯",
            "order_product_identity": {
                "status": "resolved",
                "source": "jst_order_items",
                "matched_product_name": "感应灯",
                "sku_id": "YHXXXK01B01S01",
                "i_id": "YHXXXK01",
            },
            "trace_steps": [],
        }
        result = resolve_product_identity(state)
        assert result.get("matched_product_name") == "感应灯", \
            f"Should use resolved identity, got: {result.get('matched_product_name')}"
        assert not result.get("need_clarification"), \
            "Should not need clarification when identity is resolved"


# ============================================================================
# J. response_strategy_planner does not re-ask known info
# ============================================================================

class TestStrategyPlannerNoReAsk:
    """response_strategy_planner must not ask for already-provided information"""

    def test_with_resolved_identity_does_not_ask_for_sku(self):
        """When product identity is resolved, should not ask for SKU."""
        from app.agent.nodes.response_strategy_planner import response_strategy_planner
        state = {
            "intent": "product_question",
            "customer_concern": "unknown",
            "customer_state": {},
            "normalized_message": "怎么让它自动感应",
            "customer_message": "怎么让它自动感应",
            "slots": {"sku_code": "YHXXXK01B01S01", "product_name": "感应灯",
                      "order_id": "", "platform_trade_id": "5116887975001001001",
                      "tracking_no": "", "possible_numeric_id": ""},
            "matched_product_name": "感应灯",
            "order_product_identity": {
                "status": "resolved",
                "source": "jst_order_items",
                "sku_id": "YHXXXK01B01S01",
                "i_id": "YHXXXK01",
            },
            "conversation_context": {},
            "trace_steps": [],
        }
        result = response_strategy_planner(state)
        missing_slots = result.get("missing_slots", [])
        # Should NOT ask for SKU when it's already known
        assert "sku" not in missing_slots, \
            f"Should not ask for SKU when already known. missing_slots={missing_slots}"
        # Should NOT ask for order_id when platform_trade_id is present
        assert "order_id" not in missing_slots, \
            f"Should not ask for order_id when platform_trade_id is known. missing_slots={missing_slots}"

    def test_with_order_identifier_does_not_ask_for_order(self):
        """When order identifier exists, should not ask for order_id."""
        from app.agent.nodes.response_strategy_planner import response_strategy_planner
        state = {
            "intent": "installation",
            "customer_concern": "unknown",
            "customer_state": {},
            "normalized_message": "怎么让它自动感应",
            "customer_message": "怎么让它自动感应",
            "slots": {
                "product_name": "感应灯",
                "sku_code": "YHXXXK01B01S01",
                "order_id": "",
                "platform_trade_id": "5116887975001001001",
                "tracking_no": "SF5196840812297",
                "possible_numeric_id": "",
                "identifier_type": "platform_trade_id",
            },
            "matched_product_name": "感应灯",
            "order_product_identity": {
                "status": "resolved",
                "source": "jst_order_items",
                "sku_id": "YHXXXK01B01S01",
                "i_id": "YHXXXK01",
            },
            "conversation_context": {},
            "trace_steps": [],
        }
        result = response_strategy_planner(state)
        missing_slots = result.get("missing_slots", [])
        # Should NOT ask for order identifiers when they're already present
        assert not any(s in missing_slots for s in ("order_id", "tracking_no", "sku")), \
            f"Should not re-ask for known info. missing_slots={missing_slots}"


# ============================================================================
# K. product_resolver_tool reuses resolved identity
# ============================================================================

class TestProductResolverToolReusesIdentity:
    """product_resolver_tool must check state for already-resolved identity"""

    def test_reuses_resolved_identity_from_state(self):
        """When order_product_identity is resolved in state,
        product_resolver_tool should return it instead of re-matching."""
        from app.agent.tools.registry import _handle_product_resolver
        state = {
            "order_product_identity": {
                "status": "resolved",
                "source": "jst_order_items",
                "matched_product_name": "感应灯",
                "sku_id": "YHXXXK01B01S01",
                "i_id": "YHXXXK01",
                "candidates": ["感应灯", "YHXXXK01B01S01", "YHXXXK01"],
            },
            "matched_product_name": "感应灯",
        }
        inputs = {"message": "怎么让它自动感应"}
        result = _handle_product_resolver(inputs, state)
        assert result.get("matched_product_name") == "感应灯", \
            f"Should reuse resolved identity, got: {result}"
        assert not result.get("need_clarification")


# ============================================================================
# L. Tool planner invariant: single candidate ambiguity guard
# ============================================================================

class TestToolPlannerSingleCandidateGuard:
    """plan_tools ambiguous guard should only skip tools for truly ambiguous cases"""

    def test_single_candidate_in_plan_tools(self):
        """Single candidate should not trigger ambiguous guard in plan_tools."""
        from app.agent.tools.executor import plan_tools
        state = {
            "normalized_message": "怎么让它自动感应",
            "intent": "product_question",
            "customer_message": "怎么让它自动感应",
            "slots": {"identifier_type": "", "platform_trade_id": "", "order_id": "", "tracking_no": ""},
            "allowed_tools": ["product_resolver_tool", "rag_search_tool", "template_select_tool"],
            "required_tools": ["product_resolver_tool", "rag_search_tool"],
            "forbidden_tools": [],
            "allowed_source_types": ["product_facts", "faq"],
            "matched_product_name": "A2号收纳柜",
            "product_candidates": [],
            "order_product_identity": {
                "source": "sidecar_product_name",
                "status": "ambiguous",
                "candidates": [{"name": "A2号收纳柜", "sku_id": "YH06K39B02S06", "i_id": "YH06K39"}],
            },
            "trace_steps": [],
        }
        with mock.patch("app.agent.tools.executor._try_llm_tool_selection", return_value=None):
            result = plan_tools(state)
        assert len(result["tool_plan"]) > 0, \
            f"Single candidate should not skip tools. tool_plan={result['tool_plan']}"
