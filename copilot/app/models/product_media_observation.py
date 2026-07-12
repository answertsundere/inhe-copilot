"""Shadow-only, supervisor-reviewed product-media observations."""

from __future__ import annotations

import json
from datetime import datetime

from sqlalchemy import Column, DateTime, Float, ForeignKey, Index, Integer, String, Text

from app.db import Base


def _json_load(value: str, default):
    try:
        return json.loads(value or "")
    except (TypeError, ValueError):
        return default


class ProductMediaObservationCandidate(Base):
    __tablename__ = "product_media_observation_candidate"

    id = Column(Integer, primary_key=True)
    observation_uid = Column(String(64), nullable=False, unique=True, index=True)
    media_asset_id = Column(Integer, nullable=False, index=True)
    product_id = Column(String(64), nullable=False, default="", index=True)
    i_id = Column(String(64), nullable=False, default="", index=True)
    sku_code = Column(String(64), nullable=False, default="", index=True)
    observed_media_sha256 = Column(String(64), nullable=False, default="")
    asset_content_hash = Column(String(128), nullable=False, default="")
    hash_comparison_status = Column(String(48), nullable=False, default="")
    media_role = Column(String(48), nullable=False, default="")
    observation_type = Column(String(64), nullable=False, default="", index=True)
    attribute_key = Column(String(64), nullable=False, default="", index=True)
    raw_observation = Column(Text, nullable=False, default="")
    normalized_value = Column(String(128), nullable=False, default="")
    normalized_unit = Column(String(32), nullable=False, default="")
    normalized_domain = Column(String(32), nullable=False, default="")
    ocr_text = Column(Text, nullable=False, default="")
    region_json = Column(Text, nullable=False, default="null")
    confidence = Column(Float, nullable=False, default=0.0)
    extraction_model = Column(String(128), nullable=False, default="")
    extraction_version = Column(String(64), nullable=False, default="")
    prompt_version = Column(String(64), nullable=False, default="")
    schema_version = Column(String(64), nullable=False, default="")
    extraction_run_uid = Column(String(64), nullable=False, default="")
    risk_class = Column(String(16), nullable=False, default="low")
    status = Column(String(32), nullable=False, default="pending_review", index=True)
    version = Column(Integer, nullable=False, default=1)
    invalidation_reason = Column(String(128), nullable=False, default="")
    conflict_status = Column(String(64), nullable=False, default="")
    variant_scope = Column(String(128), nullable=False, default="")
    original_payload_hash = Column(String(64), nullable=False, default="")
    reviewed_raw_observation = Column(Text, nullable=False, default="")
    reviewed_normalized_value = Column(String(128), nullable=False, default="")
    reviewed_unit = Column(String(32), nullable=False, default="")
    reviewed_attribute_key = Column(String(64), nullable=False, default="")
    reviewed_variant_scope = Column(String(128), nullable=False, default="")
    reviewed_by = Column(String(64), nullable=False, default="")
    reviewed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        Index("idx_pmo_candidate_media_status", "media_asset_id", "status"),
        Index("idx_pmo_candidate_product_status", "i_id", "sku_code", "status"),
    )

    def to_dict(self, *, include_audit: bool = False) -> dict:
        data = {
            "id": self.id,
            "observation_uid": self.observation_uid,
            "media_asset_id": self.media_asset_id,
            "product_id": self.product_id,
            "i_id": self.i_id,
            "sku_code": self.sku_code,
            "observed_media_sha256": self.observed_media_sha256,
            "asset_content_hash": self.asset_content_hash,
            "hash_comparison_status": self.hash_comparison_status,
            "media_role": self.media_role,
            "observation_type": self.observation_type,
            "attribute_key": self.attribute_key,
            "raw_observation": self.raw_observation,
            "normalized_value": self.normalized_value or None,
            "normalized_unit": self.normalized_unit or None,
            "normalized_domain": self.normalized_domain or None,
            "ocr_text": self.ocr_text,
            "region": _json_load(self.region_json, None),
            "confidence": self.confidence,
            "extraction_model": self.extraction_model,
            "extraction_version": self.extraction_version,
            "prompt_version": self.prompt_version,
            "schema_version": self.schema_version,
            "extraction_run_uid": self.extraction_run_uid,
            "risk_class": self.risk_class,
            "status": self.status,
            "version": self.version,
            "invalidation_reason": self.invalidation_reason or None,
            "conflict_status": self.conflict_status or None,
            "variant_scope": self.variant_scope or None,
            "original_payload_hash": self.original_payload_hash,
            "direct_answer_allowed": False,
            "used_for_generation": False,
            "can_change_can_send": False,
        }
        if include_audit:
            data.update({
                "reviewed_raw_observation": self.reviewed_raw_observation or None,
                "reviewed_normalized_value": self.reviewed_normalized_value or None,
                "reviewed_unit": self.reviewed_unit or None,
                "reviewed_attribute_key": self.reviewed_attribute_key or None,
                "reviewed_variant_scope": self.reviewed_variant_scope or None,
                "reviewed_by": self.reviewed_by or None,
                "reviewed_at": self.reviewed_at.isoformat() if self.reviewed_at else None,
                "created_at": self.created_at.isoformat() if self.created_at else None,
                "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            })
        return data


class ProductMediaObservationReviewEvent(Base):
    __tablename__ = "product_media_observation_review_event"

    id = Column(Integer, primary_key=True)
    candidate_id = Column(Integer, ForeignKey("product_media_observation_candidate.id"), nullable=False, index=True)
    action = Column(String(32), nullable=False, index=True)
    before_status = Column(String(32), nullable=False, default="")
    after_status = Column(String(32), nullable=False, default="")
    reviewer = Column(String(64), nullable=False, default="")
    reviewed_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    reason = Column(Text, nullable=False, default="")
    changed_fields_json = Column(Text, nullable=False, default="{}")
    request_id = Column(String(64), nullable=False, default="", index=True)

    def to_dict(self) -> dict:
        return {
            "id": self.id, "candidate_id": self.candidate_id, "action": self.action,
            "before_status": self.before_status, "after_status": self.after_status,
            "reviewer": self.reviewer, "reviewed_at": self.reviewed_at.isoformat() if self.reviewed_at else None,
            "reason": self.reason, "changed_fields": _json_load(self.changed_fields_json, {}),
            "request_id": self.request_id or None,
        }
