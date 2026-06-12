"""
变更日志仓库 - 创建 / 列表过滤 / 分页
"""

from datetime import datetime
from typing import Optional

from sqlalchemy import func

from app.db import SessionLocal
from app.models.kb_tables import KBChangeLog


class KBChangelogRepository:
    """变更日志仓库"""

    # ─── 创建 ───

    @staticmethod
    def create(**kwargs) -> KBChangeLog:
        db = SessionLocal()
        try:
            entry = KBChangeLog(**kwargs)
            db.add(entry)
            db.commit()
            db.refresh(entry)
            return entry
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    # ─── 查询单条 ───

    @staticmethod
    def get_by_id(log_id: int) -> Optional[KBChangeLog]:
        db = SessionLocal()
        try:
            return db.query(KBChangeLog).filter(KBChangeLog.id == log_id).first()
        finally:
            db.close()

    # ─── 列表 ───

    @staticmethod
    def list_entries(
        target_type: str = "",
        target_id: int = None,
        performed_by: str = "",
        action: str = "",
        date_from: datetime = None,
        date_to: datetime = None,
        limit: int = 20,
        offset: int = 0,
    ) -> tuple:
        db = SessionLocal()
        try:
            q = db.query(KBChangeLog)
            if target_type:
                q = q.filter(KBChangeLog.target_type == target_type)
            if target_id is not None:
                q = q.filter(KBChangeLog.target_id == target_id)
            if performed_by:
                q = q.filter(KBChangeLog.performed_by == performed_by)
            if action:
                q = q.filter(KBChangeLog.action == action)
            if date_from:
                q = q.filter(KBChangeLog.created_at >= date_from)
            if date_to:
                q = q.filter(KBChangeLog.created_at <= date_to)
            total = q.count()
            items = (
                q.order_by(KBChangeLog.created_at.desc())
                .offset(offset)
                .limit(limit)
                .all()
            )
            return items, total
        finally:
            db.close()

    # ─── 按目标实体查看历史 ───

    @staticmethod
    def get_target_history(target_type: str, target_id: int, limit: int = 50) -> list:
        """获取某个目标实体的完整变更历史"""
        db = SessionLocal()
        try:
            return (
                db.query(KBChangeLog)
                .filter(
                    KBChangeLog.target_type == target_type,
                    KBChangeLog.target_id == target_id,
                )
                .order_by(KBChangeLog.created_at.desc())
                .limit(limit)
                .all()
            )
        finally:
            db.close()

    # ─── 统计 ───

    @staticmethod
    def get_action_stats(
        date_from: datetime = None,
        date_to: datetime = None,
    ) -> dict:
        """获取操作类型分布统计"""
        db = SessionLocal()
        try:
            q = db.query(KBChangeLog)
            if date_from:
                q = q.filter(KBChangeLog.created_at >= date_from)
            if date_to:
                q = q.filter(KBChangeLog.created_at <= date_to)

            total = q.count()
            if total == 0:
                return {"total": 0, "action_distribution": {}, "type_distribution": {}}

            # 操作类型分布
            action_rows = (
                q.with_entities(
                    KBChangeLog.action,
                    func.count(KBChangeLog.id),
                )
                .group_by(KBChangeLog.action)
                .all()
            )
            action_distribution = {r[0]: r[1] for r in action_rows if r[0]}

            # 目标类型分布
            type_rows = (
                q.with_entities(
                    KBChangeLog.target_type,
                    func.count(KBChangeLog.id),
                )
                .group_by(KBChangeLog.target_type)
                .all()
            )
            type_distribution = {r[0]: r[1] for r in type_rows if r[0]}

            return {
                "total": total,
                "action_distribution": action_distribution,
                "type_distribution": type_distribution,
            }
        finally:
            db.close()
