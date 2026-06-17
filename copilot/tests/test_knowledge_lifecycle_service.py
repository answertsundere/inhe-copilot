"""
测试知识生命周期服务
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
    _test_db_path = os.path.join(tempfile.gettempdir(), f"test_lifecycle_{uuid.uuid4().hex}.db")

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
from app.services.knowledge_lifecycle_service import KnowledgeLifecycleService


_counter = 0

def _unique_suffix():
    global _counter
    _counter += 1
    return f"-{uuid.uuid4().hex[:6]}"


def _create_entry(**overrides):
    defaults = {
        "source_type": "product_facts",
        "title": f"测试知识{_unique_suffix()}",
        "content": f"这是一条测试知识内容{_unique_suffix()}，用于功能验证。",
        "intent": "product_question",
        "product_scope": [f"测试商品-{uuid.uuid4().hex[:6]}"],
        "sku_scope": [f"SKU-{uuid.uuid4().hex[:6]}"],
        "risk_level": "low",
        "created_by": "test_user",
        "source_sheet": "商品详情页",
    }
    defaults.update(overrides)
    return KnowledgeEntryRepository.create(**defaults)


def _get_db():
    from app.db import SessionLocal
    return SessionLocal()


def _get_db_entry(entry_id):
    from app.models.knowledge_base import KnowledgeEntry
    db = _get_db()
    try:
        return db.query(KnowledgeEntry).filter(KnowledgeEntry.id == entry_id).first()
    finally:
        db.close()


def _set_status(entry_id, status):
    from app.models.knowledge_base import KnowledgeEntry
    from app.db import SessionLocal
    db = SessionLocal()
    try:
        e = db.query(KnowledgeEntry).filter(KnowledgeEntry.id == entry_id).first()
        e.status = status
        db.commit()
        # Expire all to force re-read
        db.expire_all()
    finally:
        db.close()


class TestKnowledgeLifecycleService:

    def test_create_draft(self):
        result = KnowledgeLifecycleService.create_draft(
            source_type="product_facts",
            title="测试",
            content="测试内容",
            created_by="tester",
        )
        assert "error" not in result
        assert result["status"] == "draft"

    def test_update_draft(self):
        entry = _create_entry()
        result = KnowledgeLifecycleService.update_draft(
            entry.id, {"title": "更新标题"}, updated_by="tester"
        )
        assert "error" not in result
        assert result["message"] == "更新成功"

    def test_cannot_update_published(self):
        entry = _create_entry()
        _set_status(entry.id, "published")

        result = KnowledgeLifecycleService.update_draft(
            entry.id, {"title": "尝试更新"}, updated_by="tester"
        )
        assert "error" in result

    def test_submit_review_from_draft(self):
        entry = _create_entry()
        result = KnowledgeLifecycleService.submit_review(entry.id, "reviewer")
        assert "error" not in result
        assert result["status"] == "pending_review"

    def test_cannot_submit_review_from_published(self):
        entry = _create_entry()
        _set_status(entry.id, "published")

        result = KnowledgeLifecycleService.submit_review(entry.id, "reviewer")
        assert "error" in result

    def test_approve_success(self):
        from app.models.knowledge_base import KnowledgeChunk

        entry = _create_entry()
        _set_status(entry.id, "pending_review")

        result = KnowledgeLifecycleService.approve(entry.id, "supervisor")
        assert "error" not in result
        assert result["status"] == "published"

        db = _get_db()
        try:
            chunks = db.query(KnowledgeChunk).filter(
                KnowledgeChunk.entry_id == entry.id
            ).all()
            assert len(chunks) > 0
        finally:
            db.close()

    def test_approve_with_quality_issues(self):
        entry = _create_entry(title="", content="测试")
        _set_status(entry.id, "pending_review")

        result = KnowledgeLifecycleService.approve(entry.id, "supervisor")
        assert "error" in result
        assert "blocking_issues" in result

    def test_reject(self):
        entry = _create_entry()
        _set_status(entry.id, "pending_review")

        result = KnowledgeLifecycleService.reject(entry.id, "supervisor", "内容不准确")
        assert "error" not in result
        assert result["status"] == "rejected"

    def test_archive_deletes_chunks(self):
        from app.models.knowledge_base import KnowledgeChunk

        entry = _create_entry()
        _set_status(entry.id, "pending_review")
        approve_result = KnowledgeLifecycleService.approve(entry.id, "supervisor")
        assert "error" not in approve_result, f"approve failed: {approve_result}"

        db = _get_db()
        try:
            chunks = db.query(KnowledgeChunk).filter(
                KnowledgeChunk.entry_id == entry.id
            ).all()
            assert len(chunks) > 0
        finally:
            db.close()

        result = KnowledgeLifecycleService.archive(entry.id, "admin")
        assert "error" not in result
        assert result["status"] == "archived"
        assert result["chunks_remaining"] == 0

    def test_rollback_creates_draft_no_chunks(self):
        from app.repositories.knowledge_version_repository import KnowledgeVersionRepository
        from app.models.knowledge_base import KnowledgeChunk

        entry = _create_entry()
        _set_status(entry.id, "pending_review")
        KnowledgeLifecycleService.approve(entry.id, "supervisor")

        KnowledgeVersionRepository.create_version(entry.id, "admin", "测试快照")

        result = KnowledgeLifecycleService.rollback_to_draft(entry.id, 1, "admin")
        assert "error" not in result
        assert result["status"] == "draft"

        db = _get_db()
        try:
            chunks = db.query(KnowledgeChunk).filter(
                KnowledgeChunk.entry_id == entry.id
            ).count()
            assert chunks == 0
        finally:
            db.close()

    def test_publish_uses_same_quality_gate_as_approve(self):
        entry = _create_entry(title="", content="")
        _set_status(entry.id, "pending_review")

        result = KnowledgeLifecycleService.publish(entry.id, "supervisor")
        assert "error" in result
        assert "blocking_issues" in result

    def test_create_revision(self):
        entry = _create_entry()
        _set_status(entry.id, "pending_review")
        approve_result = KnowledgeLifecycleService.approve(entry.id, "supervisor")
        assert "error" not in approve_result, f"approve failed: {approve_result}"

        result = KnowledgeLifecycleService.create_revision(entry.id, "editor")
        assert "error" not in result, f"revision failed: {result}"
        assert result["status"] == "draft"
        assert "revision_entry_id" in result

        original = _get_db_entry(entry.id)
        assert original.status == "published"

    def test_draft_not_searchable(self):
        from app.repositories.knowledge_chunk_repository import KnowledgeChunkRepository

        _create_entry()
        # draft has no chunks, so search won't find it

        results = KnowledgeChunkRepository.search_chunks(
            query="测试",
            source_types=["product_facts"],
        )
        # No chunks exist for drafts
        for r in results:
            assert r.get("entry_status") != "draft" or r.get("entry_status") is None

    def test_pending_review_not_searchable(self):
        from app.repositories.knowledge_chunk_repository import KnowledgeChunkRepository

        entry = _create_entry()
        _set_status(entry.id, "pending_review")

        results = KnowledgeChunkRepository.search_chunks(
            query="测试",
            source_types=["product_facts"],
        )
        for r in results:
            assert r.get("entry_status") != "pending_review"
