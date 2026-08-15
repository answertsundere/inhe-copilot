import json
from unittest import mock


def _tracking_state(**overrides):
    state = {
        "customer_message": "SF0229477422177 到哪里了",
        "normalized_message": "SF0229477422177 到哪里了",
        "intent": "logistics_trace",
        "risk_level": "low",
        "requires_human_review": False,
        "needs_human_review": False,
        "slots": {
            "identifier_type": "tracking_no",
            "tracking_no": "SF0229477422177",
            "order_id": "",
            "platform_trade_id": "",
            "possible_numeric_id": "",
        },
        "trace_steps": [],
    }
    state.update(overrides)
    return state


def test_explicit_tracking_skips_intent_llm(monkeypatch):
    from app import config
    from app.agent.nodes import llm_intent_router as module

    monkeypatch.setattr(config, "COPILOT_EXPLICIT_LOGISTICS_FAST_PATH_ENABLED", True)
    monkeypatch.setattr(
        module,
        "get_llm_client",
        lambda: (_ for _ in ()).throw(AssertionError("intent LLM must not be called")),
    )

    result = module.llm_intent_router(_tracking_state())

    assert result["intent"] == "logistics_trace"
    assert result["router_source"] == "explicit_logistics_identifier_fast_path"
    assert result["identifier_value"] == "SF0229477422177"


def test_explicit_tracking_skips_fact_type_llm(monkeypatch):
    from app import config
    from app.agent.nodes import query_fact_type_classifier as module

    monkeypatch.setattr(config, "COPILOT_EXPLICIT_LOGISTICS_FAST_PATH_ENABLED", True)
    monkeypatch.setattr(
        module,
        "classify_query_fact_type_llm_first",
        lambda state: (_ for _ in ()).throw(AssertionError("fact type LLM must not be called")),
    )

    result = module.query_fact_type_classifier(_tracking_state())

    assert result["query_fact_type"] == ""
    assert result["query_fact_type_source"] == "explicit_logistics_identifier_fast_path"


def test_order_identity_with_logistics_routing_keeps_turn_understanding(
    monkeypatch,
):
    from app import config
    from app.agent.nodes import query_fact_type_classifier as module

    calls = []

    def classify(state, **_kwargs):
        calls.append(state["intent"])
        return {
            "query_fact_type": "",
            "confidence": 1.0,
            "matched_terms": [],
            "source": "llm",
            "reason": "minimal_turn_understanding_validated",
            "risk_hint": "medium",
            "secondary_fact_types": [],
            "customer_goals": [{
                "schema_version": "canonical-customer-goal/v1",
                "goal_ref": f"goal-{state['intent']}",
                "goal_kind": "customer_goal",
                "claim_type_status": "unmapped",
                "claim_type": "",
                "attribute_key": "",
                "semantic_key": "",
                "policy_intent_ref": "",
                "goal_summary": "current customer logistics request",
                "source": "current_customer_message",
            }],
            "goal_understanding_status": "valid",
            "goal_understanding_diagnostics": [],
        }

    monkeypatch.setattr(config, "COPILOT_EXPLICIT_LOGISTICS_FAST_PATH_ENABLED", True)
    monkeypatch.setattr(module, "classify_query_fact_type_llm_first", classify)

    for intent in ("logistics_eta", "shipping", "logistics"):
        result = module.query_fact_type_classifier(_tracking_state(
            customer_message="current customer logistics request",
            normalized_message="current customer logistics request",
            intent=intent,
            slots={
                "identifier_type": "order_id",
                "tracking_no": "",
                "order_id": "fixture-order",
                "platform_trade_id": "",
                "possible_numeric_id": "",
            },
        ))

        assert result["query_fact_type_source"] == "llm"
        assert result["turn_understanding"]["goal_understanding_status"] == "valid"
        assert len(result["turn_understanding"]["requested_claims"]) == 1

    assert calls == ["logistics_eta", "shipping", "logistics"]


def test_explicit_tracking_skips_customer_state_llm(monkeypatch):
    from app import config
    from app.agent.nodes import customer_state_analyzer as module

    monkeypatch.setattr(config, "COPILOT_EXPLICIT_LOGISTICS_FAST_PATH_ENABLED", True)
    monkeypatch.setattr(
        module,
        "_llm_analyze",
        lambda state: (_ for _ in ()).throw(AssertionError("customer state LLM must not be called")),
    )

    result = module.customer_state_analyzer(_tracking_state())

    assert result["customer_concern"] == "wants_eta_certainty"
    assert result["trace_steps"][-1]["source"] == "explicit_logistics_identifier_fast_path"


def test_explicit_tracking_uses_deterministic_required_tool_plan(monkeypatch):
    from app import config
    from app.agent.tools import executor

    monkeypatch.setattr(config, "COPILOT_EXPLICIT_LOGISTICS_FAST_PATH_ENABLED", True)
    state = _tracking_state(
        allowed_tools=["jst_lookup_tracking_tool", "rag_search_tool"],
        required_tools=["jst_lookup_tracking_tool"],
        forbidden_tools=["jst_lookup_order_tool", "jst_lookup_outbound_tool"],
        allowed_source_types=["shipping_policy"],
    )

    with mock.patch(
        "app.agent.tools.executor._try_llm_tool_selection",
        side_effect=AssertionError("tool planning LLM must not be called"),
    ):
        result = executor.plan_tools(state)

    assert result["tool_planner_source"] == "explicit_logistics_identifier_fast_path"
    assert result["tool_plan"] == [{
        "tool_name": "jst_lookup_tracking_tool",
        "inputs": {"tracking_no": "SF0229477422177"},
    }]


