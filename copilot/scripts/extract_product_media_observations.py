"""Extract pending, shadow-only observations from approved product media.

The script opens SQLite in query-only mode, writes only a sanitized report to
``outputs/``, and never invokes the formal Agent path.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import event, or_

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def load_project_dotenv(path: Path | None = None) -> bool:
    """Load project .env without overriding already-exported process values."""
    dotenv_path = path or PROJECT_ROOT / ".env"
    if not dotenv_path.is_file():
        return False
    try:
        from dotenv import load_dotenv
        load_dotenv(dotenv_path=dotenv_path, override=False)
        return True
    except ImportError:
        for raw_line in dotenv_path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip("\"'"))
        return True


# Load before importing app.config through any application module.
load_project_dotenv()
sys.path.insert(0, str(PROJECT_ROOT))

import app.models.kb_tables  # noqa: E402,F401
from app.db import SessionLocal  # noqa: E402
from app.models.kb_tables import KBMediaAsset, KBProduct  # noqa: E402
from app.models.knowledge_base import KnowledgeEntry  # noqa: E402
from app.services.eval_sanitizer_service import sanitize_obj  # noqa: E402
from app.services.product_media_observation_service import (  # noqa: E402
    ProductMediaObservationExtractor,
    ProductMediaObservationProviderError,
    ProductMediaObservationSchemaError,
    call_product_media_vlm,
    media_asset_eligibility,
    resolve_product_media_image,
    vlm_configuration_status,
)


class ReadOnlyDatabaseGuard:
    """SQLite query-only guard with a measured write-attempt counter."""

    def __init__(self, db):
        self.db = db
        self.connection = db.connection()
        self.write_attempt_count = 0
        self.enabled = False

    def _count_write_attempt(self, _conn, _cursor, statement, _parameters, _context, _executemany) -> None:
        operation = str(statement or "").lstrip().split(None, 1)[0].upper() if str(statement or "").strip() else ""
        if operation in {"INSERT", "UPDATE", "DELETE", "REPLACE", "CREATE", "ALTER", "DROP"}:
            self.write_attempt_count += 1

    def enable(self) -> None:
        if self.connection.dialect.name != "sqlite":
            raise RuntimeError("product_media_observation_requires_sqlite_query_only")
        event.listen(self.connection, "before_cursor_execute", self._count_write_attempt)
        self.connection.exec_driver_sql("PRAGMA query_only=ON")
        self.enabled = bool(self.connection.exec_driver_sql("PRAGMA query_only").scalar())
        if not self.enabled:
            raise RuntimeError("sqlite_query_only_not_enabled")

    def close(self) -> None:
        try:
            if self.enabled:
                self.connection.exec_driver_sql("PRAGMA query_only=OFF")
        finally:
            event.remove(self.connection, "before_cursor_execute", self._count_write_attempt)


def _current_approved_media_query(db, media_role: str):
    return (
        db.query(KBMediaAsset)
        .filter(KBMediaAsset.asset_type == media_role)
        .filter(KBMediaAsset.status == "approved")
        .filter(KBMediaAsset.usable_for_agent == 1)
        .filter(KBMediaAsset.refresh_status.notin_(["needs_refresh", "error"]))
        .filter(or_(KBMediaAsset.url_expires_at.is_(None), KBMediaAsset.url_expires_at > datetime.utcnow()))
        .order_by(KBMediaAsset.id.asc())
    )


def _formal_kb_state_fingerprint(db) -> str:
    """Compare formal-table state without exporting business content or raw hashes."""
    fields_by_model = (
        (KBProduct, ("id", "i_id", "status", "specs_json", "updated_at")),
        (KnowledgeEntry, ("id", "status", "index_status", "content_hash", "updated_at")),
        (KBMediaAsset, ("id", "status", "usable_for_agent", "content_hash", "updated_at")),
    )
    digest = hashlib.sha256()
    for model, field_names in fields_by_model:
        columns = [getattr(model, field) for field in field_names]
        for row in db.query(*columns).order_by(model.id.asc()).yield_per(500):
            digest.update(repr(tuple(row)).encode("utf-8"))
    return digest.hexdigest()


def _summary(rows: list[dict[str, Any]], *, guard: ReadOnlyDatabaseGuard, state_unchanged: bool) -> dict[str, Any]:
    observations = [item for row in rows for item in row.get("observations", [])]
    rejected = [item for row in rows for item in row.get("rejected_evidence", [])]
    warnings = [warning for row in rows for warning in row.get("warnings", [])]
    hash_statuses = Counter(row.get("hash_comparison_status") for row in rows if row.get("hash_comparison_status"))
    return {
        "schema_version": "product_media_observation_shadow_report_v2",
        "shadow_only": True,
        "database_query_only": guard.enabled,
        "formal_kb_state_unchanged": state_unchanged,
        "formal_kb_write_attempt_count": guard.write_attempt_count,
        "can_change_can_send_count": sum(1 for item in observations if item.get("can_change_can_send")),
        "scanned_count": len(rows),
        "model_call_count": sum(1 for row in rows if row.get("model_called")),
        "extraction_success_count": sum(1 for row in rows if row.get("model_success")),
        "observation_candidate_count": len(observations),
        "rejected_count": len(rejected),
        "identity_scoped_count": sum(1 for item in observations if item.get("i_id")),
        "observation_type_counts": dict(sorted(Counter(item.get("observation_type") for item in observations).items())),
        "rejected_reason_counts": dict(sorted(Counter(item.get("reason") for item in rejected).items())),
        "low_confidence_count": sum(1 for item in rejected if item.get("reason") == "low_confidence"),
        "out_of_scope_high_risk_count": sum(1 for item in rejected if item.get("reason") == "out_of_scope_high_risk"),
        "missing_region_count": sum(1 for item in observations if "region_missing" in (item.get("warning_reasons") or [])),
        "hash_verified_count": hash_statuses.get("verified_match", 0),
        "hash_mismatch_count": hash_statuses.get("mismatch", 0),
        "legacy_hash_warning_count": hash_statuses.get("asset_hash_not_comparable", 0),
        "warning_counts": dict(sorted(Counter(warnings).items())),
    }


def _with_read_only_database(callback):
    db = SessionLocal()
    guard = ReadOnlyDatabaseGuard(db)
    try:
        guard.enable()
        before = _formal_kb_state_fingerprint(db)
        value = callback(db, guard)
        after = _formal_kb_state_fingerprint(db)
        return value, guard, before == after
    finally:
        guard.close()
        db.close()


def build_media_inventory() -> dict[str, Any]:
    """Read-only inventory for deciding whether a bounded shadow run is safe."""
    def collect(db, guard):
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
            "schema_version": "product_media_observation_inventory_v2",
            "read_only": True,
            "total_media_asset_count": len(rows),
            "approved_usable_count": len(approved_usable),
            "approved_usable_by_media_role": dict(sorted(role_counts.items())),
            "approved_usable_with_asset_url_count": sum(1 for row in approved_usable if row.asset_url),
            "approved_usable_with_i_id_count": sum(1 for row in approved_usable if row.i_id),
            "approved_usable_with_sku_code_count": sum(1 for row in approved_usable if row.sku_code),
            "approved_usable_with_product_id_count": sum(1 for row in approved_usable if row.product_id is not None),
            "existing_observation_metadata_counts": dict(sorted(source_fields.items())),
        }

    inventory, guard, unchanged = _with_read_only_database(collect)
    inventory.update({
        "database_query_only": guard.enabled,
        "formal_kb_state_unchanged": unchanged,
        "formal_kb_write_attempt_count": guard.write_attempt_count,
    })
    return inventory


def run(*, media_role: str, limit: int, timeout_seconds: int, max_tokens: int, max_observations: int) -> dict[str, Any]:
    def extract(db, guard):
        assets = _current_approved_media_query(db, media_role).limit(max(1, limit)).all()
        extractor = ProductMediaObservationExtractor(max_tokens=max_tokens, max_observations=max_observations)
        return [extractor.extract_asset(asset, timeout_seconds=timeout_seconds) for asset in assets]

    rows, guard, unchanged = _with_read_only_database(extract)
    return {"summary": _summary(rows, guard=guard, state_unchanged=unchanged), "results": rows}


def run_preflight(*, timeout_seconds: int, max_tokens: int, max_observations: int) -> dict[str, Any]:
    """Validate configuration and one minimal VLM request without observations."""
    config_status = vlm_configuration_status()

    def check(db, guard):
        result: dict[str, Any] = {
            "preflight": True,
            "vlm_enabled": config_status["enabled"],
            "api_base_configured": config_status["api_base_configured"],
            "api_key_configured": config_status["api_key_configured"],
            "model_configured": config_status["model_configured"],
            "minimal_visual_call_success": False,
            "fallback_reason": "",
        }
        if not all(config_status.values()):
            result["fallback_reason"] = "config_error"
            return result
        assets = _current_approved_media_query(db, "size_image").limit(5).all()
        result["media_attempt_count"] = 0
        if not assets:
            result["fallback_reason"] = "media_read_failed"
            return result
        for asset in assets:
            if media_asset_eligibility(asset):
                continue
            result["media_attempt_count"] += 1
            try:
                image = resolve_product_media_image(asset, timeout_seconds=timeout_seconds)
            except Exception:
                image = None
            if not image:
                continue
            try:
                response = call_product_media_vlm(
                    asset,
                    image[0],
                    image[1],
                    timeout_seconds=timeout_seconds,
                    max_tokens=max_tokens,
                    max_observations=max_observations,
                )
            except ProductMediaObservationSchemaError as exc:
                result["fallback_reason"] = exc.category
                return result
            except ProductMediaObservationProviderError as exc:
                result["fallback_reason"] = exc.category
                return result
            except Exception:
                result["fallback_reason"] = "provider_error"
                return result
            if not isinstance(response, dict) or not isinstance(response.get("observations"), list):
                result["fallback_reason"] = "schema_error"
                return result
            result["minimal_visual_call_success"] = True
            result["fallback_reason"] = ""
            return result
        result["fallback_reason"] = "media_read_failed"
        return result

    result, guard, unchanged = _with_read_only_database(check)
    result.update({
        "shadow_only": True,
        "database_query_only": guard.enabled,
        "formal_kb_state_unchanged": unchanged,
        "formal_kb_write_attempt_count": guard.write_attempt_count,
        "observation_candidate_count": 0,
        "can_change_can_send_count": 0,
    })
    return {"summary": result, "results": []}


def main() -> int:
    parser = argparse.ArgumentParser(description="Extract shadow-only product media observations.")
    parser.add_argument("--media-role", default="", help="KBMediaAsset asset_type, for example size_image")
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--timeout-seconds", type=int, default=20)
    parser.add_argument("--max-tokens", type=int, default=1024, choices=range(32, 4097))
    parser.add_argument("--max-observations", type=int, default=5, choices=range(1, 11))
    parser.add_argument("--dry-run", action="store_true", help="Explicit no-op marker; shadow extraction never writes the database.")
    parser.add_argument("--diagnose-only", action="store_true", help="Write a read-only media inventory without fetching images or calling VLM.")
    parser.add_argument("--preflight", action="store_true", help="Validate VLM configuration and one bounded visual call without observations.")
    parser.add_argument("--json-output", default="outputs/product_media_observations_shadow.json")
    args = parser.parse_args()
    if args.preflight and (args.diagnose_only or str(args.media_role).strip()):
        parser.error("--preflight cannot be combined with --diagnose-only or --media-role")
    if not args.preflight and not args.diagnose_only and not str(args.media_role).strip():
        parser.error("--media-role is required unless --diagnose-only or --preflight is supplied")
    result = (
        run_preflight(
            timeout_seconds=int(args.timeout_seconds),
            max_tokens=int(args.max_tokens),
            max_observations=int(args.max_observations),
        )
        if args.preflight
        else {"summary": build_media_inventory(), "results": []}
        if args.diagnose_only
        else run(
            media_role=str(args.media_role),
            limit=int(args.limit),
            timeout_seconds=int(args.timeout_seconds),
            max_tokens=int(args.max_tokens),
            max_observations=int(args.max_observations),
        )
    )
    output = PROJECT_ROOT / args.json_output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(sanitize_obj(result), ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result["summary"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
