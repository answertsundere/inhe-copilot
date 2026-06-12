"""
知识反馈仓库
"""

from sqlalchemy.orm import Session
from app.models.knowledge_base import KnowledgeFeedback


def _get_db():
    from app.db import SessionLocal
    return SessionLocal()


class KnowledgeFeedbackRepository:
    """知识反馈仓库"""

    @staticmethod
    def create(
        entry_id: int,
        conversation_id: str = "",
        message_id: str = "",
        agent_reply: str = "",
        suggested_reply: str = "",
        used_knowledge_entry_ids: list = None,
        was_used: bool = False,
        csr_accepted: bool = False,
        csr_edited: bool = False,
        csr_rejected: bool = False,
        edited_reply: str = "",
        reject_reason: str = "",
        supervisor_score: int = None,
        customer_result: str = "",
    ) -> KnowledgeFeedback:
        db = _get_db()
        try:
            fb = KnowledgeFeedback(
                entry_id=entry_id,
                conversation_id=conversation_id,
                message_id=message_id,
                agent_reply=agent_reply,
                suggested_reply=suggested_reply,
                was_used=was_used,
                csr_accepted=csr_accepted,
                csr_edited=csr_edited,
                csr_rejected=csr_rejected,
                edited_reply=edited_reply,
                reject_reason=reject_reason,
                supervisor_score=supervisor_score,
                customer_result=customer_result,
            )
            if used_knowledge_entry_ids:
                fb.set_used_entry_ids(used_knowledge_entry_ids)
            db.add(fb)
            db.commit()
            db.refresh(fb)
            return fb
        finally:
            db.close()

    @staticmethod
    def list_by_entry(entry_id: int, limit: int = 100):
        db = _get_db()
        try:
            return (
                db.query(KnowledgeFeedback)
                .filter(KnowledgeFeedback.entry_id == entry_id)
                .order_by(KnowledgeFeedback.created_at.desc())
                .limit(limit)
                .all()
            )
        finally:
            db.close()
