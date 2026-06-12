"""
测试知识发布质量门槛
"""

import os
import uuid
import tempfile
import pytest

_test_db_path = None


def setup_module(module):
    global _test_db_path
    _test_db_path = os.path.join(tempfile.gettempdir(), f"test_quality_gate_{uuid.uuid4().hex}.db")

    import app.db as db_module
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    _test_engine = create_engine(f"sqlite:///{_test_db_path}", connect_args={"check_same_thread": False})
    db_module.engine = _test_engine
    db_module.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=_test_engine, expire_on_commit=False)

    from app.models.knowledge_base import Base
    Base.metadata.create_all(bind=_test_engine)


def teardown_module(module):
    try:
        if _test_db_path and os.path.exists(_test_db_path):
            os.unlink(_test_db_path)
    except Exception:
        pass



def _make_entry(**overrides):
    """创建测试知识条目 ORM 对象。"""
    from app.models.knowledge_base import KnowledgeEntry

    defaults = {
        "source_type": "product_facts",
        "title": "一号围兜颜色",
        "content": "一号狮子围兜有蓝色和粉色两种颜色可选",
        "intent": "product_question",
        "risk_level": "low",
        "status": "pending_review",
        "created_by": "tester",
        "reviewed_by": "supervisor",
        "source_sheet": "商品详情页",
        "human_review_required": False,
    }
    defaults.update(overrides)
    cols = {c.name for c in KnowledgeEntry.__table__.columns}
    entry = KnowledgeEntry(**{k: v for k, v in defaults.items() if k in cols})
    entry.set_product_scope(overrides.get("product_scope", ["一号狮子围兜"]))
    entry.set_sku_scope(overrides.get("sku_scope", ["SKU001"]))
    entry.set_platform_scope(overrides.get("platform_scope", []))

    from app.db import SessionLocal
    db = SessionLocal()
    try:
        db.add(entry)
        db.commit()
        db.refresh(entry)
    finally:
        db.close()
    return entry


class TestKnowledgeQualityGate:

    def test_valid_entry_passes(self):
        from app.services.knowledge_quality_gate import validate_for_publish
        entry = _make_entry()
        result = validate_for_publish(entry)
        assert result["passed"] is True

    def test_empty_title_blocks(self):
        from app.services.knowledge_quality_gate import validate_for_publish
        entry = _make_entry(title="")
        result = validate_for_publish(entry)
        assert result["passed"] is False
        assert any("标题" in i for i in result["blocking_issues"])

    def test_empty_content_blocks(self):
        from app.services.knowledge_quality_gate import validate_for_publish
        entry = _make_entry(content="")
        result = validate_for_publish(entry)
        assert result["passed"] is False
        assert any("内容" in i for i in result["blocking_issues"])

    def test_missing_source_type_blocks(self):
        from app.services.knowledge_quality_gate import validate_for_publish
        entry = _make_entry(source_type="")
        result = validate_for_publish(entry)
        assert result["passed"] is False
        assert any("source_type" in i for i in result["blocking_issues"])

    def test_product_facts_without_scope_blocks(self):
        from app.services.knowledge_quality_gate import validate_for_publish
        entry = _make_entry(product_scope=[], sku_scope=[])
        result = validate_for_publish(entry)
        assert result["passed"] is False
        assert any("product_scope" in i for i in result["blocking_issues"])

    def test_high_risk_without_human_review_blocks(self):
        from app.services.knowledge_quality_gate import validate_for_publish
        entry = _make_entry(content="材质为纯棉，无毒环保", human_review_required=False)
        result = validate_for_publish(entry)
        assert result["passed"] is False

    def test_forbidden_absolute_claims_blocks(self):
        from app.services.knowledge_quality_gate import validate_for_publish
        entry = _make_entry(content="绝对无毒，100%安全")
        result = validate_for_publish(entry)
        assert result["passed"] is False
        assert any("绝对承诺" in i for i in result["blocking_issues"])

    def test_phone_number_blocks(self):
        from app.services.knowledge_quality_gate import validate_for_publish
        entry = _make_entry(content="联系电话：13812345678")
        result = validate_for_publish(entry)
        assert result["passed"] is False
        assert any("手机号" in i for i in result["blocking_issues"])

    def test_id_card_blocks(self):
        from app.services.knowledge_quality_gate import validate_for_publish
        entry = _make_entry(content="身份证号：110101199001011234")
        result = validate_for_publish(entry)
        assert result["passed"] is False
        assert any("身份证" in i for i in result["blocking_issues"])

    def test_token_in_content_blocks(self):
        from app.services.knowledge_quality_gate import validate_for_publish
        entry = _make_entry(content="api_key=sk-1234567890abcdef")
        result = validate_for_publish(entry)
        assert result["passed"] is False
        assert any("Token" in i or "密钥" in i for i in result["blocking_issues"])

    def test_factual_without_source_sheet_blocks(self):
        from app.services.knowledge_quality_gate import validate_for_publish
        entry = _make_entry(
            content="这款商品颜色为蓝色",
            source_sheet="",
            source_type="product_facts",
        )
        # 规则 12 需要包含 FACT_FIELDS_REQUIRING_REFERENCE 中的关键词
        # 这里内容不含这些关键词，所以不会触发该规则
        # 但我们需要一个会触发的测试
        # 使用 "承重" 作为事实字段
        entry2 = _make_entry(
            content="承重为50公斤",
            source_sheet="",
            source_type="product_facts",
            human_review_required=True,
            reviewed_by="supervisor",
        )
        result = validate_for_publish(entry2)
        assert result["passed"] is False
        assert any("source_sheet" in i for i in result["blocking_issues"])

    def test_high_risk_same_reviewer_creator_blocks(self):
        from app.services.knowledge_quality_gate import validate_for_publish
        entry = _make_entry(
            source_type="high_risk_sop",
            created_by="tester",
            reviewed_by="tester",
            risk_level="high",
        )
        result = validate_for_publish(entry)
        assert result["passed"] is False
        assert any("审核人" in i for i in result["blocking_issues"])

    def test_human_review_required_without_reviewer_blocks(self):
        from app.services.knowledge_quality_gate import validate_for_publish
        entry = _make_entry(
            human_review_required=True,
            reviewed_by="",
        )
        result = validate_for_publish(entry)
        assert result["passed"] is False
        assert any("审核人" in i for i in result["blocking_issues"])

    def test_returns_validation_metadata(self):
        from app.services.knowledge_quality_gate import validate_for_publish
        entry = _make_entry()
        result = validate_for_publish(entry)
        assert "validated_at" in result
        assert "validation_version" in result

    def test_check_publish_quality_backward_compat(self):
        from app.services.knowledge_quality_gate import check_publish_quality
        entry = _make_entry()
        result = check_publish_quality(entry)
        assert "passed" in result
        assert "blocking_issues" in result
