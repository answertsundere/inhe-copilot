"""Compare visual-grounding providers through the same read-only V3 contract."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.extract_product_media_observations import ReadOnlyDatabaseGuard, _current_approved_media_query, load_project_dotenv

load_project_dotenv()
import app.models.kb_tables  # noqa: E402,F401
from app.db import SessionLocal  # noqa: E402
from app.services.eval_sanitizer_service import sanitize_obj  # noqa: E402
from app.services.product_media_observation_v3_service import ProductMediaObservationV3Extractor  # noqa: E402
from app.services.vision_grounding_provider_qualification_service import (  # noqa: E402
    build_qualification_report,
    normalize_stage_outcomes,
)
from scripts.extract_product_media_observations_v3 import _runner  # noqa: E402


def _configured(value: str) -> bool:
    return bool(str(value or "").strip())


def _unconfigured_report(*, provider_name: str, model_name: str, required_env: tuple[str, ...]) -> dict[str, Any]:
    configuration = {name: _configured(os.getenv(name, "")) for name in required_env}
    configured = all(configuration.values())
    return {
        "schema_version": "vision_grounding_provider_qualification_v1",
        "shadow_only": True,
        "provider_name": provider_name,
        "model_name": model_name,
        "provider_status": "provider_adapter_not_implemented" if configured else "provider_not_configured",
        "configuration": configuration,
        "records": [], "stage_outcomes": [],
        "summary": {"formal_kb_write_attempt_count": 0, "can_change_can_send_count": 0},
        "qualification_gates": {"provider_configured": False},
        "qualified_for_30_image": False,
        "used_for_final_reply": False,
        "can_change_can_send": False,
    }


def run_local_qwen_qualification(*, provider_name: str, model_name: str, base_url: str, api_key: str, limit: int, repeat: int, timeout_seconds: int, max_tokens: int) -> dict[str, Any]:
    db = SessionLocal()
    guard = ReadOnlyDatabaseGuard(db)
    try:
        guard.enable()
        assets = _current_approved_media_query(db, "size_image").limit(max(1, limit)).all()
        runner = _runner(base_url=base_url, api_key=api_key, model=model_name, max_tokens=max_tokens, max_observations=5)
        extractor = ProductMediaObservationV3Extractor(runner)
        records: list[dict[str, Any]] = []
        for asset in assets:
            for attempt in range(max(1, repeat)):
                started = time.perf_counter()
                result = extractor.extract_asset(asset, expected_product_identity={"i_id": getattr(asset, "i_id", "")}, timeout_seconds=timeout_seconds)
                latency_ms = round((time.perf_counter() - started) * 1000, 2)
                media_resolution = result.get("media_resolution") or {}
                image_sha256 = str(media_resolution.get("observed_media_sha256") or "")
                records.append({
                    "media_asset_id": int(getattr(asset, "id", 0) or 0),
                    "attempt": attempt + 1,
                    "media_resolution": media_resolution,
                    "observations": result.get("observations") or [],
                    "rejected_evidence": result.get("rejected_evidence") or [],
                    "warnings": result.get("warnings") or [],
                    "stage_outcomes": normalize_stage_outcomes(
                        provider_name=provider_name, model_name=model_name,
                        media_asset_id=int(getattr(asset, "id", 0) or 0), image_sha256=image_sha256,
                        stage_diagnostics=result.get("stage_diagnostics") or [], latency_ms=latency_ms,
                    ),
                })
        report = build_qualification_report(
            provider_name=provider_name, model_name=model_name, records=records,
            database_query_only=guard.enabled, formal_kb_write_attempt_count=guard.write_attempt_count,
        )
        report["provider_status"] = "executed"
        return report
    finally:
        guard.close()
        db.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Read-only visual grounding provider qualification.")
    parser.add_argument("--provider", choices=("local_qwen_vllm", "configured_grounding", "configured_ocr_layout"), default="local_qwen_vllm")
    parser.add_argument("--base-url", default="http://127.0.0.1:8001/v1")
    parser.add_argument("--model", default="Qwen/Qwen3-VL-8B-Instruct")
    parser.add_argument("--api-key-env", default="COPILOT_VLM_API_KEY")
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--repeat", type=int, default=2)
    parser.add_argument("--timeout-seconds", type=int, default=45)
    parser.add_argument("--max-tokens", type=int, default=1024)
    parser.add_argument("--json-output", default="outputs/vision_grounding_provider_qualification.json")
    args = parser.parse_args(argv)
    if args.provider == "local_qwen_vllm":
        report = run_local_qwen_qualification(
            provider_name="local_qwen_vllm", model_name=args.model, base_url=args.base_url,
            api_key=os.getenv(args.api_key_env, "local-shadow-only"), limit=max(1, args.limit),
            repeat=max(1, args.repeat), timeout_seconds=max(1, args.timeout_seconds), max_tokens=max(64, args.max_tokens),
        )
    elif args.provider == "configured_grounding":
        required = ("COPILOT_VISION_GROUNDING_BASE_URL", "COPILOT_VISION_GROUNDING_MODEL", "COPILOT_VISION_GROUNDING_API_KEY")
        report = _unconfigured_report(provider_name=args.provider, model_name=os.getenv(required[1], ""), required_env=required)
    else:
        required = ("COPILOT_OCR_BASE_URL", "COPILOT_OCR_MODEL", "COPILOT_OCR_API_KEY")
        report = _unconfigured_report(provider_name=args.provider, model_name=os.getenv(required[1], ""), required_env=required)
    output = PROJECT_ROOT / args.json_output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(sanitize_obj(report), ensure_ascii=True, indent=2), encoding="utf-8")
    print(json.dumps({
        "provider": report["provider_name"], "provider_status": report.get("provider_status"),
        "qualified_for_30_image": report["qualified_for_30_image"],
        "formal_kb_write_attempt_count": report["summary"].get("formal_kb_write_attempt_count", 0),
        "can_change_can_send_count": report["summary"].get("can_change_can_send_count", 0),
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
