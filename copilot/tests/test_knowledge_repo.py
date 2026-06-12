"""
测试知识库 Repository 层：CRUD、状态流、权限、高风险强制审核
"""

import pytest
import os
import tempfile
import uuid

# 独立测试数据库
_test_db_path = None


_orig_engine = None
_orig_session_local = None


def setup_module(module):
    global _test_db_path, _orig_engine, _orig_session_local
    _test_db_path = os.path.join(tempfile.gettempdir(), f"test_knowledge_repo_{uuid.uuid4().hex}.db")

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


from app.repositories.knowledge_entry_repository import KnowledgeEntryRepository
from app.repositories.knowledge_version_repository import KnowledgeVersionRepository
from app.repositories.knowledge_chunk_repository import KnowledgeChunkRepository
from app.services.knowledge_index_service import KnowledgeIndexService


class TestKnowledgeEntryCRUD:
    def test_create_entry(self):
        entry = KnowledgeEntryRepository.create(
            source_type="faq",
            title="测试FAQ",
            content="这是测试内容",
            intent="product_question",
            created_by="operator_a",
        )
        assert entry.id is not None
        assert entry.status == "draft"
        assert entry.version == 1

    def test_get_by_id(self):
        entry = KnowledgeEntryRepository.create(source_type="faq", title="T2", content="C2", created_by="op")
        found = KnowledgeEntryRepository.get_by_id(entry.id)
        assert found is not None
        assert found.title == "T2"

    def test_update_entry(self):
        entry = KnowledgeEntryRepository.create(source_type="faq", title="T3", content="C3", created_by="op")
        updated = KnowledgeEntryRepository.update(entry.id, {"title": "T3-modified"}, updated_by="op")
        assert updated.title == "T3-modified"

    def test_archive_entry(self):
        entry = KnowledgeEntryRepository.create(source_type="faq", title="T4", content="C4", created_by="op")
        archived = KnowledgeEntryRepository._archive(entry.id, user="op")
        assert archived.status == "archived"


class TestStatusFlow:
    def test_draft_to_pending_to_published(self):
        from app.services.knowledge_lifecycle_service import KnowledgeLifecycleService

        entry = KnowledgeEntryRepository.create(source_type="shipping_policy", title="发货政策", content="48小时内发货", created_by="op")
        assert entry.status == "draft"

        # operator 提交审核
        pending = KnowledgeEntryRepository._submit_for_review(entry.id, user="op")
        assert pending.status == "pending_review"

        # 通过 LifecycleService 审核通过并发布（触发索引）
        result = KnowledgeLifecycleService.approve(entry.id, user="supervisor_1")
        assert result["status"] == "published"

        # 验证 chunks 已创建
        chunks = KnowledgeChunkRepository.search_chunks(query="发货", source_types=["shipping_policy"], intent="", top_k=5)
        assert any(c["entry_id"] == entry.id for c in chunks)

    def test_reject_flow(self):
        entry = KnowledgeEntryRepository.create(source_type="faq", title="R1", content="R1c", created_by="op")
        KnowledgeEntryRepository._submit_for_review(entry.id, user="op")
        rejected = KnowledgeEntryRepository._review_reject(entry.id, user="supervisor_1", reason="内容不准确")
        assert rejected.status == "rejected"

    def test_cannot_publish_from_draft(self):
        entry = KnowledgeEntryRepository.create(source_type="faq", title="P1", content="P1c", created_by="op")
        with pytest.raises(ValueError, match="不允许发布"):
            KnowledgeEntryRepository._publish(entry.id, user="supervisor_1")


class TestHighRiskEnforcement:
    def test_high_risk_source_type_forces_review(self):
        entry = KnowledgeEntryRepository.create(
            source_type="high_risk_sop",
            title="客诉SOP",
            content="处理步骤...",
            risk_level="medium",
            created_by="op",
        )
        assert entry.auto_reply_allowed is False
        assert entry.human_review_required is True
        assert entry.risk_level == "high"

    def test_high_risk_level_forces_review(self):
        entry = KnowledgeEntryRepository.create(
            source_type="faq",
            title="高危问题",
            content="...",
            risk_level="critical",
            created_by="op",
        )
        assert entry.auto_reply_allowed is False
        assert entry.human_review_required is True

    def test_high_risk_must_supervisor_publish(self):
        entry = KnowledgeEntryRepository.create(
            source_type="high_risk_sop",
            title="高危SOP",
            content="...",
            created_by="op",
        )
        KnowledgeEntryRepository._submit_for_review(entry.id, user="op")
        with pytest.raises(ValueError, match="supervisor"):
            KnowledgeEntryRepository._publish(entry.id, user="op")


