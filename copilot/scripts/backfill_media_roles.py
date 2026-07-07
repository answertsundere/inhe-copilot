"""Safely backfill high-confidence media roles into KBMediaAsset.asset_type."""

from __future__ import annotations

import argparse
from datetime import datetime
import json
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.db import SessionLocal, init_db  # noqa: E402
from app.models.kb_tables import KBMediaAsset  # noqa: E402
from app.services.eval_sanitizer_service import sanitize_obj  # noqa: E402
from scripts.diagnose_media_role_coverage import UNKNOWN_MEDIA_TYPES, suggest_media_role  # noqa: E402


ROLE_TO_ASSET_TYPE = {
    "installation_video": "install_video",
    "installation_diagram": "install_image",
    "manual": "pack_guide_image",
    "dimension_image": "size_image",
    "accessory_image": "accessory_image",
}


def _write_json(path: str, payload: dict[str, Any]) -> None:
    if not path:
        return
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(sanitize_obj(payload), ensure_ascii=False, indent=2), encoding="utf-8")


def _candidate_change(asset: KBMediaAsset) -> dict[str, Any] | None:
    current = str(asset.asset_type or "").strip()
    if current not in UNKNOWN_MEDIA_TYPES:
        return None
    suggestion = suggest_media_role(asset)
    if suggestion.get("confidence") != "high":
        return None
    next_type = ROLE_TO_ASSET_TYPE.get(str(suggestion.get("suggested_role") or ""))
    if not next_type:
        return None
    return {
        "asset_id": asset.id,
        "from_asset_type": current or "unknown",
        "to_asset_type": next_type,
        "suggested_role": suggestion["suggested_role"],
        "matched_terms": suggestion.get("matched_terms") or [],
        "asset_title": asset.asset_title,
    }


def run(*, apply: bool = False, json_output: str = "", db_factory=SessionLocal) -> dict[str, Any]:
    db = db_factory()
    try:
        assets = db.query(KBMediaAsset).order_by(KBMediaAsset.id.asc()).all()
        changes: list[dict[str, Any]] = []
        skipped_low_confidence = 0
        conflict_count = 0
        for asset in assets:
            current = str(asset.asset_type or "").strip()
            change = _candidate_change(asset)
            if not change:
                if current in UNKNOWN_MEDIA_TYPES:
                    skipped_low_confidence += 1
                else:
                    conflict_count += 1
                continue
            changes.append(change)
            if apply:
                raw = asset.get_source_raw() or {}
                raw["media_role_backfill"] = {
                    "suggested_role": change["suggested_role"],
                    "matched_terms": change["matched_terms"],
                    "updated_at": datetime.utcnow().isoformat(),
                    "source": "backfill_media_roles",
                }
                asset.asset_type = change["to_asset_type"]
                asset.set_source_raw(raw)
                asset.updated_by = "media_role_backfill"
                asset.updated_at = datetime.utcnow()
        if apply and changes:
            db.commit()
        result = {
            "dry_run": not apply,
            "changed_count": len(changes) if apply else 0,
            "would_change_count": len(changes),
            "skipped_low_confidence": skipped_low_confidence,
            "conflict_count": conflict_count,
            "samples": changes[:20],
        }
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
    result = sanitize_obj(result)
    _write_json(json_output, result)
    return result


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Backfill high-confidence media roles. Dry-run by default.")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--json-output", default="")
    args = parser.parse_args(argv)
    init_db()
    result = run(apply=args.apply, json_output=args.json_output)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
