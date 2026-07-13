"""Read-only configuration and source-read qualification for composable grounding."""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.extract_product_media_observations import ReadOnlyDatabaseGuard, _current_approved_media_query, load_project_dotenv
load_project_dotenv()
import app.models.kb_tables  # noqa: E402,F401
from app.db import SessionLocal  # noqa: E402
from app.services.composable_vision_grounding_service import build_geometry_candidates, normalize_object_items, normalize_ocr_items, verify_candidates  # noqa: E402
from app.services.eval_sanitizer_service import sanitize_obj  # noqa: E402
from app.services.product_media_observation_service import resolve_product_media_image_details  # noqa: E402
from app.services.product_media_panel_proposal_service import propose_panel_layout  # noqa: E402
from app.services.vision_grounding_provider_qualification_service import build_qualification_report, normalize_stage_outcomes  # noqa: E402


def _available(module: str) -> bool:
    return importlib.util.find_spec(module) is not None


def provider_status(availability: dict[str, bool]) -> str:
    if not availability.get("paddleocr") or not (availability.get("groundingdino") or availability.get("transformers")):
        return "provider_not_configured"
    return "adapter_wiring_required"


def run(*, limit: int, repeat: int, timeout_seconds: int) -> dict:
    db = SessionLocal(); guard = ReadOnlyDatabaseGuard(db)
    try:
        guard.enable()
        availability = {"paddleocr": _available("paddleocr"), "groundingdino": _available("groundingdino"), "transformers": _available("transformers"), "torch": _available("torch")}
        assets = _current_approved_media_query(db, "size_image").limit(max(1, limit)).all()
        records = []
        for asset in assets:
            for attempt in range(max(1, repeat)):
                image = resolve_product_media_image_details(asset, timeout_seconds=timeout_seconds)
                result = {"media_resolution": {key: value for key, value in image.items() if key != "data"}, "observations": [], "rejected_evidence": [], "warnings": []}
                diagnostics = []
                if image.get("ok"):
                    layout = propose_panel_layout(image["data"])
                    panels = layout.get("panels") or []
                    geometry = build_geometry_candidates(ocr_items=normalize_ocr_items([], image_size=None), object_items=normalize_object_items([], image_size=None), panels=panels)
                    verification = verify_candidates(geometry["candidates"], verifier=None)
                    result["rejected_evidence"] = geometry["rejected"] + verification["rejected"]
                    diagnostics = [
                        {"stage": "image_classification", "execution_status": "success", "schema_status": "valid"},
                        {"stage": "object_localization", "execution_status": "error", "schema_status": "invalid", "reason": "object_provider_not_configured"},
                        {"stage": "label_localization", "execution_status": "error", "schema_status": "invalid", "reason": "ocr_provider_not_configured"},
                        {"stage": "measurement_binding", "execution_status": "error", "schema_status": "invalid", "reason": "verifier_not_configured"},
                    ]
                else:
                    diagnostics = [{"stage": "image_classification", "execution_status": "error", "schema_status": "invalid", "reason": "image_read_failed"}]
                result["stage_outcomes"] = normalize_stage_outcomes(provider_name="composable_ocr_geometry_provider", model_name="adapter_stub", media_asset_id=int(asset.id), image_sha256=str((result["media_resolution"] or {}).get("observed_media_sha256") or ""), stage_diagnostics=diagnostics, latency_ms=None)
                result.update({"media_asset_id": int(asset.id), "attempt": attempt + 1})
                records.append(result)
        report = build_qualification_report(provider_name="composable_ocr_geometry_provider", model_name="adapter_stub", records=records, database_query_only=guard.enabled, formal_kb_write_attempt_count=guard.write_attempt_count)
        report["provider_status"] = provider_status(availability)
        report["availability"] = availability
        return report
    finally:
        guard.close(); db.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=10); parser.add_argument("--repeat", type=int, default=2); parser.add_argument("--timeout-seconds", type=int, default=20)
    parser.add_argument("--json-output", default="outputs/composable_vision_grounding_qualification.json")
    args = parser.parse_args(argv)
    report = run(limit=args.limit, repeat=args.repeat, timeout_seconds=args.timeout_seconds)
    output = PROJECT_ROOT / args.json_output; output.parent.mkdir(parents=True, exist_ok=True); output.write_text(json.dumps(sanitize_obj(report), ensure_ascii=True, indent=2), encoding="utf-8")
    print(json.dumps({"provider_status": report["provider_status"], "qualified_for_30_image": report["qualified_for_30_image"], "availability": report["availability"], "formal_kb_write_attempt_count": report["summary"]["formal_kb_write_attempt_count"], "can_change_can_send_count": report["summary"]["can_change_can_send_count"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
