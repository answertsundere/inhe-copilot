"""Extract pending, shadow-only observations from approved product media.

The script is intentionally read-only for the database.  It writes one
sanitized JSON report under outputs/ and never invokes the formal Agent path.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import app.models.kb_tables  # noqa: F401
from app.db import SessionLocal
from app.models.kb_tables import KBMediaAsset
from app.services.eval_sanitizer_service import sanitize_obj
from app.services.product_media_observation_service import ProductMediaObservationExtractor


def _summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    observations = [item for row in rows for item in row.get("observations", [])]
    rejected = [item for row in rows for item in row.get("rejected_evidence", [])]
    warnings = [warning for row in rows for warning in row.get("warnings", [])]
    return {
        "schema_version": "product_media_observation_shadow_report_v1",
        "shadow_only": True,
        "formal_kb_mutation_count": 0,
        "can_change_can_send_count": 0,
        "scanned_count": len(rows),
        "extraction_success_count": sum(1 for row in rows if row.get("model_success")),
        "observation_candidate_count": len(observations),
        "rejected_count": len(rejected),
        "identity_scoped_count": sum(1 for item in observations if item.get("i_id")),
        "observation_type_counts": dict(sorted(Counter(item.get("observation_type") for item in observations).items())),
        "rejected_reason_counts": dict(sorted(Counter(item.get("reason") for item in rejected).items())),
        "low_confidence_count": sum(1 for item in rejected if item.get("reason") == "low_confidence"),
        "out_of_scope_high_risk_count": sum(1 for item in rejected if item.get("reason") == "out_of_scope_high_risk"),
        "missing_region_count": sum(1 for item in observations if "region_missing" in (item.get("warning_reasons") or [])),
        "warning_counts": dict(sorted(Counter(warnings).items())),
    }


def build_media_inventory() -> dict[str, Any]:
    """Read-only inventory for deciding whether a bounded shadow run is safe."""
    db = SessionLocal()
    try:
        rows = db.query(KBMediaAsset).all()
        approved_usable = [
            row for row in rows
            if str(row.status or "").lower() == "approved" and bool(row.usable_for_agent)
        ]
        role_counts = Counter(str(row.asset_type or "other") for row in approved_usable)
        source_fields = Counter()
        for row in approved_usable:
            raw = row.get_source_raw() or {}
            for field in ("ocr_text", "caption", "vision_description", "region", "observations"):
                if raw.get(field):
                    source_fields[field] += 1
        return {
            "schema_version": "product_media_observation_inventory_v1",
            "read_only": True,
            "formal_kb_mutation_count": 0,
            "total_media_asset_count": len(rows),
            "approved_usable_count": len(approved_usable),
            "approved_usable_by_media_role": dict(sorted(role_counts.items())),
            "approved_usable_with_asset_url_count": sum(1 for row in approved_usable if row.asset_url),
            "approved_usable_with_i_id_count": sum(1 for row in approved_usable if row.i_id),
            "approved_usable_with_sku_code_count": sum(1 for row in approved_usable if row.sku_code),
            "approved_usable_with_product_id_count": sum(1 for row in approved_usable if row.product_id is not None),
            "existing_observation_metadata_counts": dict(sorted(source_fields.items())),
        }
    finally:
        db.close()


def run(*, media_role: str, limit: int, timeout_seconds: int) -> dict[str, Any]:
    db = SessionLocal()
    try:
        query = (
            db.query(KBMediaAsset)
            .filter(KBMediaAsset.asset_type == media_role)
            .filter(KBMediaAsset.status == "approved")
            .filter(KBMediaAsset.usable_for_agent == 1)
            .order_by(KBMediaAsset.id.asc())
        )
        assets = query.limit(max(1, limit)).all()
        extractor = ProductMediaObservationExtractor()
        rows = [extractor.extract_asset(asset, timeout_seconds=timeout_seconds) for asset in assets]
        return {"summary": _summary(rows), "results": rows}
    finally:
        db.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="Extract shadow-only product media observations.")
    parser.add_argument("--media-role", default="", help="KBMediaAsset asset_type, for example size_image")
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--timeout-seconds", type=int, default=20)
    parser.add_argument("--dry-run", action="store_true", help="Explicit no-op marker; shadow extraction never writes the database.")
    parser.add_argument("--diagnose-only", action="store_true", help="Write a read-only media inventory without fetching images or calling VLM.")
    parser.add_argument("--json-output", default="outputs/product_media_observations_shadow.json")
    args = parser.parse_args()
    if not args.diagnose_only and not str(args.media_role).strip():
        parser.error("--media-role is required unless --diagnose-only is supplied")
    result = (
        {"summary": build_media_inventory(), "results": []}
        if args.diagnose_only
        else run(media_role=str(args.media_role), limit=int(args.limit), timeout_seconds=int(args.timeout_seconds))
    )
    output = PROJECT_ROOT / args.json_output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(sanitize_obj(result), ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result["summary"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
