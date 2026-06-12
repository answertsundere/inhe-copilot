"""
Agent 流程轨迹仓库 - 创建 / 列表过滤 / 分页 / 统计聚合
"""

from datetime import datetime
from typing import Optional

from sqlalchemy import func, cast, Float

from app.db import SessionLocal
from app.models.kb_tables import KBAgentTrace


class KBAgentTraceRepository:
    """Agent 流程轨迹仓库"""

    # ─── 创建 ───

    @staticmethod
    def create(**kwargs) -> KBAgentTrace:
        db = SessionLocal()
        try:
            trace = KBAgentTrace(**kwargs)
            db.add(trace)
            db.commit()
            db.refresh(trace)
            return trace
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    # ─── 查询单条 ───

    @staticmethod
    def get_by_id(trace_id: int) -> Optional[KBAgentTrace]:
        db = SessionLocal()
        try:
            return db.query(KBAgentTrace).filter(KBAgentTrace.id == trace_id).first()
        finally:
            db.close()

    # ─── 列表 ───

    @staticmethod
    def list_entries(
        conversation_id: str = "",
        intent: str = "",
        date_from: datetime = None,
        date_to: datetime = None,
        risk_level: str = "",
        guard_passed: bool = None,
        limit: int = 20,
        offset: int = 0,
    ) -> tuple:
        db = SessionLocal()
        try:
            q = db.query(KBAgentTrace)
            if conversation_id:
                q = q.filter(KBAgentTrace.conversation_id == conversation_id)
            if intent:
                q = q.filter(KBAgentTrace.detected_intent == intent)
            if date_from:
                q = q.filter(KBAgentTrace.created_at >= date_from)
            if date_to:
                q = q.filter(KBAgentTrace.created_at <= date_to)
            if risk_level:
                q = q.filter(KBAgentTrace.risk_level == risk_level)
            if guard_passed is not None:
                q = q.filter(KBAgentTrace.guard_passed == guard_passed)
            total = q.count()
            items = (
                q.order_by(KBAgentTrace.created_at.desc())
                .offset(offset)
                .limit(limit)
                .all()
            )
            return items, total
        finally:
            db.close()

    # ─── 统计聚合 ───

    @staticmethod
    def get_stats(
        date_from: datetime = None,
        date_to: datetime = None,
    ) -> dict:
        """获取轨迹统计概览"""
        db = SessionLocal()
        try:
            q = db.query(KBAgentTrace)
            if date_from:
                q = q.filter(KBAgentTrace.created_at >= date_from)
            if date_to:
                q = q.filter(KBAgentTrace.created_at <= date_to)

            total = q.count()
            if total == 0:
                return {
                    "total": 0,
                    "avg_confidence": 0.0,
                    "avg_duration_ms": 0.0,
                    "guard_pass_rate": 0.0,
                    "intent_distribution": {},
                    "risk_distribution": {},
                }

            # 平均置信度
            avg_confidence = q.with_entities(
                func.avg(KBAgentTrace.confidence)
            ).scalar() or 0.0

            # 平均耗时
            avg_duration = q.with_entities(
                func.avg(KBAgentTrace.total_duration_ms)
            ).scalar() or 0.0

            # Guard 通过率
            guard_passed_count = q.filter(KBAgentTrace.guard_passed == True).count()
            guard_pass_rate = round(guard_passed_count / total, 4)

            # 意图分布
            intent_rows = (
                q.with_entities(
                    KBAgentTrace.detected_intent,
                    func.count(KBAgentTrace.id),
                )
                .group_by(KBAgentTrace.detected_intent)
                .all()
            )
            intent_distribution = {r[0]: r[1] for r in intent_rows if r[0]}

            # 风险等级分布
            risk_rows = (
                q.with_entities(
                    KBAgentTrace.risk_level,
                    func.count(KBAgentTrace.id),
                )
                .group_by(KBAgentTrace.risk_level)
                .all()
            )
            risk_distribution = {r[0]: r[1] for r in risk_rows if r[0]}

            return {
                "total": total,
                "avg_confidence": round(float(avg_confidence), 4),
                "avg_duration_ms": round(float(avg_duration), 2),
                "guard_pass_rate": guard_pass_rate,
                "intent_distribution": intent_distribution,
                "risk_distribution": risk_distribution,
            }
        finally:
            db.close()

    @staticmethod
    def get_conversation_timeline(conversation_id: str) -> list:
        """获取某个会话的完整 Agent 轨迹时间线"""
        db = SessionLocal()
        try:
            return (
                db.query(KBAgentTrace)
                .filter(KBAgentTrace.conversation_id == conversation_id)
                .order_by(KBAgentTrace.created_at.asc())
                .all()
            )
        finally:
            db.close()
