"""Regression retest workflow for knowledge gap tasks."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from app.services.eval_sanitizer_service import sanitize_obj, sanitize_text
from app.services.real_conversation_quality_bucket_service import AGENT_ERROR, CONTEXT_GAP, KNOWLEDGE_GAP, SAFE_HANDOFF
from app.services.real_conversation_replay_service import RealConversationReplayService, ReplayOptions


def _utc_now() -> datetime:
    return datetime.utcnow()


def _utc_now_iso() -> str:
    return _utc_now().isoformat()


def _new_retest_run_uid(task_uid: str) -> str:
    suffix = uuid.uuid4().hex[:10]
    safe_task = sanitize_text(task_uid).replace("kgap_", "")[:18] or "task"
    return f"kgap_retest_{safe_task}_{suffix}"


def _pass_rate(passed: int, total: int) -> float:
    return round(passed / total, 4) if total else 0


def _append_verification_history(metadata: dict[str, Any], entry: dict[str, Any]) -> dict[str, Any]:
    history = metadata.get("verification_history")
    if not isinstance(history, list):
        history = []
    history.append(sanitize_obj(entry))
    metadata["verification_history"] = history
    return metadata


def _task_turn_uids(db, task) -> list[str]:
    from app.models.eval_tables import KnowledgeGapTaskSample

    turn_uids = [sanitize_text(value) for value in task.get_related_turn_uids() if sanitize_text(value)]
    if turn_uids:
        return turn_uids
    rows = (
        db.query(KnowledgeGapTaskSample.turn_uid)
        .filter(KnowledgeGapTaskSample.task_uid == task.task_uid)
        .order_by(KnowledgeGapTaskSample.id.asc())
        .all()
    )
    return [sanitize_text(row[0]) for row in rows if sanitize_text(row[0])]


def _task_case_uids(db, task) -> list[str]:
    from app.models.eval_tables import KnowledgeGapTaskSample

    case_uids = [sanitize_text(value) for value in task.get_related_case_uids() if sanitize_text(value)]
    if case_uids:
        return case_uids
    rows = (
        db.query(KnowledgeGapTaskSample.case_uid)
        .filter(KnowledgeGapTaskSample.task_uid == task.task_uid)
        .order_by(KnowledgeGapTaskSample.id.asc())
        .all()
    )
    result: list[str] = []
    seen = set()
    for row in rows:
        value = sanitize_text(row[0])
        if value and value not in seen:
            seen.add(value)
            result.append(value)
    return result


def _counts_by(values: list[str]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for value in values:
        key = sanitize_text(value) or "unknown"
        counts[key] = counts.get(key, 0) + 1
    return counts


def _summary_from_run(db, verification_run_uid: str, *, checked_turn_uids: list[str], started_at: str, finished_at: str) -> dict[str, Any]:
    from app.models.eval_tables import EvalFailure, EvalTrace
    from app.services.real_conversation_quality_bucket_service import bucket_from_trace

    traces = (
        db.query(EvalTrace)
        .filter(EvalTrace.run_uid == verification_run_uid)
        .order_by(EvalTrace.turn_index.asc(), EvalTrace.id.asc())
        .all()
    )
    failures = (
        db.query(EvalFailure)
        .filter(EvalFailure.run_uid == verification_run_uid)
        .order_by(EvalFailure.id.asc())
        .all()
    )
    failures_by_turn: dict[str, list[Any]] = {}
    for failure in failures:
        failures_by_turn.setdefault(failure.turn_uid, []).append(failure)

    buckets: list[str] = []
    for trace in traces:
        bucket = bucket_from_trace(trace, failures_by_turn.get(trace.turn_uid, []))
        buckets.append(sanitize_text(bucket.get("quality_bucket")) or "unknown")

    failure_types = [sanitize_text(row.failure_type) for row in failures if sanitize_text(row.failure_type)]
    total_turns = len(traces)
    failed_turns = sum(1 for trace in traces if not trace.passed)
    passed_turns = total_turns - failed_turns
    bucket_counts = _counts_by(buckets)
    return sanitize_obj({
        "total_turns": total_turns,
        "passed_turns": passed_turns,
        "failed_turns": failed_turns,
        "pass_rate": _pass_rate(passed_turns, total_turns),
        "remaining_failure_types": sorted(set(failure_types)),
        "remaining_quality_buckets": sorted(set(bucket for bucket in buckets if bucket != "auto_sendable")),
        "auto_sendable_count": bucket_counts.get("auto_sendable", 0),
        "safe_handoff_count": bucket_counts.get(SAFE_HANDOFF, 0),
        "knowledge_gap_count": bucket_counts.get(KNOWLEDGE_GAP, 0),
        "agent_error_count": bucket_counts.get(AGENT_ERROR, 0),
        "context_gap_count": bucket_counts.get(CONTEXT_GAP, 0),
        "checked_turn_uids": checked_turn_uids,
        "started_at": started_at,
        "finished_at": finished_at,
    })


def _is_fully_verified(summary: dict[str, Any], metadata: dict[str, Any]) -> bool:
    if int(summary.get("total_turns") or 0) <= 0:
        return False
    if int(summary.get("failed_turns") or 0) != 0:
        return False
    if int(summary.get("agent_error_count") or 0) != 0:
        return False
    if int(summary.get("knowledge_gap_count") or 0) != 0:
        return False
    if int(summary.get("context_gap_count") or 0) != 0:
        return False
    if int(summary.get("safe_handoff_count") or 0) != 0:
        return sanitize_text(metadata.get("review_decision")) == "needs_more_samples"
    return True


class KnowledgeGapRetestService:
    def preview_task(self, task_uid: str, *, max_turns: int | None = None) -> dict[str, Any]:
        from app.db import SessionLocal
        from app.models.eval_tables import KnowledgeGapTask

        db = SessionLocal()
        try:
            task = db.query(KnowledgeGapTask).filter(KnowledgeGapTask.task_uid == sanitize_text(task_uid)).one_or_none()
            if task is None:
                raise ValueError("knowledge gap task not found")
            turn_uids = _task_turn_uids(db, task)
            case_uids = _task_case_uids(db, task)
            if max_turns:
                turn_uids = turn_uids[:max(1, int(max_turns))]
            return sanitize_obj({
                "dry_run": True,
                "task_uid": task.task_uid,
                "case_uids": case_uids,
                "checked_turn_uids": turn_uids,
                "sample_count": len(turn_uids),
                "verification_status": (task.get_metadata() or {}).get("verification_status", "not_verified"),
                "error": "" if turn_uids else "context_missing",
            })
        finally:
            db.close()

    def retest_task(
        self,
        task_uid: str,
        *,
        apply: bool = True,
        verified_by: str = "",
        max_turns: int | None = None,
    ) -> dict[str, Any]:
        if not apply:
            return self.preview_task(task_uid, max_turns=max_turns)

        from app.db import SessionLocal
        from app.models.eval_tables import KnowledgeGapTask
        from app.services.knowledge_gap_task_service import _metadata_with_status_history

        db = SessionLocal()
        started_at = _utc_now_iso()
        task = None
        try:
            task = db.query(KnowledgeGapTask).filter(KnowledgeGapTask.task_uid == sanitize_text(task_uid)).one_or_none()
            if task is None:
                raise ValueError("knowledge gap task not found")
            turn_uids = _task_turn_uids(db, task)
            case_uids = _task_case_uids(db, task)
            if max_turns:
                turn_uids = turn_uids[:max(1, int(max_turns))]
            if not turn_uids:
                metadata = task.get_metadata()
                finished_at = _utc_now_iso()
                summary = sanitize_obj({
                    "total_turns": 0,
                    "passed_turns": 0,
                    "failed_turns": 0,
                    "pass_rate": 0,
                    "remaining_failure_types": ["context_missing"],
                    "remaining_quality_buckets": [],
                    "checked_turn_uids": [],
                    "started_at": started_at,
                    "finished_at": finished_at,
                    "error_message": "knowledge gap task has no related turns",
                })
                metadata.update({
                    "verification_status": "error",
                    "verification_summary": summary,
                    "last_verified_at": finished_at,
                    "verified_by": sanitize_text(verified_by),
                })
                _append_verification_history(metadata, {
                    "verification_status": "error",
                    "summary": summary,
                    "verified_by": sanitize_text(verified_by),
                    "created_at": finished_at,
                })
                task.set_metadata(sanitize_obj(metadata))
                db.commit()
                return sanitize_obj({"ok": False, "task": task.to_dict(), "verification": summary})

            verification_run_uid = _new_retest_run_uid(task.task_uid)
            metadata = _metadata_with_status_history(
                task,
                status="retest_running",
                changed_by=sanitize_text(verified_by),
                note="knowledge gap retest started",
            )
            metadata.update({
                "verification_status": "retest_running",
                "verification_run_uid": verification_run_uid,
                "verified_by": sanitize_text(verified_by),
                "last_verified_at": started_at,
            })
            task.set_metadata(sanitize_obj(metadata))
            db.commit()

            RealConversationReplayService().replay_cases(ReplayOptions(
                run_uid=verification_run_uid,
                case_uids=case_uids,
                turn_uids=turn_uids,
                source_type="knowledge_gap_retest",
                run_metadata={
                    "knowledge_gap_retest": {
                        "source_task_uid": task.task_uid,
                        "source_gap_category": task.gap_type,
                        "source_required_evidence_type": task.missing_evidence_type,
                        "source_run_uid": sanitize_text(metadata.get("source_run_uid")),
                        "checked_turn_uids": turn_uids,
                    }
                },
            ))

            db.expire_all()
            finished_at = _utc_now_iso()
            summary = _summary_from_run(
                db,
                verification_run_uid,
                checked_turn_uids=turn_uids,
                started_at=started_at,
                finished_at=finished_at,
            )
            task = db.query(KnowledgeGapTask).filter(KnowledgeGapTask.task_uid == sanitize_text(task_uid)).one()
            metadata = task.get_metadata()
            passed = _is_fully_verified(summary, metadata)
            status = "verified" if passed else "waiting_data"
            verification_status = "verified_passed" if passed else "retest_failed"
            metadata = _metadata_with_status_history(
                task,
                status=status,
                changed_by=sanitize_text(verified_by),
                note=verification_status,
            )
            metadata.update({
                "verification_status": verification_status,
                "verification_run_uid": verification_run_uid,
                "verification_summary": summary,
                "last_verified_at": finished_at,
                "verified_by": sanitize_text(verified_by),
            })
            _append_verification_history(metadata, {
                "verification_status": verification_status,
                "verification_run_uid": verification_run_uid,
                "summary": summary,
                "verified_by": sanitize_text(verified_by),
                "created_at": finished_at,
            })
            task.status = status
            task.set_metadata(sanitize_obj(metadata))
            db.commit()
            return sanitize_obj({
                "ok": passed,
                "task": task.to_dict(),
                "verification": {
                    "verification_status": verification_status,
                    "verification_run_uid": verification_run_uid,
                    "summary": summary,
                },
            })
        except Exception as exc:
            db.rollback()
            if task is not None:
                task = db.query(KnowledgeGapTask).filter(KnowledgeGapTask.id == task.id).one_or_none()
                if task is not None:
                    finished_at = _utc_now_iso()
                    summary = sanitize_obj({
                        "total_turns": 0,
                        "passed_turns": 0,
                        "failed_turns": 0,
                        "pass_rate": 0,
                        "remaining_failure_types": [],
                        "remaining_quality_buckets": [],
                        "checked_turn_uids": _task_turn_uids(db, task),
                        "started_at": started_at,
                        "finished_at": finished_at,
                        "error_message": sanitize_text(str(exc)),
                    })
                    metadata = task.get_metadata()
                    metadata.update({
                        "verification_status": "error",
                        "verification_summary": summary,
                        "last_verified_at": finished_at,
                        "verified_by": sanitize_text(verified_by),
                    })
                    _append_verification_history(metadata, {
                        "verification_status": "error",
                        "summary": summary,
                        "verified_by": sanitize_text(verified_by),
                        "created_at": finished_at,
                    })
                    task.set_metadata(sanitize_obj(metadata))
                    db.commit()
                    return sanitize_obj({"ok": False, "task": task.to_dict(), "verification": summary})
            raise
        finally:
            db.close()
