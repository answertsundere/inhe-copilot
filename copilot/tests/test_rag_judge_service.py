"""
测试 RAG Judge 服务
"""

import os
import uuid
import tempfile
import pytest

_test_db_path = None


_orig_engine = None
_orig_session_local = None


def setup_module(module):
    global _test_db_path, _orig_engine, _orig_session_local
    _test_db_path = os.path.join(tempfile.gettempdir(), f"test_rag_judge_{uuid.uuid4().hex}.db")

    import app.db as db_module
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    _orig_engine = db_module.engine
    _orig_session_local = db_module.SessionLocal

    _test_engine = create_engine(f"sqlite:///{_test_db_path}", connect_args={"check_same_thread": False})
    db_module.engine = _test_engine
    db_module.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=_test_engine, expire_on_commit=False)

    from app.models.knowledge_base import Base
    Base.metadata.create_all(bind=_test_engine)


def teardown_module(module):
    global _orig_engine, _orig_session_local
    import app.db as db_module
    if _orig_engine is not None:
        db_module.engine = _orig_engine
    if _orig_session_local is not None:
        db_module.SessionLocal = _orig_session_local
    try:
        if _test_db_path and os.path.exists(_test_db_path):
            os.unlink(_test_db_path)
    except Exception:
        pass


from app.services.rag_judge_service import judge_evidence, _deterministic_judge, INTENT_TO_ALLOWED_FACT_TYPES


def _make_evidence(**overrides):
    defaults = {
        "entry_id": 1,
        "chunk_id": 1,
        "source_type": "product_facts",
        "entry_status": "published",
        "chunk_text": "一号狮子围兜采用TPU防水材质",
        "product_scope": ["一号狮子围兜"],
        "sku_scope": ["SKU001"],
        "score": 0.8,
    }
    defaults.update(overrides)
    return defaults


