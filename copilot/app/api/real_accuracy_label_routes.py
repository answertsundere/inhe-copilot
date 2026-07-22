"""Authenticated supervisor workbench API for privacy-safe Gold claim labels."""

from __future__ import annotations

import json
import os
from collections import Counter
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
    transition_claims_for_review,
)
from app.services.real_accuracy_claim_review_service import (
    STRATEGY_GROUPS,
    bounded_conversation_window,
    build_claim_review_plan,
    build_minimum_supervisor_queue,
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


def _public_case(case: dict[str, Any], plan_item: dict[str, Any]) -> dict[str, Any]:
    return {
        "case_uid": case.get("case_uid"),
        "classification": case.get("classification"),
        "customer_message": case.get("customer_message"),
        "conversation_window": plan_item.get("conversation_window"),
        "target_recommendation": plan_item.get("target_recommendation"),
        "explicit_target": case.get("explicit_target"),
        "query_class": case.get("query_class"),
        "risk_level": case.get("risk_level"),
        "sidecar_present": case.get("sidecar_present"),
        "sidecar_context_presence": plan_item.get("sidecar_context_presence"),
        "reference_label": {
            "label_status": (case.get("reference_label") or {}).get("label_status"),
            "reference_text": (case.get("reference_label") or {}).get("reference_text"),
        },
        "privacy_review_required": bool((case.get("notes") or {}).get("privacy_review_required")),
        "strategy": plan_item.get("strategy"),
        "proposal_status": plan_item.get("proposal_status"),
        "source_reference": plan_item.get("source_reference"),
        "candidate_claims": plan_item.get("candidate_claims"),
        "required_actions": plan_item.get("required_actions"),
        "prohibited_claims": plan_item.get("prohibited_claims"),
        "formal_evidence_summary": plan_item.get("formal_evidence_summary"),
        "label_eligibility": plan_item.get("label_eligibility"),
        "exclusion_reason": plan_item.get("exclusion_reason"),
        "label": plan_item.get("saved_label"),
    }


def _gold_30_plan_items(plan: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    queue = build_minimum_supervisor_queue(plan, target_claim_count=30, minimum_domain_count=5)
    claims_by_case: dict[str, list[dict[str, Any]]] = {}
    for item in queue.get("items") or []:
        case_uid = str(item.get("case_uid") or "")
        claim = item.get("atomic_claim")
        if case_uid and isinstance(claim, dict):
            claims_by_case.setdefault(case_uid, []).append(claim)
    scoped: list[dict[str, Any]] = []
    for item in plan.get("items") or []:
        claims = claims_by_case.get(str(item.get("case_uid") or ""))
        if not claims:
            continue
        row = dict(item)
        row["candidate_claims"] = claims
        row["required_actions"] = sorted({
            action for claim in claims for action in claim.get("required_action_points") or []
        })
        row["prohibited_claims"] = sorted({
            phrase for claim in claims for phrase in claim.get("forbidden_claims") or []
        })
        scoped.append(row)
    return scoped, queue


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
    explicit_uid = str(((case.get("explicit_target") or {}).get("target_turn_uid") or ""))
    if explicit_uid and normalized and normalized != [explicit_uid]:
        raise LabelValidationError("target_turn_must_match_explicit_target")
    return sorted(normalized, key=lambda uid: int(turns_by_uid[uid].get("turn_index") or 0))


def _current_actor_role() -> str:
    if has_any_role("admin"):
        return "admin"
    if has_any_role("supervisor"):
        return "supervisor"
    return "reviewer"


def _approval_auth_summary() -> dict[str, Any]:
    principal = current_principal()
    cloudflare_verified = principal.auth_type == "cloudflare_access"
    return {
        "auth_mode": principal.auth_type,
        "cloudflare_access_verified": cloudflare_verified,
        "authoritative_approval_allowed": bool(
            cloudflare_verified and principal.roles.intersection({"supervisor", "admin"})
        ),
    }


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
    strategy_group = str(request.args.get("strategy_group") or "").strip()
    plan = build_claim_review_plan(dataset, list(labels.values()))
    scoped_items, queue = _gold_30_plan_items(plan)
    queue_claim_uids = {
        str((item.get("atomic_claim") or {}).get("claim_uid") or "")
        for item in queue.get("items") or []
    }
    claim_status_counts: Counter[str] = Counter()
    historical_claim_status_counts: Counter[str] = Counter()
    approved_domains: set[str] = set()
    claim_domain = {
        str((item.get("atomic_claim") or {}).get("claim_uid") or ""): str(item.get("business_domain") or "")
        for item in queue.get("items") or []
    }
    for label in labels.values():
        for claim in ((label.get("label") or {}).get("claims") or []):
            status_value = str(claim.get("review_status") or "draft")
            historical_claim_status_counts[status_value] += 1
            claim_uid = str(claim.get("claim_uid") or "")
            if claim_uid not in queue_claim_uids:
                continue
            claim_status_counts[status_value] += 1
            if status_value == "approved" and claim_domain.get(claim_uid):
                approved_domains.add(claim_domain[claim_uid])
    cases_by_uid = {str(case.get("case_uid") or ""): case for case in dataset.get("cases") or []}
    rows = [
        _public_case(cases_by_uid[item["case_uid"]], item)
        for item in scoped_items
        if item["case_uid"] in cases_by_uid
    ]
    if status:
        rows = [item for item in rows if item.get("classification") == status]
    if strategy_group:
        rows = [item for item in rows if ((item.get("strategy") or {}).get("id") == strategy_group)]
    return jsonify({
        "dataset_id": dataset.get("dataset_id"),
        "dataset_version": dataset.get("dataset_version"),
        "privacy_scan_status": (dataset.get("privacy") or {}).get("privacy_scan_status"),
        "strategy_groups": [
            {"id": key, **value} for key, value in STRATEGY_GROUPS.items()
        ],
        "workflow_summary": {
            **_approval_auth_summary(),
            "review_scope": "gold_30",
            "queue_status": queue.get("queue_status"),
            "selected_claim_count": queue.get("selected_claim_count"),
            "selected_case_count": len(scoped_items),
            "selected_domain_count": queue.get("selected_domain_count"),
            "domain_distribution": queue.get("domain_distribution"),
            "approved_claim_count": int(claim_status_counts.get("approved", 0)),
            "approved_domain_count": len(approved_domains),
            "pending_claim_count": max(
                0,
                int(queue.get("selected_claim_count") or 0)
                - int(claim_status_counts.get("approved", 0)),
            ),
            "rejected_claim_count": int(historical_claim_status_counts.get("rejected", 0)),
            "active_queue_rejected_claim_count": int(claim_status_counts.get("rejected", 0)),
            "strategy_counts": plan.get("strategy_counts"),
            "proposal_status_counts": plan.get("proposal_status_counts"),
            "approved_case_count": plan.get("approved_case_count"),
            "auto_approved_count": 0,
        },
        "items": rows,
        "total": len(rows),
    })


@real_accuracy_label_bp.get("/cases/<case_uid>/window")
@require_reviewer
def get_case_window(case_uid: str):
    dataset, error = _load_dataset()
    if error:
        return error
    assert dataset is not None
    case = next((item for item in dataset.get("cases") or [] if item.get("case_uid") == case_uid), None)
    if not case:
        return jsonify({"error": "case_not_found"}), 404
    anchor = str(request.args.get("target_turn_uid") or "").strip()
    if not anchor:
        return jsonify({"error": "target_turn_uid_required"}), 422
    return jsonify({"case_uid": case_uid, "conversation_window": bounded_conversation_window(case, [anchor])})


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
        principal = current_principal()
        saved = RealAccuracyLabelStore().save(
            case_uid=case_uid,
            dataset_version=str(dataset.get("dataset_version") or ""),
            claims=payload.get("claims"),
            target_turn_uids=target_turn_uids,
            review_status=review_status,
            actor_hash=actor_hash,
            actor_role=_current_actor_role(),
            auth_type=principal.auth_type,
            dataset_hash=str((dataset.get("manifest") or {}).get("content_sha256") or ""),
            expected_version=payload.get("optimistic_lock_version"),
            allow_approval=has_any_role("supervisor", "admin"),
        )
    except LabelConflictError as exc:
        return jsonify({"error": str(exc)}), 409
    except LabelValidationError as exc:
        return jsonify({"error": str(exc)}), 422
    return jsonify({"label": saved}), 201


@real_accuracy_label_bp.post("/proposals/apply")
@require_reviewer
def apply_proposals():
    """Persist selected machine proposals as drafts only; never as Gold."""
    dataset, error = _load_dataset()
    if error:
        return error
    assert dataset is not None
    payload = request.get_json(silent=True) or {}
    requested = {str(item).strip() for item in payload.get("case_uids") or [] if str(item).strip()}
    if not requested:
        return jsonify({"error": "case_uids_required"}), 422
    store = RealAccuracyLabelStore()
    labels = {item["case_uid"]: item for item in store.list_for_dataset(str(dataset.get("dataset_version") or ""))}
    plan = build_claim_review_plan(dataset, list(labels.values()))
    scoped_items, _ = _gold_30_plan_items(plan)
    actor_hash = reviewer_actor_hash(current_principal().subject)
    principal = current_principal()
    created = 0
    skipped: dict[str, str] = {}
    for item in scoped_items:
        case_uid = str(item.get("case_uid") or "")
        if case_uid not in requested:
            continue
        if case_uid in labels:
            skipped[case_uid] = "existing_label"
        elif item.get("label_eligibility") != "ready_for_reviewer":
            skipped[case_uid] = str(item.get("exclusion_reason") or "not_eligible")
        elif not item.get("candidate_claims"):
            skipped[case_uid] = "proposal_missing"
        else:
            store.save(
                case_uid=case_uid,
                dataset_version=str(dataset.get("dataset_version") or ""),
                claims=item["candidate_claims"],
                target_turn_uids=[],
                review_status="draft",
                actor_hash=actor_hash,
                actor_role=_current_actor_role(),
                auth_type=principal.auth_type,
                dataset_hash=str((dataset.get("manifest") or {}).get("content_sha256") or ""),
                expected_version=0,
                allow_approval=False,
            )
            created += 1
    return jsonify({
        "created_draft_count": created,
        "skipped": skipped,
        "auto_approved_count": 0,
        "formal_knowledge_writes": 0,
    })


@real_accuracy_label_bp.post("/batches/review")
@require_reviewer
def submit_batch_for_review():
    """Move explicit selected drafts to reviewed; batch approval is forbidden."""
    dataset, error = _load_dataset()
    if error:
        return error
    assert dataset is not None
    payload = request.get_json(silent=True) or {}
    requested = {str(item).strip() for item in payload.get("case_uids") or [] if str(item).strip()}
    strategy_group = str(payload.get("strategy_group") or "").strip()
    if not requested or not strategy_group:
        return jsonify({"error": "case_uids_and_strategy_group_required"}), 422
    store = RealAccuracyLabelStore()
    labels = {item["case_uid"]: item for item in store.list_for_dataset(str(dataset.get("dataset_version") or ""))}
    plan = build_claim_review_plan(dataset, list(labels.values()))
    scoped_items, _ = _gold_30_plan_items(plan)
    actor_hash = reviewer_actor_hash(current_principal().subject)
    principal = current_principal()
    reviewed = 0
    skipped: dict[str, str] = {}
    for item in scoped_items:
        case_uid = str(item.get("case_uid") or "")
        if case_uid not in requested:
            continue
        if ((item.get("strategy") or {}).get("id") != strategy_group):
            skipped[case_uid] = "strategy_group_mismatch"
            continue
        label = labels.get(case_uid)
        if not label:
            skipped[case_uid] = "draft_label_required"
            continue
        if label.get("review_status") != "draft":
            skipped[case_uid] = "label_not_draft"
            continue
        target_turn_uids = ((label.get("label") or {}).get("target_turn_uids") or [])
        if not target_turn_uids:
            skipped[case_uid] = "target_buyer_turn_required"
            continue
        claims = transition_claims_for_review((label.get("label") or {}).get("claims"), review_status="reviewed")
        store.save(
            case_uid=case_uid,
            dataset_version=str(dataset.get("dataset_version") or ""),
            claims=claims,
            target_turn_uids=target_turn_uids,
            review_status="reviewed",
            actor_hash=actor_hash,
            actor_role=_current_actor_role(),
            auth_type=principal.auth_type,
            dataset_hash=str((dataset.get("manifest") or {}).get("content_sha256") or ""),
            expected_version=int(label.get("optimistic_lock_version") or 0),
            allow_approval=False,
        )
        reviewed += 1
    return jsonify({
        "reviewed_count": reviewed,
        "skipped": skipped,
        "supervisor_approved_count": 0,
        "formal_knowledge_writes": 0,
    })
