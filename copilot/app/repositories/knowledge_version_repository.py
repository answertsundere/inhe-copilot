"""
知识版本仓库
"""

import json
from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session

from app.models.knowledge_base import KnowledgeVersion, KnowledgeEntry, KnowledgeAuditLog


def _get_db():
    from app.db import SessionLocal
    return SessionLocal()


class KnowledgeVersionRepository:
    """知识版本仓库"""

    @staticmethod
    def create_version(
        entry_id: int,
        changed_by: str = "",
        change_reason: str = "",
        db=None,
    ) -> Optional[KnowledgeVersion]:
        own_session = db is None
        if own_session:
            db = _get_db()
        try:
            entry = db.query(KnowledgeEntry).filter(KnowledgeEntry.id == entry_id).first()
            if not entry:
                return None

            snapshot = entry.to_dict(include_content=True)
            snapshot["version"] = entry.version
            snapshot["snapshotted_at"] = datetime.utcnow().isoformat()

            version = KnowledgeVersion(
                entry_id=entry_id,
                version=entry.version,
                content_snapshot=json.dumps(snapshot, ensure_ascii=False, default=str),
                changed_by=changed_by,
                change_reason=change_reason,
            )
            db.add(version)
            if own_session:
                db.commit()
                db.refresh(version)
            return version
        finally:
            if own_session:
                db.close()

    @staticmethod
    def get_versions(entry_id: int):
        db = _get_db()
        try:
            return (
                db.query(KnowledgeVersion)
                .filter(KnowledgeVersion.entry_id == entry_id)
                .order_by(KnowledgeVersion.version.desc())
                .all()
            )
        finally:
            db.close()

    @staticmethod
    def get_version(entry_id: int, version: int) -> Optional[KnowledgeVersion]:
        db = _get_db()
        try:
            return (
                db.query(KnowledgeVersion)
                .filter(
                    KnowledgeVersion.entry_id == entry_id,
                    KnowledgeVersion.version == version,
                )
                .first()
            )
        finally:
            db.close()

    @staticmethod
    def _rollback(entry_id: int, version: int, user: str = "") -> Optional[KnowledgeEntry]:
        """内部回滚方法。所有回滚操作应通过 KnowledgeLifecycleService.rollback_to_draft() 进行。"""
        db = _get_db()
        try:
            entry = db.query(KnowledgeEntry).filter(KnowledgeEntry.id == entry_id).first()
            if not entry:
                return None

            v = KnowledgeVersionRepository.get_version(entry_id, version)
            if not v:
                raise ValueError(f"版本 {version} 不存在")

            snapshot = json.loads(v.content_snapshot)

            # 恢复字段
            entry.title = snapshot.get("title", entry.title)
            entry.content = snapshot.get("content", entry.content)
            entry.intent = snapshot.get("intent", entry.intent)
            entry.sub_intent = snapshot.get("sub_intent", entry.sub_intent)
            entry.category = snapshot.get("category", entry.category)
            entry.risk_level = snapshot.get("risk_level", entry.risk_level)
            entry.auto_reply_allowed = snapshot.get("auto_reply_allowed", entry.auto_reply_allowed)
            entry.human_review_required = snapshot.get("human_review_required", entry.human_review_required)
            entry.condition_text = snapshot.get("condition_text", entry.condition_text)
            entry.forbidden_usage = snapshot.get("forbidden_usage", entry.forbidden_usage)

            entry.set_product_scope(snapshot.get("product_scope", []))
            entry.set_sku_scope(snapshot.get("sku_scope", []))
            entry.set_platform_scope(snapshot.get("platform_scope", []))

            old_status = entry.status
            entry.status = "draft"
            entry.version += 1
            entry.updated_by = user
            entry.updated_at = datetime.utcnow()

            # 删除该 entry 的所有 chunks（draft 不应有正式 chunks）
            from app.models.knowledge_base import KnowledgeChunk
            db.query(KnowledgeChunk).filter(
                KnowledgeChunk.entry_id == entry_id
            ).delete()

            db.commit()
            db.refresh(entry)

            # 记录审计日志
            audit = KnowledgeAuditLog(
                entry_id=entry_id,
                action="rollback",
                old_status=old_status,
                new_status="draft",
                performed_by=user,
                details=f"回滚到版本 {version}",
            )
            db.add(audit)
            db.commit()

            # 生成新版本记录
            KnowledgeVersionRepository.create_version(entry_id, user, f"回滚到版本 {version}")

            # 注意：不创建正式 chunks，draft 不进入正式索引
            # 索引由 KnowledgeLifecycleService 通过 KnowledgeIndexPipeline 处理

            return entry
        finally:
            db.close()
