"""
测试 Revision 版本关系 + Rollback 语义修复
"""

import os
import uuid
import tempfile
import pytest

_test_db_path = None


def setup_module(module):
    global _test_db_path
    _test_db_path = os.path.join(tempfile.gettempdir(), f"test_lifecycle_rev_{uuid.uuid4().hex}.db")

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


class TestRevisionAndRollback:

    def _create_published_entry(self, product_scope=None):
        from app.services.knowledge_lifecycle_service import KnowledgeLifecycleService
        from app.services.knowledge_index_pipeline import KnowledgeIndexPipeline
        import uuid

        unique = uuid.uuid4().hex[:8]
        result = KnowledgeLifecycleService.create_draft(
            source_type="faq",
            title=f"测试FAQ-{unique}",
            content=f"测试内容-{unique}",
            intent="product_question",
            product_scope=product_scope or [f"测试商品-{unique}"],
            created_by="tester",
        )
        entry_id = result["id"]

        # 提交审核并通过
        KnowledgeLifecycleService.submit_review(entry_id, user="tester")

        # Mock Pipeline.index_published_entry 避免依赖 embedding
        original_index = KnowledgeIndexPipeline.index_published_entry
        KnowledgeIndexPipeline.index_published_entry = lambda eid: {"index_status": "ready", "chunks_created": 1}
        try:
            result = KnowledgeLifecycleService.approve(entry_id, user="tester")
        finally:
            KnowledgeIndexPipeline.index_published_entry = original_index

        if result.get("status") != "published":
            # 调试：检查质量门失败原因
            from app.repositories.knowledge_entry_repository import KnowledgeEntryRepository
            from app.services.knowledge_quality_gate import validate_for_publish
            entry = KnowledgeEntryRepository.get_by_id(entry_id)
            q = validate_for_publish(entry)
            raise AssertionError(f"approve failed: {result}, entry.product_scope={entry.get_product_scope()}, quality={q}")

        return entry_id

    def test_create_revision_keeps_original_published(self):
        from app.services.knowledge_lifecycle_service import KnowledgeLifecycleService
        from app.repositories.knowledge_entry_repository import KnowledgeEntryRepository

        entry_id = self._create_published_entry()
        result = KnowledgeLifecycleService.create_revision(entry_id, user="tester")

        assert "revision_entry_id" in result
        revision_id = result["revision_entry_id"]

        # 原 entry 仍保持 published
        original = KnowledgeEntryRepository.get_by_id(entry_id)
        assert original.status == "published"

        # 新 entry 是 draft
        revision = KnowledgeEntryRepository.get_by_id(revision_id)
        assert revision.status == "draft"
        assert revision.parent_entry_id == entry_id

    def test_create_revision_creates_version_snapshot(self):
        from app.services.knowledge_lifecycle_service import KnowledgeLifecycleService
        from app.repositories.knowledge_version_repository import KnowledgeVersionRepository

        entry_id = self._create_published_entry()
        versions_before = len(KnowledgeVersionRepository.get_versions(entry_id))

        KnowledgeLifecycleService.create_revision(entry_id, user="tester")

        versions_after = len(KnowledgeVersionRepository.get_versions(entry_id))
        assert versions_after == versions_before + 1

    def test_rollback_to_draft_cleans_chunks(self):
        from app.services.knowledge_lifecycle_service import KnowledgeLifecycleService
        from app.repositories.knowledge_entry_repository import KnowledgeEntryRepository
        from app.repositories.knowledge_version_repository import KnowledgeVersionRepository
        from app.models.knowledge_base import KnowledgeChunk
        from app.db import SessionLocal

        entry_id = self._create_published_entry()

        # 创建修订版
        KnowledgeLifecycleService.create_revision(entry_id, user="tester")

        # 获取版本列表
        versions = KnowledgeVersionRepository.get_versions(entry_id)
        assert len(versions) >= 1
        target_version = versions[0].version

        # rollback
        result = KnowledgeLifecycleService.rollback_to_draft(entry_id, target_version, user="tester")
        assert result["status"] == "draft"

        # 验证 chunks 已清理
        db = SessionLocal()
        try:
            remaining = db.query(KnowledgeChunk).filter(KnowledgeChunk.entry_id == entry_id).count()
            assert remaining == 0
        finally:
            db.close()

    def test_rollback_increments_version(self):
        from app.services.knowledge_lifecycle_service import KnowledgeLifecycleService
        from app.repositories.knowledge_version_repository import KnowledgeVersionRepository
        from app.repositories.knowledge_entry_repository import KnowledgeEntryRepository

        entry_id = self._create_published_entry()
        original_entry = KnowledgeEntryRepository.get_by_id(entry_id)
        original_version = original_entry.version

        versions = KnowledgeVersionRepository.get_versions(entry_id)
        target_version = versions[0].version

        result = KnowledgeLifecycleService.rollback_to_draft(entry_id, target_version, user="tester")

        entry = KnowledgeEntryRepository.get_by_id(entry_id)
        assert entry.version > original_version
        assert entry.status == "draft"

    def test_revision_cannot_be_created_from_draft(self):
        from app.services.knowledge_lifecycle_service import KnowledgeLifecycleService

        result = KnowledgeLifecycleService.create_draft(
            source_type="faq",
            title="草稿测试",
            content="内容",
            intent="product_question",
            created_by="tester",
        )
        entry_id = result["id"]

        result = KnowledgeLifecycleService.create_revision(entry_id, user="tester")
        assert "error" in result
        assert "published" in result["error"]

    def test_revision_publish_archives_original(self):
        """修订版发布成功后，原 published 条目必须被归档。"""
        from app.services.knowledge_lifecycle_service import KnowledgeLifecycleService
        from app.repositories.knowledge_entry_repository import KnowledgeEntryRepository
        from app.services.knowledge_index_pipeline import KnowledgeIndexPipeline

        entry_id = self._create_published_entry()
        result = KnowledgeLifecycleService.create_revision(entry_id, user="tester")
        revision_id = result["revision_entry_id"]

        # 修改 revision 内容、标题和商品范围，避免质量门冲突检测
        KnowledgeLifecycleService.update_draft(
            revision_id,
            {
                "title": f"修订版FAQ-{revision_id}",
                "content": f"修订后的内容-{revision_id}",
                "product_scope": [f"修订商品-{revision_id}"],
            },
            updated_by="tester"
        )
        KnowledgeLifecycleService.submit_review(revision_id, user="tester")

        # Mock 索引并通过审核
        original_index = KnowledgeIndexPipeline.index_published_entry
        KnowledgeIndexPipeline.index_published_entry = lambda eid: {"index_status": "ready", "chunks_created": 1}
        try:
            approve_result = KnowledgeLifecycleService.approve(revision_id, user="tester")
        finally:
            KnowledgeIndexPipeline.index_published_entry = original_index

        assert approve_result["status"] == "published", f"revision approve failed: {approve_result}"

        # 原 entry 应该被归档
        original = KnowledgeEntryRepository.get_by_id(entry_id)
        assert original.status == "archived"
        assert original.index_status == "removed"

        # revision 应该是 published
        revision = KnowledgeEntryRepository.get_by_id(revision_id)
        assert revision.status == "published"

    def test_only_one_published_per_revision_chain(self):
        """同一 revision 链中只有一个 published + ready 条目。"""
        from app.services.knowledge_lifecycle_service import KnowledgeLifecycleService
        from app.repositories.knowledge_entry_repository import KnowledgeEntryRepository
        from app.services.knowledge_index_pipeline import KnowledgeIndexPipeline
        from app.db import SessionLocal
        from app.models.knowledge_base import KnowledgeEntry

        entry_id = self._create_published_entry()
        result = KnowledgeLifecycleService.create_revision(entry_id, user="tester")
        revision_id = result["revision_entry_id"]

        KnowledgeLifecycleService.submit_review(revision_id, user="tester")

        original_index = KnowledgeIndexPipeline.index_published_entry
        KnowledgeIndexPipeline.index_published_entry = lambda eid: {"index_status": "ready", "chunks_created": 1}
        try:
            KnowledgeLifecycleService.approve(revision_id, user="tester")
        finally:
            KnowledgeIndexPipeline.index_published_entry = original_index

        # 查询同一链中 published 的数量
        db = SessionLocal()
        try:
            # 链包括 entry_id 和以 entry_id 为 parent 的所有条目
            chain_ids = [entry_id]
            # 查找所有以 entry_id 为 parent 的条目
            children = db.query(KnowledgeEntry).filter(
                KnowledgeEntry.parent_entry_id == entry_id
            ).all()
            chain_ids.extend([c.id for c in children])

            published_count = db.query(KnowledgeEntry).filter(
                KnowledgeEntry.id.in_(chain_ids),
                KnowledgeEntry.status == "published",
            ).count()
            assert published_count == 1, f"revision 链中有 {published_count} 个 published 条目，应为 1"
        finally:
            db.close()
