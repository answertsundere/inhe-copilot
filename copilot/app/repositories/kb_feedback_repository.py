"""
反馈学习数据仓库 - 创建 / 列表过滤 / 分页 / 统计聚合
"""

from datetime import datetime
from typing import Optional

from sqlalchemy import func

from app.db import SessionLocal
from app.models.kb_tables import KBFeedback


class KBFeedbackRepository:
    """反馈学习数据仓库"""

    # ─── 创建 ───

    @staticmethod
    def create(**kwargs) -> KBFeedback:
        db = SessionLocal()
        try:
            fb = KBFeedback(**kwargs)
            db.add(fb)
            db.commit()
            db.refresh(fb)
            return fb
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    # ─── 查询单条 ───

    @staticmethod
    def get_by_id(feedback_id: int) -> Optional[KBFeedback]:
        db = SessionLocal()
        try:
            return db.query(KBFeedback).filter(KBFeedback.id == feedback_id).first()
        finally:
            db.close()

    # ─── 列表 ───

    @staticmethod
    def list_entries(
        csr_action: str = "",
        date_from: datetime = None,
        date_to: datetime = None,
        qa_id: int = None,
        conversation_id: str = "",
        risk_level: str = "",
        source: str = "",
        limit: int = 20,
        offset: int = 0,
    ) -> tuple:
        db = SessionLocal()
        try:
            q = db.query(KBFeedback)
            if csr_action:
                q = q.filter(KBFeedback.csr_action == csr_action)
            if date_from:
                q = q.filter(KBFeedback.created_at >= date_from)
            if date_to:
                q = q.filter(KBFeedback.created_at <= date_to)
            if qa_id is not None:
                q = q.filter(KBFeedback.qa_id == qa_id)
            if conversation_id:
                q = q.filter(KBFeedback.conversation_id == conversation_id)
            if risk_level:
                q = q.filter(KBFeedback.risk_level == risk_level)
            if source:
                q = q.filter(KBFeedback.source == source)
            total = q.count()
            items = (
                q.order_by(KBFeedback.created_at.desc())
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
        """获取反馈统计：采纳率、平均奖励分数等"""
        db = SessionLocal()
        try:
            q = db.query(KBFeedback)
            if date_from:
                q = q.filter(KBFeedback.created_at >= date_from)
            if date_to:
                q = q.filter(KBFeedback.created_at <= date_to)

            total = q.count()
            if total == 0:
                return {
                    "total": 0,
                    "acceptance_rate": 0.0,
                    "avg_reward_score": 0.0,
                    "action_distribution": {},
                    "risk_distribution": {},
                }

            # 采纳率：csr_action 为 accept / use_directly 类的占比
            accept_actions = {"accept", "use_directly", "approved", "采纳", "直接使用"}
            accepted = q.filter(KBFeedback.csr_action.in_(accept_actions)).count()
            acceptance_rate = round(accepted / total, 4)

            # 平均奖励分数
            avg_reward = q.with_entities(
                func.avg(KBFeedback.reward_score)
            ).scalar()
            avg_reward_score = round(float(avg_reward), 4) if avg_reward else 0.0

            # CSR 操作分布
            action_rows = (
                q.with_entities(
                    KBFeedback.csr_action,
                    func.count(KBFeedback.id),
                )
                .group_by(KBFeedback.csr_action)
                .all()
            )
            action_distribution = {r[0]: r[1] for r in action_rows if r[0]}

            # 风险等级分布
            risk_rows = (
                q.with_entities(
                    KBFeedback.risk_level,
                    func.count(KBFeedback.id),
                )
                .group_by(KBFeedback.risk_level)
                .all()
            )
            risk_distribution = {r[0]: r[1] for r in risk_rows if r[0]}

            return {
                "total": total,
                "acceptance_rate": acceptance_rate,
                "avg_reward_score": avg_reward_score,
                "action_distribution": action_distribution,
                "risk_distribution": risk_distribution,
            }
        finally:
            db.close()

    @staticmethod
    def get_qa_feedback_stats(qa_id: int) -> dict:
        """获取某个 QA 条目的反馈统计"""
        db = SessionLocal()
        try:
            q = db.query(KBFeedback).filter(KBFeedback.qa_id == qa_id)
            total = q.count()
            if total == 0:
                return {"qa_id": qa_id, "total": 0, "acceptance_rate": 0.0, "avg_reward_score": 0.0}

            accept_actions = {"accept", "use_directly", "approved", "采纳", "直接使用"}
            accepted = q.filter(KBFeedback.csr_action.in_(accept_actions)).count()
            avg_reward = q.with_entities(func.avg(KBFeedback.reward_score)).scalar()

            return {
                "qa_id": qa_id,
                "total": total,
                "acceptance_rate": round(accepted / total, 4),
                "avg_reward_score": round(float(avg_reward), 4) if avg_reward else 0.0,
            }
        finally:
            db.close()
