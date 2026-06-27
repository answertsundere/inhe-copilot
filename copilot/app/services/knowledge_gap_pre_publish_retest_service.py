"""Pre-publish retest workflow for knowledge gap publish queue items.

The service replays only the queue item's related real-conversation samples.
It can approve the queue item for a later handoff, but it never writes formal
product, knowledge, media, policy, or rule tables.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from app.services.eval_sanitizer_service import sanitize_obj, sanitize_text
from app.services.knowledge_gap_retest_service import _summary_from_run, _task_case_uids, _task_turn_uids
from app.services.real_conversation_quality_bucket_service import AGENT_ERROR, CONTEXT_GAP, KNOWLEDGE_GAP, SAFE_HANDOFF
from app.services.real_conversation_replay_service import RealConversationReplayService, ReplayOptions


RETEST_ALLOWED_STATUSES = {"queued", "exported"}


def _now() -> datetime:
    return datetime.utcnow()


def _now_iso() -> str:
    return _now().isoformat()


def _new_pre_publish_run_uid(queue_uid: str) -> str:
    safe_queue = sanitize_text(queue_uid).replace("kgpub_", "")[:18] or "queue"
    return f"kgap_prepub_{safe_queue}_{uuid.uuid4().hex[:10]}"


def _count_by(values: list[str]) -> dict[str, int]:
    result: dict[str, int] = {}
    for value in values:
        key = sanitize_text(value) or "unknown"
        result[key] = result.get(key, 0) + 1
    return result


def _quality_bucket_counts(db, run_uid: str) -> dict[str, int]:
    from app.models.eval_tables import EvalFailure, EvalTrace
    from app.services.real_conversation_quality_bucket_service import bucket_from_trace

    failures = db.query(EvalFailure).filter(EvalFailure.run_uid == run_uid).all()
    failures_by_turn: dict[str, list[Any]] = {}
    for failure in failures:
        failures_by_turn.setdefault(failure.turn_uid, []).append(failure)
    buckets: list[str] = []
    traces = db.query(EvalTrace).filter(EvalTrace.run_uid == run_uid).all()
    for trace in traces:
        bucket = bucket_from_trace(trace, failures_by_turn.get(trace.turn_uid, []))
        buckets.append(sanitize_text(bucket.get("quality_bucket")) or "unknown")
    return _count_by(buckets)


def _block_reasons_from_summary(summary: dict[str, Any]) -> list[str]:
    reasons: list[str] = []
    if int(summary.get("total_turns") or 0) <= 0:
        reasons.append("no related samples were replayed")
    if int(summary.get("failed_turns") or 0) != 0:
        reasons.append("retest still has failed turns")
    if int(summary.get("agent_error_count") or 0) != 0:
        reasons.append("retest still has agent_error turns")
    if int(summary.get("knowledge_gap_count") or 0) != 0:
        reasons.append("retest still has knowledge_gap turns")
    if int(summary.get("context_gap_count") or 0) != 0:
        reasons.append("retest still has context_gap turns")
    if int(summary.get("safe_handoff_count") or 0) != 0:
        reasons.append("retest still has safe_handoff turns")
    if "rag_miss" in set(summary.get("remaining_failure_types") or []):
        reasons.append("retest still has rag_miss failures")
    return reasons


def _retest_passed(summary: dict[str, Any]) -> bool:
    return not _block_reasons_from_summary(summary)


class KnowledgeGapPrePublishRetestService:
    def preview(self, queue_uid: str, *, max_turns: int | None = None) -> dict[str, Any]:
        from app.db import SessionLocal
        from app.models.eval_tables import KnowledgeGapPublishQueue, KnowledgeGapTask, KnowledgeGapTaskSample

        db = SessionLocal()
        try:
            item = self._load_retestable_queue_item(db, queue_uid)
            task = db.query(KnowledgeGapTask).filter(KnowledgeGapTask.task_uid == item.task_uid).one_or_none()
            if task is None:
                raise ValueError("knowledge gap task not found for publish queue item")
            turn_uids = _task_turn_uids(db, task)
            case_uids = _task_case_uids(db, task)
            if max_turns:
                turn_uids = turn_uids[:max(1, int(max_turns))]
            if not turn_uids:
                raise ValueError("related real-conversation samples are required before publish approval")

            samples = (
                db.query(KnowledgeGapTaskSample)
                .filter(KnowledgeGapTaskSample.task_uid == task.task_uid)
                .filter(KnowledgeGapTaskSample.turn_uid.in_(turn_uids))
                .order_by(KnowledgeGapTaskSample.id.asc())
                .all()
            )
            return sanitize_obj({
                "dry_run": True,
                "queue_uid": item.queue_uid,
                "task_uid": task.task_uid,
                "case_uids": case_uids,
                "checked_turn_uids": turn_uids,
                "sample_count": len(turn_uids),
                "source_run_uid": item.source_run_uid or (task.get_metadata() or {}).get("source_run_uid", ""),
                "approval_status": item.approval_status,
                "pre_publish_retest_status": item.pre_publish_retest_status,
                "samples": [
                    {
                        "case_uid": sample.case_uid,
                        "turn_uid": sample.turn_uid,
                        "failure_type": sample.failure_type,
                        "query_fact_type": sample.query_fact_type,
                    }
                    for sample in samples
                ],
            })
        finally:
            db.close()

    def run(self, queue_uid: str, *, max_turns: int | None = None, triggered_by: str = "") -> dict[str, Any]:
        from app.db import SessionLocal
        from app.models.eval_tables import KnowledgeGapPublishQueue, KnowledgeGapTask

        db = SessionLocal()
        started_at = _now_iso()
        item = None
        try:
            item = self._load_retestable_queue_item(db, queue_uid)
            task = db.query(KnowledgeGapTask).filter(KnowledgeGapTask.task_uid == item.task_uid).one_or_none()
            if task is None:
                raise ValueError("knowledge gap task not found for publish queue item")
            turn_uids = _task_turn_uids(db, task)
            case_uids = _task_case_uids(db, task)
            if max_turns:
                turn_uids = turn_uids[:max(1, int(max_turns))]
            if not turn_uids:
                raise ValueError("related real-conversation samples are required before publish approval")

            verification_run_uid = _new_pre_publish_run_uid(item.queue_uid)
            item.pre_publish_retest_status = "running"
            item.pre_publish_retest_run_uid = verification_run_uid
            item.approved_to_publish = False
            item.approval_status = "retest_required"
            item.set_pre_publish_block_reasons([])
            item.set_pre_publish_retest_summary({
                "started_at": started_at,
                "checked_turn_uids": turn_uids,
            })
            db.commit()

            RealConversationReplayService().replay_cases(ReplayOptions(
                run_uid=verification_run_uid,
                case_uids=case_uids,
                turn_uids=turn_uids,
                source_type="knowledge_gap_pre_publish_retest",
                run_metadata={
                    "knowledge_gap_pre_publish_retest": {
                        "source_queue_uid": item.queue_uid,
                        "source_task_uid": task.task_uid,
                        "source_draft_uid": item.draft_uid,
                        "source_payload_fingerprint": item.payload_fingerprint,
                        "checked_turn_uids": turn_uids,
                    }
                },
            ))

            db.expire_all()
            finished_at = _now_iso()
            summary = _summary_from_run(
                db,
                verification_run_uid,
                checked_turn_uids=turn_uids,
                started_at=started_at,
                finished_at=finished_at,
            )
            summary["quality_bucket_counts"] = _quality_bucket_counts(db, verification_run_uid)
            item = (
                db.query(KnowledgeGapPublishQueue)
                .filter(KnowledgeGapPublishQueue.queue_uid == sanitize_text(queue_uid))
                .one()
            )
            passed = _retest_passed(summary)
            block_reasons = [] if passed else _block_reasons_from_summary(summary)
            item.pre_publish_retest_status = "passed" if passed else "failed"
            item.set_pre_publish_retest_summary(summary)
            item.set_pre_publish_block_reasons(block_reasons)
            item.approved_to_publish = bool(passed)
            item.approval_status = "approved_to_publish" if passed else "retest_required"
            if passed:
                item.approved_to_publish_at = _now()
                item.approved_to_publish_by = sanitize_text(triggered_by)
                item.locked_payload_fingerprint = item.payload_fingerprint
            else:
                item.approved_to_publish_at = None
                item.approved_to_publish_by = ""
                item.locked_payload_fingerprint = ""
            metadata = item.get_metadata()
            metadata.setdefault("pre_publish_retest_history", [])
            metadata["pre_publish_retest_history"].append(sanitize_obj({
                "status": item.pre_publish_retest_status,
                "approval_status": item.approval_status,
                "verification_run_uid": verification_run_uid,
                "triggered_by": sanitize_text(triggered_by),
                "summary": summary,
                "created_at": finished_at,
            }))
            item.set_metadata(metadata)
            db.commit()
            return sanitize_obj({
                "ok": passed,
                "queue_item": item.to_dict(),
                "summary": summary,
                "block_reasons": block_reasons,
            })
        except Exception as exc:
            db.rollback()
            if item is not None:
                item = (
                    db.query(KnowledgeGapPublishQueue)
                    .filter(KnowledgeGapPublishQueue.queue_uid == sanitize_text(queue_uid))
                    .one_or_none()
                )
                if item is not None:
                    finished_at = _now_iso()
                    summary = sanitize_obj({
                        "total_turns": 0,
                        "passed_turns": 0,
                        "failed_turns": 0,
                        "pass_rate": 0,
                        "remaining_failure_types": [],
                        "remaining_quality_buckets": [],
                        "checked_turn_uids": [],
                        "started_at": started_at,
                        "finished_at": finished_at,
                        "error_message": sanitize_text(str(exc)),
                    })
                    item.pre_publish_retest_status = "failed"
                    item.set_pre_publish_retest_summary(summary)
                    item.set_pre_publish_block_reasons(["pre-publish retest failed with an exception"])
                    item.approved_to_publish = False
                    item.approval_status = "retest_required"
                    item.approved_to_publish_at = None
                    item.approved_to_publish_by = ""
                    item.locked_payload_fingerprint = ""
                    db.commit()
                    return sanitize_obj({
                        "ok": False,
                        "queue_item": item.to_dict(),
                        "summary": summary,
                        "block_reasons": item.get_pre_publish_block_reasons(),
                    })
            raise
        finally:
            db.close()

    def _load_retestable_queue_item(self, db, queue_uid: str):
        from app.models.eval_tables import KnowledgeGapPublishQueue

        item = (
            db.query(KnowledgeGapPublishQueue)
            .filter(KnowledgeGapPublishQueue.queue_uid == sanitize_text(queue_uid))
            .one_or_none()
        )
        if item is None:
            raise ValueError("publish queue item not found")
        if item.status not in RETEST_ALLOWED_STATUSES:
            raise ValueError(f"{item.status} queue items cannot run pre-publish retest")
        if item.publish_dry_run_status != "passed" or not item.ready_for_publish:
            raise ValueError("publish dry-run must pass before pre-publish retest")
        return item
