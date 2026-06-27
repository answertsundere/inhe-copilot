"""Evaluation replay APIs."""

from flask import Blueprint, jsonify, request

from app.api.admin_auth import current_user_name, require_supervisor
from app.services.eval_sanitizer_service import sanitize_obj, sanitize_text


eval_bp = Blueprint("eval", __name__)


REVIEW_DECISION_FIX_AREAS = {
    "correct": "",
    "incorrect": "manual_triage",
    "needs_knowledge": "knowledge_rag",
    "needs_rule": "agent_rules",
    "needs_media": "media_pipeline",
    "needs_human_policy": "human_policy_risk_boundary",
}

REPAIR_TASK_STATUSES = {"open", "in_progress", "resolved", "ignored"}
REPAIR_TASK_PRIORITIES = {"low", "medium", "high"}
KNOWLEDGE_GAP_STATUSES = {
    "open",
    "triaged",
    "assigned",
    "draft_ready",
    "waiting_data",
    "rejected",
    "resolved_pending_retest",
    "verified",
    "closed",
    "drafting",
    "pending_review",
    "approved",
    "queued_for_publish",
    "published",
}
KNOWLEDGE_GAP_PRIORITIES = {"low", "medium", "high"}
KNOWLEDGE_GAP_REVIEW_DECISIONS = {
    "fill_product_field",
    "upload_media_asset",
    "write_aftersales_policy",
    "write_promotion_policy",
    "fix_context_extraction",
    "improve_evidence_mapping",
    "ignore_false_positive",
    "needs_more_samples",
}


def _knowledge_gap_status_allowed(task, status: str, payload: dict | None = None) -> tuple[bool, str]:
    if status == "verified":
        return False, "knowledge gap tasks can only become verified after retest passes"
    if status == "closed":
        metadata = task.get_metadata() if task is not None else {}
        review_decision = sanitize_text(metadata.get("review_decision") or (payload or {}).get("review_decision"))
        verification_status = sanitize_text(metadata.get("verification_status"))
        note = sanitize_text((payload or {}).get("review_note") or (payload or {}).get("note") or metadata.get("review_note"))
        if verification_status == "verified_passed" or review_decision == "ignore_false_positive":
            return True, ""
        if not note:
            return False, "closing an unverified knowledge gap requires review_note"
    return True, ""


def _db():
    from app.db import SessionLocal
    return SessionLocal()


def _truthy(value) -> bool:
    if value is True:
        return True
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y"}
    return False


