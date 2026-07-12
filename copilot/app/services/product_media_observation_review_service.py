"""Staging-only import and supervisor review service for VLM observations."""

from __future__ import annotations

import hashlib
import json
from contextlib import contextmanager
from datetime import datetime
from typing import Any

from sqlalchemy import event

from app.models.kb_tables import KBMediaAsset
from app.models.product_media_observation import ProductMediaObservationCandidate, ProductMediaObservationReviewEvent
from app.services.product_media_observation_service import resolve_product_media_image


ALLOWED_STATUSES = {"pending_review", "approved_shadow", "rejected", "invalidated", "superseded"}
TRANSITIONS = {
    "pending_review": {"approved_shadow", "rejected", "invalidated"},
    "approved_shadow": {"invalidated", "superseded"},
}
STAGING_TYPES = (ProductMediaObservationCandidate, ProductMediaObservationReviewEvent)
FORMAL_KNOWLEDGE_TABLES = {
    "kb_product",
    "product_identity_mappings",
    "kb_product_activity_rule",
    "kb_generic_service_rule",
    "kb_qa",
    "kb_question_variant",
    "kb_sop",
    "kb_case",
    "kb_agent_trace",
    "kb_feedback",
    "kb_review_task",
    "kb_change_log",
    "kb_media_asset",
    "kb_training_sample",
    "kb_training_sample_attachment",
}


class ObservationReviewError(ValueError):
    pass


class FormalKnowledgeWriteBlocked(ObservationReviewError):
    pass


def _text(value: Any) -> str:
    return str(value or "").strip()


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


@contextmanager
def staging_write_guard(session):
    """Reject formal knowledge DML during observation operations."""
    stats = {"staging_write_count": 0, "audit_event_count": 0, "formal_kb_write_attempt_count": 0}

    def before_flush(_session, _context, _instances):
        changed = list(_session.new) + list(_session.dirty) + list(_session.deleted)
        for entity in changed:
            if isinstance(entity, STAGING_TYPES):
                if entity in _session.new or _session.is_modified(entity, include_collections=False):
                    stats["staging_write_count"] += int(isinstance(entity, ProductMediaObservationCandidate))
                    stats["audit_event_count"] += int(isinstance(entity, ProductMediaObservationReviewEvent))
                continue
            table = getattr(entity, "__table__", None)
            if table is not None and table.name in FORMAL_KNOWLEDGE_TABLES:
                stats["formal_kb_write_attempt_count"] += 1
                raise FormalKnowledgeWriteBlocked("formal_knowledge_write_blocked")

    event.listen(session, "before_flush", before_flush)
    try:
        yield stats
    finally:
        event.remove(session, "before_flush", before_flush)


def _candidate_payload(observation: dict[str, Any], row: dict[str, Any], report_version: str) -> dict[str, Any]:
    payload = {
        "observation_uid": _text(observation.get("observation_uid")),
        "media_asset_id": int(observation.get("media_asset_id") or row.get("media_asset_id") or 0),
        "product_id": _text(observation.get("product_id")), "i_id": _text(observation.get("i_id")),
        "sku_code": _text(observation.get("sku_code")), "observed_media_sha256": _text(observation.get("observed_media_sha256")),
        "asset_content_hash": _text(observation.get("asset_content_hash")),
        "hash_comparison_status": _text(observation.get("hash_comparison_status")),
        "media_role": _text(observation.get("media_role")), "observation_type": _text(observation.get("observation_type")),
        "attribute_key": _text(observation.get("attribute_key")), "raw_observation": _text(observation.get("raw_observation")),
        "normalized_value": _text(observation.get("normalized_value")), "normalized_unit": _text(observation.get("normalized_unit")),
        "normalized_domain": _text(observation.get("normalized_domain")), "ocr_text": _text(observation.get("ocr_text")),
        "region_json": _json(observation.get("region")), "confidence": float(observation.get("confidence") or 0),
        "extraction_model": _text(observation.get("extraction_model")), "extraction_version": _text(observation.get("extraction_version")),
        "prompt_version": _text((observation.get("provenance") or {}).get("prompt_version")),
        "schema_version": _text((observation.get("provenance") or {}).get("schema_version") or report_version),
        "extraction_run_uid": _text((observation.get("provenance") or {}).get("extraction_run_uid")),
        "risk_class": "low", "status": "pending_review", "version": 1,
        "invalidation_reason": "", "conflict_status": "", "variant_scope": "",
    }
    payload["original_payload_hash"] = hashlib.sha256(_json(payload).encode("utf-8")).hexdigest()
    return payload


def validate_candidate_payload(payload: dict[str, Any], asset: KBMediaAsset | None) -> str:
    if not payload["observation_uid"] or not payload["media_asset_id"]:
        return "candidate_identity_missing"
    if not asset:
        return "media_asset_missing"
    if not payload["i_id"] or payload["i_id"] != _text(asset.i_id):
        return "product_identity_mismatch"
    if payload["sku_code"] and payload["sku_code"] != _text(asset.sku_code):
        return "product_identity_mismatch"
    if _text(asset.status).lower() != "approved" or not bool(asset.usable_for_agent):
        return "media_not_review_eligible"
    if not payload["observed_media_sha256"] or len(payload["observed_media_sha256"]) != 64:
        return "observed_media_hash_missing"
    return ""