class _FakeMessage:
    def __init__(self, content):
        self.content = content


class _FakeResponse:
    def __init__(self, payload):
        self.choices = [type("Choice", (), {
            "message": _FakeMessage(json.dumps(payload, ensure_ascii=False)),
        })()]


class _CountingCompletions:
    def __init__(self):
        self.calls = 0

    def create(self, **kwargs):
        self.calls += 1
        return _FakeResponse({
            "intent": "logistics_eta",
            "confidence": 0.8,
            "identifier_type": "none",
            "identifier_value": "",
            "product_name": "",
            "question_type": "eta",
            "need_tool": False,
            "tool_name": "none",
            "reason": "ambiguous logistics request still needs semantic routing",
        })


def test_logistics_without_explicit_identifier_keeps_llm_routing(monkeypatch):
    from app import config
    from app.agent.nodes import llm_intent_router as module

    monkeypatch.setattr(config, "COPILOT_EXPLICIT_LOGISTICS_FAST_PATH_ENABLED", True)
    completions = _CountingCompletions()
    fake_client = type("Client", (), {
        "api_key": "test",
        "model": "test-model",
        "client": type("OpenAI", (), {
            "chat": type("Chat", (), {"completions": completions})(),
        })(),
        "create_chat_completion": lambda self, **kwargs: (
            self.client.chat.completions.create(**kwargs)
        ),
    })()
    monkeypatch.setattr(module, "get_llm_client", lambda: fake_client)
    state = _tracking_state(
        customer_message="我的快递大概几天到",
        normalized_message="我的快递大概几天到",
        intent="logistics_eta",
        slots={
            "identifier_type": "none",
            "tracking_no": "",
            "order_id": "",
            "platform_trade_id": "",
            "possible_numeric_id": "",
        },
    )

    result = module.llm_intent_router(state)

    assert completions.calls == 1
    assert result["router_source"] == "llm"


def test_high_risk_logistics_does_not_use_fast_path(monkeypatch):
    from app import config
    from app.services.logistics_fast_path import get_explicit_logistics_identifier

    monkeypatch.setattr(config, "COPILOT_EXPLICIT_LOGISTICS_FAST_PATH_ENABLED", True)
    state = _tracking_state(
        risk_level="high",
        requires_human_review=True,
        customer_message="SF0229477422177 再不处理我就投诉平台",
        normalized_message="SF0229477422177 再不处理我就投诉平台",
    )

    assert get_explicit_logistics_identifier(state) is None


def test_unknown_numeric_identifier_does_not_use_fast_path(monkeypatch):
    from app import config
    from app.services.logistics_fast_path import get_explicit_logistics_identifier

    monkeypatch.setattr(config, "COPILOT_EXPLICIT_LOGISTICS_FAST_PATH_ENABLED", True)
    state = _tracking_state(slots={
        "identifier_type": "unknown_identifier",
        "tracking_no": "",
        "order_id": "",
        "platform_trade_id": "",
        "possible_numeric_id": "123456789012",
    })

    assert get_explicit_logistics_identifier(state) is None


def test_explicit_identifier_tool_failure_does_not_repeat_legacy_jst_lookup():
    from app.agent.graph import _route_after_tool_executor

    state = _tracking_state(
        tool_planner_source="explicit_logistics_identifier_fast_path",
        required_tools=["jst_lookup_tracking_tool"],
        tool_results={
            "jst_lookup_tracking_tool": {
                "found": False,
                "safe_fallback_reason": "tracking_no_not_found_in_recent_7d",
            },
        },
    )

    assert _route_after_tool_executor(state) == "tool_success"


def test_failed_jst_lookup_promotes_loaded_local_order_as_fallback():
    from app.agent.tools.executor import _extract_legacy_fields

    local_order = {
        "o_id": "202501010003",
        "status": "待发货",
        "l_id": "",
        "items": [{"name": "多功能置物架"}],
    }
    result = _extract_legacy_fields(
        {"jst_lookup_order_tool": {"found": False}},
        {"order": local_order},
    )

    assert result["order_found"] is True
    assert result["order_source"] == "local_order_fallback"
    assert result["order_status"] == "pending_shipment"
    assert result["shipment_status"] == "pending"
    assert result["local_order_fallback_used"] is True


def test_interactive_platform_trade_lookup_skips_expensive_history_scans(monkeypatch):
    from app.integrations.jst import live_query

    miss = lambda query_type: {
        "found": False,
        "query_type": query_type,
        "endpoint": "test",
        "duration_ms": 10,
        "safe_fallback_reason": "not_found",
    }
    monkeypatch.setattr(
        live_query,
        "lookup_outbound_by_so_id",
        lambda value: miss("outbound_so_id"),
    )
    monkeypatch.setattr(
        live_query,
        "lookup_order_by_platform_order_id",
        lambda value: miss("platform_order_id"),
    )
    monkeypatch.setattr(
        live_query,
        "lookup_order_by_platform_order_id_history",
        lambda value: (_ for _ in ()).throw(
            AssertionError("interactive lookup must not scan 75-day history")
        ),
    )
    monkeypatch.setattr(
        live_query,
        "lookup_order_by_outer_so_id",
        lambda value: (_ for _ in ()).throw(
            AssertionError("interactive lookup must not scan recent orders")
        ),
    )

    result = live_query.lookup_order_by_identifier(
        "5118207015382036103",
        "platform_trade_id",
        exhaustive=False,
    )

    assert result["found"] is False
    assert result["safe_fallback_reason"] == "not_found_fast_path"
    assert [item["query_type"] for item in result["attempted_paths"]] == [
        "outbound_so_id",
        "order_id",
        "platform_order_id",
    ]
