"""Authenticated review API for the immutable v4.2 long-conversation set."""

from __future__ import annotations

import json
import os
from collections import Counter
from pathlib import Path
from typing import Any

from flask import Blueprint, jsonify, request

from app.api.admin_auth import current_principal, has_any_role, require_reviewer, require_supervisor
from app.services.high_quality_long_conversation_review_service import (
    HighQualityReviewConflictError,
    HighQualityReviewDatasetError,
    HighQualityReviewLabelError,
    HighQualityReviewLabelStore,
    build_approved_review_manifest,
    load_and_validate_review_dataset,
)
from app.services.real_accuracy_label_service import reviewer_actor_hash


high_quality_review_bp = Blueprint(
    "high_quality_long_conversation_review",
    __name__,
    url_prefix="/api/kb/hq-long-conversation-review",
)


def _dataset_path() -> Path:
    configured = os.environ.get("COPILOT_HQ_LONG_CONVERSATION_REVIEW_SET_PATH", "").strip()
    if configured:
        return Path(configured).expanduser()
    return Path(__file__).resolve().parents[2] / "outputs" / "high_quality_long_conversation_review_set_v4.json"


def _load_dataset() -> tuple[dict[str, Any] | None, dict[str, Any] | None, tuple[Any, int] | None]:
    path = _dataset_path()
    if not path.is_file():
        return None, None, (jsonify({"error": "review_dataset_not_configured"}), 503)
    try:
        dataset, validation = load_and_validate_review_dataset(path)
    except HighQualityReviewDatasetError:
        return None, None, (jsonify({"error": "review_dataset_unreadable"}), 503)
    if validation["validation_status"] != "passed":
        return None, validation, (
            jsonify({"error": "review_dataset_validation_failed", "reason_codes": validation["findings"]}),
            422,
        )
    return dataset, validation, None


def _review_store() -> HighQualityReviewLabelStore:
    return HighQualityReviewLabelStore()


def _current_role() -> str:
    if has_any_role("admin"):
        return "admin"
    if has_any_role("supervisor"):
        return "supervisor"
    return "reviewer"


def _public_product_context(scenario: dict[str, Any]) -> dict[str, Any]:
    context = scenario.get("product_context") if isinstance(scenario.get("product_context"), dict) else {}
    return {
        "product_name": str(context.get("product_name") or ""),
        "variant_reference": str(context.get("variant_reference") or ""),
        "identity_source": str(context.get("identity_source") or ""),
        "identity_present": bool(context.get("i_id") or context.get("sku_code") or context.get("product_id")),
    }


def _public_scenario(scenario: dict[str, Any], label: dict[str, Any] | None) -> dict[str, Any]:
    return {
        "scenario_uid": scenario.get("scenario_uid"),
        "scenario_title": scenario.get("scenario_title"),
        "business_domain": scenario.get("business_domain"),
        "risk_level": scenario.get("risk_level"),
        "current_buyer_message": scenario.get("current_buyer_message"),
        "conversation_history": [
            {
                "turn_uid": turn.get("turn_uid"),
                "turn_index": turn.get("turn_index"),
                "role": turn.get("role"),
                "content": turn.get("content"),
                "message_type": turn.get("message_type"),
            }
            for turn in scenario.get("conversation_history") or []
        ],
        "product_context": _public_product_context(scenario),
        "order_context": {
            "order_context_present": bool((scenario.get("order_context") or {}).get("order_id")),
            "real_order_data_included": False,
        },
        "gold_reply_original": scenario.get("gold_reply"),
        "expected_claims": scenario.get("expected_claims") or [],
        "source_evidence": [
            {
                "evidence_uid": item.get("evidence_uid"),
                "fact_type": item.get("fact_type"),
                "attribute_key": item.get("attribute_key"),
                "content": item.get("content"),
                "review_status": item.get("review_status"),
                "evidence_role": item.get("evidence_role"),
                "direct_answer_allowed": bool(item.get("direct_answer_allowed")),
            }
            for item in scenario.get("source_evidence") or []
        ],
        "required_actions": scenario.get("required_actions") or [],
        "forbidden_claims": scenario.get("forbidden_claims") or [],
        "must_handoff": bool(scenario.get("must_handoff")),
        "media_expectation": scenario.get("media_expectation"),
        "label": label,
    }


def _public_summary(scenario: dict[str, Any], label: dict[str, Any] | None) -> dict[str, Any]:
    return {
        "scenario_uid": scenario.get("scenario_uid"),
        "scenario_title": scenario.get("scenario_title"),
        "business_domain": scenario.get("business_domain"),
        "risk_level": scenario.get("risk_level"),
        "current_buyer_message": scenario.get("current_buyer_message"),
        "label": label,
    }


def _dataset_and_labels():
    dataset, validation, error = _load_dataset()
    if error:
        return None, None, None, error
    assert dataset is not None and validation is not None
    store = _review_store()
    store.register_dataset(
        dataset_id=validation["dataset_id"],
        dataset_version=validation["dataset_version"],
        dataset_sha256=validation["computed_content_sha256"],
    )
    labels = {
        item["scenario_uid"]: item
        for item in store.list_labels(validation["computed_content_sha256"])
    }
    return dataset, validation, labels, None


