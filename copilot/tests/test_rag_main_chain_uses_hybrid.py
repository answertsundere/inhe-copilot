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


def test_rag_retrieve_uses_identity_i_id_as_sku_scope(monkeypatch):
    from app.agent.nodes.rag_retrieve import rag_retrieve

    captured = {}

    class FakeRetriever:
        def retrieve(self, **kwargs):
            captured.update(kwargs)
            return []

    monkeypatch.setattr("app.retrieval.retriever_factory.get_retriever", lambda: FakeRetriever())

    rag_retrieve({
        "customer_message": "这个如何安装方便吗",
        "normalized_message": "这个如何安装方便吗",
        "intent": "installation",
        "allowed_source_types": ["faq", "product_facts"],
        "order_product_identity": {
            "status": "resolved",
            "matched_product_name": "一号小熊床护栏",
            "i_id": "YH64K01",
            "sku_id": "",
        },
        "slots": {"product_name": "一号小熊床护栏"},
        "trace_steps": [],
    })

    assert "YH64K01" in captured["sku_scope"]


def test_rag_retrieve_separates_current_query_from_retrieval_query(monkeypatch):
    from app.agent.nodes.rag_retrieve import rag_retrieve

    class FakeRetriever:
        def retrieve(self, **kwargs):
            return []

    monkeypatch.setattr("app.retrieval.retriever_factory.get_retriever", lambda: FakeRetriever())

    result = rag_retrieve({
        "customer_message": "\u8fd9\u4e2a\u6709\u5473\u9053\u5417",
        "normalized_message": "\u8fd9\u4e2a\u6709\u5473\u9053\u5417",
        "intent": "odor_question",
        "allowed_source_types": ["faq", "product_facts"],
        "matched_product_name": "\u4e00\u53f7\u5c0f\u718a\u5e8a\u62a4\u680f",
        "query_fact_type": "odor",
        "slots": {"product_name": "\u4e00\u53f7\u5c0f\u718a\u5e8a\u62a4\u680f"},
        "history_snapshot": {"confirmed_product": "\u65e7\u5546\u54c1"},
        "trace_steps": [],
    })

    assert result["current_query"] == "\u8fd9\u4e2a\u6709\u5473\u9053\u5417"
    assert "\u8fd9\u4e2a\u6709\u5473\u9053\u5417" in result["retrieval_query"]
    assert "\u4e00\u53f7\u5c0f\u718a\u5e8a\u62a4\u680f" in result["retrieval_query"]
    assert "\u65e7\u5546\u54c1" not in result["retrieval_query"]
    trace = next(t for t in result["trace_steps"] if t.get("node") == "rag_retrieve")
    assert trace["current_query"] == result["current_query"]
    assert trace["retrieval_query"] == result["retrieval_query"]
    assert trace["history_included"] is False


def test_evidence_filter_matches_full_sku_to_family_i_id():
    from app.agent.nodes.evidence_filter_node import evidence_filter_node

    result = evidence_filter_node({
        "retrieved_chunks": [{
            "chunk_id": "kbqa:1404",
            "entry_id": "kbqa:1404",
            "title": "一号小熊床护栏安装方便吗？",
            "chunk_text": "安装非常方便。",
            "source_type": "faq",
            "intent": "general",
            "score": 1.0,
            "rerank_score": 1.0,
            "sku_scope": ["YH64K01"],
            "product_scope": ["一号小熊床护栏"],
            "metadata": {"auto_reply_allowed": True},
            "entry_status": "published",
            "index_status": "ready",
        }],
        "intent": "installation",
        "allowed_source_types": ["faq"],
        "slots": {"sku_code": "YH64K01B03S26", "product_name": "一号小熊床护栏"},
        "matched_product_name": "一号小熊床护栏",
        "trace_steps": [],
    })

    assert result["knowledge_evidence"]
    assert result["knowledge_evidence"][0]["scope_match"] is True
    assert result["knowledge_evidence"][0]["mismatch_reason"] == ""


def test_tool_executor_retries_rag_after_product_resolver(monkeypatch):
    from app.agent.tools.executor import _extract_rag_and_product_fields

    captured = {}

    class FakeRetriever:
        def retrieve(self, **kwargs):
            captured.update(kwargs)
            return [{
                "chunk_id": "kbqa:344",
                "entry_id": "kbqa:344",
                "title": "九号防夹滑门收纳柜材质是什么？防潮吗？",
                "chunk_text": "主要采用冷轧钢管/环保PP/无纺布等材质。",
                "source_type": "faq",
                "score": 5.0,
                "rerank_score": 5.0,
                "metadata": {"auto_reply_allowed": True},
                "entry_status": "published",
                "index_status": "ready",
                "sku_scope": ["YH06K53"],
                "product_scope": ["九号防夹滑门收纳柜"],
            }]

    monkeypatch.setattr("app.retrieval.retriever_factory.get_retriever", lambda: FakeRetriever())

    fields = _extract_rag_and_product_fields(
        {
            "product_resolver_tool": {
                "matched_product_name": "九号防夹滑门收纳柜",
                "candidates": [{"name": "九号防夹滑门收纳柜", "sku_id": "YH06K53B01S13", "i_id": "YH06K53"}],
                "sku_id": "YH06K53B01S13",
                "i_id": "YH06K53",
            },
            "rag_search_tool": {"chunks": [], "retrieval_mode": "retriever_hybrid"},
        },
        {
            "customer_message": "这个材质安全吗？会不会容易受潮？",
            "normalized_message": "这个材质安全吗？会不会容易受潮？",
            "allowed_source_types": ["faq", "product_facts"],
            "query_fact_type": "material",
            "slots": {},
        },
    )

    assert "YH06K53" in captured["sku_scope"]
    assert fields["knowledge_evidence"]
    assert fields["rag_retrieval_mode"] == "retriever_hybrid_after_product_resolver"
