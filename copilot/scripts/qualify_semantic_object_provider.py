"""Compare a semantic object-provider candidate against the conservative shadow baseline."""

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
    _current_approved_media_query,
    _formal_kb_state_fingerprint,
    load_project_dotenv,
)

load_project_dotenv()
import app.models.kb_tables  # noqa: E402,F401
from app.db import SessionLocal  # noqa: E402
from app.services.composable_vision_ocr_provider_service import preferred_ocr_provider, recognize_windows_ocr  # noqa: E402
from app.services.eval_sanitizer_service import sanitize_obj  # noqa: E402
from app.services.product_media_observation_service import resolve_product_media_image_details  # noqa: E402
from app.services.product_media_panel_proposal_service import propose_panel_layout  # noqa: E402
from app.services.semantic_object_grounding_provider_service import (  # noqa: E402
    execute_semantic_object_provider,
    preferred_semantic_object_provider,
)
from scripts.qualify_composable_object_provider import build_report, run as run_opencv_baseline  # noqa: E402


def _image_size(image: dict[str, Any]) -> tuple[int, int] | None:
    size = image.get("source_image_size") or {}
    try:
        return int(size["width"]), int(size["height"])
    except (KeyError, TypeError, ValueError):
        return None


def _ocr_items(image: dict[str, Any], *, timeout_seconds: int) -> list[dict[str, Any]]:
    provider = preferred_ocr_provider(requested_provider="auto", timeout_seconds=min(timeout_seconds, 5))
    if not provider.get("configured") or provider.get("provider_name") != "windows_ocr":
        return []
    result = recognize_windows_ocr(
        image_data=image["data"], extension=str(image.get("extension") or ".png"),
        image_sha256=str(image.get("observed_media_sha256") or ""), timeout_seconds=timeout_seconds,
    )
    return list(result.get("items") or []) if not result.get("execution_error") else []


def _summary_aliases(report: dict[str, Any]) -> None:
    summary = report["summary"]
    summary["execution_success_rate"] = summary["object_execution_success_rate"]
    summary["schema_success_rate"] = summary["object_schema_success_rate"]
    summary["object_semantic_scope_resolution_rate"] = summary["object_scope_resolution_rate"]


def run(*, provider_name: str, limit: int, repeat: int, timeout_seconds: int, compare_opencv_baseline: bool = True) -> dict[str, Any]:
    if limit > 10:
        raise ValueError("semantic_object_qualification_stops_at_10_images")
    db = SessionLocal()
    guard = ReadOnlyDatabaseGuard(db)
    try:
        guard.enable()
        before = _formal_kb_state_fingerprint(db)
        provider = preferred_semantic_object_provider(requested_provider=provider_name)
        assets = _current_approved_media_query(db, "size_image").limit(max(1, limit)).all()
        records: list[dict[str, Any]] = []
        for asset in assets:
            for attempt in range(max(1, repeat)):
                image = resolve_product_media_image_details(asset, timeout_seconds=timeout_seconds)
                record = {
                    "media_asset_id": int(asset.id), "attempt": attempt + 1,
                    "media_resolution": {key: value for key, value in image.items() if key != "data"},
                    "panel_proposal": {}, "object_result": {"objects": [], "execution_error": "", "schema_error": ""},
                }
                if not image.get("ok"):
                    record["object_result"]["execution_error"] = str(image.get("reason") or "image_read_failed")
                else:
                    proposal = propose_panel_layout(image["data"])
                    panels = proposal.get("panels") if proposal.get("status") == "ready" else []
                    record["panel_proposal"] = proposal
                    result = execute_semantic_object_provider(
                        provider=provider, image_data=image["data"], image_sha256=str(image.get("observed_media_sha256") or ""),
                        image_size=_image_size(image), panels=panels, ocr_items=_ocr_items(image, timeout_seconds=timeout_seconds),
                    )
                    for item in result.get("objects") or []:
                        panel = next((candidate for candidate in panels if candidate.get("proposal_id") == item.get("panel_id")), None)
                        if panel:
                            item["panel_bbox"] = panel.get("panel_bbox")
                    record["object_result"] = result
                records.append(record)
        after = _formal_kb_state_fingerprint(db)
        report = build_report(
            provider=provider, records=records, database_query_only=guard.enabled,
            formal_kb_write_attempt_count=guard.write_attempt_count, formal_kb_state_unchanged=before == after,
            qualification_run=True,
        )
        report["schema_version"] = "semantic_object_provider_qualification_v1"
        _summary_aliases(report)
        report["provider_diagnostic"] = provider
        report["comparison"] = {"opencv_conservative_baseline": None}
        if compare_opencv_baseline:
            baseline = run_opencv_baseline(provider_name="auto", limit=limit, repeat=repeat, timeout_seconds=timeout_seconds)
            report["comparison"]["opencv_conservative_baseline"] = baseline["summary"]
        return report
    finally:
        guard.close()
        db.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--provider", choices=("auto", "groundingdino", "florence2"), default="auto")
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--repeat", type=int, default=2)
    parser.add_argument("--timeout-seconds", type=int, default=20)
    parser.add_argument("--without-opencv-baseline", action="store_true")
    parser.add_argument("--json-output", default="outputs/semantic_object_provider_qualification.json")
    args = parser.parse_args(argv)
    report = run(
        provider_name=args.provider, limit=args.limit, repeat=args.repeat, timeout_seconds=args.timeout_seconds,
        compare_opencv_baseline=not args.without_opencv_baseline,
    )
    output = PROJECT_ROOT / args.json_output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(sanitize_obj(report), ensure_ascii=True, indent=2), encoding="utf-8")
    print(json.dumps({"provider_status": report["provider_status"], "qualified_for_30_image": report["qualified_for_30_image"], "summary": report["summary"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
