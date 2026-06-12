"""
真实客服案例仓库 - CRUD / 列表过滤 / 分页
"""

from datetime import datetime
from typing import Optional

from sqlalchemy import or_

from app.db import SessionLocal
from app.models.kb_tables import KBCase


class KBCaseRepository:
    """客服案例仓库"""

    # ─── 创建 ───

    @staticmethod
    def create(**kwargs) -> KBCase:
        db = SessionLocal()
        try:
            case = KBCase(**kwargs)
            db.add(case)
            db.commit()
            db.refresh(case)
            return case
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    # ─── 查询单条 ───

    @staticmethod
    def get_by_id(case_id: int) -> Optional[KBCase]:
        db = SessionLocal()
        try:
            return db.query(KBCase).filter(KBCase.id == case_id).first()
        finally:
            db.close()

    @staticmethod
    def get_by_code(case_code: str) -> Optional[KBCase]:
        db = SessionLocal()
        try:
            return db.query(KBCase).filter(KBCase.case_code == case_code).first()
        finally:
            db.close()

    # ─── 更新 ───

    @staticmethod
    def update(case_id: int, updates: dict, updated_by: str = "") -> Optional[KBCase]:
        db = SessionLocal()
        try:
            case = db.query(KBCase).filter(KBCase.id == case_id).first()
            if not case:
                return None

            allowed_fields = {
                "case_code", "scenario",
                "customer_dialogue", "correct_reply", "wrong_reply",
                "reply_quality_score", "empathy_score", "accuracy_score",
                "wrong_reply_score", "wrong_reason", "supervisor_comment",
                "final_result", "category_l1", "risk_level",
                "qa_id", "status",
            }
            json_setters = {
                "tags": "set_tags",
            }

            for k, v in updates.items():
                if k.startswith("_"):
                    continue
                if k in json_setters:
                    getattr(case, json_setters[k])(v)
                elif k in allowed_fields:
                    setattr(case, k, v)

            case.created_by = updated_by or case.created_by
            case.updated_at = datetime.utcnow()
            db.commit()
            db.refresh(case)
            return case
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    # ─── 删除 ───

    @staticmethod
    def delete(case_id: int) -> bool:
        db = SessionLocal()
        try:
            case = db.query(KBCase).filter(KBCase.id == case_id).first()
            if not case:
                return False
            db.delete(case)
            db.commit()
            return True
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    # ─── 列表 ───

    @staticmethod
    def list_entries(
        scenario: str = "",
        category_l1: str = "",
        risk_level: str = "",
        search: str = "",
        status: str = "",
        limit: int = 20,
        offset: int = 0,
    ) -> tuple:
        db = SessionLocal()
        try:
            q = db.query(KBCase)
            if scenario:
                q = q.filter(KBCase.scenario.ilike(f"%{scenario}%"))
            if category_l1:
                q = q.filter(KBCase.category_l1 == category_l1)
            if risk_level:
                q = q.filter(KBCase.risk_level == risk_level)
            if status:
                q = q.filter(KBCase.status == status)
            if search:
                like = f"%{search}%"
                q = q.filter(
                    or_(
                        KBCase.case_code.ilike(like),
                        KBCase.scenario.ilike(like),
                        KBCase.customer_dialogue.ilike(like),
                    )
                )
            total = q.count()
            items = (
                q.order_by(KBCase.created_at.desc())
                .offset(offset)
                .limit(limit)
                .all()
            )
            return items, total
        finally:
            db.close()
