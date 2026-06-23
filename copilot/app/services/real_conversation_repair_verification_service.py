"""Regression verification for real conversation repair tasks."""

import uuid
from datetime import datetime
from typing import Any

from app.services.eval_sanitizer_service import sanitize_obj, sanitize_text
from app.services.real_conversation_replay_service import RealConversationReplayService, ReplayOptions


def _utc_now() -> datetime:
    return datetime.utcnow()


def _utc_now_iso() -> str:
    return _utc_now().isoformat()


def _new_verification_run_uid(task_uid: str) -> str:
    suffix = uuid.uuid4().hex[:10]
    safe_task = sanitize_text(task_uid).replace("repair_", "")[:18] or "task"
    return f"verify_{safe_task}_{suffix}"


def _pass_rate(passed: int, total: int) -> float:
    return round(passed / total, 4) if total else 0


def _summary_from_replay(
    replay: dict[str, Any],
    *,
    checked_turn_uids: list[str],
    started_at: str,
    finished_at: str,
    remaining_failure_types: list[str],
) -> dict[str, Any]:
    total_turns = int(replay.get("turns") or replay.get("total_turns") or 0)
    failed_turns = int(replay.get("failed") or replay.get("failed_turns") or 0)
    passed_turns = int(replay.get("passed") or replay.get("passed_turns") or 0)
    return sanitize_obj({
        "total_turns": total_turns,
        "passed_turns": passed_turns,
        "failed_turns": failed_turns,
        "pass_rate": _pass_rate(passed_turns, total_turns),
        "remaining_failure_types": remaining_failure_types,
        "checked_turn_uids": checked_turn_uids,
        "started_at": started_at,
        "finished_at": finished_at,
    })


class RealConversationRepairVerificationService:
    def preview_task(self, task_uid: str) -> dict[str, Any]:
        from app.db import SessionLocal
        from app.models.eval_tables import EvalRepairTask

        db = SessionLocal()
        try:
            task = db.query(EvalRepairTask).filter(EvalRepairTask.task_uid == sanitize_text(task_uid)).one_or_none()
            if task is None:
                raise ValueError("repair task not found")
            return sanitize_obj({
                "dry_run": True,
                "task_uid": task.task_uid,
                "run_uid": task.run_uid,
                "case_uids": task.get_related_case_uids(),
                "checked_turn_uids": task.get_related_turn_uids(),
                "verification_status": task.verification_status,
            })
        finally:
            db.close()

    def verify_task(self, task_uid: str, *, verified_by: str = "") -> dict[str, Any]:
        from app.db import SessionLocal
        from app.models.eval_tables import EvalFailure, EvalRepairTask

        db = SessionLocal()
        started_at = _utc_now_iso()
        task = None
        try:
            task = db.query(EvalRepairTask).filter(EvalRepairTask.task_uid == sanitize_text(task_uid)).one_or_none()
            if task is None:
                raise ValueError("repair task not found")
            case_uids = task.get_related_case_uids()
            turn_uids = task.get_related_turn_uids()
            verification_run_uid = _new_verification_run_uid(task.task_uid)

            task.verification_status = "running"
            task.verification_run_uid = verification_run_uid
            task.verified_by = sanitize_text(verified_by)
            task.set_verification_summary({
                "checked_turn_uids": turn_uids,
                "started_at": started_at,
            })
            db.commit()

            replay = RealConversationReplayService().replay_cases(ReplayOptions(
                run_uid=verification_run_uid,
                case_uids=case_uids,
                turn_uids=turn_uids,
                source_type="real_conversation_verification",
                run_metadata={
                    "verification": {
                        "task_uid": task.task_uid,
                        "original_run_uid": task.run_uid,
                        "checked_turn_uids": turn_uids,
                    }
                },
            ))
            db.expire_all()
            failures = (
                db.query(EvalFailure)
                .filter(EvalFailure.run_uid == verification_run_uid)
                .order_by(EvalFailure.id.asc())
                .all()
            )
            remaining_failure_types = sorted({sanitize_text(row.failure_type) for row in failures if row.failure_type})
            finished_at = _utc_now_iso()
            summary = _summary_from_replay(
                replay,
                checked_turn_uids=turn_uids,
                started_at=started_at,
                finished_at=finished_at,
                remaining_failure_types=remaining_failure_types,
            )
            task = db.query(EvalRepairTask).filter(EvalRepairTask.task_uid == sanitize_text(task_uid)).one()
            task.last_verified_at = _utc_now()
            task.verification_run_uid = verification_run_uid
            task.verified_by = sanitize_text(verified_by)
            task.set_verification_summary(summary)
            if int(summary["failed_turns"]) == 0:
                task.verification_status = "verified_passed"
                task.status = "resolved"
            else:
                task.verification_status = "retest_failed"
                task.status = "in_progress"
            db.commit()
            return sanitize_obj({
                "ok": True,
                "task": task.to_dict(),
                "verification": summary,
            })
        except Exception as exc:
            db.rollback()
            if task is not None:
                task = db.query(EvalRepairTask).filter(EvalRepairTask.id == task.id).one_or_none()
                if task is not None:
                    finished_at = _utc_now_iso()
                    summary = sanitize_obj({
                        "total_turns": 0,
                        "passed_turns": 0,
                        "failed_turns": 0,
                        "pass_rate": 0,
                        "remaining_failure_types": [],
                        "checked_turn_uids": task.get_related_turn_uids(),
                        "started_at": started_at,
                        "finished_at": finished_at,
                        "error_message": sanitize_text(str(exc)),
                    })
                    task.last_verified_at = _utc_now()
                    task.verification_status = "error"
                    task.verified_by = sanitize_text(verified_by)
                    task.set_verification_summary(summary)
                    db.commit()
                    return sanitize_obj({
                        "ok": False,
                        "task": task.to_dict(),
                        "verification": summary,
                    })
            raise
        finally:
            db.close()
