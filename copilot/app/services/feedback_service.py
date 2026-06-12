"""
反馈记录服务 - 用 JSONL 文件记录客服反馈
"""

import json
import os
from datetime import datetime

from app.config import FEEDBACK_FILE


class FeedbackService:
    """反馈记录服务"""

    def __init__(self, filepath: str = ""):
        self.filepath = filepath or FEEDBACK_FILE
        self._ensure_dir()

    def _ensure_dir(self):
        dirpath = os.path.dirname(self.filepath)
        if dirpath:
            os.makedirs(dirpath, exist_ok=True)

    def save(
        self,
        customer_message: str,
        suggested_reply: str,
        action: str,
        order_id: str = "",
        final_reply: str = "",
        risk_level: str = "",
        source: str = "analysis",
        review_id: str = "",
        reject_reason: str = "",
        used_knowledge_entry_ids: list = None,
        used_fact_tools: str = "",
        need_human_review: bool = False,
    ) -> dict:
        """
        保存一条反馈记录。
        action: accepted / edited / rejected / escalated / human_review
        source: analysis / review / copilot_panel / sidecar
        """
        record = {
            "customer_message": customer_message,
            "order_id": order_id,
            "suggested_reply": suggested_reply,
            "final_reply": final_reply,
            "action": action,
            "risk_level": risk_level,
            "source": source,
            "review_id": review_id,
            "reject_reason": reject_reason,
            "used_knowledge_entry_ids": used_knowledge_entry_ids or [],
            "used_fact_tools": used_fact_tools,
            "need_human_review": need_human_review,
            "has_final_reply": bool(final_reply.strip()),
            "suggested_reply_length": len(suggested_reply),
            "final_reply_length": len(final_reply),
            "created_at": datetime.now().isoformat(),
        }

        with open(self.filepath, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

        return record

    def load_all(self, limit: int = 100) -> list:
        if not os.path.exists(self.filepath):
            return []
        records = []
        with open(self.filepath, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    records.append(json.loads(line))
        records.sort(key=lambda x: x.get("created_at", ""), reverse=True)
        return records[:limit]

    def get_stats(self) -> dict:
        records = self.load_all(limit=10000)
        if not records:
            return {
                "total": 0, "accepted": 0, "edited": 0,
                "rejected": 0, "escalated": 0,
                "acceptance_rate": 0.0, "escalation_rate": 0.0, "edit_rate": 0.0,
                "review_source_count": 0, "analysis_source_count": 0,
            }

        counts = {"accepted": 0, "edited": 0, "rejected": 0, "escalated": 0}
        source_counts = {"analysis": 0, "review": 0}
        for r in records:
            action = r.get("action", "")
            if action in counts:
                counts[action] += 1
            src = r.get("source", "analysis")
            if src in source_counts:
                source_counts[src] += 1

        total = len(records)
        acceptance_rate = round((counts["accepted"] + counts["edited"]) / total * 100, 1) if total else 0.0
        escalation_rate = round(counts["escalated"] / total * 100, 1) if total else 0.0
        edit_rate = round(counts["edited"] / total * 100, 1) if total else 0.0

        return {
            "total": total,
            **counts,
            "acceptance_rate": acceptance_rate,
            "escalation_rate": escalation_rate,
            "edit_rate": edit_rate,
            "review_source_count": source_counts["review"],
            "analysis_source_count": source_counts["analysis"],
        }
