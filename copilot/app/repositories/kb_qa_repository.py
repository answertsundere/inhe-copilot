"""
问答知识库仓库 - CRUD / 列表过滤 / 变体管理 / 状态流转 / 内容哈希 / 变更日志 / 高风险审核
"""

import hashlib
import json
from datetime import datetime
from typing import Optional

from sqlalchemy import or_, func

from app.db import SessionLocal
from app.models.kb_tables import KBQA, KBQuestionVariant, KBReviewTask, KBChangeLog


def _compute_content_hash(question: str, answer: str) -> str:
    """计算问答内容哈希"""
    text = f"{question.strip()}|{answer.strip()}"
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:32]


def _needs_review(old: KBQA, updates: dict) -> bool:
    """判断 QA 更新是否需要自动创建审核任务"""
    # risk_level 变更
    if "risk_level" in updates and updates["risk_level"] != old.risk_level:
        return True
    # answer 变更且 risk_level 为 medium/high/critical
    if "answer" in updates and updates["answer"] != old.answer:
        if old.risk_level in ("medium", "high", "critical"):
            return True
    # auto_reply 从 False 变为 True
    if "auto_reply" in updates and updates["auto_reply"] is True and old.auto_reply is False:
        return True
    # human_review 从 True 变为 False
    if "human_review" in updates and updates["human_review"] is False and old.human_review is True:
        return True
    return False


