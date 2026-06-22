"""Eval replay management APIs."""

from __future__ import annotations

from flask import Blueprint, jsonify, request

from app.api.admin_auth import require_supervisor
from app.models.eval_tables import EvalCase, EvalFailure, EvalRepairTask, EvalRun
from app.services.eval_repair_task_service import task_to_dict
from app.services.eval_replay_service import (
    EvalReplayService,
    ensure_eval_tables,
    eval_case_to_dict,
    eval_failure_to_dict,
    eval_run_to_dict,
    get_run_detail,
)

eval_bp = Blueprint("eval", __name__, url_prefix="/api/eval")


@eval_bp.route("/cases", methods=["GET"])
def api_eval_cases():
    denied = require_supervisor()
    if denied:
        return denied
    ensure_eval_tables()
    limit = _limit(request.args.get("limit"), default=50)
    category = str(request.args.get("category") or "").strip()
    status = str(request.args.get("status") or "").strip()
    db = _session()
    try:
        query = db.query(EvalCase)
        if category:
            query = query.filter(EvalCase.category == category)
        if status:
            query = query.filter(EvalCase.status == status)
        rows = query.order_by(EvalCase.priority.desc(), EvalCase.id.desc()).limit(limit).all()
        return jsonify({"items": [eval_case_to_dict(row) for row in rows], "limit": limit})
    finally:
        db.close()


@eval_bp.route("/cases", methods=["POST"])
def api_eval_create_case():
    denied = require_supervisor()
    if denied:
        return denied
    data = request.get_json(silent=True) or {}
    if not (data.get("customer_message") or data.get("customer_message_sanitized") or data.get("message")):
        return jsonify({"error": "customer_message_required"}), 400
    item = EvalReplayService().create_case(data)
    return jsonify({"item": item}), 201


@eval_bp.route("/runs", methods=["POST"])
def api_eval_create_run():
    denied = require_supervisor()
    if denied:
        return denied
    data = request.get_json(silent=True) or {}
    limit = _limit(data.get("limit"), default=30)
    result = EvalReplayService().run_replay(
        limit=limit,
        category=str(data.get("category") or ""),
        run_type=str(data.get("run_type") or "manual"),
        apply=bool(data.get("apply", True)),
        config_snapshot={"api": True, "limit": limit, "category": data.get("category") or ""},
    )
    return jsonify(result), 201


@eval_bp.route("/runs", methods=["GET"])
def api_eval_runs():
    denied = require_supervisor()
    if denied:
        return denied
    ensure_eval_tables()
    limit = _limit(request.args.get("limit"), default=50)
    db = _session()
    try:
        rows = db.query(EvalRun).order_by(EvalRun.started_at.desc(), EvalRun.id.desc()).limit(limit).all()
        return jsonify({"items": [eval_run_to_dict(row) for row in rows], "limit": limit})
    finally:
        db.close()


@eval_bp.route("/runs/<run_uid>", methods=["GET"])
def api_eval_run_detail(run_uid: str):
    denied = require_supervisor()
    if denied:
        return denied
    detail = get_run_detail(run_uid)
    if not detail:
        return jsonify({"error": "not_found"}), 404
    return jsonify(detail)


@eval_bp.route("/failures", methods=["GET"])
def api_eval_failures():
    denied = require_supervisor()
    if denied:
        return denied
    ensure_eval_tables()
    limit = _limit(request.args.get("limit"), default=50)
    failure_type = str(request.args.get("failure_type") or "").strip()
    db = _session()
    try:
        query = db.query(EvalFailure)
        if failure_type:
            query = query.filter(EvalFailure.failure_type == failure_type)
        rows = query.order_by(EvalFailure.created_at.desc(), EvalFailure.id.desc()).limit(limit).all()
        return jsonify({"items": [eval_failure_to_dict(row) for row in rows], "limit": limit})
    finally:
        db.close()


@eval_bp.route("/repair-tasks", methods=["GET"])
def api_eval_repair_tasks():
    denied = require_supervisor()
    if denied:
        return denied
    ensure_eval_tables()
    limit = _limit(request.args.get("limit"), default=50)
    db = _session()
    try:
        rows = db.query(EvalRepairTask).order_by(EvalRepairTask.priority.desc(), EvalRepairTask.updated_at.desc()).limit(limit).all()
        return jsonify({"items": [task_to_dict(row) for row in rows], "limit": limit})
    finally:
        db.close()


def _limit(raw, *, default: int) -> int:
    try:
        value = int(raw or default)
    except (TypeError, ValueError):
        value = default
    return max(1, min(value, 200))


def _session():
    from app import db as db_module

    return db_module.SessionLocal()
