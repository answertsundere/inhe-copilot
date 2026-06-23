"""Evaluation replay APIs."""

from flask import Blueprint, jsonify, request

from app.api.admin_auth import current_user_name, require_supervisor
from app.services.eval_sanitizer_service import sanitize_obj, sanitize_text


eval_bp = Blueprint("eval", __name__)


def _db():
    from app.db import SessionLocal
    return SessionLocal()


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
    from app.models.eval_tables import EvalFailure, EvalRun, EvalTrace

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
        return jsonify(sanitize_obj({
            "run": run.to_dict(),
            "turns": [row.to_dict() for row in traces],
            "failures": [row.to_dict() for row in failures],
        }))
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
        return jsonify(sanitize_obj({
            "turn": turn.to_dict(),
            "traces": [row.to_dict() for row in traces],
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
    if not run_uid or not case_uid or not turn_uid or decision not in {"correct", "incorrect", "needs_review"}:
        return jsonify({"error": "invalid review payload"}), 400

    db = _db()
    try:
        row = EvalReview(
            run_uid=run_uid,
            case_uid=case_uid,
            turn_uid=turn_uid,
            decision=decision,
            reason=sanitize_text(data.get("reason")),
            reviewer=current_user_name(),
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