class KBQARepository:
    """问答知识库仓库"""

    # ─── 创建 ───

    @staticmethod
    def create(**kwargs) -> KBQA:
        db = SessionLocal()
        try:
            qa = KBQA(**kwargs)
            # 计算 content_hash
            qa.content_hash = _compute_content_hash(qa.question, qa.answer)
            db.add(qa)
            db.commit()
            db.refresh(qa)

            _log_change(
                db, target_type="kb_qa", target_id=qa.id,
                target_title=qa.question, action="create",
                after_status=qa.status, performed_by=qa.created_by,
                snapshot=qa.to_dict(include_variants=True),
                reason="新建问答知识",
            )
            return qa
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    # ─── 查询单条 ───

    @staticmethod
    def get_by_id(qa_id: int) -> Optional[KBQA]:
        db = SessionLocal()
        try:
            return db.query(KBQA).filter(KBQA.id == qa_id).first()
        finally:
            db.close()

    @staticmethod
    def get_by_hash(content_hash: str) -> Optional[KBQA]:
        db = SessionLocal()
        try:
            return db.query(KBQA).filter(KBQA.content_hash == content_hash).first()
        finally:
            db.close()

    # ─── 更新 ───

    @staticmethod
    def update(qa_id: int, updates: dict, updated_by: str = "") -> Optional[KBQA]:
        db = SessionLocal()
        try:
            qa = db.query(KBQA).filter(KBQA.id == qa_id).first()
            if not qa:
                return None

            before_snapshot = qa.to_dict(include_variants=True)

            allowed_fields = {
                "question", "answer", "intent", "sub_intent",
                "category_l1", "category_l2", "category_l3",
                "product_id", "risk_level", "auto_reply", "human_review",
                "source_type", "import_batch_id",
            }
            json_setters = {
                "sku_codes": "set_sku_codes",
                "keywords": "set_keywords",
            }

            changed = []
            for k, v in updates.items():
                if k.startswith("_"):
                    continue
                if k in json_setters:
                    getattr(qa, json_setters[k])(v)
                    changed.append(k)
                elif k in allowed_fields:
                    setattr(qa, k, v)
                    changed.append(k)

            # 重算 content_hash
            if "question" in updates or "answer" in updates:
                qa.content_hash = _compute_content_hash(qa.question, qa.answer)

            qa.updated_by = updated_by or qa.updated_by
            qa.updated_at = datetime.utcnow()
            db.commit()
            db.refresh(qa)

            # 判断是否需要自动创建审核任务
            if _needs_review(qa, updates):
                _auto_create_review_task(
                    db, qa=qa, before_snapshot=before_snapshot,
                    changed_fields=changed, requested_by=updated_by,
                )

            _log_change(
                db, target_type="kb_qa", target_id=qa.id,
                target_title=qa.question, action="update",
                before_status=qa.status, after_status=qa.status,
                performed_by=updated_by, changed_fields=changed,
                snapshot=qa.to_dict(include_variants=True),
                reason="更新问答知识",
            )
            return qa
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    # ─── 列表 ───

    @staticmethod
    def list_entries(
        intent: str = "",
        risk_level: str = "",
        status: str = "",
        product_id: int = None,
        source_type: str = "",
        search: str = "",
        auto_reply: bool = None,
        human_review: bool = None,
        limit: int = 20,
        offset: int = 0,
    ) -> tuple:
        db = SessionLocal()
        try:
            q = db.query(KBQA)
            if intent:
                q = q.filter(KBQA.intent == intent)
            if risk_level:
                q = q.filter(KBQA.risk_level == risk_level)
            if status:
                q = q.filter(KBQA.status == status)
            if product_id is not None:
                q = q.filter(KBQA.product_id == product_id)
            if source_type:
                q = q.filter(KBQA.source_type == source_type)
            if auto_reply is not None:
                q = q.filter(KBQA.auto_reply == auto_reply)
            if human_review is not None:
                q = q.filter(KBQA.human_review == human_review)
            if search:
                like = f"%{search}%"
                q = q.filter(
                    or_(
                        KBQA.question.ilike(like),
                        KBQA.answer.ilike(like),
                    )
                )
            total = q.count()
            items = (
                q.order_by(KBQA.updated_at.desc())
                .offset(offset)
                .limit(limit)
                .all()
            )
            return items, total
        finally:
            db.close()

    # ─── 变体管理 ───

    @staticmethod
    def add_variant(qa_id: int, variant_text: str, source: str = "manual", created_by: str = "") -> KBQuestionVariant:
        db = SessionLocal()
        try:
            variant = KBQuestionVariant(
                qa_id=qa_id,
                variant_text=variant_text.strip(),
                source=source,
                created_by=created_by,
            )
            db.add(variant)
            db.commit()
            db.refresh(variant)
            return variant
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    @staticmethod
    def remove_variant(variant_id: int) -> bool:
        db = SessionLocal()
        try:
            variant = db.query(KBQuestionVariant).filter(KBQuestionVariant.id == variant_id).first()
            if not variant:
                return False
            db.delete(variant)
            db.commit()
            return True
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    @staticmethod
    def list_variants(qa_id: int) -> list:
        db = SessionLocal()
        try:
            return (
                db.query(KBQuestionVariant)
                .filter(KBQuestionVariant.qa_id == qa_id)
                .order_by(KBQuestionVariant.created_at.desc())
                .all()
            )
        finally:
            db.close()

    # ─── 状态流转 ───

    @staticmethod
    def submit_for_review(qa_id: int, user: str = "") -> Optional[KBQA]:
        db = SessionLocal()
        try:
            qa = db.query(KBQA).filter(KBQA.id == qa_id).first()
            if not qa:
                return None
            if qa.status not in ("draft", "rejected"):
                raise ValueError(f"当前状态 {qa.status} 不允许提交审核")

            old_status = qa.status
            qa.status = "pending_review"
            qa.updated_by = user
            qa.updated_at = datetime.utcnow()
            db.commit()
            db.refresh(qa)

            _log_change(
                db, target_type="kb_qa", target_id=qa.id,
                target_title=qa.question, action="submit_review",
                before_status=old_status, after_status="pending_review",
                performed_by=user, reason="问答提交审核",
            )
            return qa
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    @staticmethod
    def approve(qa_id: int, user: str = "") -> Optional[KBQA]:
        db = SessionLocal()
        try:
            qa = db.query(KBQA).filter(KBQA.id == qa_id).first()
            if not qa:
                return None
            if qa.status != "pending_review":
                raise ValueError(f"当前状态 {qa.status} 不允许审核通过")

            old_status = qa.status
            qa.status = "published"
            qa.published_at = datetime.utcnow()
            qa.reviewed_by = user
            qa.version += 1
            qa.updated_by = user
            qa.updated_at = datetime.utcnow()
            db.commit()
            db.refresh(qa)

            _log_change(
                db, target_type="kb_qa", target_id=qa.id,
                target_title=qa.question, action="approve",
                before_status=old_status, after_status="published",
                performed_by=user, reason="问答审核通过并发布",
            )
            return qa
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    @staticmethod
    def reject(qa_id: int, user: str = "", reason: str = "") -> Optional[KBQA]:
        db = SessionLocal()
        try:
            qa = db.query(KBQA).filter(KBQA.id == qa_id).first()
            if not qa:
                return None
            if qa.status != "pending_review":
                raise ValueError(f"当前状态 {qa.status} 不允许驳回")

            old_status = qa.status
            qa.status = "rejected"
            qa.reviewed_by = user
            qa.updated_by = user
            qa.updated_at = datetime.utcnow()
            db.commit()
            db.refresh(qa)

            _log_change(
                db, target_type="kb_qa", target_id=qa.id,
                target_title=qa.question, action="reject",
                before_status=old_status, after_status="rejected",
                performed_by=user, reason=f"问答审核驳回: {reason}",
            )
            return qa
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    @staticmethod
    def archive(qa_id: int, user: str = "") -> Optional[KBQA]:
        db = SessionLocal()
        try:
            qa = db.query(KBQA).filter(KBQA.id == qa_id).first()
            if not qa:
                return None
            if qa.status == "archived":
                return qa

            old_status = qa.status
            qa.status = "archived"
            qa.updated_by = user
            qa.updated_at = datetime.utcnow()
            db.commit()
            db.refresh(qa)

            _log_change(
                db, target_type="kb_qa", target_id=qa.id,
                target_title=qa.question, action="archive",
                before_status=old_status, after_status="archived",
                performed_by=user, reason="问答归档",
            )
            return qa
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()


