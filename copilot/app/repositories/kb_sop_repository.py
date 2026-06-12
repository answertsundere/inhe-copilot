"""
SOP 知识库仓库 - CRUD / 列表过滤 / 状态流转 / 变更日志
"""

import json
from datetime import datetime
from typing import Optional

from sqlalchemy import or_

from app.db import SessionLocal
from app.models.kb_tables import KBSOP, KBChangeLog


class KBSOPRepository:
    """SOP 知识库仓库"""

    # ─── 创建 ───

    @staticmethod
    def create(**kwargs) -> KBSOP:
        db = SessionLocal()
        try:
            sop = KBSOP(**kwargs)
            db.add(sop)
            db.commit()
            db.refresh(sop)

            _log_change(
                db, target_type="kb_sop", target_id=sop.id,
                target_title=sop.scenario, action="create",
                after_status=sop.status, performed_by=sop.created_by,
                snapshot=sop.to_dict(), reason="新建SOP",
            )
            return sop
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    # ─── 查询单条 ───

    @staticmethod
    def get_by_id(sop_id: int) -> Optional[KBSOP]:
        db = SessionLocal()
        try:
            return db.query(KBSOP).filter(KBSOP.id == sop_id).first()
        finally:
            db.close()

    @staticmethod
    def get_by_code(scenario_code: str) -> Optional[KBSOP]:
        db = SessionLocal()
        try:
            return db.query(KBSOP).filter(KBSOP.scenario_code == scenario_code).first()
        finally:
            db.close()

    # ─── 更新 ───

    @staticmethod
    def update(sop_id: int, updates: dict, updated_by: str = "") -> Optional[KBSOP]:
        db = SessionLocal()
        try:
            sop = db.query(KBSOP).filter(KBSOP.id == sop_id).first()
            if not sop:
                return None

            allowed_fields = {
                "scenario", "scenario_code", "risk_level",
                "escalation_condition", "escalation_target",
                "response_template", "category_l1",
                "status", "owner",
            }
            json_setters = {
                "keywords": "set_keywords",
                "steps": "set_steps",
                "forbidden_actions": "set_forbidden_actions",
            }

            changed = []
            for k, v in updates.items():
                if k.startswith("_"):
                    continue
                if k in json_setters:
                    getattr(sop, json_setters[k])(v)
                    changed.append(k)
                elif k in allowed_fields:
                    setattr(sop, k, v)
                    changed.append(k)

            sop.updated_by = updated_by or sop.updated_by
            sop.updated_at = datetime.utcnow()
            db.commit()
            db.refresh(sop)

            _log_change(
                db, target_type="kb_sop", target_id=sop.id,
                target_title=sop.scenario, action="update",
                before_status=sop.status, after_status=sop.status,
                performed_by=updated_by, changed_fields=changed,
                snapshot=sop.to_dict(), reason="更新SOP",
            )
            return sop
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    # ─── 列表 ───

    @staticmethod
    def list_entries(
        risk_level: str = "",
        status: str = "",
        category_l1: str = "",
        search: str = "",
        limit: int = 20,
        offset: int = 0,
    ) -> tuple:
        db = SessionLocal()
        try:
            q = db.query(KBSOP)
            if risk_level:
                q = q.filter(KBSOP.risk_level == risk_level)
            if status:
                q = q.filter(KBSOP.status == status)
            if category_l1:
                q = q.filter(KBSOP.category_l1 == category_l1)
            if search:
                like = f"%{search}%"
                q = q.filter(
                    or_(
                        KBSOP.scenario.ilike(like),
                        KBSOP.scenario_code.ilike(like),
                    )
                )
            total = q.count()
            items = (
                q.order_by(KBSOP.updated_at.desc())
                .offset(offset)
                .limit(limit)
                .all()
            )
            return items, total
        finally:
            db.close()

    # ─── 状态流转 ───

    @staticmethod
    def submit_for_review(sop_id: int, user: str = "") -> Optional[KBSOP]:
        db = SessionLocal()
        try:
            sop = db.query(KBSOP).filter(KBSOP.id == sop_id).first()
            if not sop:
                return None
            if sop.status not in ("draft", "rejected"):
                raise ValueError(f"当前状态 {sop.status} 不允许提交审核")

            old_status = sop.status
            sop.status = "pending_review"
            sop.updated_by = user
            sop.updated_at = datetime.utcnow()
            db.commit()
            db.refresh(sop)

            _log_change(
                db, target_type="kb_sop", target_id=sop.id,
                target_title=sop.scenario, action="submit_review",
                before_status=old_status, after_status="pending_review",
                performed_by=user, reason="SOP提交审核",
            )
            return sop
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    @staticmethod
    def approve(sop_id: int, user: str = "") -> Optional[KBSOP]:
        db = SessionLocal()
        try:
            sop = db.query(KBSOP).filter(KBSOP.id == sop_id).first()
            if not sop:
                return None
            if sop.status != "pending_review":
                raise ValueError(f"当前状态 {sop.status} 不允许审核通过")

            old_status = sop.status
            sop.status = "published"
            sop.reviewed_by = user
            sop.version += 1
            sop.updated_by = user
            sop.updated_at = datetime.utcnow()
            db.commit()
            db.refresh(sop)

            _log_change(
                db, target_type="kb_sop", target_id=sop.id,
                target_title=sop.scenario, action="approve",
                before_status=old_status, after_status="published",
                performed_by=user, reason="SOP审核通过并发布",
            )
            return sop
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    @staticmethod
    def reject(sop_id: int, user: str = "", reason: str = "") -> Optional[KBSOP]:
        db = SessionLocal()
        try:
            sop = db.query(KBSOP).filter(KBSOP.id == sop_id).first()
            if not sop:
                return None
            if sop.status != "pending_review":
                raise ValueError(f"当前状态 {sop.status} 不允许驳回")

            old_status = sop.status
            sop.status = "rejected"
            sop.reviewed_by = user
            sop.updated_by = user
            sop.updated_at = datetime.utcnow()
            db.commit()
            db.refresh(sop)

            _log_change(
                db, target_type="kb_sop", target_id=sop.id,
                target_title=sop.scenario, action="reject",
                before_status=old_status, after_status="rejected",
                performed_by=user, reason=f"SOP审核驳回: {reason}",
            )
            return sop
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    @staticmethod
    def archive(sop_id: int, user: str = "") -> Optional[KBSOP]:
        db = SessionLocal()
        try:
            sop = db.query(KBSOP).filter(KBSOP.id == sop_id).first()
            if not sop:
                return None
            if sop.status == "archived":
                return sop

            old_status = sop.status
            sop.status = "archived"
            sop.updated_by = user
            sop.updated_at = datetime.utcnow()
            db.commit()
            db.refresh(sop)

            _log_change(
                db, target_type="kb_sop", target_id=sop.id,
                target_title=sop.scenario, action="archive",
                before_status=old_status, after_status="archived",
                performed_by=user, reason="SOP归档",
            )
            return sop
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()


# ─── 内部变更日志辅助 ───

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
