"""
知识条目仓库 - SQLAlchemy 实现
"""

import hashlib
import json
from datetime import datetime
from typing import Optional

from sqlalchemy import or_, func
from sqlalchemy.orm import Session

from app.models.knowledge_base import KnowledgeEntry, KnowledgeAuditLog


# 高风险 source_type
HIGH_RISK_SOURCE_TYPES = {"high_risk_sop", "forbidden_rules"}

def _get_db():
    from app.db import SessionLocal
    return SessionLocal()


def _compute_content_hash(title: str, content: str) -> str:
    text = f"{title.strip()}|{content.strip()}"
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:32]


class KnowledgeEntryRepository:
    """知识条目仓库"""

    @staticmethod
    def create(
        source_type: str,
        title: str,
        content: str,
        intent: str = "general",
        sub_intent: str = "",
        category: str = "",
        category_l3: str = "",
        search_keywords: str = "",
        scene_tag: str = "",
        product_line: str = "",
        product_scope: list = None,
        sku_scope: list = None,
        platform_scope: list = None,
        risk_level: str = "low",
        auto_reply_allowed: bool = True,
        human_review_required: bool = False,
        condition_text: str = "",
        forbidden_usage: str = "",
        created_by: str = "",
        source_sheet: str = "",
        row_number: int = 0,
        import_batch_id: str = "",
    ) -> KnowledgeEntry:
        db = _get_db()
        try:
            # 高风险强制设置
            if source_type in HIGH_RISK_SOURCE_TYPES or risk_level in ("high", "critical"):
                auto_reply_allowed = False
                human_review_required = True
                if risk_level not in ("high", "critical"):
                    risk_level = "high"

            entry = KnowledgeEntry(
                source_type=source_type,
                title=title.strip(),
                content=content.strip(),
                intent=intent,
                sub_intent=sub_intent,
                category=category,
                category_l3=category_l3,
                search_keywords=search_keywords,
                scene_tag=scene_tag,
                product_line=product_line,
                risk_level=risk_level,
                auto_reply_allowed=auto_reply_allowed,
                human_review_required=human_review_required,
                condition_text=condition_text,
                forbidden_usage=forbidden_usage,
                status="draft",
                version=1,
                created_by=created_by,
                updated_by=created_by,
                source_sheet=source_sheet,
                row_number=row_number,
                import_batch_id=import_batch_id,
                content_hash=_compute_content_hash(title, content),
            )
            entry.set_product_scope(product_scope or [])
            entry.set_sku_scope(sku_scope or [])
            entry.set_platform_scope(platform_scope or [])

            db.add(entry)
            db.commit()
            db.refresh(entry)

            # 审计日志
            _add_audit_log(db, entry.id, "create", "", "draft", created_by, "新建知识条目")
            return entry
        finally:
            db.close()

    @staticmethod
    def get_by_id(entry_id: int) -> Optional[KnowledgeEntry]:
        db = _get_db()
        try:
            return db.query(KnowledgeEntry).filter(KnowledgeEntry.id == entry_id).first()
        finally:
            db.close()

    @staticmethod
    def update(
        entry_id: int,
        updates: dict,
        updated_by: str = "",
    ) -> Optional[KnowledgeEntry]:
        db = _get_db()
        try:
            entry = db.query(KnowledgeEntry).filter(KnowledgeEntry.id == entry_id).first()
            if not entry:
                return None

            # 已发布的不允许直接修改，必须先归档或回滚
            if entry.status == "published" and updates.get("_force") is not True:
                raise ValueError("已发布知识不允许直接修改，请先归档")

            allowed_fields = {
                "title", "content", "intent", "sub_intent", "category",
                "category_l3", "search_keywords", "scene_tag", "product_line",
                "risk_level", "auto_reply_allowed", "human_review_required",
                "condition_text", "forbidden_usage",
            }
            for k, v in updates.items():
                if k.startswith("_"):
                    continue
                if k in allowed_fields:
                    setattr(entry, k, v)
                elif k == "product_scope":
                    entry.set_product_scope(v)
                elif k == "sku_scope":
                    entry.set_sku_scope(v)
                elif k == "platform_scope":
                    entry.set_platform_scope(v)

            # 重新计算 content_hash
            if "title" in updates or "content" in updates:
                entry.content_hash = _compute_content_hash(entry.title, entry.content)

            entry.updated_by = updated_by or entry.updated_by
            entry.updated_at = datetime.utcnow()

            # 高风险强制设置
            if entry.source_type in HIGH_RISK_SOURCE_TYPES or entry.risk_level in ("high", "critical"):
                entry.auto_reply_allowed = False
                entry.human_review_required = True

            db.commit()
            db.refresh(entry)

            _add_audit_log(db, entry.id, "update", entry.status, entry.status, updated_by, json.dumps(updates, ensure_ascii=False, default=str)[:500])
            return entry
        finally:
            db.close()

    @staticmethod
    def list_entries(
        source_type: str = "",
        intent: str = "",
        status: str = "",
        risk_level: str = "",
        search_query: str = "",
        limit: int = 50,
        offset: int = 0,
        # 扩展筛选参数
        fact_type: str = "",
        product_id: str = "",
        sku_id: str = "",
        business_key: str = "",
        batch_id: str = "",
        index_status: str = "",
        human_review_required: str = "",
        auto_reply_allowed: str = "",
        sort_by: str = "updated_at",
        sort_order: str = "desc",
    ) -> tuple:
        db = _get_db()
        try:
            q = db.query(KnowledgeEntry)
            if source_type:
                q = q.filter(KnowledgeEntry.source_type == source_type)
            if intent:
                q = q.filter(KnowledgeEntry.intent == intent)
            if status:
                q = q.filter(KnowledgeEntry.status == status)
            if risk_level:
                q = q.filter(KnowledgeEntry.risk_level == risk_level)
            if fact_type:
                q = q.filter(KnowledgeEntry.fact_type == fact_type)
            if product_id:
                q = q.filter(KnowledgeEntry.product_id == product_id)
            if sku_id:
                q = q.filter(KnowledgeEntry.sku_id == sku_id)
            if business_key:
                q = q.filter(KnowledgeEntry.business_key == business_key)
            if batch_id:
                q = q.filter(KnowledgeEntry.import_batch_id == batch_id)
            if index_status:
                q = q.filter(KnowledgeEntry.index_status == index_status)
            if human_review_required != "":
                q = q.filter(KnowledgeEntry.human_review_required == (human_review_required.lower() in ("true", "1")))
            if auto_reply_allowed != "":
                q = q.filter(KnowledgeEntry.auto_reply_allowed == (auto_reply_allowed.lower() in ("true", "1")))
            if search_query:
                like = f"%{search_query}%"
                q = q.filter(
                    or_(
                        KnowledgeEntry.title.ilike(like),
                        KnowledgeEntry.content.ilike(like),
                    )
                )
            # 排序白名单
            _SORT_WHITELIST = {
                "id": KnowledgeEntry.id,
                "updated_at": KnowledgeEntry.updated_at,
                "created_at": KnowledgeEntry.created_at,
                "title": KnowledgeEntry.title,
                "status": KnowledgeEntry.status,
                "risk_level": KnowledgeEntry.risk_level,
                "source_confidence": KnowledgeEntry.source_confidence,
            }
            sort_col = _SORT_WHITELIST.get(sort_by, KnowledgeEntry.updated_at)
            if sort_order.lower() == "asc":
                q = q.order_by(sort_col.asc())
            else:
                q = q.order_by(sort_col.desc())

            total = q.count()
            items = q.offset(offset).limit(limit).all()
            return items, total
        finally:
            db.close()

    @staticmethod
    def _submit_for_review(entry_id: int, user: str = "") -> Optional[KnowledgeEntry]:
        db = _get_db()
        try:
            entry = db.query(KnowledgeEntry).filter(KnowledgeEntry.id == entry_id).first()
            if not entry:
                return None
            if entry.status not in ("draft", "rejected"):
                raise ValueError(f"当前状态 {entry.status} 不允许提交审核")

            old_status = entry.status
            entry.status = "pending_review"
            entry.updated_by = user
            entry.updated_at = datetime.utcnow()
            db.commit()
            db.refresh(entry)

            _add_audit_log(db, entry.id, "submit_review", old_status, "pending_review", user, "提交审核")
            return entry
        finally:
            db.close()

    @staticmethod
    def _review_approve(entry_id: int, user: str = "") -> Optional[KnowledgeEntry]:
        """审核通过：设置状态为 published，不创建 chunks。

        索引由 KnowledgeLifecycleService.approve() 通过 KnowledgeIndexPipeline 处理。
        """
        db = _get_db()
        try:
            entry = db.query(KnowledgeEntry).filter(KnowledgeEntry.id == entry_id).first()
            if not entry:
                return None
            if entry.status != "pending_review":
                raise ValueError(f"当前状态 {entry.status} 不是待审核")

            old_status = entry.status

            # 先创建版本快照（publish 前的状态）
            from app.repositories.knowledge_version_repository import KnowledgeVersionRepository
            KnowledgeVersionRepository.create_version(entry_id, user, "审核通过时快照")

            entry.status = "published"
            entry.published_at = datetime.utcnow()
            entry.version += 1
            entry.reviewed_by = user
            entry.updated_by = user
            entry.updated_at = datetime.utcnow()
            db.commit()
            db.refresh(entry)

            _add_audit_log(db, entry.id, "review", old_status, "published", user, "审核通过")
            return entry
        finally:
            db.close()

    @staticmethod
    def _review_reject(entry_id: int, user: str = "", reason: str = "") -> Optional[KnowledgeEntry]:
        db = _get_db()
        try:
            entry = db.query(KnowledgeEntry).filter(KnowledgeEntry.id == entry_id).first()
            if not entry:
                return None
            if entry.status != "pending_review":
                raise ValueError(f"当前状态 {entry.status} 不是待审核")

            old_status = entry.status
            entry.status = "rejected"
            entry.reviewed_by = user
            entry.updated_by = user
            entry.updated_at = datetime.utcnow()
            db.commit()
            db.refresh(entry)

            _add_audit_log(db, entry.id, "review", old_status, "rejected", user, f"审核驳回: {reason}")
            return entry
        finally:
            db.close()

    @staticmethod
    def _publish(entry_id: int, user: str = "") -> Optional[KnowledgeEntry]:
        """设置 published 状态，不创建 chunks。

        索引由 KnowledgeLifecycleService 通过 KnowledgeIndexPipeline 处理。
        """
        db = _get_db()
        try:
            entry = db.query(KnowledgeEntry).filter(KnowledgeEntry.id == entry_id).first()
            if not entry:
                return None
            if entry.status != "pending_review":
                raise ValueError(f"当前状态 {entry.status} 不允许发布")

            # 高风险必须 supervisor 审核
            if entry.source_type in HIGH_RISK_SOURCE_TYPES or entry.risk_level in ("high", "critical"):
                if not user or user == entry.created_by:
                    raise ValueError("高风险知识必须由 supervisor 审核后才能发布")

            old_status = entry.status
            entry.status = "published"
            entry.published_at = datetime.utcnow()
            entry.version += 1
            entry.updated_by = user
            entry.updated_at = datetime.utcnow()
            db.commit()
            db.refresh(entry)

            _add_audit_log(db, entry.id, "publish", old_status, "published", user, "发布知识")
            return entry
        finally:
            db.close()

    @staticmethod
    def _archive(entry_id: int, user: str = "") -> Optional[KnowledgeEntry]:
        db = _get_db()
        try:
            entry = db.query(KnowledgeEntry).filter(KnowledgeEntry.id == entry_id).first()
            if not entry:
                return None
            if entry.status == "archived":
                return entry

            old_status = entry.status
            entry.status = "archived"
            entry.updated_by = user
            entry.updated_at = datetime.utcnow()
            db.commit()
            db.refresh(entry)

            _add_audit_log(db, entry.id, "archive", old_status, "archived", user, "归档知识")
            return entry
        finally:
            db.close()

    @staticmethod
    def check_duplicate(title: str, source_type: str, content: str) -> Optional[KnowledgeEntry]:
        db = _get_db()
        try:
            h = _compute_content_hash(title, content)
            return (
                db.query(KnowledgeEntry)
                .filter(KnowledgeEntry.content_hash == h)
                .first()
            )
        finally:
            db.close()

    @staticmethod
    def get_stats(entry_id: int) -> dict:
        db = _get_db()
        try:
            from app.models.knowledge_base import KnowledgeFeedback
            total_feedback = (
                db.query(func.count(KnowledgeFeedback.id))
                .filter(KnowledgeFeedback.entry_id == entry_id)
                .scalar()
            )
            accepted = (
                db.query(func.count(KnowledgeFeedback.id))
                .filter(KnowledgeFeedback.entry_id == entry_id, KnowledgeFeedback.csr_accepted == True)
                .scalar()
            )
            return {
                "entry_id": entry_id,
                "total_feedback": total_feedback or 0,
                "accepted_count": accepted or 0,
                "acceptance_rate": round(accepted / total_feedback, 2) if total_feedback else 0.0,
            }
        finally:
            db.close()


def _add_audit_log(db, entry_id, action, old_status, new_status, performed_by, details):
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