class TestRAGJudgeService:

    def test_correct_evidence_passes(self):
        result = judge_evidence(
            query="一号围兜防水吗",
            resolved_product="一号狮子围兜",
            used_evidence=[_make_evidence()],
        )
        assert result["passed"] is True
        assert result["deterministic_passed"] is True

    def test_wrong_product_detected(self):
        result = judge_evidence(
            query="一号围兜防水吗",
            resolved_product="一号狮子围兜",
            used_evidence=[_make_evidence(product_scope=["六号防摔枕"])],
        )
        assert result["wrong_product_detected"] is True
        assert result["passed"] is False

    def test_wrong_sku_detected(self):
        result = judge_evidence(
            query="一号围兜防水吗",
            resolved_product="一号狮子围兜",
            resolved_sku="SKU001",
            used_evidence=[_make_evidence(sku_scope=["SKU002"])],
        )
        assert result["wrong_sku_detected"] is True
        assert result["passed"] is False

    def test_wrong_fact_type_detected(self):
        result = judge_evidence(
            query="一号围兜防水吗",
            resolved_product="一号狮子围兜",
            expected_fact_type="product_facts",
            used_evidence=[_make_evidence(source_type="shipping_policy")],
        )
        assert result["wrong_fact_type_detected"] is True
        assert result["passed"] is False

    def test_non_published_evidence_rejected(self):
        result = judge_evidence(
            query="一号围兜防水吗",
            resolved_product="一号狮子围兜",
            used_evidence=[_make_evidence(entry_status="draft")],
        )
        assert result["status_match"] is False
        assert result["passed"] is False

    def test_number_prefix_conflict(self):
        result = judge_evidence(
            query="十号防摔枕材质",
            resolved_product="十号防摔枕",
            used_evidence=[_make_evidence(product_scope=["十一号防摔枕"])],
        )
        assert result["conflicting_evidence_detected"] is True
        assert result["passed"] is False

    def test_no_evidence_returns_pass(self):
        result = judge_evidence(query="测试查询", used_evidence=[])
        assert result["passed"] is True
        assert result["judge_mode"] == "no_evidence"

    def test_llm_judge_cannot_override_deterministic_rejection(self):
        det = _deterministic_judge(
            query="测试",
            resolved_product="一号围兜",
            resolved_sku="",
            expected_fact_type="",
            evidence=[_make_evidence(entry_status="draft")],
            final_reply="",
        )
        assert det["deterministic_passed"] is False

    def test_unsupported_claim_in_reply(self):
        result = judge_evidence(
            query="一号围兜防水吗",
            resolved_product="一号狮子围兜",
            used_evidence=[_make_evidence()],
            final_reply="十一号围兜不防水",
        )
        assert result["confidence"] < 1.0

    def test_returns_judge_metadata(self):
        result = judge_evidence(
            query="测试",
            used_evidence=[_make_evidence()],
        )
        assert "judge_mode" in result
        assert "duration_ms" in result
        assert "confidence" in result
        assert "reasons" in result

    # ========== INTENT_TO_ALLOWED_FACT_TYPES 映射测试 ==========

    def test_intent_mapping_blocks_wrong_fact_type(self):
        # logistics intent 使用 product_facts 证据应该被拒绝
        result = judge_evidence(
            query="我的包裹什么时候到",
            expected_fact_type="logistics_eta",
            used_evidence=[_make_evidence(source_type="product_facts")],
        )
        assert result["wrong_fact_type_detected"] is True
        assert result["passed"] is False
        assert "不允许的证据类型" in str(result["reasons"])

    def test_intent_mapping_allows_correct_fact_type(self):
        result = judge_evidence(
            query="我的包裹什么时候到",
            expected_fact_type="logistics_eta",
            used_evidence=[_make_evidence(source_type="logistics_fact")],
        )
        assert result["wrong_fact_type_detected"] is False
        assert result["passed"] is True

    def test_intent_mapping_allows_shipping_policy_for_logistics(self):
        result = judge_evidence(
            query="什么时候发货",
            expected_fact_type="shipping",
            used_evidence=[_make_evidence(source_type="shipping_policy")],
        )
        assert result["wrong_fact_type_detected"] is False
        assert result["passed"] is True

    def test_intent_mapping_blocks_policy_for_product_question(self):
        result = judge_evidence(
            query="这个围兜防水吗",
            expected_fact_type="product_question",
            used_evidence=[_make_evidence(source_type="shipping_policy")],
        )
        assert result["wrong_fact_type_detected"] is True
        assert result["passed"] is False

    def test_intent_mapping_falls_back_for_unknown_intent(self):
        # 未知 intent 应该保持旧行为
        result = judge_evidence(
            query="测试",
            expected_fact_type="unknown_intent",
            used_evidence=[_make_evidence(source_type="shipping_policy")],
        )
        # 未知 intent 不触发 fact_type 检查
        assert result["wrong_fact_type_detected"] is False

    def test_intent_mapping_required_intents_present(self):
        required = {
            "product_question", "product_consult",
            "logistics_eta", "logistics_trace", "shipping", "logistics",
            "aftersales", "refund", "complaint",
            "installation", "delivery_not_received",
        }
        assert required.issubset(set(INTENT_TO_ALLOWED_FACT_TYPES.keys()))

    def test_intent_mapping_no_empty_sets(self):
        for intent, allowed in INTENT_TO_ALLOWED_FACT_TYPES.items():
            assert len(allowed) > 0, f"intent={intent} has empty allowed set"


class TestRAGJudgeNodeIdentityFallback:

    def test_uses_sidecar_candidate_when_matched_product_missing(self):
        from app.agent.nodes.rag_judge_node import rag_judge_node

        state = {
            "customer_message": "这个安全吗",
            "normalized_message": "这个安全吗",
            "intent": "product_question",
            "matched_product_name": "",
            "product_candidates": [{"value": "英禾喂养台多功能收纳柜"}],
            "slots": {},
            "knowledge_evidence": [
                _make_evidence(
                    product_scope=["一号小熊床护栏"],
                    sku_scope=[],
                    chunk_text="床护栏安装说明",
                )
            ],
            "retrieved_chunks": [],
            "trace_steps": [],
        }

        result = rag_judge_node(state)

        assert result["rag_judge_result"]["wrong_product_detected"] is True
        assert result["knowledge_evidence"] == []
        assert result["answer_mode"] == "no_evidence_clarification"