# ─── 内部辅助函数 ───

def _auto_create_review_task(db, qa: KBQA, before_snapshot: dict, changed_fields: list, requested_by: str = ""):
    """高风险变更自动创建审核任务"""
    after_snapshot = qa.to_dict(include_variants=True)
    priority = "high" if qa.risk_level in ("high", "critical") else "normal"

    summary_parts = []
    if "risk_level" in changed_fields:
        summary_parts.append(f"风险等级变更为 {qa.risk_level}")
    if "answer" in changed_fields:
        summary_parts.append("回答内容变更")
    if "auto_reply" in changed_fields:
        summary_parts.append("自动回复设置变更")
    if "human_review" in changed_fields:
        summary_parts.append("人工审核设置变更")

    task = KBReviewTask(
        target_type="kb_qa",
        target_id=qa.id,
        change_type="update",
        change_summary="; ".join(summary_parts),
        priority=priority,
        risk_level=qa.risk_level,
        requested_by=requested_by or "",
    )
    task.set_before_snapshot(before_snapshot)
    task.set_after_snapshot(after_snapshot)
    task.set_changed_fields(changed_fields)
    db.add(task)
    db.commit()


def _log_change(
    db,
    target_type: str,
    target_id: int,
    target_title: str,
    action: str,
    performed_by: str,
    reason: str = "",
    before_status: str = "",
    after_status: str = "",
    changed_fields: list = None,
    snapshot: dict = None,
):
    """在当前 session 中写入 KBChangeLog"""
    entry = KBChangeLog(
        target_type=target_type,
        target_id=target_id,
        target_title=target_title,
        action=action,
        before_status=before_status,
        after_status=after_status,
        performed_by=performed_by or "",
        change_reason=reason,
    )
    if snapshot:
        entry.set_snapshot(snapshot)
    if changed_fields:
        entry.set_changed_fields(changed_fields)
    db.add(entry)
    db.commit()
