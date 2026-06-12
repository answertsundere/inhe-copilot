"""
知识生命周期服务 - 统一状态机

所有知识状态变更必须通过此服务完成。
API、Repository 和页面不得自行拼装状态变更。
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)


class KnowledgeLifecycleService:
    """知识生命周期服务 - 唯一状态变更入口。"""

    @staticmethod
    def create_draft(**kwargs) -> dict:
        """创建草稿。委托给 KnowledgeEntryRepository.create()。"""
        from app.repositories.knowledge_entry_repository import KnowledgeEntryRepository

        entry = KnowledgeEntryRepository.create(**kwargs)
        return _entry_result(entry, "创建成功")

    @staticmethod
    def update_draft(entry_id: int, updates: dict, updated_by: str = "") -> dict:
        """更新草稿。只有 draft 和 rejected 状态允许更新。"""
        from app.repositories.knowledge_entry_repository import KnowledgeEntryRepository

        entry = KnowledgeEntryRepository.get_by_id(entry_id)
        if not entry:
            return {"error": "知识不存在", "entry_id": entry_id}

        if entry.status not in ("draft", "rejected"):
            return {
                "error": f"当前状态 {entry.status} 不允许编辑，只有 draft/rejected 可以编辑",
                "entry_id": entry_id,
                "status": entry.status,
            }

        updated = KnowledgeEntryRepository.update(entry_id, updates, updated_by=updated_by)
        return _entry_result(updated, "更新成功")

    @staticmethod
    def submit_review(entry_id: int, user: str = "") -> dict:
        """提交审核: draft/rejected → pending_review。"""
        from app.repositories.knowledge_entry_repository import KnowledgeEntryRepository

        entry = KnowledgeEntryRepository.get_by_id(entry_id)
        if not entry:
            return {"error": "知识不存在", "entry_id": entry_id}

        if entry.status not in ("draft", "rejected"):
            return {
                "error": f"当前状态 {entry.status} 不允许提交审核",
                "entry_id": entry_id,
                "status": entry.status,
            }

        result = KnowledgeEntryRepository._submit_for_review(entry_id, user)
        if not result:
            return {"error": "提交审核失败", "entry_id": entry_id}
        return _entry_result(result, "已提交审核")

    @staticmethod
    def approve(entry_id: int, user: str = "") -> dict:
        """审核通过: pending_review → quality gate → published + index。

        与 publish 使用同一质量门槛。
        """
        from app.repositories.knowledge_entry_repository import KnowledgeEntryRepository
        from app.services.knowledge_quality_gate import validate_for_publish
        from app.services.knowledge_index_pipeline import KnowledgeIndexPipeline

        entry = KnowledgeEntryRepository.get_by_id(entry_id)
        if not entry:
            return {"error": "知识不存在", "entry_id": entry_id}

        if entry.status != "pending_review":
            return {
                "error": f"当前状态 {entry.status} 不是待审核",
                "entry_id": entry_id,
                "status": entry.status,
            }

        # 质量门槛检查
        quality = validate_for_publish(entry)
        if not quality["passed"]:
            return {
                "error": "质量检查未通过",
                "entry_id": entry_id,
                "status": entry.status,
                "blocking_issues": quality["blocking_issues"],
                "suggested_fixes": quality["suggested_fixes"],
                "quality_result": quality,
            }

        # 原子操作：版本快照 + 状态变更在同一事务中
        from app.db import SessionLocal
        from app.models.knowledge_base import KnowledgeEntry
        from app.repositories.knowledge_version_repository import KnowledgeVersionRepository
        db = SessionLocal()
        try:
            e = db.query(KnowledgeEntry).filter(KnowledgeEntry.id == entry_id).first()
            if not e:
                return {"error": "知识不存在", "entry_id": entry_id}

            old_status = e.status

            # 在同一事务中创建版本快照
            KnowledgeVersionRepository.create_version(
                entry_id, user, "审核通过时快照", db=db
            )

            e.status = "published"
            e.published_at = datetime.utcnow()
            e.version += 1
            e.reviewed_by = user
            e.updated_by = user
            e.updated_at = datetime.utcnow()
            db.commit()
            db.refresh(e)
        finally:
            db.close()

        # 通过 Pipeline 索引
        index_result = KnowledgeIndexPipeline.index_published_entry(entry_id)

        if index_result.get("index_status") == "failed":
            # 索引失败：补偿回滚到 pending_review
            logger.error(
                "Index failed after approve for entry %s, compensating: %s",
                entry_id, index_result.get("error"),
            )
            _compensate_rollback_to_pending(entry_id, user, index_result.get("error", ""))

            return {
                "error": "索引创建失败，已回滚到待审核状态",
                "entry_id": entry_id,
                "status": "pending_review",
                "index_error": index_result.get("error"),
                "compensated": True,
            }

        # Revision 替换语义：如果当前 entry 是 revision，归档原 published 条目
        parent_id = entry.parent_entry_id if entry else None
        parent_archive_error = None
        if parent_id:
            archive_result = _archive_parent_on_revision_publish(
                parent_id, entry_id, user
            )
            if archive_result.get("error"):
                parent_archive_error = archive_result["error"]
                logger.error(
                    "Revision publish succeeded but parent archive failed: %s",
                    archive_result["error"],
                )

        # 审计日志
        audit_detail = "审核通过并发布"
        if parent_archive_error:
            audit_detail += f"（原条目归档失败: {parent_archive_error}）"
        _add_audit(entry_id, "approve", old_status, "published", user, audit_detail)

        entry = KnowledgeEntryRepository.get_by_id(entry_id)
        result = _entry_result(entry, audit_detail)
        result["index_result"] = index_result
        result["quality_result"] = quality
        if parent_id:
            result["parent_archived"] = archive_result.get("parent_id")
        if parent_archive_error:
            result["error"] = "原条目归档失败"
            result["parent_archive_error"] = parent_archive_error
        return result

    @staticmethod
    def reject(entry_id: int, user: str = "", reason: str = "") -> dict:
        """审核驳回: pending_review → rejected。"""
        from app.repositories.knowledge_entry_repository import KnowledgeEntryRepository

        entry = KnowledgeEntryRepository.get_by_id(entry_id)
        if not entry:
            return {"error": "知识不存在", "entry_id": entry_id}

        if entry.status != "pending_review":
            return {
                "error": f"当前状态 {entry.status} 不是待审核",
                "entry_id": entry_id,
                "status": entry.status,
            }

        result = KnowledgeEntryRepository._review_reject(entry_id, user, reason)
        if not result:
            return {"error": "驳回失败", "entry_id": entry_id}
        return _entry_result(result, f"已驳回: {reason}")

    @staticmethod
    def publish(entry_id: int, user: str = "") -> dict:
        """发布知识。与 approve 使用同一质量门槛。

        只有 pending_review 状态可以直接发布。
        """
        from app.repositories.knowledge_entry_repository import KnowledgeEntryRepository

        entry = KnowledgeEntryRepository.get_by_id(entry_id)
        if not entry:
            return {"error": "知识不存在", "entry_id": entry_id}

        if entry.status != "pending_review":
            return {
                "error": f"当前状态 {entry.status} 不允许发布，必须先提交审核",
                "entry_id": entry_id,
                "status": entry.status,
            }

        # 发布与审核通过使用完全相同的质量门槛
        return KnowledgeLifecycleService.approve(entry_id, user)

    @staticmethod
    def _force_publish(entry_id: int, user: str = "") -> dict:
        """内部方法：跳过质量门槛直接发布，仅供向后兼容的旧调用方使用。

        新代码应使用 approve() / publish()，始终经过质量门槛。
        """
        from app.db import SessionLocal
        from app.models.knowledge_base import KnowledgeEntry
        from app.repositories.knowledge_entry_repository import KnowledgeEntryRepository
        from app.services.knowledge_index_pipeline import KnowledgeIndexPipeline
        from app.repositories.knowledge_version_repository import KnowledgeVersionRepository

        entry = KnowledgeEntryRepository.get_by_id(entry_id)
        if not entry:
            return {"error": "知识不存在", "entry_id": entry_id}

        if entry.status != "pending_review":
            return {
                "error": f"当前状态 {entry.status} 不是待审核",
                "entry_id": entry_id,
                "status": entry.status,
            }

        db = SessionLocal()
        try:
            e = db.query(KnowledgeEntry).filter(KnowledgeEntry.id == entry_id).first()
            if not e:
                return {"error": "知识不存在", "entry_id": entry_id}

            old_status = e.status

            KnowledgeVersionRepository.create_version(
                entry_id, user, "向后兼容强制发布快照", db=db
            )

            e.status = "published"
            e.published_at = datetime.utcnow()
            e.version += 1
            e.reviewed_by = user
            e.updated_by = user
            e.updated_at = datetime.utcnow()
            db.commit()
            db.refresh(e)
        finally:
            db.close()

        index_result = KnowledgeIndexPipeline.index_published_entry(entry_id)

        if index_result.get("index_status") == "failed":
            _compensate_rollback_to_pending(entry_id, user, index_result.get("error", ""))
            return {
                "error": "索引创建失败，已回滚到待审核状态",
                "entry_id": entry_id,
                "status": "pending_review",
                "index_error": index_result.get("error"),
                "compensated": True,
            }

        _add_audit(entry_id, "_force_publish", old_status, "published", user,
                    "向后兼容强制发布（跳过质量门槛）")

        entry = KnowledgeEntryRepository.get_by_id(entry_id)
        result = _entry_result(entry, "已发布（向后兼容模式）")
        result["index_result"] = index_result
        return result

    @staticmethod
    def create_revision(entry_id: int, user: str = "") -> dict:
        """创建修订版: published → 快照 + 新 entry 为 draft。

        旧 published 继续在线，新 draft 审核通过后再替换。
        """
        from app.repositories.knowledge_entry_repository import KnowledgeEntryRepository
        from app.repositories.knowledge_version_repository import KnowledgeVersionRepository

        entry = KnowledgeEntryRepository.get_by_id(entry_id)
        if not entry:
            return {"error": "知识不存在", "entry_id": entry_id}

        if entry.status != "published":
            return {
                "error": f"当前状态 {entry.status} 不允许创建修订，只有 published 可以",
                "entry_id": entry_id,
                "status": entry.status,
            }

        # 创建版本快照
        KnowledgeVersionRepository.create_version(entry_id, user, "创建修订版时快照")

        # 创建新 entry 作为 draft，关联原 entry
        new_entry = KnowledgeEntryRepository.create(
            source_type=entry.source_type,
            title=entry.title,
            content=entry.content,
            intent=entry.intent,
            sub_intent=entry.sub_intent,
            category=entry.category,
            category_l3=entry.category_l3,
            search_keywords=entry.search_keywords,
            product_scope=entry.get_product_scope(),
            sku_scope=entry.get_sku_scope(),
            platform_scope=entry.get_platform_scope(),
            risk_level=entry.risk_level,
            auto_reply_allowed=entry.auto_reply_allowed,
            human_review_required=entry.human_review_required,
            condition_text=entry.condition_text,
            forbidden_usage=entry.forbidden_usage,
            created_by=user,
        )
        # 建立 revision 关系
        from app.db import SessionLocal
        from app.models.knowledge_base import KnowledgeEntry as KEModel
        db = SessionLocal()
        try:
            ne = db.query(KEModel).filter(KEModel.id == new_entry.id).first()
            if ne:
                ne.parent_entry_id = entry_id
                db.commit()
                db.refresh(ne)
        finally:
            db.close()

        _add_audit(entry_id, "create_revision", "published", "published", user,
                    f"创建修订版 entry_id={new_entry.id}")

        result = _entry_result(new_entry, "修订版已创建为草稿")
        result["original_entry_id"] = entry_id
        result["revision_entry_id"] = new_entry.id
        return result

    @staticmethod
    def archive(entry_id: int, user: str = "") -> dict:
        """归档: any → archived + Pipeline.remove_entry()。"""
        from app.repositories.knowledge_entry_repository import KnowledgeEntryRepository
        from app.services.knowledge_index_pipeline import KnowledgeIndexPipeline

        entry = KnowledgeEntryRepository.get_by_id(entry_id)
        if not entry:
            return {"error": "知识不存在", "entry_id": entry_id}

        if entry.status == "archived":
            return _entry_result(entry, "已经是归档状态")

        old_status = entry.status

        # 先删除索引 chunks
        remove_result = KnowledgeIndexPipeline.remove_entry(entry_id)

        # 再修改状态
        result = KnowledgeEntryRepository._archive(entry_id, user)
        if not result:
            return {"error": "归档失败", "entry_id": entry_id}

        # 验证 chunks 已清理
        from app.models.knowledge_base import KnowledgeChunk
        db = _get_db()
        try:
            remaining = db.query(KnowledgeChunk).filter(
                KnowledgeChunk.entry_id == entry_id
            ).count()
        finally:
            db.close()

        _add_audit(entry_id, "archive", old_status, "archived", user,
                    f"归档并删除 {remove_result.get('chunks_deleted', 0)} 个 chunks")

        result_data = _entry_result(result, "归档成功")
        result_data["chunks_deleted"] = remove_result.get("chunks_deleted", 0)
        result_data["chunks_remaining"] = remaining
        return result_data

    @staticmethod
    def rollback_to_draft(entry_id: int, version: int, user: str = "") -> dict:
        """回滚到草稿: any → snapshot + 恢复版本内容为 draft，不索引。

        原线上 published 版本保留（如果有的话）。
        """
        from app.repositories.knowledge_entry_repository import KnowledgeEntryRepository
        from app.repositories.knowledge_version_repository import KnowledgeVersionRepository

        entry = KnowledgeEntryRepository.get_by_id(entry_id)
        if not entry:
            return {"error": "知识不存在", "entry_id": entry_id}

        v = KnowledgeVersionRepository.get_version(entry_id, version)
        if not v:
            return {"error": f"版本 {version} 不存在", "entry_id": entry_id}

        old_status = entry.status

        # 创建当前状态快照
        KnowledgeVersionRepository.create_version(entry_id, user, f"回滚前快照")

        # 恢复版本内容，但设为 draft
        import json
        snapshot = json.loads(v.content_snapshot)

        from app.db import SessionLocal
        from app.models.knowledge_base import KnowledgeEntry, KnowledgeChunk
        db = SessionLocal()
        try:
            e = db.query(KnowledgeEntry).filter(KnowledgeEntry.id == entry_id).first()
            if not e:
                return {"error": "知识不存在", "entry_id": entry_id}

            # 恢复字段
            e.title = snapshot.get("title", e.title)
            e.content = snapshot.get("content", e.content)
            e.intent = snapshot.get("intent", e.intent)
            e.sub_intent = snapshot.get("sub_intent", e.sub_intent)
            e.category = snapshot.get("category", e.category)
            e.risk_level = snapshot.get("risk_level", e.risk_level)
            e.auto_reply_allowed = snapshot.get("auto_reply_allowed", e.auto_reply_allowed)
            e.human_review_required = snapshot.get("human_review_required", e.human_review_required)
            e.condition_text = snapshot.get("condition_text", e.condition_text)
            e.forbidden_usage = snapshot.get("forbidden_usage", e.forbidden_usage)

            e.set_product_scope(snapshot.get("product_scope", []))
            e.set_sku_scope(snapshot.get("sku_scope", []))
            e.set_platform_scope(snapshot.get("platform_scope", []))

            # 设为 draft
            e.status = "draft"
            e.version += 1
            e.index_status = "pending"
            e.content_hash = ""
            e.updated_by = user
            e.updated_at = datetime.utcnow()

            # 删除该 entry 的所有 chunks（draft 不应有正式 chunks）
            db.query(KnowledgeChunk).filter(
                KnowledgeChunk.entry_id == entry_id
            ).delete()

            db.commit()
            db.refresh(e)
        finally:
            db.close()

        _add_audit(entry_id, "rollback", old_status, "draft", user,
                    f"回滚到版本 {version}，状态设为 draft")

        entry = KnowledgeEntryRepository.get_by_id(entry_id)
        result = _entry_result(entry, f"已回滚到版本 {version}，状态为 draft")
        result["rolled_back_from_version"] = version
        return result


def _get_db():
    from app.db import SessionLocal
    return SessionLocal()


def _entry_result(entry, message: str) -> dict:
    if not entry:
        return {"error": "知识不存在"}
    return {
        "id": entry.id,
        "status": entry.status,
        "index_status": getattr(entry, "index_status", "unknown"),
        "message": message,
    }


def _add_audit(entry_id, action, old_status, new_status, performed_by, details):
    from app.models.knowledge_base import KnowledgeAuditLog
    db = _get_db()
    try:
        log = KnowledgeAuditLog(
            entry_id=entry_id,
            action=action,
            old_status=old_status,
            new_status=new_status,
            performed_by=performed_by,
            details=details,
        )
        db.add(log)
        db.commit()
    finally:
        db.close()


def _archive_parent_on_revision_publish(parent_id: int, revision_id: int, user: str = "") -> dict:
    """Revision 发布成功时，归档原 published 条目。

    1. 删除原 entry 的所有 chunks
    2. 将原 entry 状态设为 archived
    3. 记录审计日志
    """
    from app.models.knowledge_base import KnowledgeEntry, KnowledgeChunk, KnowledgeAuditLog
    from app.services.knowledge_index_pipeline import KnowledgeIndexPipeline

    # 先删除索引 chunks
    remove_result = KnowledgeIndexPipeline.remove_entry(parent_id)

    db = _get_db()
    try:
        parent = db.query(KnowledgeEntry).filter(KnowledgeEntry.id == parent_id).first()
        if not parent:
            return {"error": "原条目不存在", "parent_id": parent_id}

        old_status = parent.status
        parent.status = "archived"
        parent.index_status = "removed"
        parent.content_hash = ""
        parent.updated_by = user
        parent.updated_at = datetime.utcnow()
        db.commit()
        db.refresh(parent)

        # 审计日志
        audit = KnowledgeAuditLog(
            entry_id=parent_id,
            action="archive_by_revision",
            old_status=old_status,
            new_status="archived",
            performed_by=user,
            details=f"revision {revision_id} 发布成功，原条目归档",
        )
        db.add(audit)
        db.commit()

        return {
            "parent_id": parent_id,
            "old_status": old_status,
            "chunks_deleted": remove_result.get("chunks_deleted", 0),
        }
    finally:
        db.close()


def _compensate_rollback_to_pending(entry_id, user, reason):
    """索引失败时的补偿回滚：恢复到 pending_review。"""
    from app.models.knowledge_base import KnowledgeEntry, KnowledgeChunk
    db = _get_db()
    try:
        e = db.query(KnowledgeEntry).filter(KnowledgeEntry.id == entry_id).first()
        if e:
            e.status = "pending_review"
            e.index_status = "failed"
            e.published_at = None
            # 删除失败时创建的部分 chunks
            db.query(KnowledgeChunk).filter(
                KnowledgeChunk.entry_id == entry_id
            ).delete()
            db.commit()

        _add_audit(entry_id, "compensate_rollback", "published", "pending_review",
                    user or "system", f"索引失败补偿回滚: {reason}")
    finally:
        db.close()