class TestVersionRollback:
    def test_rollback_restores_content(self):
        entry = KnowledgeEntryRepository.create(source_type="faq", title="V1", content="原始内容", created_by="op")
        entry_id = entry.id
        KnowledgeEntryRepository._submit_for_review(entry_id, user="op")
        KnowledgeEntryRepository._review_approve(entry_id, user="supervisor_1")

        # 先归档才能修改（业务规则：已发布不能直接修改）
        KnowledgeEntryRepository._archive(entry_id, user="supervisor_1")

        # 修改
        KnowledgeEntryRepository.update(entry_id, {"title": "V1-modified", "content": "修改后内容"}, updated_by="op")

        # 回滚到版本 1（发布时的快照）
        from app.services.knowledge_lifecycle_service import KnowledgeLifecycleService
        result = KnowledgeLifecycleService.rollback_to_draft(entry_id, version=1, user="supervisor_1")
        assert result["status"] == "draft"
        rolled = KnowledgeEntryRepository.get_by_id(entry_id)
        assert rolled.title == "V1"  # 恢复原始标题


class TestChunkCreation:
    def test_publish_creates_chunks(self):
        entry = KnowledgeEntryRepository.create(
            source_type="product_facts",
            title="儿童书架",
            content="材质：实木\n\n尺寸：60x120cm\n\n承重：50kg",
            intent="product_question",
            created_by="op",
        )
        entry_id = entry.id
        KnowledgeEntryRepository._submit_for_review(entry_id, user="op")
        KnowledgeIndexService.on_publish(entry_id, user="supervisor_1")

        chunks = KnowledgeChunkRepository.search_chunks(
            query="材质",
            source_types=["product_facts"],
            intent="product_question",
            top_k=5,
        )
        assert len(chunks) > 0
        assert any("材质" in c["chunk_text"] for c in chunks)

    def test_draft_not_searchable(self):
        entry = KnowledgeEntryRepository.create(
            source_type="faq",
            title="草稿FAQ",
            content="这是草稿内容",
            intent="product_question",
            created_by="op",
        )
        # 不发布
        chunks = KnowledgeChunkRepository.search_chunks(
            query="草稿",
            source_types=["faq"],
            top_k=5,
        )
        assert len(chunks) == 0


class TestDuplicateCheck:
    def test_duplicate_detection(self):
        KnowledgeEntryRepository.create(source_type="faq", title="Dup", content="Dup content", created_by="op")
        dup = KnowledgeEntryRepository.check_duplicate("Dup", "faq", "Dup content")
        assert dup is not None

        not_dup = KnowledgeEntryRepository.check_duplicate("Dup", "faq", "Different content")
        assert not_dup is None



