"""
人工复核队列服务 - 用 JSONL 文件保存需要人工复核的消息
"""

import json
import os
import uuid
from datetime import datetime
from typing import Optional


class ReviewQueueService:
    """人工复核队列"""

    def __init__(self, filepath: str = ""):
        self.filepath = filepath
        self._ensure_dir()

    def _ensure_dir(self):
        dirpath = os.path.dirname(self.filepath)
        if dirpath:
            os.makedirs(dirpath, exist_ok=True)

    # ---- 写入 ----

    def enqueue(self, suggestion_dict: dict, customer_message: str, order_id: str = "") -> dict:
        """
        将一条分析结果加入复核队列。
        如果已是 pending 且 customer_message + order_id 相同，不重复写入。
        返回队列记录。
        """
        # 防重复：检查最后 200 条
        existing = self._load_recent(200)
        msg_key = customer_message.strip() + "|" + (order_id or "").strip()
        for rec in existing:
            if (rec.get("status") == "pending"
                    and rec.get("customer_message", "").strip() + "|" + rec.get("order_id", "").strip() == msg_key):
                return rec  # 已存在，返回已有记录

        record = {
            "id": str(uuid.uuid4()),
            "customer_message": customer_message,
            "order_id": order_id or "",
            "suggested_reply": suggestion_dict.get("suggested_reply", ""),
            "final_reply": "",
            "risk_level": suggestion_dict.get("risk_level", "low"),
            "intent": suggestion_dict.get("intent", ""),
            "customer_emotion": suggestion_dict.get("customer_emotion", ""),
            "policy_warnings": suggestion_dict.get("policy_warnings", []),
            "guard_warnings": suggestion_dict.get("guard_warnings", []),
            "action_proposal": suggestion_dict.get("action_proposal", {}),
            "status": "pending",
            "created_at": datetime.now().isoformat(),
            "updated_at": datetime.now().isoformat(),
            "reviewed_by": "",
            "review_note": "",
        }

        with open(self.filepath, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

        return record

    def decide(self, review_id: str, status: str, final_reply: str = "",
               reviewed_by: str = "", review_note: str = "") -> Optional[dict]:
        """
        处理复核决策。
        status: approved / edited / rejected / escalated
        edited 时 final_reply 不能为空。
        返回更新后的记录，或 None（id 不存在）。
        抛出 ValueError（status 非法 / edited 缺 final_reply）。
        """
        valid = {"approved", "edited", "rejected", "escalated"}
        if status not in valid:
            raise ValueError(f"非法 status: {status}，允许: {', '.join(sorted(valid))}")

        if status == "edited" and not final_reply.strip():
            raise ValueError("edited 状态必须提供 final_reply")

        records = self._load_all()
        found = None
        for rec in records:
            if rec["id"] == review_id:
                found = rec
                break

        if found is None:
            return None

        found["status"] = status
        found["final_reply"] = final_reply or (found["suggested_reply"] if status == "approved" else "")
        found["reviewed_by"] = reviewed_by
        found["review_note"] = review_note
        found["updated_at"] = datetime.now().isoformat()

        # 全量重写
        self._write_all(records)
        return found

    # ---- 读取 ----

    def get_by_id(self, review_id: str) -> Optional[dict]:
        for rec in self._load_all():
            if rec["id"] == review_id:
                return rec
        return None

    def list_reviews(self, status: str = "", limit: int = 50) -> list:
        records = self._load_all()
        if status:
            records = [r for r in records if r.get("status") == status]
        records.sort(key=lambda x: x.get("created_at", ""), reverse=True)
        return records[:limit]

    def count_pending(self) -> int:
        return len([r for r in self._load_all() if r.get("status") == "pending"])

    # ---- 内部 ----

    def _load_all(self) -> list:
        if not os.path.exists(self.filepath):
            return []
        records = []
        with open(self.filepath, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        records.append(json.loads(line))
                    except json.JSONDecodeError:
                        pass
        return records

    def _load_recent(self, n: int) -> list:
        if not os.path.exists(self.filepath):
            return []
        lines = []
        with open(self.filepath, "r", encoding="utf-8") as f:
            for line in f:
                lines.append(line)
        records = []
        for line in lines[-n:]:
            line = line.strip()
            if line:
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
        return records

    def _write_all(self, records: list):
        with open(self.filepath, "w", encoding="utf-8") as f:
            for rec in records:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
