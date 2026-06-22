"""Generate aggregate repair tasks from eval failures."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Any

from app.models.eval_tables import EvalFailure, EvalRepairTask
from app.services.eval_sanitizer_service import sanitize_text


OWNER_BY_AREA = {
    "query_understanding": "agent",
    "evidence_rerank": "rag",
    "product_card_data": "data",
    "media_asset_data": "data",
    "tool_policy": "agent",
    "final_answer_auditor": "quality",
    "semantic_compiler": "quality",
    "generic_service_rule": "agent",
    "frontend_display": "frontend",
}


def generate_repair_tasks(run_uid: str | None = None) -> list[dict[str, Any]]:
    db = _session()
    try:
        query = db.query(EvalFailure).filter(EvalFailure.status == "open")
        if run_uid:
            query = query.filter(EvalFailure.run_uid == run_uid)
        failures = query.all()
        grouped: dict[tuple[str, str], list[EvalFailure]] = {}
        for failure in failures:
            key = (failure.failure_type or "unknown", failure.suggested_fix_area or "unknown")
            grouped.setdefault(key, []).append(failure)

        tasks = []
        for (failure_type, area), rows in grouped.items():
            task = _upsert_task(db, failure_type, area, rows)
            for row in rows:
                row.repair_task_uid = task.repair_task_uid
                row.updated_at = datetime.utcnow()
            tasks.append(task_to_dict(task))
        db.commit()
        return tasks
    finally:
        db.close()


def task_to_dict(task: EvalRepairTask) -> dict[str, Any]:
    return {
        "id": task.id,
        "repair_task_uid": task.repair_task_uid,
        "title": task.title,
        "description": task.description,
        "failure_count": task.failure_count,
        "suggested_owner": task.suggested_owner,
        "suggested_files": _loads(task.suggested_files_json, []),
        "status": task.status,
        "priority": task.priority,
        "created_at": task.created_at.isoformat() if task.created_at else "",
        "updated_at": task.updated_at.isoformat() if task.updated_at else "",
    }


def _upsert_task(db, failure_type: str, area: str, rows: list[EvalFailure]) -> EvalRepairTask:
    uid = _task_uid(failure_type, area)
    task = db.query(EvalRepairTask).filter(EvalRepairTask.repair_task_uid == uid).first()
    files = _suggested_files(rows)
    if task is None:
        task = EvalRepairTask(repair_task_uid=uid, created_at=datetime.utcnow())
        db.add(task)
    task.title = f"Fix {failure_type} in {area}"
    task.description = sanitize_text(
        f"{len(rows)} eval failure(s) share failure_type={failure_type}, suggested_fix_area={area}. "
        f"Inspect sanitized eval_failures and add/adjust regression coverage before changing production logic.",
        max_len=1000,
    )
    task.failure_count = len(rows)
    task.suggested_owner = OWNER_BY_AREA.get(area, "agent")
    task.suggested_files_json = json.dumps(files, ensure_ascii=False, sort_keys=True)
    task.status = task.status or "open"
    task.priority = min(row_priority(rows), 100)
    task.updated_at = datetime.utcnow()
    return task


def row_priority(rows: list[EvalFailure]) -> int:
    severity_rank = {"high": 90, "medium": 60, "low": 30}
    return max(severity_rank.get(row.severity, 50) for row in rows) if rows else 50


def _task_uid(failure_type: str, area: str) -> str:
    digest = hashlib.sha256(f"{failure_type}:{area}".encode("utf-8")).hexdigest()[:12]
    return f"repair_{digest}"


def _suggested_files(rows: list[EvalFailure]) -> list[str]:
    files: list[str] = []
    for row in rows:
        actual = _loads(row.actual_json, {})
        for file in actual.get("suggested_files") or []:
            if file and file not in files:
                files.append(file)
    return files[:8]


def _loads(raw: str, default):
    try:
        parsed = json.loads(raw or "")
    except (TypeError, json.JSONDecodeError):
        return default
    return parsed if parsed is not None else default


def _session():
    from app import db as db_module

    return db_module.SessionLocal()
