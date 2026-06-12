"""
测试知识索引一致性
"""

import os
import uuid
import tempfile
import pytest

_test_db_path = None


def setup_module(module):
    global _test_db_path
    _test_db_path = os.path.join(tempfile.gettempdir(), f"test_index_consistency_{uuid.uuid4().hex}.db")

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


from app.repositories.knowledge_entry_repository import KnowledgeEntryRepository
from app.services.knowledge_lifecycle_service import KnowledgeLifecycleService
from app.services.knowledge_index_pipeline import KnowledgeIndexPipeline
from app.repositories.knowledge_version_repository import KnowledgeVersionRepository
from app.models.knowledge_base import KnowledgeEntry, KnowledgeChunk


def _set_status(entry_id, status):
    from app.db import engine
    from sqlalchemy import text
    with engine.connect() as conn:
        conn.execute(text("UPDATE knowledge_entries SET status=:status WHERE id=:id"),
                     {"status": status, "id": entry_id})
        conn.commit()


def _create_and_publish(**overrides):
    _suffix = uuid.uuid4().hex[:6]
    defaults = {
        "source_type": "product_facts",
        "title": f"测试知识条目-{_suffix}",
        "content": f"这是一条测试知识内容-{_suffix}，用于验证索引功能正常工作。",
        "intent": "product_question",
        "product_scope": [f"测试商品-{_suffix}"],
        "sku_scope": [f"SKU-{_suffix}"],
        "risk_level": "low",
        "created_by": "tester",
        "source_sheet": "测试来源",
    }
    defaults.update(overrides)
    entry = KnowledgeEntryRepository.create(**defaults)
    _set_status(entry.id, "pending_review")
    result = KnowledgeLifecycleService.approve(entry.id, "supervisor")
    # approve returns a dict with id, status, etc.
    # If quality gate blocked, the test should handle it
    return result


class TestKnowledgeIndexConsistency:

    def test_published_entry_has_ready_index(self):
        result = _create_and_publish()
        assert "error" not in result, f"approve failed: {result}"
        entry_id = result["id"]

        status = KnowledgeIndexPipeline.get_index_status(entry_id)
        assert status["index_status"] == "ready"
        assert status["chunk_count"] > 0

    def test_non_published_rejected_from_index(self):
        entry = KnowledgeEntryRepository.create(
            source_type="product_facts", title="测试", content="测试内容", created_by="tester",
        )
        result = KnowledgeIndexPipeline.index_published_entry(entry.id)
        assert result.get("rejected") is True

    def test_archive_removes_chunks(self):
        result = _create_and_publish()
        assert "error" not in result, f"approve failed: {result}"
        entry_id = result["id"]

        status = KnowledgeIndexPipeline.get_index_status(entry_id)
        assert status["chunk_count"] > 0

        KnowledgeLifecycleService.archive(entry_id, "admin")

        status = KnowledgeIndexPipeline.get_index_status(entry_id)
        assert status["chunk_count"] == 0

    def test_rollback_no_chunks(self):
        result = _create_and_publish()
        assert "error" not in result, f"approve failed: {result}"
        entry_id = result["id"]

        KnowledgeVersionRepository.create_version(entry_id, "admin", "测试")
        KnowledgeLifecycleService.rollback_to_draft(entry_id, 1, "admin")

        status = KnowledgeIndexPipeline.get_index_status(entry_id)
        assert status["status"] == "draft"
        assert status["chunk_count"] == 0

    def test_validate_index_consistency(self):
        result = _create_and_publish()
        assert "error" not in result, f"approve failed: {result}"
        consistency = KnowledgeIndexPipeline.validate_index_consistency(result["id"])
        assert consistency["consistent"] is True

    def test_inconsistent_when_published_no_chunks(self):
        from sqlalchemy import text
        entry = KnowledgeEntryRepository.create(
            source_type="product_facts", title="测试", content="测试内容", created_by="tester",
        )
        # Use raw SQL to bypass any session caching
        from app.db import engine
        with engine.connect() as conn:
            conn.execute(text(
                "UPDATE knowledge_entries SET status='published', index_status='ready', content_hash='fake' WHERE id=:id"
            ), {"id": entry.id})
            conn.commit()

        consistency = KnowledgeIndexPipeline.validate_index_consistency(entry.id)
        assert consistency["consistent"] is False
        assert len(consistency["issues"]) > 0

    def test_revision_does_not_overwrite_published(self):
        result = _create_and_publish()
        assert "error" not in result, f"approve failed: {result}"
        entry_id = result["id"]

        revision = KnowledgeLifecycleService.create_revision(entry_id, "editor")
        assert "error" not in revision, f"revision failed: {revision}"
        revision_id = revision.get("revision_entry_id")
        assert revision_id is not None

        original_status = KnowledgeIndexPipeline.get_index_status(entry_id)
        assert original_status["status"] == "published"
        assert original_status["index_status"] == "ready"
        assert original_status["chunk_count"] > 0

        revision_status = KnowledgeIndexPipeline.get_index_status(revision_id)
        assert revision_status["status"] == "draft"
        assert revision_status["chunk_count"] == 0

    def test_rebuild_entry_only_published(self):
        result = _create_and_publish()
        assert "error" not in result, f"approve failed: {result}"
        rebuild_result = KnowledgeIndexPipeline.rebuild_entry(result["id"])
        assert rebuild_result.get("index_status") == "ready"

    def test_rebuild_rejects_non_published(self):
        entry = KnowledgeEntryRepository.create(
            source_type="product_facts", title="测试", content="测试内容", created_by="tester",
        )
        rebuild_result = KnowledgeIndexPipeline.rebuild_entry(entry.id)
        assert rebuild_result.get("rejected") is True

    def test_published_failed_not_searchable(self):
        from app.repositories.knowledge_chunk_repository import KnowledgeChunkRepository

        entry = KnowledgeEntryRepository.create(
            source_type="product_facts", title="测试失败", content="失败条目内容",
            created_by="tester",
        )
        from app.db import SessionLocal
        db = SessionLocal()
        try:
            e = db.query(KnowledgeEntry).filter(KnowledgeEntry.id == entry.id).first()
            e.status = "published"
            e.index_status = "failed"
            db.commit()
        finally:
            db.close()

        results = KnowledgeChunkRepository.search_chunks(
            query="失败条目", source_types=["product_facts"],
        )
        entry_ids = [r["entry_id"] for r in results]
        assert entry.id not in entry_ids
