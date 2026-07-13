"""Run a read-only object-proposal qualification for the composable vision PoC."""

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
from app.services.composable_vision_object_provider_service import (  # noqa: E402
    preferred_object_provider,
    propose_deterministic_objects,
)
from app.services.composable_vision_ocr_provider_service import preferred_ocr_provider, recognize_windows_ocr  # noqa: E402
from app.services.eval_sanitizer_service import sanitize_obj  # noqa: E402
from app.services.product_media_observation_service import resolve_product_media_image_details  # noqa: E402
from app.services.product_media_panel_proposal_service import propose_panel_layout  # noqa: E402
from app.services.vision_grounding_provider_qualification_service import bbox_iou, is_normalized_bbox  # noqa: E402


_SCOPED_OBJECT_TYPES = {"packaging", "product", "component", "accessory", "included_item"}


def _rate(numerator: int, denominator: int) -> dict[str, float | int]:
    return {"numerator": numerator, "denominator": denominator, "rate": numerator / denominator if denominator else 0.0}


def _percentile(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    return ordered[max(0, int((len(ordered) - 1) * percentile))]


def _contains(outer: dict[str, Any], inner: dict[str, Any]) -> bool:
    try:
        return (
            float(outer["x"]) <= float(inner["x"])
            and float(outer["y"]) <= float(inner["y"])
            and float(inner["x"]) + float(inner["width"]) <= float(outer["x"]) + float(outer["width"])
            and float(inner["y"]) + float(inner["height"]) <= float(outer["y"]) + float(outer["height"])
        )
    except (KeyError, TypeError, ValueError):
        return False


def _object_signatures(objects: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {
        f"{item.get('panel_id') or 'root'}|{item.get('object_label') or ''}": item
        for item in objects
        if is_normalized_bbox(item.get("bbox"))
    }


def _repeatability(records: list[dict[str, Any]]) -> dict[str, Any]:
    by_asset: dict[int, list[dict[str, Any]]] = {}
    for row in records:
        by_asset.setdefault(int(row.get("media_asset_id") or 0), []).append(row)
    comparable = [rows for rows in by_asset.values() if len(rows) > 1]
    type_matches = 0
    iou_matches = 0
    iou_total = 0
    for rows in comparable:
        baseline = _object_signatures(rows[0].get("object_result", {}).get("objects") or [])
        stable = True
        for row in rows[1:]:
            current = _object_signatures(row.get("object_result", {}).get("objects") or [])
            if set(current) != set(baseline):
                stable = False
            for signature, baseline_item in baseline.items():
                current_item = current.get(signature)
                if not current_item or current_item.get("object_type") != baseline_item.get("object_type"):
                    stable = False
                    continue
                overlap = bbox_iou(baseline_item.get("bbox"), current_item.get("bbox"))
                if overlap is not None:
                    iou_total += 1
                    iou_matches += int(overlap >= 0.85)
        type_matches += int(stable)
    return {
        "repeated_asset_count": len(comparable),
        "repeat_object_type_stability_rate": _rate(type_matches, len(comparable)),
        "repeat_bbox_iou_stability_rate": _rate(iou_matches, iou_total),
    }


def _leakage_counts(objects: list[dict[str, Any]]) -> tuple[int, int, int]:
    package_as_product = sum(
        1
        for item in objects
        if item.get("object_type") == "product" and item.get("scope_reason") == "packaging_text_hint"
    )
    component_as_overall = sum(
        1
        for item in objects
        if item.get("object_type") == "component" and item.get("attribute_key") in {"overall_dimension", "product_dimension"}
    )
    cross_panel = sum(
        1
        for item in objects
        if item.get("panel_bbox") and not _contains(item["panel_bbox"], item.get("bbox") or {})
    )
    return package_as_product, component_as_overall, cross_panel


def build_report(
    *, provider: dict[str, Any], records: list[dict[str, Any]], database_query_only: bool,
    formal_kb_write_attempt_count: int, formal_kb_state_unchanged: bool, qualification_run: bool = True,
) -> dict[str, Any]:
    results = [row.get("object_result") or {} for row in records]
    objects = [item for result in results for item in result.get("objects") or []]
    image_read = sum(1 for row in records if (row.get("media_resolution") or {}).get("ok"))
    execution = sum(1 for result in results if not result.get("execution_error"))
    schema = sum(1 for result in results if not result.get("execution_error") and not result.get("schema_error"))
    object_bbox = sum(1 for result in results if any(is_normalized_bbox(item.get("bbox")) for item in result.get("objects") or []))
    scoped = sum(1 for item in objects if item.get("object_type") in _SCOPED_OBJECT_TYPES)
    package_leaks, component_leaks, cross_panel = _leakage_counts(objects)
    latencies = [float(result["latency_ms"]) for result in results if result.get("latency_ms") is not None]
    repeatability = _repeatability(records)
    distinct_assets = {int(row.get("media_asset_id") or 0) for row in records}
    counts = Counter(str(item.get("object_type") or "unknown_object_scope") for item in objects)
    summary = {
        "image_read_success_rate": _rate(image_read, len(records)),
        "object_execution_success_rate": _rate(execution, len(records)),
        "object_schema_success_rate": _rate(schema, len(records)),
        "object_bbox_rate": _rate(object_bbox, len(records)),
        "object_scope_resolution_rate": _rate(scoped, len(objects)),
        "packaging_object_detected_count": counts["packaging"],
        "product_object_detected_count": counts["product"],
        "component_object_detected_count": counts["component"],
        "unknown_object_scope_count": counts["unknown_object_scope"],
        "component_not_supported_count": sum(
            1 for result in results for diagnostic in result.get("diagnostics") or [] if diagnostic.get("reason") == "component_not_supported"
        ),
        "package_product_leakage_count": package_leaks,
        "component_overall_leakage_count": component_leaks,
        "cross_panel_object_count": cross_panel,
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
        "object_execution_success": summary["object_execution_success_rate"]["rate"] >= 0.95,
        "object_schema_success": summary["object_schema_success_rate"]["rate"] >= 0.95,
        "object_bbox": summary["object_bbox_rate"]["rate"] >= 0.90,
        "object_scope_resolution": summary["object_scope_resolution_rate"]["rate"] >= 0.90,
        "repeat_object_type_stability": summary["repeat_object_type_stability_rate"]["rate"] >= 0.90,
        "repeat_bbox_iou_stability": summary["repeat_bbox_iou_stability_rate"]["rate"] >= 0.85,
        "no_package_product_leakage": package_leaks == 0,
        "no_component_overall_leakage": component_leaks == 0,
        "no_cross_panel_object": cross_panel == 0,
        "no_formal_kb_write": formal_kb_write_attempt_count == 0,
        "no_can_send_change": summary["can_change_can_send_count"] == 0,
    }
    return {
        "schema_version": "composable_object_provider_qualification_v1",
        "shadow_only": True,
        "provider_status": "configured" if provider.get("configured") else "provider_not_configured",
        "provider": provider,
        "records": records,
        "summary": summary,
        "qualification_gates": gates,
        "scan_mode": "qualification_10_image" if qualification_run else "expanded_object_only_shadow_scan",
        "qualified_for_30_image": bool(provider.get("configured")) and all(gates.values()) if qualification_run else None,
        "database_query_only": database_query_only,
        "formal_kb_state_unchanged": formal_kb_state_unchanged,
        "pending_review_candidate_count": 0,
        "used_for_final_reply": False,
        "can_change_can_send": False,
    }


def _ocr_labels(image: dict[str, Any], *, timeout_seconds: int) -> dict[str, Any]:
    provider = preferred_ocr_provider(requested_provider="auto", timeout_seconds=min(timeout_seconds, 5))
    if not provider.get("configured") or provider.get("provider_name") != "windows_ocr":
        return {"items": [], "execution_error": "ocr_provider_not_configured", "schema_error": ""}
    return recognize_windows_ocr(
        image_data=image["data"], extension=str(image.get("extension") or ".png"),
        image_sha256=str(image.get("observed_media_sha256") or ""), timeout_seconds=timeout_seconds,
    )


def run(*, provider_name: str, limit: int, repeat: int, timeout_seconds: int, allow_expanded_shadow_scan: bool = False) -> dict[str, Any]:
    if limit > 10 and not allow_expanded_shadow_scan:
        raise ValueError("expanded_object_shadow_scan_requires_explicit_flag")
    db = SessionLocal()
    guard = ReadOnlyDatabaseGuard(db)
    try:
        guard.enable()
        before = _formal_kb_state_fingerprint(db)
        provider = preferred_object_provider(requested_provider=provider_name)
        assets = _current_approved_media_query(db, "size_image").limit(max(1, limit)).all()
        records: list[dict[str, Any]] = []
        for asset in assets:
            for attempt in range(max(1, repeat)):
                image = resolve_product_media_image_details(asset, timeout_seconds=timeout_seconds)
                record = {
                    "media_asset_id": int(asset.id), "attempt": attempt + 1,
                    "media_resolution": {key: value for key, value in image.items() if key != "data"},
                    "panel_proposal": {}, "ocr_summary": {},
                    "object_result": {"objects": [], "execution_error": "", "schema_error": ""},
                }
                if not image.get("ok"):
                    record["object_result"]["execution_error"] = str(image.get("reason") or "image_read_failed")
                elif not provider.get("configured"):
                    record["object_result"]["execution_error"] = "provider_not_configured"
                elif provider.get("provider_name") != "deterministic_primary_subject_proposal":
                    record["object_result"]["execution_error"] = "provider_adapter_not_implemented"
                else:
                    proposal = propose_panel_layout(image["data"])
                    panels = proposal.get("panels") if proposal.get("status") == "ready" else []
                    ocr_result = _ocr_labels(image, timeout_seconds=timeout_seconds)
                    record["panel_proposal"] = {key: value for key, value in proposal.items() if key != "image_data"}
                    record["ocr_summary"] = {
                        "configured": not bool(ocr_result.get("execution_error")),
                        "item_count": len(ocr_result.get("items") or []),
                        "execution_error": ocr_result.get("execution_error") or "",
                        "schema_error": ocr_result.get("schema_error") or "",
                    }
                    record["object_result"] = propose_deterministic_objects(
                        image_data=image["data"], image_sha256=str(image.get("observed_media_sha256") or ""),
                        panels=panels, ocr_items=list(ocr_result.get("items") or []),
                    )
                    for item in record["object_result"].get("objects") or []:
                        panel = next((candidate for candidate in panels if candidate.get("proposal_id") == item.get("panel_id")), None)
                        if panel:
                            item["panel_bbox"] = panel.get("panel_bbox")
                records.append(record)
        after = _formal_kb_state_fingerprint(db)
        return build_report(
            provider=provider, records=records, database_query_only=guard.enabled,
            formal_kb_write_attempt_count=guard.write_attempt_count, formal_kb_state_unchanged=before == after,
            qualification_run=limit <= 10,
        )
    finally:
        guard.close()
        db.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--provider", default="auto", choices=("auto", "deterministic", "groundingdino", "florence2"))
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--repeat", type=int, default=2)
    parser.add_argument("--timeout-seconds", type=int, default=20)
    parser.add_argument("--allow-expanded-shadow-scan", action="store_true")
    parser.add_argument("--json-output", default="outputs/composable_object_provider_qualification.json")
    args = parser.parse_args(argv)
    report = run(
        provider_name=args.provider, limit=args.limit, repeat=args.repeat, timeout_seconds=args.timeout_seconds,
        allow_expanded_shadow_scan=args.allow_expanded_shadow_scan,
    )
    output = PROJECT_ROOT / args.json_output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(sanitize_obj(report), ensure_ascii=True, indent=2), encoding="utf-8")
    print(json.dumps({"provider_status": report["provider_status"], "qualified_for_30_image": report["qualified_for_30_image"], "summary": report["summary"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