class TestPublishChain:
    """P0: review_approve → published → chunks → 检索 验收"""

    def test_review_approve_sets_published(self):
        e = KnowledgeEntryRepository.create(source_type="faq", title="P1", content="P1c", created_by="op")
        KnowledgeEntryRepository._submit_for_review(e.id, user="op")
        reviewed = KnowledgeEntryRepository._review_approve(e.id, user="supervisor_1")
        assert reviewed.status == "published"

    def test_review_approve_creates_chunks(self):
        from app.services.knowledge_lifecycle_service import KnowledgeLifecycleService
        e = KnowledgeEntryRepository.create(source_type="faq", title="P2", content="P2 chunk content", created_by="op", product_scope=["P2产品"])
        KnowledgeEntryRepository._submit_for_review(e.id, user="op")
        result = KnowledgeLifecycleService.approve(e.id, user="supervisor_1")
        assert result["status"] == "published"
        chunks = KnowledgeChunkRepository.search_chunks(query="chunk", source_types=["faq"], intent="", top_k=5)
        assert any(c["entry_id"] == e.id for c in chunks)

    def test_published_retrievable_by_rag(self):
        from app.services.knowledge_lifecycle_service import KnowledgeLifecycleService
        e = KnowledgeEntryRepository.create(source_type="faq", title="P3", content="P3 retrievable content", intent="product_question", created_by="op", product_scope=["P3产品"])
        KnowledgeEntryRepository._submit_for_review(e.id, user="op")
        result = KnowledgeLifecycleService.approve(e.id, user="supervisor_1")
        assert result["status"] == "published"
        chunks = KnowledgeChunkRepository.search_chunks(query="retrievable", source_types=["faq"], intent="product_question", top_k=5)
        assert any(c["entry_id"] == e.id for c in chunks)

    def test_draft_pending_archived_not_retrievable(self):
        # draft
        d = KnowledgeEntryRepository.create(source_type="faq", title="P4d", content="P4 draft", created_by="op")
        # pending
        p = KnowledgeEntryRepository.create(source_type="faq", title="P4p", content="P4 pending", created_by="op")
        KnowledgeEntryRepository._submit_for_review(p.id, user="op")
        # published then archived
        a = KnowledgeEntryRepository.create(source_type="faq", title="P4a", content="P4 archived", created_by="op")
        KnowledgeEntryRepository._submit_for_review(a.id, user="op")
        KnowledgeEntryRepository._review_approve(a.id, user="supervisor_1")
        KnowledgeEntryRepository._archive(a.id, user="supervisor_1")

        for entry in [d, p, a]:
            chunks = KnowledgeChunkRepository.search_chunks(query="P4", source_types=["faq"], intent="", top_k=5)
            assert not any(c["entry_id"] == entry.id for c in chunks), f"{entry.status} should not be retrievable"

    def test_high_risk_review_keeps_flags(self):
        e = KnowledgeEntryRepository.create(
            source_type="high_risk_sop", title="P5", content="P5c",
            intent="complaint", risk_level="high",
            auto_reply_allowed=True, human_review_required=False,
            created_by="op",
        )
        assert e.auto_reply_allowed == False
        assert e.human_review_required == True
        KnowledgeEntryRepository._submit_for_review(e.id, user="op")
        reviewed = KnowledgeEntryRepository._review_approve(e.id, user="supervisor_1")
        assert reviewed.status == "published"
        assert reviewed.auto_reply_allowed == False
        assert reviewed.human_review_required == True

    def test_operator_cannot_publish_high_risk(self):
        e = KnowledgeEntryRepository.create(
            source_type="high_risk_sop", title="P6", content="P6c",
            intent="complaint", risk_level="high",
            created_by="op",
        )
        KnowledgeEntryRepository._submit_for_review(e.id, user="op")
        with pytest.raises(ValueError):
            KnowledgeEntryRepository._publish(e.id, user="op")

    def test_archived_rollback_success(self):
        from app.services.knowledge_lifecycle_service import KnowledgeLifecycleService
        e = KnowledgeEntryRepository.create(source_type="faq", title="P7", content="P7c", created_by="op")
        KnowledgeEntryRepository._submit_for_review(e.id, user="op")
        KnowledgeEntryRepository._review_approve(e.id, user="supervisor_1")
        KnowledgeEntryRepository._archive(e.id, user="supervisor_1")
        result = KnowledgeLifecycleService.rollback_to_draft(e.id, version=1, user="supervisor_1")
        assert result["status"] == "draft"

    def test_rollback_not_retrievable_until_republished(self):
        from app.services.knowledge_lifecycle_service import KnowledgeLifecycleService
        e = KnowledgeEntryRepository.create(source_type="faq", title="回滚测试", content="回滚测试内容", created_by="op", product_scope=["回滚产品"])
        KnowledgeEntryRepository._submit_for_review(e.id, user="op")
        result = KnowledgeLifecycleService.approve(e.id, user="supervisor_1")
        assert result["status"] == "published"
        KnowledgeLifecycleService.archive(e.id, user="supervisor_1")
        KnowledgeLifecycleService.rollback_to_draft(e.id, version=1, user="supervisor_1")
        chunks = KnowledgeChunkRepository.search_chunks(query="回滚", source_types=["faq"], intent="", top_k=5)
        assert not any(c["entry_id"] == e.id for c in chunks)

        # republish
        KnowledgeEntryRepository._submit_for_review(e.id, user="op")
        result2 = KnowledgeLifecycleService.approve(e.id, user="supervisor_1")
        assert result2["status"] == "published"
        chunks2 = KnowledgeChunkRepository.search_chunks(query="回滚", source_types=["faq"], intent="", top_k=5)
        assert any(c["entry_id"] == e.id for c in chunks2)
