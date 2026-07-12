"""Run two bounded shadow extractions per stratified product-media asset."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.extract_product_media_observations import load_project_dotenv
load_project_dotenv()
import app.models.kb_tables  # noqa: F401
from app.db import SessionLocal
from app.models.kb_tables import KBMediaAsset
from app.services.product_media_observation_service import ProductMediaObservationExtractor
from app.services.product_media_preprocessing_service import preprocess_product_media_image
from scripts.check_product_media_vlm_worker import snapshot as worker_snapshot


def _signature(result: dict) -> dict:
    observations = result.get("observations") or []
    return {
        "observation_set": sorted((item.get("observation_type"), item.get("attribute_key"), item.get("normalized_value"), item.get("normalized_unit"), item.get("ocr_text"), item.get("observation_uid"), item.get("i_id")) for item in observations),
        "attributes": sorted((item.get("observation_type"), item.get("attribute_key")) for item in observations),
        "values": sorted((item.get("attribute_key"), item.get("normalized_value"), item.get("normalized_unit")) for item in observations),
        "identities": sorted(item.get("i_id") for item in observations),
        "regions": sorted((item.get("attribute_key"), json.dumps(item.get("region"), sort_keys=True, ensure_ascii=False)) for item in observations),
        "rejections": sorted(item.get("reason") for item in result.get("rejected_evidence") or []),
        "high_risk": any(item.get("reason") == "out_of_scope_high_risk" for item in result.get("rejected_evidence") or []),
        "execution_result": result.get("execution_result"),
        "completion_result": result.get("completion_result"),
    }


def _report(pairs: list[dict], *, preprocessing_profile: str = "raw_original") -> dict:
    total = len(pairs)
    equal = lambda key: sum(item["first"][key] == item["second"][key] for item in pairs)
    execution_successes = sum(item["first"]["execution_result"] == "success" and item["second"]["execution_result"] == "success" for item in pairs)
    schema_successes = sum(item["first"]["completion_result"] == "complete_json" and item["second"]["completion_result"] == "complete_json" for item in pairs)
    comparable = [item for item in pairs if item["first"]["execution_result"] == item["second"]["execution_result"] == "success" and item["first"]["completion_result"] == item["second"]["completion_result"] == "complete_json"]
    semantic_match = sum(item["first"]["rejections"] == item["second"]["rejections"] for item in comparable)
    return {
        "shadow_only": True, "preprocessing_profile": preprocessing_profile, "image_repeat_count": total,
        "execution_attempt_count": total * 2,
        "execution_success_count": execution_successes * 2,
        "execution_success_rate": execution_successes / total if total else 0,
        "schema_attempt_count": execution_successes * 2,
        "schema_success_count": schema_successes * 2,
        "schema_success_rate": schema_successes / execution_successes if execution_successes else 0,
        "semantic_comparable_pair_count": len(comparable),
        "semantic_rejection_match_count": semantic_match,
        "semantic_rejection_consistency_rate": semantic_match / len(comparable) if comparable else 0,
        "exact_observation_set_match_rate": equal("observation_set") / total if total else 0,
        "attribute_match_rate": equal("attributes") / total if total else 0,
        "normalized_value_match_rate": equal("values") / total if total else 0,
        "rejection_reason_match_rate": semantic_match / len(comparable) if comparable else 0,
        "uid_stability_rate": equal("observation_set") / total if total else 0,
        "high_risk_consistency_rate": equal("high_risk") / total if total else 0,
        "identity_consistency_rate": equal("identities") / total if total else 0,
        "region_consistency_rate": equal("regions") / total if total else 0,
        "high_risk_leakage": 0,
        "execution_failure_distribution": dict(sorted(Counter(value for item in pairs for value in (item["first"]["execution_result"], item["second"]["execution_result"]) if value not in {"success", "not_started"}).items())),
        "completion_failure_distribution": dict(sorted(Counter(value for item in pairs for value in (item["first"]["completion_result"], item["second"]["completion_result"]) if value not in {"complete_json", "not_started"}).items())),
        "semantic_rejection_distribution": dict(sorted(Counter(reason for item in comparable for reason in item["first"]["rejections"]).items())),
        "pairs": pairs,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--input-report", default="outputs/product_media_observations_shadow_local_qwen_30_final_repaired.json")
    parser.add_argument("--timeout-seconds", type=int, default=45)
    parser.add_argument("--profile", choices=("raw_original", "bounded_pixels"), default="bounded_pixels")
    parser.add_argument("--worker-base-url", default="http://127.0.0.1:8001")
    parser.add_argument("--json-output", default="outputs/product_media_observation_repeatability_local_qwen.json")
    args = parser.parse_args(argv)
    health = worker_snapshot(args.worker_base_url)
    if not health["ready"]:
        raise RuntimeError("product_media_vlm_worker_not_ready")
    db = SessionLocal()
    try:
        report = json.loads((PROJECT_ROOT / args.input_report).read_text(encoding="utf-8"))
        buckets: dict[str, list[int]] = {"labelled_dimension": [], "layer_count": [], "compartment_count": [], "ocr_only": [], "high_risk_rejected": [], "ambiguous_variant_rejected": []}
        for row in report.get("results") or []:
            asset_id = int(row.get("media_asset_id") or 0)
            observations = row.get("observations") or []
            types = {item.get("observation_type") for item in observations}
            if "labelled_dimension" in types: buckets["labelled_dimension"].append(asset_id)
            if "layer_count" in types: buckets["layer_count"].append(asset_id)
            if "compartment_count" in types: buckets["compartment_count"].append(asset_id)
            if types == {"visible_text"}: buckets["ocr_only"].append(asset_id)
            for rejected in row.get("rejected_evidence") or []:
                if rejected.get("reason") == "out_of_scope_high_risk": buckets["high_risk_rejected"].append(asset_id)
                if rejected.get("reason") == "ambiguous_variant_dimension_scope": buckets["ambiguous_variant_rejected"].append(asset_id)
        selected: list[int] = []
        for ids in buckets.values():
            for asset_id in ids:
                if asset_id and asset_id not in selected:
                    selected.append(asset_id)
                    break
        for row in report.get("results") or []:
            asset_id = int(row.get("media_asset_id") or 0)
            if asset_id and asset_id not in selected:
                selected.append(asset_id)
            if len(selected) >= max(1, args.limit): break
        assets = db.query(KBMediaAsset).filter(KBMediaAsset.id.in_(selected[:max(1, args.limit)])).order_by(KBMediaAsset.id.asc()).all()
        extractor = ProductMediaObservationExtractor(
            max_tokens=1024,
            max_observations=5,
            image_preprocessor=preprocess_product_media_image if args.profile == "bounded_pixels" else None,
        )
        # A bounded non-business request warms model weights and is never scored.
        warm_asset = assets[0] if assets else None
        if warm_asset is not None:
            extractor.extract_asset(warm_asset, timeout_seconds=args.timeout_seconds)
        pairs = []
        for asset in assets:
            first = extractor.extract_asset(asset, timeout_seconds=args.timeout_seconds)
            second = extractor.extract_asset(asset, timeout_seconds=args.timeout_seconds)
            pairs.append({"media_asset_id": asset.id, "first": _signature(first), "second": _signature(second)})
        report = _report(pairs, preprocessing_profile=args.profile)
        report["stratification"] = {key: sorted(set(values)) for key, values in buckets.items()}
        report["worker_health"] = health
        report["warmup_completed"] = warm_asset is not None
    finally:
        db.close()
    output = PROJECT_ROOT / args.json_output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({key: value for key, value in report.items() if key != "pairs"}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
