"""
审核任务仓库 - 创建 / 列表过滤 / 审批通过（应用变更）/ 驳回 / 统计
"""

import json
from datetime import datetime
from typing import Optional

from sqlalchemy import func

from app.db import SessionLocal
from app.models.kb_tables import KBReviewTask, KBChangeLog


class KBReviewRepository:
    """审核任务仓库"""

    # ─── 创建审核任务 ───

    @staticmethod
    def create_task(**kwargs) -> KBReviewTask:
        db = SessionLocal()
        try:
            task = KBReviewTask(**kwargs)
            db.add(task)
            db.commit()
            db.refresh(task)
            return task
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    # ─── 查询单条 ───

    @staticmethod
    def get_by_id(task_id: int) -> Optional[KBReviewTask]:
        db = SessionLocal()
        try:
            return db.query(KBReviewTask).filter(KBReviewTask.id == task_id).first()
        finally:
            db.close()

    # ─── 列表 ───

    @staticmethod
    def list_tasks(
        status: str = "",
        target_type: str = "",
        priority: str = "",
        risk_level: str = "",
        requested_by: str = "",
        reviewer: str = "",
        limit: int = 20,
        offset: int = 0,
    ) -> tuple:
        db = SessionLocal()
        try:
            q = db.query(KBReviewTask)
            if status:
                q = q.filter(KBReviewTask.status == status)
            if target_type:
                q = q.filter(KBReviewTask.target_type == target_type)
            if priority:
                q = q.filter(KBReviewTask.priority == priority)
            if risk_level:
                q = q.filter(KBReviewTask.risk_level == risk_level)
            if requested_by:
                q = q.filter(KBReviewTask.requested_by == requested_by)
            if reviewer:
                q = q.filter(KBReviewTask.reviewer == reviewer)
            total = q.count()
            items = (
                q.order_by(KBReviewTask.created_at.desc())
                .offset(offset)
                .limit(limit)
                .all()
            )
            return items, total
        finally:
            db.close()

    # ─── 审批通过 ───

    @staticmethod
    def approve(task_id: int, reviewer: str = "", opinion: str = "") -> Optional[KBReviewTask]:
        """审批通过：更新任务状态并将变更应用到目标实体"""
        db = SessionLocal()
        try:
            task = db.query(KBReviewTask).filter(KBReviewTask.id == task_id).first()
            if not task:
                return None
            if task.status != "pending":
                raise ValueError(f"当前状态 {task.status} 不允许审批，仅 pending 可操作")

            task.status = "approved"
            task.reviewer = reviewer
            task.reviewed_at = datetime.utcnow()
            task.review_opinion = opinion or "审核通过"
            db.commit()
            db.refresh(task)

            # 将变更应用到目标实体
            _apply_reviewed_changes(db, task)

            # 写变更日志
            _log_review_action(
                db, task=task, action="review_approve",
                performed_by=reviewer, reason=opinion or "审核通过并应用变更",
            )
            return task
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    # ─── 驳回 ───

    @staticmethod
    def reject(task_id: int, reviewer: str = "", opinion: str = "") -> Optional[KBReviewTask]:
        db = SessionLocal()
        try:
            task = db.query(KBReviewTask).filter(KBReviewTask.id == task_id).first()
            if not task:
                return None
            if task.status != "pending":
                raise ValueError(f"当前状态 {task.status} 不允许驳回，仅 pending 可操作")

            task.status = "rejected"
            task.reviewer = reviewer
            task.reviewed_at = datetime.utcnow()
            task.review_opinion = opinion or "审核驳回"
            db.commit()
            db.refresh(task)

            _log_review_action(
                db, task=task, action="review_reject",
                performed_by=reviewer, reason=opinion or "审核驳回",
            )
            return task
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    # ─── 统计 ───

    @staticmethod
    def get_stats() -> dict:
        """获取审核任务统计概览"""
        db = SessionLocal()
        try:
            total = db.query(func.count(KBReviewTask.id)).scalar() or 0

            # 状态分布
            status_rows = (
                db.query(KBReviewTask.status, func.count(KBReviewTask.id))
                .group_by(KBReviewTask.status)
                .all()
            )
            status_distribution = {r[0]: r[1] for r in status_rows if r[0]}

            # 优先级分布
            priority_rows = (
                db.query(KBReviewTask.priority, func.count(KBReviewTask.id))
                .group_by(KBReviewTask.priority)
                .all()
            )
            priority_distribution = {r[0]: r[1] for r in priority_rows if r[0]}

            # 目标类型分布
            type_rows = (
                db.query(KBReviewTask.target_type, func.count(KBReviewTask.id))
                .group_by(KBReviewTask.target_type)
                .all()
            )
            type_distribution = {r[0]: r[1] for r in type_rows if r[0]}

            # 待审核高风险任务数
            pending_high_risk = (
                db.query(func.count(KBReviewTask.id))
                .filter(
                    KBReviewTask.status == "pending",
                    KBReviewTask.risk_level.in_(["high", "critical"]),
                )
                .scalar()
            ) or 0

            return {
                "total": total,
                "status_distribution": status_distribution,
                "priority_distribution": priority_distribution,
                "type_distribution": type_distribution,
                "pending_high_risk_count": pending_high_risk,
            }
        finally:
            db.close()


