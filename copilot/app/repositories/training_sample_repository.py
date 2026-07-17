"""
客服训练样本仓库 - 创建 / 列表过滤 / 详情 / 更新 / 附件
"""

from datetime import datetime
from typing import Optional

from sqlalchemy import func
from sqlalchemy.orm import joinedload

from app.db import SessionLocal
from app.models.kb_tables import KBTrainingSample, KBTrainingSampleAttachment


class TrainingSampleRepository:
    """客服训练样本仓库"""

    VALID_REVIEW_STATUSES = {"待处理", "已确认", "已入库", "已上线"}
    VALID_AUTO_REPLY_TYPES = {"可自动", "需人工确认", "禁止自动"}
    VALID_RISK_LEVELS = {"低", "中", "高"}

    # ─── 创建样本 ───

    @staticmethod
    def create(**kwargs) -> KBTrainingSample:
        db = SessionLocal()
        try:
            sample = KBTrainingSample(**kwargs)
            db.add(sample)
            db.commit()
            db.refresh(sample)
            return (
                db.query(KBTrainingSample)
                .options(joinedload(KBTrainingSample.attachments))
                .filter(KBTrainingSample.id == sample.id)
                .first()
            )
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    # ─── 查询单条 ───

    @staticmethod
    def get_by_id(sample_id: int) -> Optional[KBTrainingSample]:
        db = SessionLocal()
        try:
            return (
                db.query(KBTrainingSample)
                .options(joinedload(KBTrainingSample.attachments))
                .filter(KBTrainingSample.id == sample_id)
                .first()
            )
        finally:
            db.close()

    # ─── 列表 ───

    @staticmethod
    def list_items(
        review_status: str = "",
        question_type: str = "",
        difficulty_reason: str = "",
        risk_level: str = "",
        keyword: str = "",
        created_by: str = "",
        limit: int = 20,
        offset: int = 0,
    ) -> tuple:
        db = SessionLocal()
        try:
            q = db.query(KBTrainingSample)
            if review_status:
                q = q.filter(KBTrainingSample.review_status == review_status)
            if question_type:
                q = q.filter(KBTrainingSample.question_type == question_type)
            if difficulty_reason:
                q = q.filter(KBTrainingSample.difficulty_reason == difficulty_reason)
            if risk_level:
                q = q.filter(KBTrainingSample.risk_level == risk_level)
            if created_by:
                q = q.filter(KBTrainingSample.created_by == created_by)
            if keyword:
                like = f"%{keyword}%"
                q = q.filter(
                    (KBTrainingSample.customer_quote.ilike(like))
                    | (KBTrainingSample.full_context.ilike(like))
                    | (KBTrainingSample.csr_actual_reply.ilike(like))
                    | (KBTrainingSample.correct_answer.ilike(like))
                    | (KBTrainingSample.product_title.ilike(like))
                    | (KBTrainingSample.sku.ilike(like))
                    | (KBTrainingSample.order_no.ilike(like))
                    | (KBTrainingSample.notes.ilike(like))
                )
            total = q.count()
            items = (
                q.order_by(KBTrainingSample.created_at.desc())
                .offset(offset)
                .limit(limit)
                .all()
            )
            return items, total
        finally:
            db.close()

    # ─── 更新 ───

    @staticmethod
    def update(sample_id: int, **kwargs) -> Optional[KBTrainingSample]:
        db = SessionLocal()
        try:
            sample = (
                db.query(KBTrainingSample)
                .filter(KBTrainingSample.id == sample_id)
                .first()
            )
            if not sample:
                return None

            allowed = {
                "collected_at",
                "csr_name",
                "shop_platform",
                "customer_quote",
                "full_context",
                "product_title",
                "sku",
                "order_no",
                "question_type",
                "difficulty_reason",
                "csr_actual_reply",
                "correct_answer",
                "need_knowledge_base",
                "target_knowledge_base",
                "need_media",
                "media_links_json",
                "risk_level",
                "auto_reply_type",
                "review_status",
                "owner",
                "notes",
                "eval_contract_json",
                "eval_created_at",
            }
            for key, value in kwargs.items():
                if key in allowed:
                    setattr(sample, key, value)

            db.commit()
            db.refresh(sample)
            return (
                db.query(KBTrainingSample)
                .options(joinedload(KBTrainingSample.attachments))
                .filter(KBTrainingSample.id == sample.id)
                .first()
            )
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    # ─── 附件 ───

    @staticmethod
    def add_attachment(sample_id: int, **kwargs) -> KBTrainingSampleAttachment:
        db = SessionLocal()
        try:
            att = KBTrainingSampleAttachment(sample_id=sample_id, **kwargs)
            db.add(att)
            db.commit()
            db.refresh(att)
            return att
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    @staticmethod
    def get_attachment(attachment_id: int) -> Optional[KBTrainingSampleAttachment]:
        db = SessionLocal()
        try:
            return (
                db.query(KBTrainingSampleAttachment)
                .filter(KBTrainingSampleAttachment.id == attachment_id)
                .first()
            )
        finally:
            db.close()

    @staticmethod
    def delete_attachment(attachment_id: int) -> bool:
        db = SessionLocal()
        try:
            att = (
                db.query(KBTrainingSampleAttachment)
                .filter(KBTrainingSampleAttachment.id == attachment_id)
                .first()
            )
            if not att:
                return False
            db.delete(att)
            db.commit()
            return True
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    @staticmethod
    def delete(sample_id: int) -> bool:
        db = SessionLocal()
        try:
            sample = (
                db.query(KBTrainingSample)
                .filter(KBTrainingSample.id == sample_id)
                .first()
            )
            if not sample:
                return False
            db.delete(sample)
            db.commit()
            return True
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()
