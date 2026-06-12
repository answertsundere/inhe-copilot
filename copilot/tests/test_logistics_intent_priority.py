import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.agent.nodes.detect_intent import detect_intent
from app.agent.nodes.router_validation import router_validation


def test_numeric_identifier_with_delivery_eta_is_logistics():
    msg = "5118207015382036103我的快递大概什么时候到"
    result = detect_intent({"customer_message": msg, "normalized_message": msg, "trace_steps": []})
    assert result["intent"] == "logistics_eta"
    assert result["skill"] == "logistics"


def test_router_validation_overrides_wrong_llm_product_route():
    msg = "5118207015382036103我的快递大概什么时候到"
    state = {
        "customer_message": msg,
        "normalized_message": msg,
        "intent": "product_question",
        "skill": "product",
        "selected_tool": "rag_retrieve",
        "router_source": "llm",
        "router_reason": "mock wrong route",
        "slots": {
            "possible_numeric_id": "5118207015382036103",
            "identifier_type": "unknown_identifier",
        },
        "router_decision": {
            "intent": "product_question",
            "tool_name": "rag_retrieve",
            "identifier_type": "none",
            "identifier_value": "",
        },
        "trace_steps": [],
    }
    result = router_validation(state)
    assert result["intent"] == "logistics_eta"
    assert result["skill"] == "logistics"
    assert result["selected_tool"] == "jst_live_query"
    assert result["router_source"] == "validation_override"
    assert result["identifier_value"] == "5118207015382036103"


def test_router_validation_preserves_signed_not_received():
    msg = "显示签收了但我没收到"
    state = {
        "customer_message": msg,
        "normalized_message": msg,
        "intent": "general",
        "selected_tool": "none",
        "router_source": "llm",
        "router_reason": "mock wrong route",
        "slots": {},
        "router_decision": {"intent": "general", "tool_name": "none"},
        "trace_steps": [],
    }
    result = router_validation(state)
    assert result["intent"] == "delivery_not_received"
    assert result["skill"] == "logistics"
    assert result["selected_tool"] == "none"
    assert result["router_source"] == "validation_override"
