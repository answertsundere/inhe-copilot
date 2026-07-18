"""Authenticated supervisor workbench API for privacy-safe Gold claim labels."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from flask import Blueprint, jsonify, request

from app.api.admin_auth import current_principal, has_any_role, require_reviewer
from app.services.real_accuracy_gold_set_service import validate_gold_dataset
from app.services.real_accuracy_label_service import (
    LabelConflictError,
    LabelValidationError,
    RealAccuracyLabelStore,
    reviewer_actor_hash,
)


real_accuracy_label_bp = Blueprint("real_accuracy_labels", __name__, url_prefix="/api/kb/real-accuracy")


def _dataset_path() -> Path | None:
    value = os.environ.get("COPILOT_REAL_ACCURACY_GOLD_SET_PATH", "").strip()
    return Path(value).expanduser() if value else None


def _load_dataset() -> tuple[dict[str, Any] | None, tuple[dict[str, Any], int] | None]:
    path = _dataset_path()
    if not path or not path.is_file():
        return None, (jsonify({"error": "gold_set_not_configured"}), 503)
    try:
        dataset = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None, (jsonify({"error": "gold_set_unreadable"}), 503)
    findings = validate_gold_dataset(dataset)
    if findings or (dataset.get("privacy") or {}).get("privacy_scan_status") != "passed":
        return None, (jsonify({"error": "gold_set_privacy_validation_failed", "reason_codes": sorted(set(findings))}), 422)
    return dataset, None


def _public_case(case: dict[str, Any], label: dict[str, Any] | None) -> dict[str, Any]:
    return {
        "case_uid": case.get("case_uid"),
        "classification": case.get("classification"),
        "customer_message": case.get("customer_message"),
        "conversation": case.get("conversation"),
        "query_class": case.get("query_class"),
        "risk_level": case.get("risk_level"),
        "sidecar_present": case.get("sidecar_present"),
        "reference_label": case.get("reference_label"),
        "privacy_review_required": bool((case.get("notes") or {}).get("privacy_review_required")),
        "label": label,
    }


def _validate_target_turns(case: dict[str, Any], target_turn_uids: Any, review_status: str) -> list[str]:
    if target_turn_uids is None:
        target_turn_uids = []
    if not isinstance(target_turn_uids, list):
        raise LabelValidationError("target_turn_uids_list_required")
    normalized = [str(item).strip() for item in target_turn_uids if str(item).strip()]
    turns_by_uid = {
        str(turn.get("turn_uid") or ""): turn
        for turn in (case.get("conversation") or {}).get("turns") or []
    }
    if review_status in {"reviewed", "approved"} and not normalized:
        raise LabelValidationError("target_buyer_turn_required")
    if any(uid not in turns_by_uid for uid in normalized):
        raise LabelValidationError("target_turn_not_in_case")
    if any(turns_by_uid[uid].get("speaker_role") != "BUYER" for uid in normalized):
        raise LabelValidationError("target_turn_must_be_buyer")
    return sorted(normalized, key=lambda uid: int(turns_by_uid[uid].get("turn_index") or 0))


@real_accuracy_label_bp.get("/cases")
@require_reviewer
def list_cases():
    dataset, error = _load_dataset()
    if error:
        return error
    assert dataset is not None
    store = RealAccuracyLabelStore()
    labels = {item["case_uid"]: item for item in store.list_for_dataset(str(dataset.get("dataset_version") or ""))}
    status = str(request.args.get("status") or "").strip()
    rows = [_public_case(case, labels.get(str(case.get("case_uid") or ""))) for case in dataset.get("cases") or []]
    if status:
        rows = [item for item in rows if item.get("classification") == status]
    return jsonify({
        "dataset_id": dataset.get("dataset_id"),
        "dataset_version": dataset.get("dataset_version"),
        "privacy_scan_status": (dataset.get("privacy") or {}).get("privacy_scan_status"),
        "items": rows,
        "total": len(rows),
    })


@real_accuracy_label_bp.post("/cases/<case_uid>/labels")
@require_reviewer
def save_case_label(case_uid: str):
    dataset, error = _load_dataset()
    if error:
        return error
    assert dataset is not None
    case = next((item for item in dataset.get("cases") or [] if item.get("case_uid") == case_uid), None)
    if not case:
        return jsonify({"error": "case_not_found"}), 404
    if (case.get("notes") or {}).get("privacy_review_required"):
        return jsonify({"error": "privacy_review_required"}), 422
    payload = request.get_json(silent=True) or {}
    review_status = str(payload.get("review_status") or "draft")
    try:
        target_turn_uids = _validate_target_turns(case, payload.get("target_turn_uids"), review_status)
        actor_hash = reviewer_actor_hash(current_principal().subject)
        saved = RealAccuracyLabelStore().save(
            case_uid=case_uid,
            dataset_version=str(dataset.get("dataset_version") or ""),
            claims=payload.get("claims"),
            target_turn_uids=target_turn_uids,
            review_status=review_status,
            actor_hash=actor_hash,
            expected_version=payload.get("optimistic_lock_version"),
            allow_approval=has_any_role("supervisor", "admin"),
        )
    except LabelConflictError as exc:
        return jsonify({"error": str(exc)}), 409
    except LabelValidationError as exc:
        return jsonify({"error": str(exc)}), 422
    return jsonify({"label": saved}), 201