def import_report(session, report: dict[str, Any], *, apply: bool) -> dict[str, Any]:
    summary = report.get("summary") or {}
    if summary.get("schema_version") != "product_media_observation_shadow_report_v2":
        raise ObservationReviewError("unsupported_observation_report_schema")
    result = {"dry_run": not apply, "candidate_import_count": 0, "duplicate_skipped_count": 0,
              "high_risk_skipped_count": 0, "ambiguity_group_count": 0, "skipped": [],
              "staging_write_count": 0, "audit_event_count": 0, "formal_kb_write_attempt_count": 0,
              "formal_kb_state_unchanged": True}
    seen_uids: set[str] = set()
    for row in report.get("results") or []:
        for rejected in row.get("rejected_evidence") or []:
            reason = _text(rejected.get("reason"))
            result["high_risk_skipped_count"] += int(reason == "out_of_scope_high_risk")
            result["ambiguity_group_count"] += int(reason == "ambiguous_variant_dimension_scope")
        for observation in row.get("observations") or []:
            if _text(observation.get("risk_class")).lower() not in {"", "low"}:
                result["high_risk_skipped_count"] += 1
                continue
            payload = _candidate_payload(observation, row, _text(summary.get("schema_version")))
            if payload["observation_uid"] in seen_uids:
                result["duplicate_skipped_count"] += 1
                continue
            seen_uids.add(payload["observation_uid"])
            asset = session.get(KBMediaAsset, payload["media_asset_id"])
            reason = validate_candidate_payload(payload, asset)
            if reason:
                result["skipped"].append({"observation_uid": payload["observation_uid"], "reason": reason})
                continue
            existing = session.query(ProductMediaObservationCandidate).filter_by(observation_uid=payload["observation_uid"]).one_or_none()
            if existing:
                result["duplicate_skipped_count"] += 1
                continue
            result["candidate_import_count"] += 1
            if apply:
                session.add(ProductMediaObservationCandidate(**payload))
    if apply:
        with staging_write_guard(session) as stats:
            session.commit()
        result.update(stats)
    return result


def _current_asset_check(candidate: ProductMediaObservationCandidate, asset: KBMediaAsset | None) -> str:
    if not asset or _text(asset.status).lower() != "approved" or not bool(asset.usable_for_agent):
        return "media_not_review_eligible"
    if candidate.i_id != _text(asset.i_id) or (candidate.sku_code and candidate.sku_code != _text(asset.sku_code)):
        return "product_identity_mismatch"
    image = resolve_product_media_image(asset)
    if not image:
        return "media_read_failed"
    if hashlib.sha256(image[0]).hexdigest() != candidate.observed_media_sha256:
        return "media_changed_since_extraction"
    return ""


def transition_candidate(session, candidate_id: int, *, action: str, reviewer: str, reason: str,
                         expected_version: int, edits: dict[str, Any] | None = None, request_id: str = "") -> ProductMediaObservationCandidate:
    candidate = session.get(ProductMediaObservationCandidate, candidate_id)
    if not candidate:
        raise ObservationReviewError("candidate_not_found")
    if candidate.version != expected_version:
        raise ObservationReviewError("version_conflict")
    target = {"approve": "approved_shadow", "reject": "rejected", "invalidate": "invalidated"}.get(action)
    if not target or target not in TRANSITIONS.get(candidate.status, set()):
        raise ObservationReviewError("invalid_status_transition")
    if action in {"approve", "reject"} and not _text(reason):
        raise ObservationReviewError("review_reason_required")
    asset_issue = _current_asset_check(candidate, session.get(KBMediaAsset, candidate.media_asset_id))
    if asset_issue:
        if asset_issue == "media_changed_since_extraction" and candidate.status in TRANSITIONS and "invalidated" in TRANSITIONS[candidate.status]:
            before = candidate.status
            candidate.status, candidate.invalidation_reason, candidate.version = "invalidated", asset_issue, candidate.version + 1
            session.add(ProductMediaObservationReviewEvent(candidate_id=candidate.id, action="invalidate", before_status=before,
                after_status="invalidated", reviewer=reviewer, reason=asset_issue, changed_fields_json="{}", request_id=request_id))
            with staging_write_guard(session): session.commit()
        raise ObservationReviewError(asset_issue)
    if candidate.risk_class != "low" or candidate.conflict_status:
        raise ObservationReviewError("candidate_not_approvable")
    before = candidate.status
    changed = {}
    if action == "approve" and edits:
        allowed = {"reviewed_raw_observation", "reviewed_normalized_value", "reviewed_unit", "reviewed_attribute_key", "reviewed_variant_scope"}
        for key, value in edits.items():
            if key in allowed and _text(value) != _text(getattr(candidate, key)):
                changed[key] = _text(value)
                setattr(candidate, key, _text(value))
    candidate.status, candidate.reviewed_by, candidate.reviewed_at, candidate.version = target, reviewer, datetime.utcnow(), candidate.version + 1
    session.add(ProductMediaObservationReviewEvent(candidate_id=candidate.id, action=action, before_status=before, after_status=target,
        reviewer=reviewer, reason=_text(reason), changed_fields_json=_json(changed), request_id=_text(request_id)))
    with staging_write_guard(session): session.commit()
    return candidate


def candidate_events(session, candidate_id: int) -> list[dict[str, Any]]:
    return [event.to_dict() for event in session.query(ProductMediaObservationReviewEvent).filter_by(candidate_id=candidate_id).order_by(ProductMediaObservationReviewEvent.id.asc())]