@high_quality_review_bp.get("")
@require_reviewer
def list_review_scenarios():
    dataset, validation, labels, error = _dataset_and_labels()
    if error:
        return error
    assert dataset is not None and validation is not None and labels is not None
    status_filter = str(request.args.get("status") or "").strip()
    domain_filter = str(request.args.get("business_domain") or "").strip()
    risk_filter = str(request.args.get("risk_level") or "").strip()
    items = [
        _public_summary(scenario, labels.get(str(scenario.get("scenario_uid") or "")))
        for scenario in dataset.get("scenarios") or []
    ]
    if status_filter:
        items = [item for item in items if str((item.get("label") or {}).get("status") or "draft") == status_filter]
    if domain_filter:
        items = [item for item in items if item.get("business_domain") == domain_filter]
    if risk_filter:
        items = [item for item in items if item.get("risk_level") == risk_filter]
    status_counts = Counter(str(label.get("status") or "draft") for label in labels.values())
    status_counts["draft"] += max(0, len(dataset.get("scenarios") or []) - len(labels))
    return jsonify({
        "dataset_id": validation["dataset_id"],
        "dataset_version": validation["dataset_version"],
        "dataset_sha256": validation["computed_content_sha256"],
        "total": len(items),
        "scenario_count": validation["scenario_count"],
        "status_counts": {key: int(status_counts.get(key, 0)) for key in ("draft", "reviewed", "approved", "rejected")},
        "business_domains": sorted({str(item.get("business_domain") or "") for item in dataset.get("scenarios") or []}),
        "risk_levels": sorted({str(item.get("risk_level") or "") for item in dataset.get("scenarios") or []}),
        "authoritative_approval_allowed": bool(
            current_principal().auth_type == "cloudflare_access" and has_any_role("supervisor", "admin")
        ),
        "items": items,
    })


@high_quality_review_bp.get("/progress")
@require_reviewer
def review_progress():
    dataset, _, _, error = _dataset_and_labels()
    if error:
        return error
    assert dataset is not None
    return jsonify(build_approved_review_manifest(dataset, _review_store()))


@high_quality_review_bp.get("/manifest")
@require_reviewer
def approved_manifest():
    dataset, _, _, error = _dataset_and_labels()
    if error:
        return error
    assert dataset is not None
    return jsonify(build_approved_review_manifest(dataset, _review_store()))


@high_quality_review_bp.get("/<scenario_uid>")
@require_reviewer
def get_review_scenario(scenario_uid: str):
    dataset, validation, labels, error = _dataset_and_labels()
    if error:
        return error
    assert dataset is not None and validation is not None and labels is not None
    scenario = next((item for item in dataset.get("scenarios") or [] if item.get("scenario_uid") == scenario_uid), None)
    if not scenario:
        return jsonify({"error": "scenario_not_found"}), 404
    events = [
        event for event in _review_store().list_events(validation["computed_content_sha256"])
        if event.get("scenario_uid") == scenario_uid
    ]
    public_events = [
        {
            "event_uid": event.get("event_uid"),
            "actor_role": event.get("actor_role"),
            "action": event.get("action"),
            "from_status": event.get("from_status"),
            "to_status": event.get("to_status"),
            "previous_version": event.get("previous_version"),
            "new_version": event.get("new_version"),
            "gold_reply_revised": event.get("gold_reply_revised"),
            "notes": event.get("notes"),
            "timestamp": event.get("timestamp"),
        }
        for event in events
    ]
    return jsonify({"scenario": _public_scenario(scenario, labels.get(scenario_uid)), "revision_history": public_events})


def _save_review(scenario_uid: str, requested_status: str):
    dataset, validation, _, error = _dataset_and_labels()
    if error:
        return error
    assert dataset is not None and validation is not None
    scenario = next((item for item in dataset.get("scenarios") or [] if item.get("scenario_uid") == scenario_uid), None)
    if not scenario:
        return jsonify({"error": "scenario_not_found"}), 404
    payload = request.get_json(silent=True) or {}
    principal = current_principal()
    try:
        saved = _review_store().save(
            dataset_id=validation["dataset_id"],
            dataset_version=validation["dataset_version"],
            dataset_sha256=validation["computed_content_sha256"],
            scenario_uid=scenario_uid,
            gold_reply_original=str(scenario.get("gold_reply") or ""),
            gold_reply_revised=str(payload.get("gold_reply_revised") or scenario.get("gold_reply") or ""),
            fact_correct=payload.get("fact_correct") is True,
            business_action_correct=payload.get("business_action_correct") is True,
            safety_boundary_correct=payload.get("safety_boundary_correct") is True,
            human_tone_correct=payload.get("human_tone_correct") is True,
            notes=str(payload.get("notes") or ""),
            requested_status=requested_status,
            actor_hmac=reviewer_actor_hash(principal.subject),
            actor_role=_current_role(),
            auth_type=principal.auth_type,
            expected_version=payload.get("version"),
        )
    except HighQualityReviewConflictError as exc:
        return jsonify({"error": str(exc)}), 409
    except HighQualityReviewLabelError as exc:
        return jsonify({"error": str(exc)}), 422
    return jsonify({"label": saved}), 201


@high_quality_review_bp.post("/<scenario_uid>/draft")
@require_reviewer
def save_review_draft(scenario_uid: str):
    return _save_review(scenario_uid, "draft")


@high_quality_review_bp.post("/<scenario_uid>/submit")
@require_reviewer
def submit_review(scenario_uid: str):
    return _save_review(scenario_uid, "reviewed")


@high_quality_review_bp.post("/<scenario_uid>/approve")
@require_supervisor
def approve_review(scenario_uid: str):
    return _save_review(scenario_uid, "approved")


@high_quality_review_bp.post("/<scenario_uid>/reject")
@require_supervisor
def reject_review(scenario_uid: str):
    return _save_review(scenario_uid, "rejected")
