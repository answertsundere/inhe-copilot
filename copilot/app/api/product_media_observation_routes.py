"""Supervisor API for shadow-only product-media observation review."""

from __future__ import annotations

from flask import Blueprint, jsonify, request

from app.api.admin_auth import current_user_name, require_supervisor
from app.db import SessionLocal
from app.models.kb_tables import KBMediaAsset
from app.models.product_media_observation import ProductMediaObservationCandidate
from app.services.product_media_observation_review_service import ObservationReviewError, candidate_events, transition_candidate

product_media_observation_bp = Blueprint("product_media_observations", __name__, url_prefix="/api/kb/product-media-observations")


def _candidate_item(candidate: ProductMediaObservationCandidate, assets: dict[int, KBMediaAsset]) -> dict:
    item = candidate.to_dict()
    asset = assets.get(candidate.media_asset_id)
    item["source_media"] = {
        "asset_id": candidate.media_asset_id,
        "asset_url": str(asset.asset_url or "") if asset else "",
        "asset_title": str(asset.asset_title or "") if asset else "",
        "product_name": str(asset.product_name or "") if asset else "",
    }
    return item


@product_media_observation_bp.get("")
@require_supervisor
def list_candidates():
    db = SessionLocal()
    try:
        query = db.query(ProductMediaObservationCandidate)
        for field in ("status", "i_id", "media_asset_id", "observation_type", "attribute_key", "conflict_status"):
            value = str(request.args.get(field) or "").strip()
            if value:
                query = query.filter(getattr(ProductMediaObservationCandidate, field) == value)
        rows = query.order_by(ProductMediaObservationCandidate.updated_at.desc()).all()
        asset_ids = {row.media_asset_id for row in rows}
        assets = {
            asset.id: asset
            for asset in db.query(KBMediaAsset).filter(KBMediaAsset.id.in_(asset_ids)).all()
        } if asset_ids else {}
        return jsonify({"items": [_candidate_item(row, assets) for row in rows], "total": len(rows)})
    finally:
        db.close()


@product_media_observation_bp.get("/conflicts")
@require_supervisor
def conflicts():
    db = SessionLocal()
    try:
        rows = db.query(ProductMediaObservationCandidate).filter(ProductMediaObservationCandidate.conflict_status != "").all()
        return jsonify({"items": [row.to_dict(include_audit=True) for row in rows]})
    finally:
        db.close()


@product_media_observation_bp.get("/<int:candidate_id>")
@require_supervisor
def candidate_detail(candidate_id: int):
    db = SessionLocal()
    try:
        candidate = db.get(ProductMediaObservationCandidate, candidate_id)
        if not candidate:
            return jsonify({"error": "candidate_not_found"}), 404
        return jsonify({"candidate": candidate.to_dict(include_audit=True), "history": candidate_events(db, candidate_id)})
    finally:
        db.close()


@product_media_observation_bp.post("/<int:candidate_id>/<action>")
@require_supervisor
def review_candidate(candidate_id: int, action: str):
    payload = request.get_json(silent=True) or {}
    try:
        expected_version = int(payload.get("version"))
    except (TypeError, ValueError):
        return jsonify({"error": "version_required"}), 400
    db = SessionLocal()
    try:
        candidate = transition_candidate(db, candidate_id, action=action, reviewer=current_user_name(),
            reason=str(payload.get("reason") or ""), expected_version=expected_version,
            edits=payload.get("edits") if isinstance(payload.get("edits"), dict) else None,
            request_id=str(request.headers.get("X-Request-Id") or ""))
        return jsonify({"candidate": candidate.to_dict(include_audit=True)})
    except ObservationReviewError as exc:
        db.rollback()
        status = 409 if str(exc) == "version_conflict" else 400
        return jsonify({"error": str(exc)}), status
    finally:
        db.close()
