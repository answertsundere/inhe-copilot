"""Export read-only Label Studio tasks for product-media annotation.

The export contains source references and shadow suggestions only.  It neither
downloads media into the repository nor writes to any knowledge table.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict, deque
from io import BytesIO
from pathlib import Path
from typing import Any

from PIL import Image

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
    label_studio_config_xml,
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


def _asset_id(asset: Any) -> int:
    return int(getattr(asset, "id", 0) or (asset.get("id", 0) if isinstance(asset, dict) else 0))


def _sampling_bucket(asset: Any) -> str:
    """Use durable media metadata only; names, SKU values, and image content are excluded."""
    role = str(getattr(asset, "asset_type", "") or (asset.get("asset_type", "") if isinstance(asset, dict) else "")).strip().lower()
    tags = set(getattr(asset, "get_scene_tags", lambda: [])() if not isinstance(asset, dict) else (asset.get("scene_tags") or []))
    if {"packaging", "mode", "multi_panel"}.intersection({str(tag).lower() for tag in tags}):
        return "structured_layout"
    return role or "other_image"


def _has_local_source(asset: Any) -> bool:
    raw = _source_raw(asset)
    return any(bool(raw.get(field)) for field in ("original_path", "cache_path", "local_cache_path", "cached_path", "download_path", "file_path"))


def select_balanced_pilot_assets(assets: list[Any], *, candidate_scan_limit: int) -> list[tuple[Any, str]]:
    """Round-robin across durable role/layout buckets before source bytes are read."""
    local_buckets: dict[str, deque[Any]] = defaultdict(deque)
    remote_buckets: dict[str, deque[Any]] = defaultdict(deque)
    for asset in sorted((item for item in assets if is_annotation_image_asset(item)), key=lambda item: (*annotation_priority(item), _asset_id(item))):
        (local_buckets if _has_local_source(asset) else remote_buckets)[_sampling_bucket(asset)].append(asset)
    selected: list[tuple[Any, str]] = []
    for buckets in (local_buckets, remote_buckets):
        while buckets and len(selected) < candidate_scan_limit:
            for bucket in sorted(tuple(buckets)):
                values = buckets[bucket]
                if values:
                    selected.append((values.popleft(), bucket))
                if not values:
                    buckets.pop(bucket, None)
                if len(selected) >= candidate_scan_limit:
                    break
    return selected


def _image_metadata(asset: Any, *, timeout_seconds: int) -> tuple[dict[str, Any] | None, str]:
    details = resolve_product_media_image_details(asset, timeout_seconds=timeout_seconds)
    if not details.get("ok"):
        return None, str(details.get("reason") or "image_read_failed")
    try:
        with Image.open(BytesIO(details["data"])) as image:
            size = {"width": int(image.width), "height": int(image.height)}
    except (KeyError, OSError, ValueError):
        return None, "image_decode_failed"
    return {
        "data": details["data"],
        "extension": str(details.get("extension") or ".png"),
        "observed_media_sha256": str(details.get("observed_media_sha256") or ""),
        "source_image_size": size,
        "source_kind": str(details.get("source_kind") or ""),
        "asset_hash_comparison_status": str(details.get("asset_hash_comparison_status") or ""),
    }, ""


def build_pilot_tasks(assets: list[Any], *, limit: int, candidate_scan_limit: int, timeout_seconds: int, materialize_dir: Path | None = None) -> dict[str, Any]:
    """Build only readable approved/usable image tasks with bytes-derived provenance."""
    approved = [
        asset for asset in assets
        if str(getattr(asset, "status", "") or (asset.get("status", "") if isinstance(asset, dict) else "")).lower() == "approved"
        and bool(getattr(asset, "usable_for_agent", False) if not isinstance(asset, dict) else asset.get("usable_for_agent"))
        and is_annotation_image_asset(asset)
    ]
    tasks: list[dict[str, Any]] = []
    failures: Counter[str] = Counter()
    distribution: Counter[str] = Counter()
    available_buckets = {_sampling_bucket(asset) for asset in approved}
    for asset, bucket in select_balanced_pilot_assets(approved, candidate_scan_limit=candidate_scan_limit):
        metadata, reason = _image_metadata(asset, timeout_seconds=timeout_seconds)
        if metadata is None:
            failures[reason] += 1
            continue
        detail_for_task = {key: value for key, value in metadata.items() if key not in {"data", "extension"}}
        task = build_label_studio_task(asset, ocr_items=_ocr_items(asset, include_live_ocr=False, timeout_seconds=timeout_seconds), model_candidates=_model_candidates(asset), image_details=detail_for_task)
        task["meta"]["pilot_sampling_bucket"] = bucket
        task["meta"]["pilot_sampling_reason"] = "approved_usable_media_role_or_layout_bucket"
        if materialize_dir:
            materialize_dir.mkdir(parents=True, exist_ok=True)
            suffix = metadata["extension"] if metadata["extension"].startswith(".") else f".{metadata['extension']}"
            filename = f"{metadata['observed_media_sha256']}{suffix.lower()}"
            target = materialize_dir / filename
            if not target.exists():
                target.write_bytes(metadata["data"])
            task["data"]["image"] = f"/data/local-files/?d=media/{filename}"
            task["meta"]["label_studio_local_media_path"] = f"media/{filename}"
        tasks.append(task)
        distribution[bucket] += 1
        if len(tasks) >= limit:
            break
    return {
        "schema_version": "product_media_annotation_pilot_v1",
        "requested_task_count": limit,
        "task_count": len(tasks),
        "candidate_scan_limit": candidate_scan_limit,
        "approved_usable_image_candidate_count": len(approved),
        "sampling_distribution": dict(sorted(distribution.items())),
        "missing_sampling_buckets": sorted(available_buckets.difference(distribution)),
        "source_read_failures": dict(sorted(failures.items())),
        "tasks": tasks,
    }


def run(*, limit: int, include_live_ocr: bool, timeout_seconds: int, pilot_size: int = 0, candidate_scan_limit: int = 120, materialize_dir: Path | None = None) -> dict[str, Any]:
    db = SessionLocal()
    guard = ReadOnlyDatabaseGuard(db)
    try:
        guard.enable()
        before = _formal_kb_state_fingerprint(db)
        assets = db.query(KBMediaAsset).order_by(KBMediaAsset.id.asc()).all()
        if pilot_size:
            pilot = build_pilot_tasks(assets, limit=max(1, pilot_size), candidate_scan_limit=max(pilot_size, candidate_scan_limit), timeout_seconds=timeout_seconds, materialize_dir=materialize_dir)
            tasks = pilot.pop("tasks")
        else:
            pilot = {}
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
            **pilot,
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
    parser.add_argument("--pilot-size", type=int, default=0, help="Build a readable approved/usable pilot with bytes-derived provenance.")
    parser.add_argument("--candidate-scan-limit", type=int, default=120)
    parser.add_argument("--json-output", default="outputs/product_media_annotation_tasks.json")
    parser.add_argument("--manifest-output", default="")
    parser.add_argument("--label-config-output", default="")
    parser.add_argument("--materialize-dir", default="", help="Optional local Label Studio media directory outside the repository.")
    args = parser.parse_args(argv)
    report = run(limit=args.limit, include_live_ocr=args.include_live_ocr, timeout_seconds=args.timeout_seconds, pilot_size=args.pilot_size, candidate_scan_limit=args.candidate_scan_limit, materialize_dir=Path(args.materialize_dir) if args.materialize_dir else None)
    output = PROJECT_ROOT / args.json_output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report["tasks"], ensure_ascii=False, indent=2), encoding="utf-8-sig")
    if args.pilot_size:
        manifest = PROJECT_ROOT / (args.manifest_output or f"{output.with_suffix('')}_manifest.json")
        manifest.parent.mkdir(parents=True, exist_ok=True)
        manifest.write_text(json.dumps({key: value for key, value in report.items() if key != "tasks"} | {"tasks": report["tasks"]}, ensure_ascii=False, indent=2), encoding="utf-8-sig")
        config_output = PROJECT_ROOT / (args.label_config_output or "outputs/label_studio_product_media_annotation_config.xml")
        config_output.parent.mkdir(parents=True, exist_ok=True)
        config_output.write_text(label_studio_config_xml(), encoding="utf-8-sig")
    print(json.dumps({key: value for key, value in report.items() if key != "tasks"}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
