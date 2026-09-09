"""
人工复核队列服务 - 用 JSONL 文件保存需要人工复核的消息
"""

import json
import os
import hashlib
import threading
import uuid
from datetime import datetime
from typing import Optional


# The application uses one process. Share the lock across queue instances so
# read/append and review rewrites cannot interleave within that process.
_QUEUE_LOCK = threading.RLock()


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

    def enqueue(
        self, suggestion_dict: dict, customer_message: str, order_id: str = "", *,
        source: str = "", conversation_id: str = "", message_id: str = "",
        request_id: str = "", shop_id: str = "",
    ) -> dict:
        """
        将一条分析结果加入复核队列。
        仅完整执行身份及审核内容相同的 pending 记录可复用；身份缺失不猜重。
        返回队列记录。
        """
        identity = self._enqueue_identity(source, conversation_id, message_id, request_id, shop_id)
        content = {
            "enqueue_identity": identity,
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
        }

        with _QUEUE_LOCK:
            if identity:
                for rec in self._load_all():
                    if (rec.get("status") == "pending"
                            and all(rec.get(key) == value for key, value in content.items())):
                        return rec
            record = {
                **content,
                "id": str(uuid.uuid4()),
                "status": "pending",
                "created_at": datetime.now().isoformat(),
                "updated_at": datetime.now().isoformat(),
                "reviewed_by": "",
                "review_note": "",
            }
            with open(self.filepath, "a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")

        return record

    @staticmethod
    def _enqueue_identity(source, conversation_id, message_id, request_id, shop_id) -> dict:
        parts = [source, shop_id, conversation_id, message_id, request_id]
        if any(not isinstance(value, str) or len(value) > 512 or value != value.strip()
               or any(ord(char) < 32 or ord(char) == 127 for char in value) for value in parts):
            return {}
        if (not source or not conversation_id or conversation_id in {"default", "qianniu"}
                or not (message_id or request_id)):
            return {}
        # Structured encoding avoids delimiter collisions. Do not persist raw
        # conversation/shop IDs or infer identity from text, time or order IDs.
        try:
            encoded = json.dumps(parts, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        except UnicodeEncodeError:
            return {}
        return {"schema_version": "review-event/v1", "sha256": hashlib.sha256(encoded).hexdigest()}

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

        with _QUEUE_LOCK:
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
        with _QUEUE_LOCK:
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

    def _write_all(self, records: list):
        with open(self.filepath, "w", encoding="utf-8") as f:
            for rec in records:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
