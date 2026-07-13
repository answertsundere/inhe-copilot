"""Export read-only Label Studio tasks for product-media annotation.

The export contains source references and shadow suggestions only.  It neither
downloads media into the repository nor writes to any knowledge table.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.extract_product_media_observations import (  # noqa: E402
    ReadOnlyDatabaseGuard,
    _formal_kb_state_fingerprint,
    load_project_dotenv,
)

load_project_dotenv()
import app.models.kb_tables  # noqa: E402,F401
from app.db import SessionLocal  # noqa: E402
from app.models.kb_tables import KBMediaAsset  # noqa: E402
from app.services.composable_vision_ocr_provider_service import preferred_ocr_provider, recognize_windows_ocr  # noqa: E402
from app.services.product_media_annotation_schema_service import (  # noqa: E402
    annotation_priority,
    build_label_studio_task,
    is_annotation_image_asset,
    validate_label_studio_task,
)
from app.services.product_media_observation_service import resolve_product_media_image_details  # noqa: E402


def _source_raw(asset: Any) -> dict[str, Any]:
    if isinstance(asset, dict):
        raw = asset.get("source_raw")
    elif hasattr(asset, "get_source_raw"):
        raw = asset.get_source_raw()
    else:
        raw = getattr(asset, "source_raw", None)
    return raw if isinstance(raw, dict) else {}


def _model_candidates(asset: Any) -> list[dict[str, Any]]:
    raw = _source_raw(asset)
    candidates = raw.get("model_candidates") or raw.get("visual_candidates") or []
    return [item for item in candidates if isinstance(item, dict)] if isinstance(candidates, list) else []


def _ocr_items(asset: Any, *, include_live_ocr: bool, timeout_seconds: int) -> list[dict[str, Any]]:
    raw = _source_raw(asset)
    stored = raw.get("ocr_items") or raw.get("ocr_boxes")
    if isinstance(stored, list):
        return [item for item in stored if isinstance(item, dict)]
    if not include_live_ocr:
        return []
    provider = preferred_ocr_provider(requested_provider="auto", timeout_seconds=min(timeout_seconds, 5))
    if not provider.get("configured") or provider.get("provider_name") != "windows_ocr":
        return []
    image = resolve_product_media_image_details(asset, timeout_seconds=timeout_seconds)
    if not image.get("ok"):
        return []
    result = recognize_windows_ocr(
        image_data=image["data"],
        extension=str(image.get("extension") or ".png"),
        image_sha256=str(image.get("observed_media_sha256") or ""),
        timeout_seconds=timeout_seconds,
    )
    return [item for item in result.get("items") or [] if isinstance(item, dict)]


def build_tasks(assets: list[Any], *, include_live_ocr: bool = False, timeout_seconds: int = 20) -> list[dict[str, Any]]:
    """Pure ordering wrapper used by the CLI and tests; it never filters by names."""
    image_assets = [asset for asset in assets if is_annotation_image_asset(asset)]
    ordered = sorted(image_assets, key=lambda asset: (*annotation_priority(asset), int(getattr(asset, "id", 0) or (asset.get("id", 0) if isinstance(asset, dict) else 0))))
    return [
        build_label_studio_task(
            asset,
            ocr_items=_ocr_items(asset, include_live_ocr=include_live_ocr, timeout_seconds=timeout_seconds),
            model_candidates=_model_candidates(asset),
        )
        for asset in ordered
    ]


def run(*, limit: int, include_live_ocr: bool, timeout_seconds: int) -> dict[str, Any]:
    db = SessionLocal()
    guard = ReadOnlyDatabaseGuard(db)
    try:
        guard.enable()
        before = _formal_kb_state_fingerprint(db)
        assets = db.query(KBMediaAsset).order_by(KBMediaAsset.id.asc()).all()
        tasks = build_tasks(assets, include_live_ocr=include_live_ocr, timeout_seconds=timeout_seconds)[:max(1, limit)]
        after = _formal_kb_state_fingerprint(db)
        return {
            "schema_version": "product_media_annotation_task_export_v1",
            "task_count": len(tasks),
            "validation_error_count": sum(len(validate_label_studio_task(task)) for task in tasks),
            "database_query_only": guard.enabled,
            "formal_kb_state_unchanged": before == after,
            "formal_kb_write_attempt_count": guard.write_attempt_count,
            "can_change_can_send_count": 0,
            "tasks": tasks,
        }
    finally:
        guard.close()
        db.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--include-live-ocr", action="store_true")
    parser.add_argument("--timeout-seconds", type=int, default=20)
    parser.add_argument("--json-output", default="outputs/product_media_annotation_tasks.json")
    args = parser.parse_args(argv)
    report = run(limit=args.limit, include_live_ocr=args.include_live_ocr, timeout_seconds=args.timeout_seconds)
    output = PROJECT_ROOT / args.json_output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report["tasks"], ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({key: value for key, value in report.items() if key != "tasks"}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
