"""
Analysis Snapshot — 服务端分析结果快照。

每次 /api/analyze 和 /api/copilot/context 成功后保存快照。
feedback 和 Bad Case 从服务端快照读取，不依赖前端上传。
"""

from __future__ import annotations

import json
import os
import threading
import uuid
from datetime import datetime
from typing import Optional

from app.config import BASE_DIR

SNAPSHOTS_DIR = os.environ.get(
    "COPILOT_SNAPSHOTS_DIR",
    os.path.join(BASE_DIR, "data", "snapshots"),
)

_lock = threading.Lock()


def _ensure_dir():
    os.makedirs(SNAPSHOTS_DIR, exist_ok=True)


def _new_request_id() -> str:
    return "req-" + uuid.uuid4().hex[:10]


def _new_message_id() -> str:
    return "msg-" + uuid.uuid4().hex[:10]


def _now() -> str:
    return datetime.now().isoformat()


def save_snapshot(
    request_id: str,
    message_id: str,
    conversation_id: str,
    source: str,
    scenario: str,
    customer_message: str,
    suggested_reply: str,
    intent: str,
    risk_level: str,
    need_human_review: bool,
    execution_debug: dict | None = None,
    evidence_debug: dict | None = None,
    trace_steps: list | None = None,
    used_knowledge_entry_ids: list | None = None,
    used_fact_tools: str = "",
    copilot_context: dict | None = None,
) -> dict:
    """保存分析快照到磁盘。"""
    _ensure_dir()
    snapshot = {
        "request_id": request_id,
        "message_id": message_id,
        "conversation_id": conversation_id,
        "source": source,
        "scenario": scenario,
        "customer_message": customer_message,
        "suggested_reply": suggested_reply,
        "intent": intent,
        "risk_level": risk_level,
        "need_human_review": need_human_review,
        "execution_debug_json": json.dumps(execution_debug or {}, ensure_ascii=False),
        "evidence_debug_json": json.dumps(evidence_debug or {}, ensure_ascii=False),
        "trace_steps_json": json.dumps(trace_steps or [], ensure_ascii=False),
        "used_knowledge_entry_ids_json": json.dumps(used_knowledge_entry_ids or [], ensure_ascii=False),
        "used_fact_tools_json": used_fact_tools or "",
        "copilot_context_json": json.dumps(copilot_context or {}, ensure_ascii=False),
        "created_at": _now(),
    }

    filepath = os.path.join(SNAPSHOTS_DIR, f"{message_id}.json")
    with _lock:
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(snapshot, f, ensure_ascii=False, indent=2)

    return snapshot


def get_snapshot(message_id: str) -> Optional[dict]:
    """根据 message_id 查询快照。"""
    filepath = os.path.join(SNAPSHOTS_DIR, f"{message_id}.json")
    if not os.path.exists(filepath):
        return None
    with open(filepath, "r", encoding="utf-8") as f:
        return json.load(f)


def generate_ids() -> tuple[str, str]:
    """生成 (request_id, message_id)。"""
    return _new_request_id(), _new_message_id()
