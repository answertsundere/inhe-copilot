"""
测试 RAG evidence 过滤 - 验证新增字段
"""

import pytest


def test_formal_attribution_survives_retrieval_metadata_boundary():
    from app.agent.nodes.evidence_filter_node import evidence_filter_node

    result = evidence_filter_node({
        "retrieved_chunks": [{
            "score": 0.9,
            "chunk_id": "chunk-width",
            "entry_id": "entry-width",
            "title": "Dimensions",
            "source_type": "product_facts",
            "chunk_text": "Width is 45 cm.",
            "metadata": {
                "auto_reply_allowed": True,
                "evidence_uid": "evidence-width",
                "fact_type": "dimensions",
                "fact_review_status": "reviewed",
                "attribute_key": "width",
                "subject_scope": "product",
                "product_scope": ["IID-A"],
                "sku_scope": ["SKU-A"],
                "source_table": "product_data_hub",
                "source_id": "hub-fact-width",
                "protocol_source_type": "product_data_hub",
            },
            "entry_status": "published",
            "entry_risk_level": "low",
        }],
        "intent": "product_question",
        "allowed_source_types": ["product_facts"],
        "slots": {"sku_code": "SKU-A", "i_id": "IID-A"},
    })

    evidence = result["knowledge_evidence"]
    assert len(evidence) == 1
    assert evidence[0]["evidence_uid"] == "evidence-width"
    assert evidence[0]["fact_type"] == "dimensions"
    assert evidence[0]["fact_review_status"] == "reviewed"
    assert evidence[0]["attribute_key"] == "width"
    assert evidence[0]["subject_scope"] == "product"
    assert evidence[0]["product_scope"] == ["IID-A"]
    assert evidence[0]["source_table"] == "product_data_hub"
    assert evidence[0]["source_id"] == "hub-fact-width"
    assert evidence[0]["protocol_source_type"] == "product_data_hub"


