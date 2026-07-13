"""Run staged, read-only Product Media Observation v3 extraction."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import sys
from collections import Counter
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from openai import OpenAI
from scripts.extract_product_media_observations import ReadOnlyDatabaseGuard, _current_approved_media_query
import app.models.kb_tables  # noqa: F401
from app.db import SessionLocal
from app.services.product_media_observation_v3_service import ProductMediaObservationV3Extractor, parse_v3_model_json, v3_model_prompt
from app.services.product_media_preprocessing_service import preprocess_product_media_image


def _image_data_url(data: bytes, extension: str) -> str:
    suffix = extension.lower().lstrip(".")
    mime = "image/jpeg" if suffix in {"jpg", "jpeg"} else f"image/{suffix or 'png'}"
    return f"data:{mime};base64,{base64.b64encode(data).decode('ascii')}"


def _runner(*, base_url: str, api_key: str, model: str, max_tokens: int, max_observations: int):
    client = OpenAI(base_url=base_url.rstrip("/") + "/", api_key=api_key)
    prepared_cache: dict[str, tuple[bytes, str]] = {}

    def run(stage: str, _asset, image: bytes, extension: str, timeout_seconds: int, context: dict):
        cache_key = hashlib.sha256(image).hexdigest()
        if cache_key not in prepared_cache:
            prepared = preprocess_product_media_image(image)
            prepared_cache[cache_key] = (prepared.data, prepared.extension)
        data, derived_extension = prepared_cache[cache_key]
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": "Return strict JSON only. Do not include markdown."},
                {"role": "user", "content": [
                    {"type": "text", "text": v3_model_prompt(max_observations=max_observations, stage=stage, context=context)},
                    {"type": "image_url", "image_url": {"url": _image_data_url(data, derived_extension)}},
                ]},
            ], temperature=0, max_tokens=max_tokens, timeout=timeout_seconds,
            response_format={"type": "json_object"},
        )
        choice = (response.choices or [None])[0]
        return parse_v3_model_json(getattr(getattr(choice, "message", None), "content", ""))

    return run


def _summary(rows: list[dict], guard: ReadOnlyDatabaseGuard) -> dict:
    observations = [item for row in rows for item in row["observations"]]
    rejected = [item for row in rows for item in row["rejected_evidence"]]
    diagnostics = [item for row in rows for item in row.get("stage_diagnostics", [])]
    labelled = [item for item in observations if item["observation_type"] == "labelled_measurement"]
    stage_valid = Counter(item["stage"] for item in diagnostics if item.get("schema_status") == "valid")
    stage_execution = Counter(item["stage"] for item in diagnostics if item.get("execution_status") == "success")
    repair_expected_count = sum(
        1 for row in rows
        if any(item.get("stage") == "panel_bbox_repair" for item in row.get("stage_diagnostics", []))
    )
    expected_stage_count = len(rows) * 4 + repair_expected_count
    executed_count = sum(stage_execution.values())
    schema_count = sum(stage_valid.values())
    resolution_rows = [row.get("media_resolution") or {} for row in rows]
    multi_panel_rows = [
        row for row in rows
        if any(
            item.get("stage") == "image_classification" and item.get("schema_status") == "valid"
            and item.get("result_count", 0) > 1
            for item in row.get("stage_diagnostics", [])
        )
    ]
    panel_observations = [item for item in observations if item.get("panel_ref")]
    return {
        "schema_version": "product_media_observation_v3_shadow_report", "shadow_only": True,
        "database_query_only": guard.enabled, "formal_kb_write_attempt_count": guard.write_attempt_count,
        "scanned_count": len(rows), "observation_count": len(observations), "rejected_count": len(rejected),
        "image_read_success_rate": {
            "numerator": sum(1 for item in resolution_rows if item.get("ok")),
            "denominator": len(rows),
            "rate": sum(1 for item in resolution_rows if item.get("ok")) / len(rows) if rows else 0.0,
        },
        "execution_success_rate": {"numerator": executed_count, "denominator": expected_stage_count, "rate": executed_count / expected_stage_count if expected_stage_count else 0.0},
        "schema_success_rate": {"numerator": schema_count, "denominator": expected_stage_count, "rate": schema_count / expected_stage_count if expected_stage_count else 0.0},
        "stage_execution_success_counts": dict(sorted(stage_execution.items())), "stage_schema_success_counts": dict(sorted(stage_valid.items())),
        "panel_bbox_coverage_rate": {
            "numerator": sum(1 for item in panel_observations if item.get("panel_bbox")),
            "denominator": len(panel_observations),
            "rate": sum(1 for item in panel_observations if item.get("panel_bbox")) / len(panel_observations) if panel_observations else 0.0,
        },
        "multi_panel_image_count": len(multi_panel_rows),
        "panel_bbox_repair_attempt_count": repair_expected_count,
        "labelled_dimension_count": len(labelled), "labelled_dimension_bound_bbox_count": sum(1 for item in labelled if item.get("object_bbox") and item.get("label_bbox")),
        "labelled_dimension_bound_bbox_coverage_rate": (sum(1 for item in labelled if item.get("object_bbox") and item.get("label_bbox")) / len(labelled)) if labelled else 0.0,
        "subject_scope_counts": dict(sorted(Counter(item["subject_scope"] for item in observations).items())),
        "observation_type_counts": dict(sorted(Counter(item["observation_type"] for item in observations).items())),
        "rejected_reason_counts": dict(sorted(Counter(item["reason"] for item in rejected).items())),
        "media_resolution_reason_counts": dict(sorted(Counter(item.get("reason", "resolved") for item in resolution_rows).items())),
        "packaging_product_leakage_count": sum(1 for item in observations if item["subject_scope"] == "product" and "packaging_measurement_not_product_dimension" in item.get("warning_reasons", [])),
        "component_overall_leakage_count": sum(1 for item in observations if item["subject_scope"] == "product" and "component_measurement_not_product_dimension" in item.get("warning_reasons", [])),
        "high_risk_accepted_count": sum(1 for item in observations if item.get("risk_class") == "high"),
        "can_change_can_send_count": sum(1 for item in observations if item["can_change_can_send"]),
    }


def run(*, limit: int, timeout_seconds: int, max_tokens: int, max_observations: int, base_url: str, api_key: str, model: str) -> dict:
    db = SessionLocal(); guard = ReadOnlyDatabaseGuard(db)
    try:
        guard.enable()
        assets = _current_approved_media_query(db, "size_image").limit(max(1, limit)).all()
        extractor = ProductMediaObservationV3Extractor(_runner(base_url=base_url, api_key=api_key, model=model, max_tokens=max_tokens, max_observations=max_observations))
        rows = [extractor.extract_asset(asset, timeout_seconds=timeout_seconds) for asset in assets]
    finally:
        guard.close(); db.close()
    return {"summary": _summary(rows, guard), "results": rows}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, required=True); parser.add_argument("--base-url", required=True); parser.add_argument("--model", required=True)
    parser.add_argument("--api-key-env", default="COPILOT_VLM_API_KEY"); parser.add_argument("--timeout-seconds", type=int, default=45)
    parser.add_argument("--max-tokens", type=int, default=1024); parser.add_argument("--max-observations", type=int, default=5); parser.add_argument("--json-output", required=True)
    args = parser.parse_args(); api_key = os.getenv(args.api_key_env, "")
    if not api_key: parser.error("configured API key environment variable is required")
    report = run(limit=args.limit, timeout_seconds=args.timeout_seconds, max_tokens=args.max_tokens, max_observations=args.max_observations, base_url=args.base_url, api_key=api_key, model=args.model)
    output = PROJECT_ROOT / args.json_output; output.parent.mkdir(parents=True, exist_ok=True); output.write_text(json.dumps(report, ensure_ascii=True, indent=2), encoding="utf-8")
    print(json.dumps(report["summary"], ensure_ascii=False)); return 0


if __name__ == "__main__":
    raise SystemExit(main())
