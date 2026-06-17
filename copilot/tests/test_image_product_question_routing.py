from app.agent.nodes.generate_reply import generate_reply
from app.agent.nodes.llm_intent_router import _sanitize_decision
from app.agent.nodes.response_strategy_router import response_strategy_router
from app.agent.nodes.router_validation import router_validation


def _image_detachable_state() -> dict:
    message = "[\u56fe\u72471]\n\u8fd9\u662f\u53ef\u62c6\u5378\u7684\u5417"
    return {
        "normalized_message": message,
        "customer_message": message,
        "intent": "image_attachment",
        "risk_level": "low",
        "router_decision": {
            "intent": "image_attachment",
            "need_tool": False,
            "tool_name": "none",
        },
        "router_source": "rule_fallback",
        "router_reason": "image attachment",
        "selected_tool": "none",
        "product_candidates": [{"value": "YH88K01B09S26", "type": "sku_id_candidate"}],
        "matched_product_name": "\u4e00\u53f7\u5582\u517b\u67dc",
        "slots": {},
        "conversation_context": {},
        "trace_steps": [],
    }


def test_image_with_text_product_question_routes_to_rag():
    result = router_validation(_image_detachable_state())

    assert result["intent"] == "product_question"
    assert result["selected_tool"] == "rag_retrieve"


def test_llm_router_cannot_force_text_product_question_back_to_image_attachment():
    state = _image_detachable_state()

    result = _sanitize_decision(
        {"intent": "image_attachment", "need_tool": False, "tool_name": "none"},
        state,
    )

    assert result["intent"] == "product_question"
    assert result["tool_name"] == "rag_retrieve"


def test_image_text_product_question_strategy_still_queries_knowledge():
    result = response_strategy_router(_image_detachable_state())

    assert result["response_strategy"] == "product_question"
    assert result["should_query_knowledge"] is True
    assert "rag_search_tool" in result["required_tools"]


def test_image_text_product_question_reply_does_not_use_generic_image_prompt():
    state = _image_detachable_state()
    state["answer_mode"] = "product_answer"

    result = generate_reply(state)

    assert "\u60a8\u53d1\u7684\u56fe\u7247\u6211\u4eec\u9700\u8981\u7ed3\u5408\u5177\u4f53\u95ee\u9898" not in result["suggested_reply"]
    assert result["answer_mode"] == "no_evidence_clarification"
