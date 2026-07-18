"""Supervisor staging endpoints for material-governance review batches."""

from __future__ import annotations

import os

from flask import Blueprint, jsonify, request

from app.api.admin_auth import current_user_name, require_reviewer, require_supervisor
from app.services.material_review_batch_service import MaterialReviewBatchError, MaterialReviewStagingStore


material_review_bp = Blueprint("material_review", __name__, url_prefix="/api/kb/material-review")


def _store() -> MaterialReviewStagingStore:
    path = os.environ.get("COPILOT_MATERIAL_REVIEW_STAGING_DB", "").strip()
    if not path:
        raise MaterialReviewBatchError("material_review_staging_not_configured")
    return MaterialReviewStagingStore(path)


@material_review_bp.route("/batches", methods=["GET"])
@require_reviewer
def list_material_review_batches():
    try:
        return jsonify({"batches": _store().list_batches(), "formal_kb_writes": 0})
    except MaterialReviewBatchError as exc:
        return jsonify({"error": str(exc)}), 503


@material_review_bp.route("/batches/<batch_uid>/decision", methods=["POST"])
@require_supervisor
def decide_material_review_batch(batch_uid: str):
    payload = request.get_json(silent=True) or {}
    try:
        result = _store().decide(
            batch_uid=batch_uid,
            action=str(payload.get("action") or ""),
            reviewer_uid=current_user_name(),
            expected_version=int(payload.get("expected_version")),
        )
        return jsonify(result)
    except (MaterialReviewBatchError, TypeError, ValueError) as exc:
        return jsonify({"error": str(exc)}), 409