# ─── 内部辅助函数 ───

def _apply_reviewed_changes(db, task: KBReviewTask):
    """将审核通过的变更应用到目标实体"""
    after_snapshot = task.get_after_snapshot()
    if not after_snapshot:
        return

    target_type = task.target_type
    target_id = task.target_id
    changed_fields = task.get_changed_fields()

    # 根据目标类型加载对应实体并应用变更
    if target_type == "kb_qa":
        from app.models.kb_tables import KBQA
        qa = db.query(KBQA).filter(KBQA.id == target_id).first()
        if qa:
            for field in changed_fields:
                if field in after_snapshot:
                    if field == "sku_codes":
                        qa.set_sku_codes(after_snapshot[field])
                    elif field == "keywords":
                        qa.set_keywords(after_snapshot[field])
                    elif hasattr(qa, field):
                        setattr(qa, field, after_snapshot[field])
            qa.updated_at = datetime.utcnow()
            db.commit()

    elif target_type == "kb_product":
        from app.models.kb_tables import KBProduct
        product = db.query(KBProduct).filter(KBProduct.id == target_id).first()
        if product:
            for field in changed_fields:
                if field in after_snapshot:
                    if field == "sku_list":
                        product.set_sku_list(after_snapshot[field])
                    elif field == "specs":
                        product.set_specs(after_snapshot[field])
                    elif field == "logistics":
                        product.set_logistics(after_snapshot[field])
                    elif field == "warranty":
                        product.set_warranty(after_snapshot[field])
                    elif hasattr(product, field):
                        setattr(product, field, after_snapshot[field])
            product.updated_at = datetime.utcnow()
            db.commit()

    elif target_type == "kb_sop":
        from app.models.kb_tables import KBSOP
        sop = db.query(KBSOP).filter(KBSOP.id == target_id).first()
        if sop:
            for field in changed_fields:
                if field in after_snapshot:
                    if field == "keywords":
                        sop.set_keywords(after_snapshot[field])
                    elif field == "steps":
                        sop.set_steps(after_snapshot[field])
                    elif field == "forbidden_actions":
                        sop.set_forbidden_actions(after_snapshot[field])
                    elif hasattr(sop, field):
                        setattr(sop, field, after_snapshot[field])
            sop.updated_at = datetime.utcnow()
            db.commit()


def _log_review_action(db, task: KBReviewTask, action: str, performed_by: str, reason: str = ""):
    """写入审核操作变更日志"""
    entry = KBChangeLog(
        target_type=task.target_type,
        target_id=task.target_id,
        target_title=f"审核任务 #{task.id}",
        action=action,
        before_status="pending",
        after_status=task.status,
        performed_by=performed_by or "",
        change_reason=reason,
        review_task_id=task.id,
    )
    entry.set_snapshot(task.to_dict())
    entry.set_changed_fields(task.get_changed_fields())
    db.add(entry)
    db.commit()
