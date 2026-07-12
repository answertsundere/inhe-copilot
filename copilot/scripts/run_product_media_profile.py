"""Run one bounded, read-only local-VLM profile over a dynamic media set."""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from collections import Counter
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.extract_product_media_observations import load_project_dotenv
from scripts.check_product_media_vlm_worker import snapshot as worker_snapshot
load_project_dotenv()
import app.models.kb_tables  # noqa: F401
from app.db import SessionLocal
from app.models.kb_tables import KBMediaAsset
from app.services.product_media_observation_service import (
    ProductMediaObservationExtractor, ProductMediaObservationProviderError,
    ProductMediaObservationSchemaError, configured_product_media_vlm_connection,
    run_product_media_vlm_transport,
)
from app.services.product_media_preprocessing_service import preprocess_product_media_image


def _asset_ids(report: dict, limit: int) -> list[int]:
    groups = {"dimension": [], "count": [], "ocr": [], "high_risk": [], "ambiguous": []}
    for row in report.get("results") or []:
        asset_id = int(row.get("media_asset_id") or 0)
        types = {entry.get("observation_type") for entry in row.get("observations") or []}
        if "labelled_dimension" in types: groups["dimension"].append(asset_id)
        if {"layer_count", "compartment_count"}.intersection(types): groups["count"].append(asset_id)
        if types == {"visible_text"}: groups["ocr"].append(asset_id)
        reasons = {entry.get("reason") for entry in row.get("rejected_evidence") or []}
        if "out_of_scope_high_risk" in reasons: groups["high_risk"].append(asset_id)
        if "ambiguous_variant_dimension_scope" in reasons: groups["ambiguous"].append(asset_id)
    selected: list[int] = []
    for values in groups.values():
        for value in values:
            if value and value not in selected:
                selected.append(value); break
    for row in report.get("results") or []:
        value = int(row.get("media_asset_id") or 0)
        if value and value not in selected: selected.append(value)
        if len(selected) >= limit: break
    return selected[:limit]


def _rate(numerator: int, denominator: int) -> dict:
    return {"numerator": numerator, "denominator": denominator, "rate": numerator / denominator if denominator else 0.0}


def run(
    *,
    input_report: str,
    profile: str,
    limit: int,
    timeout_seconds: int,
    max_tokens: int,
    worker_base_url: str,
) -> dict:
    health = worker_snapshot(worker_base_url)
    if not health["ready"]: raise RuntimeError("product_media_vlm_worker_not_ready")
    report = json.loads((PROJECT_ROOT / input_report).read_text(encoding="utf-8"))
    ids = _asset_ids(report, limit)
    db = SessionLocal()
    try:
        assets = db.query(KBMediaAsset).filter(KBMediaAsset.id.in_(ids)).all()
        asset_by_id = {asset.id: asset for asset in assets}
        ordered = [asset_by_id[item] for item in ids if item in asset_by_id]
        processor = preprocess_product_media_image if profile == "bounded_pixels" else None
        connection = configured_product_media_vlm_connection()

        def offline_worker_runner(asset, image_bytes, extension, timeout_seconds):
            parsed, metadata = run_product_media_vlm_transport(
                asset, image_bytes, extension, connection=connection, timeout_seconds=timeout_seconds,
                request_variant="plain_json_prompt", max_tokens=max_tokens, max_observations=5,
            )
            if parsed is not None:
                return parsed
            category = str(metadata.get("error_category") or "provider_error")
            if category in {"empty_response", "truncated_response", "non_json_response", "schema_error"}:
                raise ProductMediaObservationSchemaError(category)
            raise ProductMediaObservationProviderError(category)

        extractor = ProductMediaObservationExtractor(
            model_runner=offline_worker_runner, max_tokens=max_tokens, max_observations=5, image_preprocessor=processor,
        )
        if ordered: extractor.extract_asset(ordered[0], timeout_seconds=timeout_seconds)
        rows = []
        for asset in ordered:
            started = time.perf_counter()
            result = extractor.extract_asset(asset, timeout_seconds=timeout_seconds)
            rows.append({
                "media_asset_id": asset.id,
                "execution_result": result.get("execution_result"), "completion_result": result.get("completion_result"),
                "observation_count": len(result.get("observations") or []),
                "semantic_rejections": sorted(item.get("reason") for item in result.get("rejected_evidence") or []),
                "preprocessing": result.get("preprocessing") or {},
                "total_latency_ms": round((time.perf_counter() - started) * 1000, 2),
            })
    finally: db.close()
    successful_execution = sum(row["execution_result"] == "success" for row in rows)
    successful_schema = sum(row["completion_result"] == "complete_json" for row in rows)
    latencies = [row["total_latency_ms"] for row in rows]
    return {
        "shadow_only": True, "profile": profile, "retries_enabled": False, "concurrency": 1,
        "worker_health": health, "image_count": len(rows), "max_tokens": max_tokens,
        "execution_success_rate": _rate(successful_execution, len(rows)),
        "schema_success_rate": _rate(successful_schema, successful_execution),
        "observation_yield": _rate(sum(row["observation_count"] for row in rows), len(rows)),
        "p50_latency_ms": statistics.median(latencies) if latencies else None,
        "p95_latency_ms": sorted(latencies)[max(0, int((len(latencies)-1)*.95))] if latencies else None,
        "execution_failure_distribution": dict(Counter(row["execution_result"] for row in rows if row["execution_result"] != "success")),
        "completion_failure_distribution": dict(Counter(row["completion_result"] for row in rows if row["completion_result"] != "complete_json")),
        "rows": rows,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-report", default="outputs/product_media_observations_shadow_local_qwen_30_final_repaired.json")
    parser.add_argument("--profile", choices=("raw_original", "bounded_pixels"), required=True)
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--timeout-seconds", type=int, default=45)
    parser.add_argument("--max-tokens", type=int, default=1024, choices=range(128, 2049))
    parser.add_argument("--worker-base-url", default="http://127.0.0.1:8001")
    parser.add_argument("--json-output", required=True)
    args = parser.parse_args(argv)
    result = run(
        input_report=args.input_report,
        profile=args.profile,
        limit=args.limit,
        timeout_seconds=args.timeout_seconds,
        max_tokens=args.max_tokens,
        worker_base_url=args.worker_base_url,
    )
    output = PROJECT_ROOT / args.json_output; output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({key: value for key, value in result.items() if key not in {"rows", "worker_health"}}, ensure_ascii=False))
    return 0


if __name__ == "__main__": raise SystemExit(main())
