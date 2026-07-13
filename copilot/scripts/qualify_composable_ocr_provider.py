"""Run an OCR-only, read-only 10-image qualification for the composable PoC."""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from collections import Counter
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
from app.services.vision_grounding_provider_qualification_service import bbox_iou, is_normalized_bbox  # noqa: E402


def _rate(numerator: int, denominator: int) -> dict[str, float | int]:
    return {"numerator": numerator, "denominator": denominator, "rate": numerator / denominator if denominator else 0.0}


def _percentile(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    return ordered[max(0, int((len(ordered) - 1) * percentile))]


def _repeatability(records: list[dict[str, Any]]) -> dict[str, Any]:
    by_asset: dict[int, list[dict[str, Any]]] = {}
    for row in records:
        by_asset.setdefault(int(row.get("media_asset_id") or 0), []).append(row)
    comparable = [rows for rows in by_asset.values() if len(rows) > 1]
    text_matches = 0
    iou_matches = 0
    iou_total = 0
    for rows in comparable:
        baseline = rows[0].get("ocr_result", {}).get("items") or []
        baseline_by_text = {str(item.get("text") or "").strip().lower(): item for item in baseline}
        stable = True
        for row in rows[1:]:
            current = row.get("ocr_result", {}).get("items") or []
            current_by_text = {str(item.get("text") or "").strip().lower(): item for item in current}
            if set(current_by_text) != set(baseline_by_text):
                stable = False
            for text, baseline_item in baseline_by_text.items():
                current_item = current_by_text.get(text)
                if not current_item:
                    continue
                overlap = bbox_iou(baseline_item.get("bbox"), current_item.get("bbox"))
                if overlap is not None:
                    iou_total += 1
                    iou_matches += int(overlap >= 0.8)
        text_matches += int(stable)
    return {
        "repeated_asset_count": len(comparable),
        "repeat_text_stability_rate": _rate(text_matches, len(comparable)),
        "repeat_bbox_iou_stability_rate": _rate(iou_matches, iou_total),
    }


def build_report(*, provider: dict[str, Any], records: list[dict[str, Any]], database_query_only: bool, formal_kb_write_attempt_count: int, formal_kb_state_unchanged: bool, qualification_run: bool = True) -> dict[str, Any]:
    results = [row.get("ocr_result") or {} for row in records]
    items = [item for result in results for item in result.get("items") or []]
    image_read = sum(1 for row in records if (row.get("media_resolution") or {}).get("ok"))
    execution = sum(1 for result in results if not result.get("execution_error"))
    schema = sum(1 for result in results if not result.get("execution_error") and not result.get("schema_error"))
    with_text_bbox = sum(1 for result in results if any(is_normalized_bbox(item.get("bbox")) for item in result.get("items") or []))
    classifications = [item.get("classification") or {} for item in items]
    latencies = [float(result["latency_ms"]) for result in results if result.get("latency_ms") is not None]
    repeatability = _repeatability(records)
    distinct_assets = {int(row.get("media_asset_id") or 0) for row in records}
    summary = {
        "image_read_success_rate": _rate(image_read, len(records)),
        "ocr_execution_success_rate": _rate(execution, len(records)),
        "ocr_schema_success_rate": _rate(schema, len(records)),
        "text_bbox_rate": _rate(with_text_bbox, len(records)),
        "dimension_text_detected_count": sum(1 for item in classifications if item.get("dimension_text")),
        "mode_text_detected_count": sum(1 for item in classifications if item.get("mode_text")),
        "packaging_text_detected_count": sum(1 for item in classifications if item.get("packaging_text")),
        "high_risk_text_detected_count": sum(1 for item in classifications if item.get("high_risk_text")),
        "high_risk_observation_admission_count": 0,
        "formal_kb_write_attempt_count": formal_kb_write_attempt_count,
        "can_change_can_send_count": 0,
        "latency_p50_ms": statistics.median(latencies) if latencies else None,
        "latency_p95_ms": _percentile(latencies, 0.95),
        "execution_error_counts": dict(sorted(Counter(str(result.get("execution_error") or "") for result in results if result.get("execution_error")).items())),
        "schema_error_counts": dict(sorted(Counter(str(result.get("schema_error") or "") for result in results if result.get("schema_error")).items())),
        **repeatability,
    }
    gates = {
        "fixed_10_image_set": len(distinct_assets) == 10,
        "image_read_success": summary["image_read_success_rate"]["rate"] == 1.0,
        "ocr_execution_success": summary["ocr_execution_success_rate"]["rate"] >= 0.95,
        "ocr_schema_success": summary["ocr_schema_success_rate"]["rate"] >= 0.95,
        "text_bbox": summary["text_bbox_rate"]["rate"] >= 0.95,
        "repeat_text_stability": summary["repeat_text_stability_rate"]["rate"] >= 0.90,
        "repeat_bbox_iou_stability": summary["repeat_bbox_iou_stability_rate"]["rate"] >= 0.90,
        "no_high_risk_observation_admission": summary["high_risk_observation_admission_count"] == 0,
        "no_formal_kb_write": formal_kb_write_attempt_count == 0,
        "no_can_send_change": summary["can_change_can_send_count"] == 0,
    }
    return {
        "schema_version": "composable_ocr_provider_qualification_v1",
        "shadow_only": True,
        "provider_status": "configured" if provider.get("configured") else "provider_not_configured",
        "provider": provider,
        "records": records,
        "summary": summary,
        "qualification_gates": gates,
        "scan_mode": "qualification_10_image" if qualification_run else "expanded_ocr_only_shadow_scan",
        "qualified_for_30_image": bool(provider.get("configured")) and all(gates.values()) if qualification_run else None,
        "database_query_only": database_query_only,
        "formal_kb_state_unchanged": formal_kb_state_unchanged,
        "pending_review_candidate_count": 0,
        "used_for_final_reply": False,
        "can_change_can_send": False,
    }


def run(*, provider_name: str, limit: int, repeat: int, timeout_seconds: int, allow_expanded_shadow_scan: bool = False) -> dict[str, Any]:
    if limit > 10 and not allow_expanded_shadow_scan:
        raise ValueError("expanded_ocr_shadow_scan_requires_explicit_flag")
    db = SessionLocal()
    guard = ReadOnlyDatabaseGuard(db)
    try:
        guard.enable()
        before = _formal_kb_state_fingerprint(db)
        provider = preferred_ocr_provider(requested_provider=provider_name, timeout_seconds=min(timeout_seconds, 5))
        assets = _current_approved_media_query(db, "size_image").limit(max(1, limit)).all()
        records: list[dict[str, Any]] = []
        for asset in assets:
            for attempt in range(max(1, repeat)):
                image = resolve_product_media_image_details(asset, timeout_seconds=timeout_seconds)
                result = {"media_asset_id": int(asset.id), "attempt": attempt + 1, "media_resolution": {key: value for key, value in image.items() if key != "data"}, "ocr_result": {"items": [], "execution_error": "", "schema_error": ""}}
                if not image.get("ok"):
                    result["ocr_result"]["execution_error"] = str(image.get("reason") or "image_read_failed")
                elif not provider.get("configured"):
                    result["ocr_result"]["execution_error"] = "provider_not_configured"
                elif provider.get("provider_name") == "windows_ocr":
                    result["ocr_result"] = recognize_windows_ocr(
                        image_data=image["data"], extension=str(image.get("extension") or ".png"), image_sha256=str(image.get("observed_media_sha256") or ""), timeout_seconds=timeout_seconds,
                    )
                else:
                    result["ocr_result"]["execution_error"] = "provider_adapter_not_implemented"
                records.append(result)
        after = _formal_kb_state_fingerprint(db)
        return build_report(
            provider=provider,
            records=records,
            database_query_only=guard.enabled,
            formal_kb_write_attempt_count=guard.write_attempt_count,
            formal_kb_state_unchanged=before == after,
            qualification_run=limit <= 10,
        )
    finally:
        guard.close()
        db.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--provider", default="auto", choices=("auto", "windows_ocr", "paddleocr", "tesseract", "easyocr"))
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--repeat", type=int, default=2)
    parser.add_argument("--timeout-seconds", type=int, default=20)
    parser.add_argument("--allow-expanded-shadow-scan", action="store_true")
    parser.add_argument("--json-output", default="outputs/composable_ocr_provider_qualification.json")
    args = parser.parse_args(argv)
    report = run(provider_name=args.provider, limit=args.limit, repeat=args.repeat, timeout_seconds=args.timeout_seconds, allow_expanded_shadow_scan=args.allow_expanded_shadow_scan)
    output = PROJECT_ROOT / args.json_output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(sanitize_obj(report), ensure_ascii=True, indent=2), encoding="utf-8")
    print(json.dumps({"provider_status": report["provider_status"], "qualified_for_30_image": report["qualified_for_30_image"], "summary": report["summary"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
