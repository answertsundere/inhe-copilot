from app.agent.nodes.build_response import build_response
from app.llm.prompts import build_system_prompt
from app.models.reply import ReplySuggestion


def test_system_prompt_contains_inhe_mom_care_contract():
    prompt = build_system_prompt(
        forbidden_claims=["\u4fdd\u8bc1", "\u4e00\u5b9a"],
        knowledge_context="\u5df2\u9a8c\u8bc1\u77e5\u8bc6",
    )

    assert "INHE \u5ba2\u670d Copilot" in prompt
    assert "Evidence Gate" in prompt
    assert "Product Identity Resolver" in prompt
    assert "\u5b9d\u5988" in prompt
    assert "fact_review_status" in prompt
    assert "suggested_reply" in prompt
    assert "tools_to_call" in prompt
    assert "\u4e0d\u8981\u7d22\u8981\u8ba2\u5355\u53f7\u6216\u5feb\u9012\u53f7" in prompt


def test_build_response_exposes_prompt_contract_fields():
    result = build_response({
        "suggested_reply": "\u4eb2\uff0c\u6211\u5e2e\u60a8\u6838\u5b9e\u3002",
        "requires_human_review": True,
        "review_reason": "\u6750\u8d28\u9700\u8981\u4eba\u5de5\u590d\u6838",
        "risk_level": "medium",
        "intent": "child_safety",
        "required_tools": ["product_resolver_tool", "rag_search_tool"],
        "evidence": {
            "product_facts": [{
                "title": "\u5546\u54c1\u6750\u8d28",
                "entry_id": "E001",
                "fact_review_status": "verified",
                "fact": "\u5df2\u5ba1\u6838\u4e8b\u5b9e",
            }]
        },
        "trace_steps": [],
    })

    assert result["reason_for_review"] == "\u6750\u8d28\u9700\u8981\u4eba\u5de5\u590d\u6838"
    assert result["reply_tone"] == "empathetic"
    assert "\u5546\u54c1\u6750\u8d28(E001)" in result["evidence_used"]
    assert "ProductIdentityResolver" in result["tools_to_call"]
    assert "RAG" in result["tools_to_call"]


def test_reply_suggestion_keeps_prompt_contract_fields():
    suggestion = ReplySuggestion.from_dict({
        "suggested_reply": "\u4eb2\uff0c\u6211\u5e2e\u60a8\u6838\u5b9e\u3002",
        "requires_human_review": True,
        "review_reason": "\u9700\u8981\u4eba\u5de5\u786e\u8ba4",
        "reply_tone": "empathetic",
        "evidence_used": "\u5546\u54c1\u6750\u8d28(E001)",
        "tools_to_call": ["ProductIdentityResolver", "RAG"],
    })

    data = suggestion.to_dict()

    assert data["reason_for_review"] == "\u9700\u8981\u4eba\u5de5\u786e\u8ba4"
    assert data["reply_tone"] == "empathetic"
    assert data["evidence_used"] == "\u5546\u54c1\u6750\u8d28(E001)"
    assert data["tools_to_call"] == ["ProductIdentityResolver", "RAG"]
