"""Run a bounded, read-only compatibility probe for product-media VLM transport.

The report intentionally contains transport metadata only. It never stores a
media URL, image bytes, provider response text, reasoning content, or secrets.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.extract_product_media_observations import (  # noqa: E402
    ReadOnlyDatabaseGuard,
    _current_approved_media_query,
    _formal_kb_state_fingerprint,
    load_project_dotenv,
)

load_project_dotenv()

import app.models.kb_tables  # noqa: E402,F401
from app.db import SessionLocal  # noqa: E402
from app.services.eval_sanitizer_service import sanitize_obj  # noqa: E402
from app.services.product_media_observation_service import (  # noqa: E402
    media_asset_eligibility,
    probe_product_media_vlm,
    resolve_product_media_image,
    vlm_configuration_status,
)


def _identity_summary(asset: Any) -> dict[str, str]:
    value = str(getattr(asset, "i_id", "") or "")
    return {"i_id_sha256_prefix": hashlib.sha256(value.encode("utf-8")).hexdigest()[:12] if value else ""}


def diagnose(*, media_role: str, limit: int, timeout_seconds: int) -> dict[str, Any]:
    """Probe three existing client transport profiles against one readable asset."""
    config_status = vlm_configuration_status()
    db = SessionLocal()
    guard = ReadOnlyDatabaseGuard(db)
    try:
        guard.enable()
        before = _formal_kb_state_fingerprint(db)
        result: dict[str, Any] = {
            "schema_version": "product_media_vlm_provider_diagnosis_v1",
            "shadow_only": True,
            "config_enabled": config_status["enabled"],
            "api_base_configured": config_status["api_base_configured"],
            "api_key_configured": config_status["api_key_configured"],
            "model_configured": config_status["model_configured"],
            "media_read_success": False,
            "media_byte_count": 0,
            "media_sha256": "",
            "media_asset_id": 0,
            "product_identity": {},
            "attempts": [],
            "database_query_only": guard.enabled,
            "formal_kb_state_unchanged": False,
            "formal_kb_write_attempt_count": 0,
        }
        if not all(config_status.values()):
            return result
        assets = _current_approved_media_query(db, media_role).limit(max(1, limit)).all()
        image: tuple[bytes, str] | None = None
        asset = None
        for candidate in assets:
            if media_asset_eligibility(candidate):
                continue
            try:
                resolved = resolve_product_media_image(candidate, timeout_seconds=timeout_seconds)
            except Exception:
                resolved = None
            if resolved:
                asset, image = candidate, resolved
                break
        if asset is None or image is None:
            return result
        result.update({
            "media_read_success": True,
            "media_byte_count": len(image[0]),
            "media_sha256": hashlib.sha256(image[0]).hexdigest(),
            "media_asset_id": int(getattr(asset, "id", 0) or 0),
            "product_identity": _identity_summary(asset),
        })
        # These profiles mirror the three existing bottom-level clients. They
        # are direct transport probes, not calls into any formal image pipeline.
        for variant in (
            "product_media_response_format",
            "customer_image_response_format",
            "sidecar_plain_json",
        ):
            result["attempts"].append(probe_product_media_vlm(
                asset,
                image[0],
                image[1],
                timeout_seconds=timeout_seconds,
                request_variant=variant,
                allow_compatibility_retry=variant == "product_media_response_format",
            ))
        return result
    finally:
        after = _formal_kb_state_fingerprint(db)
        # The local variable may not exist if initialization failed; the
        # caller still receives no write-capable database handle.
        if "result" in locals():
            result["formal_kb_state_unchanged"] = before == after
            result["formal_kb_write_attempt_count"] = guard.write_attempt_count
        guard.close()
        db.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only VLM provider compatibility diagnosis.")
    parser.add_argument("--media-role", default="size_image")
    parser.add_argument("--limit", type=int, default=1)
    parser.add_argument("--timeout-seconds", type=int, default=30)
    parser.add_argument("--json-output", default="outputs/product_media_vlm_provider_diagnosis.json")
    args = parser.parse_args()
    result = diagnose(
        media_role=str(args.media_role),
        limit=max(1, int(args.limit)),
        timeout_seconds=max(1, int(args.timeout_seconds)),
    )
    output = PROJECT_ROOT / args.json_output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(sanitize_obj(result), ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({
        "media_read_success": result["media_read_success"],
        "attempt_count": len(result["attempts"]),
        "database_query_only": result["database_query_only"],
        "formal_kb_state_unchanged": result["formal_kb_state_unchanged"],
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