def _count_by(rows, attr: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        key = str(getattr(row, attr, "") or "unknown")
        counts[key] = counts.get(key, 0) + 1
    return counts


def _failures_by_turn(failures) -> dict[str, list]:
    grouped: dict[str, list] = {}
    for failure in failures:
        grouped.setdefault(getattr(failure, "turn_uid", ""), []).append(failure)
    return grouped


def _trace_quality_bucket(trace, failures_by_turn: dict[str, list]) -> dict:
    from app.services.real_conversation_quality_bucket_service import bucket_from_trace

    return bucket_from_trace(trace, failures_by_turn.get(trace.turn_uid, []))


def _trace_to_dict_with_quality_bucket(trace, failures_by_turn: dict[str, list]) -> dict:
    data = trace.to_dict()
    bucket = _trace_quality_bucket(trace, failures_by_turn)
    data.update(bucket)
    return data


def _build_run_summary(run, traces, failures, reviews) -> dict:
    scored_traces = [
        row for row in traces
        if (row.get_turn_understanding() or {}).get("should_score") is not False
    ]
    total_turns = len(scored_traces) or int(getattr(run, "total_turns", 0) or 0)
    passed_turns = sum(1 for row in scored_traces if row.passed)
    if not scored_traces:
        passed_turns = int(getattr(run, "passed_turns", 0) or 0)
    latency_values = [int(row.latency_ms or 0) for row in scored_traces if row.latency_ms is not None]
    avg_latency_ms = round(sum(latency_values) / len(latency_values), 2) if latency_values else 0
    failures_by_turn = _failures_by_turn(failures)
    bucket_counts = {
        "auto_sendable": 0,
        "safe_handoff": 0,
        "context_gap": 0,
        "knowledge_gap": 0,
        "agent_error": 0,
        "unscored_or_noise": 0,
    }
    quality_denominator = 0
    quality_passed = 0
    for trace in traces:
        bucket = _trace_quality_bucket(trace, failures_by_turn)
        bucket_name = str(bucket.get("quality_bucket") or "agent_error")
        if bucket_name not in bucket_counts:
            bucket_name = "agent_error"
        bucket_counts[bucket_name] += 1
        if bucket.get("should_count_in_quality_rate") is not False:
            quality_denominator += 1
            if trace.passed:
                quality_passed += 1
    def _rate(count: int) -> float:
        return round(count / quality_denominator, 4) if quality_denominator else 0
    return {
        "failure_counts_by_type": _count_by(failures, "failure_type"),
        "review_counts_by_decision": _count_by(reviews, "decision"),
        "avg_latency_ms": avg_latency_ms,
        "requires_review_count": sum(1 for row in scored_traces if row.requires_human_review),
        "pass_rate": round(quality_passed / quality_denominator, 4) if quality_denominator else 0,
        "legacy_scored_pass_rate": round(passed_turns / total_turns, 4) if total_turns else 0,
        "auto_sendable_turns": bucket_counts["auto_sendable"],
        "safe_handoff_turns": bucket_counts["safe_handoff"],
        "context_gap_turns": bucket_counts["context_gap"],
        "knowledge_gap_turns": bucket_counts["knowledge_gap"],
        "agent_error_turns": bucket_counts["agent_error"],
        "unscored_turns": bucket_counts["unscored_or_noise"],
        "auto_sendable_rate": _rate(bucket_counts["auto_sendable"]),
        "safe_handoff_rate": _rate(bucket_counts["safe_handoff"]),
        "context_gap_rate": round(bucket_counts["context_gap"] / len(traces), 4) if traces else 0,
        "knowledge_gap_rate": _rate(bucket_counts["knowledge_gap"]),
        "agent_error_rate": _rate(bucket_counts["agent_error"]),
        "quality_denominator": quality_denominator,
        "agent_accuracy_denominator": quality_denominator,
        "agent_accuracy_passed": quality_passed,
    }


def _repair_task_query(db):
    from app.models.eval_tables import EvalRepairTask

    query = db.query(EvalRepairTask).order_by(EvalRepairTask.updated_at.desc(), EvalRepairTask.id.desc())
    status = sanitize_text(request.args.get("status"))
    fix_area = sanitize_text(request.args.get("suggested_fix_area"))
    owner = sanitize_text(request.args.get("suggested_owner"))
    run_uid = sanitize_text(request.args.get("run_uid"))
    if status:
        query = query.filter(EvalRepairTask.status == status)
    if fix_area:
        query = query.filter(EvalRepairTask.suggested_fix_area == fix_area)
    if owner:
        query = query.filter(EvalRepairTask.suggested_owner == owner)
    if run_uid:
        query = query.filter(EvalRepairTask.run_uid == run_uid)
    return query


@eval_bp.route("/api/eval/real-conversation/runs", methods=["GET"])
@eval_bp.route("/api/kb/eval/real-conversation/runs", methods=["GET"])
@require_supervisor
def list_real_conversation_runs():
    from app.models.eval_tables import EvalRun

    limit = min(max(int(request.args.get("limit", 20)), 1), 100)
    db = _db()
    try:
        rows = (
            db.query(EvalRun)
            .filter(EvalRun.source_type == "real_conversation")
            .order_by(EvalRun.created_at.desc())
            .limit(limit)
            .all()
        )
        return jsonify({"items": [sanitize_obj(row.to_dict()) for row in rows]})
    finally:
        db.close()


@eval_bp.route("/api/eval/real-conversation/runs/<run_uid>", methods=["GET"])
@eval_bp.route("/api/kb/eval/real-conversation/runs/<run_uid>", methods=["GET"])
@require_supervisor
def get_real_conversation_run(run_uid):
    from app.models.eval_tables import EvalFailure, EvalReview, EvalRun, EvalTrace

    db = _db()
    try:
        run = db.query(EvalRun).filter(EvalRun.run_uid == run_uid).one_or_none()
        if run is None:
            return jsonify({"error": "run not found"}), 404
        traces = (
            db.query(EvalTrace)
            .filter(EvalTrace.run_uid == run_uid)
            .order_by(EvalTrace.case_uid.asc(), EvalTrace.turn_index.asc())
            .all()
        )
        failures = (
            db.query(EvalFailure)
            .filter(EvalFailure.run_uid == run_uid)
            .order_by(EvalFailure.id.asc())
            .all()
        )
        reviews = (
            db.query(EvalReview)
            .filter(EvalReview.run_uid == run_uid)
            .order_by(EvalReview.id.asc())
            .all()
        )
        failures_by_turn = _failures_by_turn(failures)
        return jsonify(sanitize_obj({
            "run": run.to_dict(),
            "turns": [_trace_to_dict_with_quality_bucket(row, failures_by_turn) for row in traces],
            "failures": [row.to_dict() for row in failures],
            "reviews": [row.to_dict() for row in reviews],
            "summary": _build_run_summary(run, traces, failures, reviews),
        }))
    finally:
        db.close()


@eval_bp.route("/api/eval/real-conversation/runs/<run_uid>/quality-tasks", methods=["GET"])
@eval_bp.route("/api/kb/eval/real-conversation/runs/<run_uid>/quality-tasks", methods=["GET"])
@require_supervisor
def get_real_conversation_quality_tasks(run_uid):
    from app.services.real_conversation_quality_task_service import RealConversationQualityTaskService

    db = _db()
    try:
        result = RealConversationQualityTaskService().build_for_run(db, sanitize_text(run_uid))
        return jsonify(sanitize_obj(result))
    except ValueError as exc:
        return jsonify({"error": sanitize_text(str(exc))}), 404
    finally:
        db.close()


@eval_bp.route("/api/eval/real-conversation/runs/<run_uid>/quality-tasks/generate", methods=["POST"])
@eval_bp.route("/api/kb/eval/real-conversation/runs/<run_uid>/quality-tasks/generate", methods=["POST"])
@require_supervisor
def generate_real_conversation_quality_tasks(run_uid):
    from app.services.real_conversation_quality_task_service import RealConversationQualityTaskService

    db = _db()
    try:
        result = RealConversationQualityTaskService().generate_for_run(
            db,
            sanitize_text(run_uid),
            created_by=sanitize_text(current_user_name()),
        )
        return jsonify(sanitize_obj({"ok": True, **result.to_dict()})), 201
    except ValueError as exc:
        db.rollback()
        return jsonify({"error": sanitize_text(str(exc))}), 404
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


@eval_bp.route("/api/eval/real-conversation/turns/<turn_uid>", methods=["GET"])
@eval_bp.route("/api/kb/eval/real-conversation/turns/<turn_uid>", methods=["GET"])
@require_supervisor
def get_real_conversation_turn(turn_uid):
    from app.models.eval_tables import EvalConversationTurn, EvalFailure, EvalTrace

    db = _db()
    try:
        turn = db.query(EvalConversationTurn).filter(EvalConversationTurn.turn_uid == turn_uid).one_or_none()
        if turn is None:
            return jsonify({"error": "turn not found"}), 404
        traces = (
            db.query(EvalTrace)
            .filter(EvalTrace.turn_uid == turn_uid)
            .order_by(EvalTrace.created_at.desc())
            .all()
        )
        failures = (
            db.query(EvalFailure)
            .filter(EvalFailure.turn_uid == turn_uid)
            .order_by(EvalFailure.id.asc())
            .all()
        )
        failures_by_turn = _failures_by_turn(failures)
        return jsonify(sanitize_obj({
            "turn": turn.to_dict(),
            "traces": [_trace_to_dict_with_quality_bucket(row, failures_by_turn) for row in traces],
            "failures": [row.to_dict() for row in failures],
        }))
    finally:
        db.close()


@eval_bp.route("/api/eval/real-conversation/reviews", methods=["POST"])
@eval_bp.route("/api/kb/eval/real-conversation/reviews", methods=["POST"])
@require_supervisor
def create_real_conversation_review():
    from app.models.eval_tables import EvalReview

    data = request.get_json(silent=True) or {}
    run_uid = sanitize_text(data.get("run_uid"))
    case_uid = sanitize_text(data.get("case_uid"))
    turn_uid = sanitize_text(data.get("turn_uid"))
    decision = sanitize_text(data.get("decision"))
    if not run_uid or not case_uid or not turn_uid or decision not in REVIEW_DECISION_FIX_AREAS:
        return jsonify({"error": "invalid review payload"}), 400

    db = _db()
    try:
        row = EvalReview(
            run_uid=run_uid,
            case_uid=case_uid,
            turn_uid=turn_uid,
            decision=decision,
            reason=sanitize_text(data.get("reason")),
            suggested_fix_area=REVIEW_DECISION_FIX_AREAS[decision],
            reviewer=sanitize_text(current_user_name()),
        )
        row.set_metadata(sanitize_obj(data.get("metadata") or {}))
        db.add(row)
        db.commit()
        return jsonify({"ok": True, "review": row.to_dict()}), 201
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


@eval_bp.route("/api/eval/repair-tasks", methods=["GET"])
@eval_bp.route("/api/kb/eval/repair-tasks", methods=["GET"])
@require_supervisor
def list_repair_tasks():
    db = _db()
    try:
        limit = min(max(int(request.args.get("limit", 50)), 1), 200)
        rows = _repair_task_query(db).limit(limit).all()
        return jsonify({"items": [sanitize_obj(row.to_dict()) for row in rows]})
    finally:
        db.close()


@eval_bp.route("/api/eval/trends", methods=["GET"])
@eval_bp.route("/api/kb/eval/trends", methods=["GET"])
@require_supervisor
def get_eval_trends():
    from app.services.real_conversation_daily_replay_service import build_real_conversation_trends

    db = _db()
    try:
        trends = build_real_conversation_trends(
            db,
            days=int(request.args.get("days", 7)),
            source=sanitize_text(request.args.get("source") or "real_conversation"),
            suggested_fix_area=sanitize_text(request.args.get("suggested_fix_area")),
            suggested_owner=sanitize_text(request.args.get("suggested_owner")),
        )
        return jsonify(sanitize_obj(trends))
    finally:
        db.close()


@eval_bp.route("/api/eval/knowledge-gaps", methods=["GET"])
@eval_bp.route("/api/kb/eval/knowledge-gaps", methods=["GET"])
def list_knowledge_gaps():
    from app.services.knowledge_gap_task_service import KnowledgeGapTaskService

    db = _db()
    try:
        result = KnowledgeGapTaskService().list_tasks(
            db,
            filters={
                "status": request.args.get("status") or "",
                "run_uid": request.args.get("run_uid") or "",
                "gap_type": request.args.get("gap_type") or "",
                "gap_category": request.args.get("gap_category") or "",
                "query_fact_type": request.args.get("query_fact_type") or "",
                "required_evidence_type": request.args.get("required_evidence_type") or "",
                "missing_evidence_type": request.args.get("missing_evidence_type") or "",
                "target_system": request.args.get("target_system") or "",
                "recommended_action": request.args.get("recommended_action") or "",
                "suggested_fix_area": request.args.get("suggested_fix_area") or "",
                "suggested_owner": request.args.get("suggested_owner") or "",
                "risk_level": request.args.get("risk_level") or "",
                "product": request.args.get("product") or "",
            },
            limit=int(request.args.get("limit", 100)),
        )
        return jsonify(sanitize_obj(result))
    finally:
        db.close()


@eval_bp.route("/api/eval/knowledge-gaps/generate", methods=["POST"])
@eval_bp.route("/api/kb/eval/knowledge-gaps/generate", methods=["POST"])
@require_supervisor
def generate_knowledge_gaps():
    from app.services.knowledge_gap_task_service import KnowledgeGapTaskService

    data = request.get_json(silent=True) or {}
    db = _db()
    try:
        result = KnowledgeGapTaskService().generate_for_run(
            db,
            run_uid=sanitize_text(data.get("run_uid")),
            created_by=sanitize_text(current_user_name()),
        )
        return jsonify(sanitize_obj({"ok": True, **result.to_dict()})), 201
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


@eval_bp.route("/api/eval/knowledge-gaps/<task_uid>", methods=["GET"])
@eval_bp.route("/api/kb/eval/knowledge-gaps/<task_uid>", methods=["GET"])
def get_knowledge_gap(task_uid):
    from app.services.knowledge_gap_task_service import KnowledgeGapTaskService

    db = _db()
    try:
        detail = KnowledgeGapTaskService().get_task_detail(db, sanitize_text(task_uid))
        if detail is None:
            return jsonify({"error": "knowledge gap task not found"}), 404
        return jsonify(sanitize_obj(detail))
    finally:
        db.close()


@eval_bp.route("/api/eval/knowledge-gaps/<task_uid>", methods=["PATCH"])
@eval_bp.route("/api/kb/eval/knowledge-gaps/<task_uid>", methods=["PATCH"])
@require_supervisor
def update_knowledge_gap(task_uid):
    from app.services.knowledge_gap_task_service import KnowledgeGapTaskService

    data = request.get_json(silent=True) or {}
    status = sanitize_text(data.get("status"))
    priority = sanitize_text(data.get("priority"))
    if status and status not in KNOWLEDGE_GAP_STATUSES:
        return jsonify({"error": "invalid knowledge gap status"}), 400
    if priority and priority not in KNOWLEDGE_GAP_PRIORITIES:
        return jsonify({"error": "invalid knowledge gap priority"}), 400
    db = _db()
    try:
        if status:
            from app.models.eval_tables import KnowledgeGapTask

            existing = db.query(KnowledgeGapTask).filter(KnowledgeGapTask.task_uid == sanitize_text(task_uid)).one_or_none()
            allowed, reason = _knowledge_gap_status_allowed(existing, status, data)
            if not allowed:
                return jsonify({"error": reason}), 400
        task = KnowledgeGapTaskService().update_task(db, sanitize_text(task_uid), data)
        if task is None:
            return jsonify({"error": "knowledge gap task not found"}), 404
        return jsonify(sanitize_obj({"ok": True, "task": task}))
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


@eval_bp.route("/api/eval/knowledge-gaps/<task_uid>/triage", methods=["PATCH"])
@eval_bp.route("/api/kb/eval/knowledge-gaps/<task_uid>/triage", methods=["PATCH"])
@require_supervisor
def triage_knowledge_gap(task_uid):
    from app.services.knowledge_gap_task_service import KnowledgeGapTaskService

    data = request.get_json(silent=True) or {}
    decision = sanitize_text(data.get("review_decision"))
    status = sanitize_text(data.get("status"))
    priority = sanitize_text(data.get("priority"))
    if decision not in KNOWLEDGE_GAP_REVIEW_DECISIONS:
        return jsonify({"error": "invalid knowledge gap review decision"}), 400
    if status and status not in KNOWLEDGE_GAP_STATUSES:
        return jsonify({"error": "invalid knowledge gap status"}), 400
    if priority and priority not in KNOWLEDGE_GAP_PRIORITIES:
        return jsonify({"error": "invalid knowledge gap priority"}), 400
    db = _db()
    try:
        task = KnowledgeGapTaskService().triage_task(
            db,
            sanitize_text(task_uid),
            data,
            reviewer=sanitize_text(current_user_name()),
        )
        if task is None:
            return jsonify({"error": "knowledge gap task not found"}), 404
        return jsonify(sanitize_obj({"ok": True, "task": task}))
    except ValueError as exc:
        db.rollback()
        return jsonify({"error": sanitize_text(str(exc))}), 400
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


@eval_bp.route("/api/eval/knowledge-gaps/<task_uid>/status", methods=["PATCH"])
@eval_bp.route("/api/kb/eval/knowledge-gaps/<task_uid>/status", methods=["PATCH"])
@require_supervisor
def update_knowledge_gap_status(task_uid):
    from app.services.knowledge_gap_task_service import KnowledgeGapTaskService

    data = request.get_json(silent=True) or {}
    status = sanitize_text(data.get("status"))
    priority = sanitize_text(data.get("priority"))
    if status not in KNOWLEDGE_GAP_STATUSES:
        return jsonify({"error": "invalid knowledge gap status"}), 400
    if priority and priority not in KNOWLEDGE_GAP_PRIORITIES:
        return jsonify({"error": "invalid knowledge gap priority"}), 400
    db = _db()
    try:
        from app.models.eval_tables import KnowledgeGapTask

        existing = db.query(KnowledgeGapTask).filter(KnowledgeGapTask.task_uid == sanitize_text(task_uid)).one_or_none()
        allowed, reason = _knowledge_gap_status_allowed(existing, status, data)
        if not allowed:
            return jsonify({"error": reason}), 400
        task = KnowledgeGapTaskService().update_status(
            db,
            sanitize_text(task_uid),
            data,
            changed_by=sanitize_text(current_user_name()),
        )
        if task is None:
            return jsonify({"error": "knowledge gap task not found"}), 404
        return jsonify(sanitize_obj({"ok": True, "task": task}))
    except ValueError as exc:
        db.rollback()
        return jsonify({"error": sanitize_text(str(exc))}), 400
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


@eval_bp.route("/api/eval/knowledge-gaps/<task_uid>/draft", methods=["POST"])
@eval_bp.route("/api/kb/eval/knowledge-gaps/<task_uid>/draft", methods=["POST"])
@require_supervisor
def draft_knowledge_gap(task_uid):
    from app.services.knowledge_gap_draft_service import KnowledgeGapDraftService

    data = request.get_json(silent=True) or {}
    db = _db()
    try:
        draft = KnowledgeGapDraftService().generate_draft(
            db,
            sanitize_text(task_uid),
            generated_by="ai",
            force_regenerate=data.get("force_regenerate") is True,
        )
        if draft is None:
            return jsonify({"error": "knowledge gap task not found"}), 404
        return jsonify(sanitize_obj({"ok": True, "draft": draft})), 201
    except ValueError as exc:
        db.rollback()
        return jsonify({"error": sanitize_text(str(exc))}), 400
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


@eval_bp.route("/api/eval/knowledge-gaps/<task_uid>/draft/mark-ready", methods=["POST"])
@eval_bp.route("/api/kb/eval/knowledge-gaps/<task_uid>/draft/mark-ready", methods=["POST"])
@require_supervisor
def mark_ready_knowledge_gap_draft(task_uid):
    from app.services.knowledge_gap_draft_service import KnowledgeGapDraftService

    db = _db()
    try:
        result = KnowledgeGapDraftService().mark_ready(
            db,
            sanitize_text(task_uid),
            reviewer=sanitize_text(current_user_name()),
        )
        if result is None:
            return jsonify({"error": "knowledge gap task not found"}), 404
        return jsonify(sanitize_obj({"ok": True, **result}))
    except ValueError as exc:
        db.rollback()
        return jsonify({"error": sanitize_text(str(exc))}), 400
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


@eval_bp.route("/api/eval/knowledge-gaps/<task_uid>/draft/<draft_uid>/review", methods=["POST"])
@eval_bp.route("/api/kb/eval/knowledge-gaps/<task_uid>/draft/<draft_uid>/review", methods=["POST"])
@require_supervisor
def review_knowledge_gap_draft(task_uid, draft_uid):
    from app.services.knowledge_gap_publish_queue_service import KnowledgeGapPublishQueueService

    data = request.get_json(silent=True) or {}
    db = _db()
    try:
        result = KnowledgeGapPublishQueueService().review_draft(
            db,
            task_uid=sanitize_text(task_uid),
            draft_uid=sanitize_text(draft_uid),
            payload=data,
            reviewer=sanitize_text(current_user_name()),
        )
        if result is None:
            return jsonify({"error": "knowledge gap task not found"}), 404
        return jsonify(sanitize_obj({"ok": True, **result}))
    except ValueError as exc:
        db.rollback()
        return jsonify({"error": sanitize_text(str(exc))}), 400
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


@eval_bp.route("/api/eval/knowledge-gap-publish-queue", methods=["GET"])
@eval_bp.route("/api/kb/eval/knowledge-gap-publish-queue", methods=["GET"])
@require_supervisor
def list_knowledge_gap_publish_queue():
    from app.services.knowledge_gap_publish_queue_service import KnowledgeGapPublishQueueService

    db = _db()
    try:
        result = KnowledgeGapPublishQueueService().list_queue(
            db,
            filters={
                "status": sanitize_text(request.args.get("status")),
                "publish_target": sanitize_text(request.args.get("publish_target")),
                "risk_level": sanitize_text(request.args.get("risk_level")),
                "reviewer": sanitize_text(request.args.get("reviewer")),
                "task_uid": sanitize_text(request.args.get("task_uid")),
                "include_superseded": sanitize_text(request.args.get("include_superseded")),
            },
            limit=int(request.args.get("limit") or 100),
        )
        return jsonify(sanitize_obj(result))
    finally:
        db.close()


@eval_bp.route("/api/eval/knowledge-gap-publish-queue/<queue_uid>/export-preview", methods=["POST"])
@eval_bp.route("/api/kb/eval/knowledge-gap-publish-queue/<queue_uid>/export-preview", methods=["POST"])
@require_supervisor
def preview_knowledge_gap_publish_export(queue_uid):
    from app.services.knowledge_gap_publish_queue_service import KnowledgeGapPublishQueueService

    db = _db()
    try:
        result = KnowledgeGapPublishQueueService().export_preview(db, sanitize_text(queue_uid))
        if result is None:
            return jsonify({"error": "publish queue item not found"}), 404
        return jsonify(sanitize_obj({"ok": True, **result}))
    finally:
        db.close()


@eval_bp.route("/api/eval/knowledge-gap-publish-queue/<queue_uid>/dry-run", methods=["POST"])
@eval_bp.route("/api/kb/eval/knowledge-gap-publish-queue/<queue_uid>/dry-run", methods=["POST"])
@require_supervisor
def dry_run_knowledge_gap_publish_queue(queue_uid):
    from app.services.knowledge_gap_publish_adapter_service import PublishAdapterDryRunService

    db = _db()
    try:
        result = PublishAdapterDryRunService().dry_run(
            db,
            sanitize_text(queue_uid),
            operator=sanitize_text(current_user_name()),
        )
        if result is None:
            return jsonify({"error": "publish queue item not found"}), 404
        return jsonify(sanitize_obj({"ok": True, **result}))
    except ValueError as exc:
        db.rollback()
        return jsonify({"error": sanitize_text(str(exc))}), 400
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


@eval_bp.route("/api/eval/knowledge-gap-publish-queue/<queue_uid>/pre-publish-retest-preview", methods=["POST"])
@eval_bp.route("/api/kb/eval/knowledge-gap-publish-queue/<queue_uid>/pre-publish-retest-preview", methods=["POST"])
@require_supervisor
def preview_knowledge_gap_publish_retest(queue_uid):
    from app.services.knowledge_gap_pre_publish_retest_service import KnowledgeGapPrePublishRetestService

    data = request.get_json(silent=True) or {}
    try:
        result = KnowledgeGapPrePublishRetestService().preview(
            sanitize_text(queue_uid),
            max_turns=int(data.get("max_turns")) if data.get("max_turns") else None,
        )
        return jsonify(sanitize_obj({"ok": True, **result}))
    except ValueError as exc:
        message = sanitize_text(str(exc))
        return jsonify({"error": message}), 404 if "not found" in message else 400


@eval_bp.route("/api/eval/knowledge-gap-publish-queue/<queue_uid>/pre-publish-retest", methods=["POST"])
@eval_bp.route("/api/kb/eval/knowledge-gap-publish-queue/<queue_uid>/pre-publish-retest", methods=["POST"])
@require_supervisor
def run_knowledge_gap_publish_retest(queue_uid):
    from app.services.knowledge_gap_pre_publish_retest_service import KnowledgeGapPrePublishRetestService

    data = request.get_json(silent=True) or {}
    try:
        result = KnowledgeGapPrePublishRetestService().run(
            sanitize_text(queue_uid),
            max_turns=int(data.get("max_turns")) if data.get("max_turns") else None,
            triggered_by=sanitize_text(data.get("triggered_by") or current_user_name()),
        )
        return jsonify(sanitize_obj({"ok": True, **result}))
    except ValueError as exc:
        message = sanitize_text(str(exc))
        return jsonify({"error": message}), 404 if "not found" in message else 400


@eval_bp.route("/api/eval/knowledge-gap-publish-queue/<queue_uid>", methods=["PATCH"])
@eval_bp.route("/api/kb/eval/knowledge-gap-publish-queue/<queue_uid>", methods=["PATCH"])
@require_supervisor
def update_knowledge_gap_publish_queue(queue_uid):
    from app.services.knowledge_gap_publish_queue_service import KnowledgeGapPublishQueueService

    data = request.get_json(silent=True) or {}
    db = _db()
    try:
        result = KnowledgeGapPublishQueueService().update_queue_item(
            db,
            sanitize_text(queue_uid),
            data,
            operator=sanitize_text(current_user_name()),
        )
        if result is None:
            return jsonify({"error": "publish queue item not found"}), 404
        return jsonify(sanitize_obj({"ok": True, "queue_item": result}))
    except ValueError as exc:
        db.rollback()
        return jsonify({"error": sanitize_text(str(exc))}), 400
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


@eval_bp.route("/api/eval/knowledge-gaps/<task_uid>/retest-preview", methods=["POST"])
@eval_bp.route("/api/kb/eval/knowledge-gaps/<task_uid>/retest-preview", methods=["POST"])
@require_supervisor
def preview_knowledge_gap_retest(task_uid):
    from app.services.knowledge_gap_retest_service import KnowledgeGapRetestService

    data = request.get_json(silent=True) or {}
    try:
        result = KnowledgeGapRetestService().preview_task(
            sanitize_text(task_uid),
            max_turns=int(data.get("max_turns")) if data.get("max_turns") else None,
        )
        return jsonify(sanitize_obj({"ok": True, **result}))
    except ValueError as exc:
        return jsonify({"error": sanitize_text(str(exc))}), 404


@eval_bp.route("/api/eval/knowledge-gaps/<task_uid>/retest", methods=["POST"])
@eval_bp.route("/api/kb/eval/knowledge-gaps/<task_uid>/retest", methods=["POST"])
@require_supervisor
def retest_knowledge_gap(task_uid):
    from app.services.knowledge_gap_retest_service import KnowledgeGapRetestService

    data = request.get_json(silent=True) or {}
    apply_retest = data.get("apply") is not False
    try:
        result = KnowledgeGapRetestService().retest_task(
            sanitize_text(task_uid),
            apply=apply_retest,
            verified_by=sanitize_text(data.get("verified_by") or current_user_name()),
            max_turns=int(data.get("max_turns")) if data.get("max_turns") else None,
        )
        return jsonify(sanitize_obj(result))
    except ValueError as exc:
        return jsonify({"error": sanitize_text(str(exc))}), 404


@eval_bp.route("/api/eval/knowledge-gaps/<task_uid>/approve", methods=["POST"])
@eval_bp.route("/api/kb/eval/knowledge-gaps/<task_uid>/approve", methods=["POST"])
@require_supervisor
def approve_knowledge_gap(task_uid):
    from app.services.knowledge_gap_draft_service import KnowledgeGapDraftService

    db = _db()
    try:
        result = KnowledgeGapDraftService().approve(
            db,
            sanitize_text(task_uid),
            reviewer=sanitize_text(current_user_name()),
        )
        if result is None:
            return jsonify({"error": "knowledge gap task not found"}), 404
        return jsonify(sanitize_obj({"ok": True, **result}))
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


@eval_bp.route("/api/eval/knowledge-gaps/<task_uid>/reject", methods=["POST"])
@eval_bp.route("/api/kb/eval/knowledge-gaps/<task_uid>/reject", methods=["POST"])
@require_supervisor
def reject_knowledge_gap(task_uid):
    from app.services.knowledge_gap_draft_service import KnowledgeGapDraftService

    data = request.get_json(silent=True) or {}
    db = _db()
    try:
        result = KnowledgeGapDraftService().reject(
            db,
            sanitize_text(task_uid),
            reviewer=sanitize_text(current_user_name()),
            reason=sanitize_text(data.get("reason")),
        )
        if result is None:
            return jsonify({"error": "knowledge gap task not found"}), 404
        return jsonify(sanitize_obj({"ok": True, **result}))
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


@eval_bp.route("/api/eval/knowledge-gaps/<task_uid>/verify", methods=["POST"])
@eval_bp.route("/api/kb/eval/knowledge-gaps/<task_uid>/verify", methods=["POST"])
@require_supervisor
def verify_knowledge_gap(task_uid):
    from app.models.eval_tables import KnowledgeGapTask

    db = _db()
    try:
        task = db.query(KnowledgeGapTask).filter(KnowledgeGapTask.task_uid == sanitize_text(task_uid)).one_or_none()
        if task is None:
            return jsonify({"error": "knowledge gap task not found"}), 404
        metadata = task.get_metadata()
        metadata["verification"] = {
            "verified_by": sanitize_text(current_user_name()),
            "verification_mode": "manual_staging_check",
            "note": "Knowledge gap task was manually confirmed after staging review; no automatic replay was executed and task status was not verified.",
        }
        if task.status not in {"resolved_pending_retest", "verified"}:
            task.status = "resolved_pending_retest"
        task.set_metadata(sanitize_obj(metadata))
        db.commit()
        return jsonify(sanitize_obj({"ok": True, "task": task.to_dict()}))
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


@eval_bp.route("/api/eval/repair-tasks/generate", methods=["POST"])
@eval_bp.route("/api/kb/eval/repair-tasks/generate", methods=["POST"])
@require_supervisor
def generate_repair_tasks():
    from app.services.real_conversation_repair_task_service import RealConversationRepairTaskService

    data = request.get_json(silent=True) or {}
    db = _db()
    try:
        result = RealConversationRepairTaskService().generate_for_run(
            db,
            run_uid=sanitize_text(data.get("run_uid")),
            created_by=sanitize_text(current_user_name()),
        )
        return jsonify(sanitize_obj({"ok": True, **result.to_dict()})), 201
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


@eval_bp.route("/api/eval/repair-tasks/<task_uid>/verify", methods=["POST"])
@eval_bp.route("/api/kb/eval/repair-tasks/<task_uid>/verify", methods=["POST"])
@require_supervisor
def verify_repair_task(task_uid):
    from app.services.real_conversation_repair_verification_service import RealConversationRepairVerificationService

    data = request.get_json(silent=True) or {}
    dry_run = _truthy(data.get("dry_run")) or data.get("apply") is False
    service = RealConversationRepairVerificationService()
    try:
        if dry_run:
            return jsonify(sanitize_obj(service.preview_task(task_uid)))
        result = service.verify_task(task_uid, verified_by=sanitize_text(current_user_name()))
        return jsonify(sanitize_obj(result))
    except ValueError as exc:
        return jsonify({"error": sanitize_text(str(exc))}), 404


@eval_bp.route("/api/eval/repair-tasks/<task_uid>", methods=["GET"])
@eval_bp.route("/api/kb/eval/repair-tasks/<task_uid>", methods=["GET"])
@require_supervisor
def get_repair_task(task_uid):
    from app.models.eval_tables import EvalFailure, EvalRepairTask, EvalTrace

    db = _db()
    try:
        task = (
            db.query(EvalRepairTask)
            .filter(EvalRepairTask.task_uid == sanitize_text(task_uid))
            .one_or_none()
        )
        if task is None:
            return jsonify({"error": "repair task not found"}), 404
        turn_uids = task.get_related_turn_uids()
        failures = (
            db.query(EvalFailure)
            .filter(EvalFailure.run_uid == task.run_uid, EvalFailure.turn_uid.in_(turn_uids))
            .order_by(EvalFailure.id.asc())
            .all()
            if turn_uids else []
        )
        traces = (
            db.query(EvalTrace)
            .filter(EvalTrace.run_uid == task.run_uid, EvalTrace.turn_uid.in_(turn_uids))
            .order_by(EvalTrace.case_uid.asc(), EvalTrace.turn_index.asc())
            .all()
            if turn_uids else []
        )
        return jsonify(sanitize_obj({
            "task": task.to_dict(),
            "failures": [row.to_dict() for row in failures],
            "traces": [row.to_dict() for row in traces],
        }))
    finally:
        db.close()


@eval_bp.route("/api/eval/repair-tasks/<task_uid>", methods=["PATCH"])
@eval_bp.route("/api/kb/eval/repair-tasks/<task_uid>", methods=["PATCH"])
@require_supervisor
def update_repair_task(task_uid):
    from app.models.eval_tables import EvalRepairTask
    from app.services.real_conversation_repair_verification_service import RealConversationRepairVerificationService

    data = request.get_json(silent=True) or {}
    verify_after_resolve = _truthy(data.get("verify_after_resolve"))
    db = _db()
    try:
        task = (
            db.query(EvalRepairTask)
            .filter(EvalRepairTask.task_uid == sanitize_text(task_uid))
            .one_or_none()
        )
        if task is None:
            return jsonify({"error": "repair task not found"}), 404
        status = sanitize_text(data.get("status"))
        priority = sanitize_text(data.get("priority"))
        if status:
            if status not in REPAIR_TASK_STATUSES:
                return jsonify({"error": "invalid repair task status"}), 400
            task.status = status
        if priority:
            if priority not in REPAIR_TASK_PRIORITIES:
                return jsonify({"error": "invalid repair task priority"}), 400
            task.priority = priority
        if "assigned_to" in data:
            task.assigned_to = sanitize_text(data.get("assigned_to"))
        if "resolution_note" in data:
            task.resolution_note = sanitize_text(data.get("resolution_note"))
        db.commit()
        if status == "resolved" and verify_after_resolve:
            result = RealConversationRepairVerificationService().verify_task(
                task.task_uid,
                verified_by=sanitize_text(current_user_name()),
            )
            return jsonify(sanitize_obj({"ok": True, **result}))
        return jsonify(sanitize_obj({"ok": True, "task": task.to_dict()}))
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