class TestEvidenceFilterNewFields:
    """测试 evidence_filter_node 输出的新字段"""

    def test_scope_match_true_when_sku_matches(self):
        """SKU 匹配时 scope_match 应为 True"""
        from app.agent.nodes.evidence_filter_node import evidence_filter_node

        state = {
            "retrieved_chunks": [
                {
                    "score": 0.9,
                    "chunk_id": "c1",
                    "entry_id": "e1",
                    "title": "书架说明",
                    "source_type": "product_facts",
                    "intent": "product_question",
                    "chunk_text": "材质说明",
                    "metadata": {"auto_reply_allowed": True},
                    "sku_scope": ["SKU-001"],
                    "product_scope": [],
                    "entry_status": "published",
                    "entry_risk_level": "low",
                    "source_sheet": "",
                    "row_number": 0,
                },
            ],
            "intent": "product_question",
            "allowed_source_types": ["product_facts"],
            "slots": {"sku_code": "SKU-001"},
        }

        result = evidence_filter_node(state)
        evidence = result["knowledge_evidence"]
        assert len(evidence) == 1
        assert evidence[0]["scope_match"] is True
        assert evidence[0]["mismatch_reason"] == ""

    def test_scope_match_false_when_sku_mismatch(self):
        """SKU 不匹配且不被 evidence_filter 拒绝时 scope_match 应为 False

        注：evidence_filter_node 会先拒绝 sku_mismatch 的 chunks（第68-69行），
        所以需要测试的是 chunk 有 sku_scope 但 sku_code 未传入（slots 无 sku_code）
        的情况，scope_match 应为 True（因为没有 sku_code 无法判断不匹配）。

        实际 scope_mismatch 的检测主要在 search_hybrid 的 scope_score 中。
        此处验证的是：当 sku_code 存在且与 chunk sku 不匹配时，chunk 会被拒绝。
        """
        from app.agent.nodes.evidence_filter_node import evidence_filter_node

        state = {
            "retrieved_chunks": [
                {
                    "score": 0.9,
                    "chunk_id": "c1",
                    "entry_id": "e1",
                    "title": "书架说明",
                    "source_type": "product_facts",
                    "intent": "product_question",
                    "chunk_text": "材质说明",
                    "metadata": {"auto_reply_allowed": True},
                    "sku_scope": ["SKU-001"],
                    "product_scope": [],
                    "entry_status": "published",
                    "entry_risk_level": "low",
                    "source_sheet": "",
                    "row_number": 0,
                },
            ],
            "intent": "product_question",
            "allowed_source_types": ["product_facts"],
            "slots": {"sku_code": "SKU-999"},
        }

        result = evidence_filter_node(state)
        # evidence_filter_node 会在第68-69行拒绝 sku_mismatch 的 chunk
        evidence = result["knowledge_evidence"]
        assert len(evidence) == 0  # chunk 被拒绝了

    def test_source_confidence_field(self):
        """knowledge_evidence 应包含 source_confidence 字段"""
        from app.agent.nodes.evidence_filter_node import evidence_filter_node

        state = {
            "retrieved_chunks": [
                {
                    "score": 0.8,
                    "chunk_id": "c1",
                    "entry_id": "e1",
                    "title": "产品说明",
                    "source_type": "product_facts",
                    "intent": "general",
                    "chunk_text": "测试文本",
                    "metadata": {"auto_reply_allowed": True},
                    "entry_status": "published",
                    "entry_risk_level": "low",
                    "source_sheet": "",
                    "row_number": 0,
                },
            ],
            "intent": "general",
            "allowed_source_types": [],
            "slots": {},
        }

        result = evidence_filter_node(state)
        evidence = result["knowledge_evidence"]
        assert len(evidence) == 1
        assert evidence[0]["source_confidence"] == "high"  # product_facts -> high

    def test_rerank_score_field(self):
        """knowledge_evidence 应包含 rerank_score 字段"""
        from app.agent.nodes.evidence_filter_node import evidence_filter_node

        state = {
            "retrieved_chunks": [
                {
                    "score": 0.8,
                    "chunk_id": "c1",
                    "entry_id": "e1",
                    "title": "测试",
                    "source_type": "faq",
                    "intent": "general",
                    "chunk_text": "测试文本",
                    "metadata": {"auto_reply_allowed": True},
                    "entry_status": "published",
                    "entry_risk_level": "low",
                    "source_sheet": "",
                    "row_number": 0,
                },
            ],
            "intent": "general",
            "allowed_source_types": [],
            "slots": {},
        }

        result = evidence_filter_node(state)
        evidence = result["knowledge_evidence"]
        assert len(evidence) == 1
        assert "rerank_score" in evidence[0]
        assert isinstance(evidence[0]["rerank_score"], float)

    def test_evidence_allowed_for_exact_answer_true(self):
        """scope 匹配 + 高分时 evidence_allowed_for_exact_answer 应为 True"""
        from app.agent.nodes.evidence_filter_node import evidence_filter_node

        state = {
            "retrieved_chunks": [
                {
                    "score": 0.9,
                    "chunk_id": "c1",
                    "entry_id": "e1",
                    "title": "测试",
                    "source_type": "product_facts",
                    "intent": "general",
                    "chunk_text": "高可信度信息",
                    "metadata": {"sku_scope": ["SKU-001"], "auto_reply_allowed": True},
                    "entry_status": "published",
                    "entry_risk_level": "low",
                    "source_sheet": "",
                    "row_number": 0,
                },
            ],
            "intent": "product_question",
            "allowed_source_types": ["product_facts"],
            "slots": {"sku_code": "SKU-001"},
        }

        result = evidence_filter_node(state)
        evidence = result["knowledge_evidence"]
        assert len(evidence) == 1
        assert evidence[0]["evidence_allowed_for_exact_answer"] is True

    def test_evidence_allowed_for_exact_answer_false_on_mismatch(self):
        """scope 不匹配时 evidence_allowed_for_exact_answer 应为 False

        由于 evidence_filter_node 会直接拒绝 sku_mismatch 的 chunks，
        我们用一个无 sku_scope 的 chunk 配合低 rerank_score 来测试
        evidence_allowed_for_exact_answer = False 的场景。
        """
        from app.agent.nodes.evidence_filter_node import evidence_filter_node

        state = {
            "retrieved_chunks": [
                {
                    "score": 0.01,  # 很低的分数
                    "chunk_id": "c1",
                    "entry_id": "e1",
                    "title": "测试",
                    "source_type": "product_facts",
                    "intent": "general",
                    "chunk_text": "低分信息",
                    "metadata": {"auto_reply_allowed": True},
                    "entry_status": "published",
                    "entry_risk_level": "low",
                    "source_sheet": "",
                    "row_number": 0,
                },
            ],
            "intent": "product_question",
            "allowed_source_types": ["product_facts"],
            "slots": {},
        }

        result = evidence_filter_node(state)
        evidence = result["knowledge_evidence"]
        assert len(evidence) == 1
        # score 太低，rerank_score 应低于阈值，不允许用于精确回答
        assert evidence[0]["evidence_allowed_for_exact_answer"] is False

    def test_no_sku_scope_means_scope_match_true(self):
        """chunk 没有指定 sku_scope 时 scope_match 应为 True"""
        from app.agent.nodes.evidence_filter_node import evidence_filter_node

        state = {
            "retrieved_chunks": [
                {
                    "score": 0.8,
                    "chunk_id": "c1",
                    "entry_id": "e1",
                    "title": "通用说明",
                    "source_type": "shipping_policy",
                    "intent": "general",
                    "chunk_text": "通用发货说明",
                    "metadata": {"auto_reply_allowed": True},
                    "entry_status": "published",
                    "entry_risk_level": "low",
                    "source_sheet": "",
                    "row_number": 0,
                },
            ],
            "intent": "logistics_eta",
            "allowed_source_types": ["shipping_policy"],
            "slots": {"sku_code": "SKU-001"},
        }

        result = evidence_filter_node(state)
        evidence = result["knowledge_evidence"]
        assert len(evidence) == 1
        assert evidence[0]["scope_match"] is True

    def test_source_confidence_mapping_complete(self):
        """验证所有 source_type 都有对应的 confidence 映射"""
        from app.agent.nodes.evidence_filter_node import SOURCE_TYPE_CONFIDENCE

        expected_types = [
            "product_facts", "product_mapping", "shipping_policy",
            "aftersales_policy", "installation_guide", "faq",
            "response_templates", "high_risk_sop", "forbidden_rules",
            "real_cases", "feedback_records",
        ]
        for st in expected_types:
            assert st in SOURCE_TYPE_CONFIDENCE
            assert SOURCE_TYPE_CONFIDENCE[st] in ("high", "medium", "low")

    def test_evidence_gate_fields_are_exposed(self):
        from app.agent.nodes.evidence_filter_node import evidence_filter_node

        state = {
            "retrieved_chunks": [
                {
                    "score": 0.9,
                    "chunk_id": "c1",
                    "entry_id": "e1",
                    "title": "material",
                    "source_type": "product_facts",
                    "intent": "general",
                    "chunk_text": "material fact",
                    "metadata": {"auto_reply_allowed": True, "fact_type": "material"},
                    "fact_source_type": "structured_product_profile",
                    "material_provenance": "structured_product_profile",
                    "entry_status": "published",
                    "entry_risk_level": "low",
                    "source_sheet": "",
                    "row_number": 0,
                    "fact_type": "material",
                },
            ],
            "intent": "product_question",
            "allowed_source_types": ["product_facts"],
            "query_fact_type": "material",
            "slots": {},
        }

        result = evidence_filter_node(state)
        evidence = result["knowledge_evidence"]

        assert len(evidence) == 1
        assert evidence[0]["gate_status"] == "allowed"
        assert evidence[0]["gate_reasons"] == []
        assert evidence[0]["direct_answer_allowed"] is True
        assert evidence[0]["requires_human_review"] is False
        assert evidence[0]["material_provenance"] == "structured_product_profile"

    def test_odor_query_can_use_material_fact_when_text_mentions_no_odor(self):
        from app.agent.nodes.evidence_filter_node import evidence_filter_node

        state = {
            "retrieved_chunks": [
                {
                    "score": 0.9,
                    "chunk_id": "c-odor-material",
                    "entry_id": "e-odor-material",
                    "title": "material",
                    "source_type": "product_facts",
                    "intent": "general",
                    "chunk_text": "\u6211\u4eec\u91c7\u7528\u73af\u4fddPP\u6750\u6599\uff0c\u65e0\u6bd2\u65e0\u5473\uff0c\u4e0d\u542bBPA\u7b49\u6709\u5bb3\u7269\u8d28\u3002",
                    "metadata": {"auto_reply_allowed": True, "fact_type": "material"},
                    "entry_status": "published",
                    "entry_risk_level": "low",
                    "source_sheet": "",
                    "row_number": 0,
                    "fact_type": "material",
                },
            ],
            "intent": "product_question",
            "allowed_source_types": ["product_facts"],
            "query_fact_type": "odor",
            "slots": {},
        }

        result = evidence_filter_node(state)
        evidence = result["knowledge_evidence"]

        assert len(evidence) == 1
        assert evidence[0]["evidence_fact_type"] == "odor"
        assert evidence[0]["mismatch_reason"] == ""
        assert evidence[0]["gate_status"] == "allowed"
        assert evidence[0]["direct_answer_allowed"] is True

    def test_risky_installation_claim_is_allowed_for_installation_guide(self):
        from app.agent.nodes.evidence_filter_node import evidence_filter_node

        state = {
            "retrieved_chunks": [
                {
                    "score": 0.9,
                    "chunk_id": "c-risk-install",
                    "entry_id": "e-risk-install",
                    "title": "installation",
                    "source_type": "installation_guide",
                    "intent": "general",
                    "chunk_text": "\u5b89\u88c5\u5f88\u65b9\u4fbf\uff0c\u4e0d\u9700\u8981\u989d\u5916\u5de5\u5177\u3002",
                    "metadata": {"auto_reply_allowed": True, "fact_type": "installation"},
                    "entry_status": "published",
                    "entry_risk_level": "low",
                    "source_sheet": "",
                    "row_number": 0,
                    "fact_type": "installation",
                },
            ],
            "intent": "installation",
            "allowed_source_types": ["installation_guide"],
            "query_fact_type": "installation",
            "slots": {},
        }

        result = evidence_filter_node(state)
        evidence = result["knowledge_evidence"]

        assert len(evidence) == 1
        assert evidence[0]["gate_status"] == "allowed"
        assert evidence[0]["direct_answer_allowed"] is True
        assert evidence[0]["reference_only"] is False

    def test_scope_metadata_is_preserved_for_rag_judge(self):
        from app.agent.nodes.evidence_filter_node import evidence_filter_node

        state = {
            "retrieved_chunks": [
                {
                    "score": 0.9,
                    "chunk_id": "c-scope",
                    "entry_id": "e-scope",
                    "title": "bookcase material",
                    "source_type": "product_facts",
                    "intent": "general",
                    "chunk_text": "material fact",
                    "metadata": {"auto_reply_allowed": True},
                    "product_scope": ["儿童书架"],
                    "sku_scope": ["SKU-BOOK"],
                    "index_status": "ready",
                    "fact_review_status": "verified",
                    "entry_status": "published",
                    "entry_risk_level": "low",
                    "source_sheet": "",
                    "row_number": 0,
                },
            ],
            "intent": "product_question",
            "allowed_source_types": ["product_facts"],
            "matched_product_name": "儿童书架",
            "slots": {"sku_code": "SKU-BOOK"},
        }

        result = evidence_filter_node(state)
        evidence = result["knowledge_evidence"][0]

        assert evidence["product_scope"] == ["儿童书架"]
        assert evidence["sku_scope"] == ["SKU-BOOK"]
        assert evidence["index_status"] == "ready"
        assert evidence["fact_review_status"] == "verified"

    def test_sidecar_product_candidate_blocks_wrong_scope_evidence(self):
        from app.agent.nodes.evidence_filter_node import evidence_filter_node

        state = {
            "retrieved_chunks": [
                {
                    "score": 0.9,
                    "chunk_id": "c-wrong-product",
                    "entry_id": "e-wrong-product",
                    "title": "wrong product material",
                    "source_type": "product_facts",
                    "intent": "general",
                    "chunk_text": "material fact for another product",
                    "metadata": {"auto_reply_allowed": True},
                    "product_scope": ["一号小熊床护栏"],
                    "sku_scope": [],
                    "entry_status": "published",
                    "entry_risk_level": "low",
                    "source_sheet": "",
                    "row_number": 0,
                },
            ],
            "intent": "product_question",
            "allowed_source_types": ["product_facts"],
            "product_candidates": [{"value": "英禾喂养台多功能收纳柜"}],
            "slots": {},
        }

        result = evidence_filter_node(state)

        assert result["knowledge_evidence"] == []
        assert result["rejected_evidence"][0]["reasons"] == ["product_scope_mismatch"]
