from unittest import mock


def test_rag_retrieve_uses_search_hybrid():
    from app.agent.nodes.rag_retrieve import rag_retrieve

    state = {
        "customer_message": "一号狮子围兜防水吗？",
        "normalized_message": "一号狮子围兜防水吗？",
        "intent": "product_question",
        "allowed_source_types": ["product_facts", "product_mapping", "faq"],
        "matched_product_name": "一号狮子围兜",
        "slots": {"product_name": "一号狮子围兜"},
        "trace_steps": [],
    }
    with mock.patch("app.repositories.knowledge_chunk_repository.KnowledgeChunkRepository.search_hybrid", return_value=[]) as hybrid:
        rag_retrieve(state)

    assert hybrid.called


def test_rag_search_tool_uses_search_hybrid():
    from app.agent.tools.registry import get_tool_registry

    tool = get_tool_registry().get("rag_search_tool")
    inputs = {
        "query": "一号狮子围兜防水吗？",
        "source_types": ["product_facts", "product_mapping", "faq"],
        "intent": "product_question",
        "product_name": "一号狮子围兜",
        "product_scope": ["一号狮子围兜"],
    }
    state = {
        "intent": "product_question",
        "allowed_source_types": ["product_facts", "product_mapping", "faq"],
        "matched_product_name": "一号狮子围兜",
        "slots": {"product_name": "一号狮子围兜"},
    }
    with mock.patch("app.repositories.knowledge_chunk_repository.KnowledgeChunkRepository.search_hybrid", return_value=[]) as hybrid:
        result = tool.handler(inputs, state)

    assert hybrid.called
    # Two-pass logic: first pass returns [], so second pass triggers draft fallback
    assert result["retrieval_mode"] in ("hybrid", "hybrid_draft_fallback", "retriever_hybrid", "retriever_draft_fallback")
