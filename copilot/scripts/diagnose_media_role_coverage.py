"""Read-only media role coverage diagnostics."""

from __future__ import annotations

import argparse
from collections import Counter
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
from app.services.media_asset_service import get_auto_send_level  # noqa: E402


UNKNOWN_MEDIA_TYPES = {"", "other", "unknown", "image", "product_photo", "sku_image"}


def _write_json(path: str, payload: dict[str, Any]) -> None:
    if not path:
        return
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(sanitize_obj(payload), ensure_ascii=False, indent=2), encoding="utf-8")


def _source_values(asset: KBMediaAsset, keys: tuple[str, ...]) -> list[str]:
    raw = asset.get_source_raw() if hasattr(asset, "get_source_raw") else {}
    values: list[str] = []
    if not isinstance(raw, dict):
        return values
    for key in keys:
        value = raw.get(key)
        if isinstance(value, list):
            values.extend(str(item or "") for item in value)
        elif isinstance(value, dict):
            values.extend(str(item or "") for item in value.values())
        else:
            values.append(str(value or ""))
    return values


def _media_purpose_role(asset: KBMediaAsset) -> str:
    # answer_scenarios/scene_tags describe what a media item may help answer; they
    # are not the media role itself. A plain product photo can be useful for a
    # dimensions question, but it must not be rewritten as a size chart.
    values = _source_values(asset, ("media_purpose", "purpose"))
    normalized = {str(value or "").strip().lower() for value in values if str(value or "").strip()}
    if normalized & {"install_video", "installation_video"}:
        return "installation_video"
    if normalized & {"install_image", "installation_image", "installation_diagram", "installation", "drilling"}:
        return "installation_diagram"
    if normalized & {"manual", "instruction_manual", "pack_guide_image", "packing_list_image"}:
        return "manual"
    if normalized & {"size_image", "dimension_image", "dimensions", "size_chart"}:
        return "dimension_image"
    if normalized & {"accessory_image", "accessories", "parts_list"}:
        return "accessory_image"
    return ""


def _explicit_asset_text(asset: KBMediaAsset) -> str:
    parts = [
        asset.asset_title,
        *_source_values(asset, ("media_purpose", "purpose", "asset_source_note", "title")),
        " ".join(asset.get_scene_tags() or []) if hasattr(asset, "get_scene_tags") else "",
    ]
    return " ".join(str(part or "") for part in parts).lower()


def suggest_media_role(asset: KBMediaAsset) -> dict[str, Any]:
    purpose_role = _media_purpose_role(asset)
    if purpose_role:
        return {"suggested_role": purpose_role, "confidence": "high", "matched_terms": ["media_purpose"]}

    text = _explicit_asset_text(asset)
    checks = [
        ("installation_video", ("\u5b89\u88c5\u89c6\u9891", "\u7ec4\u88c5\u89c6\u9891", "\u5b89\u88c5\u6559\u7a0b\u89c6\u9891", "installation video", "install video")),
        ("installation_diagram", ("\u5b89\u88c5\u793a\u610f", "\u5b89\u88c5\u56fe", "\u7ec4\u88c5\u56fe", "\u5b89\u88c5\u6b65\u9aa4", "\u7ec4\u88c5\u6b65\u9aa4", "\u5b89\u88c5\u6559\u7a0b", "installation diagram", "installation guide", "install guide")),
        ("manual", ("\u8bf4\u660e\u4e66", "\u624b\u518c", "\u4f7f\u7528\u8bf4\u660e", "instruction manual")),
        ("dimension_image", ("\u5c3a\u5bf8\u56fe", "\u5c3a\u5bf8\u8868", "\u5c3a\u5bf8\u8bf4\u660e", "\u5c3a\u7801\u56fe", "\u89c4\u683c\u56fe", "size chart", "size_image", "dimension_image")),
        ("accessory_image", ("\u914d\u4ef6\u56fe", "\u96f6\u4ef6\u56fe", "\u914d\u4ef6\u6e05\u5355", "\u96f6\u4ef6\u6e05\u5355", "accessory_image", "parts list")),
    ]
    for role, terms in checks:
        hits = [term for term in terms if term in text]
        if hits:
            return {"suggested_role": role, "confidence": "high", "matched_terms": hits[:3]}
    return {"suggested_role": "unknown", "confidence": "low", "matched_terms": []}


def run(*, json_output: str = "", db_factory=SessionLocal) -> dict[str, Any]:
    db = db_factory()
    try:
        assets = db.query(KBMediaAsset).all()
        role_counter: Counter[str] = Counter()
        auto_counter: Counter[str] = Counter()
        high = 0
        low = 0
        pending = 0
        title_suggested = 0
        samples: list[dict[str, Any]] = []
        for asset in assets:
            role = str(asset.asset_type or "unknown")
            role_counter[role or "unknown"] += 1
            auto_counter[get_auto_send_level(asset)] += 1
            if asset.status != "approved" or asset.usable_for_agent != 1:
                pending += 1
            suggestion = suggest_media_role(asset)
            if suggestion["confidence"] == "high":
                high += 1
                if asset.asset_title and suggestion["matched_terms"]:
                    title_suggested += 1
                if len(samples) < 10 and role in UNKNOWN_MEDIA_TYPES:
                    samples.append({
                        "asset_id": asset.id,
                        "current_asset_type": role,
                        "suggested_role": suggestion["suggested_role"],
                        "matched_terms": suggestion["matched_terms"],
                        "asset_title": asset.asset_title,
                    })
            else:
                low += 1
        result = {
            "total_media_assets": len(assets),
            "approved_usable_media_assets": sum(1 for asset in assets if asset.status == "approved" and asset.usable_for_agent == 1),
            "media_role_non_null_count": sum(1 for asset in assets if str(asset.asset_type or "").strip() not in UNKNOWN_MEDIA_TYPES),
            "unknown_role_count": sum(1 for asset in assets if str(asset.asset_type or "").strip() in UNKNOWN_MEDIA_TYPES),
            "role_distribution": dict(role_counter.most_common()),
            "title_keyword_suggested_role_count": title_suggested,
            "source_purpose_suggested_role_count": high,
            "high_confidence_role_candidate_count": high,
            "low_confidence_role_candidate_count": low,
            "pending_review_count": pending,
            "auto_send_level_distribution": dict(auto_counter.most_common()),
            "samples": samples,
        }
    finally:
        db.close()
    result = sanitize_obj(result)
    _write_json(json_output, result)
    return result


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Diagnose KB media asset role coverage.")
    parser.add_argument("--json-output", default="")
    args = parser.parse_args(argv)
    init_db()
    result = run(json_output=args.json_output)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
