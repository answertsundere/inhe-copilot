"""Read-only visual-model qualification for Product Media Observation shadow.

Candidate connection values are read from explicitly named environment variables.
No candidate is hardcoded and this script never changes the project .env or
formal knowledge tables.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import statistics
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
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
from app.services.eval_sanitizer_service import sanitize_obj  # noqa: E402
from app.services.product_media_observation_service import (  # noqa: E402
    ProductMediaObservationExtractor,
    ProductMediaVlmConnection,
    media_asset_eligibility,
    resolve_product_media_image,
    run_product_media_vlm_transport,
)


def _configured(value: str) -> bool:
    normalized = str(value or "").strip().lower()
    return bool(normalized) and normalized not in {"none", "null", "placeholder", "your-api-key"} and not normalized.startswith("<")


def _identity_summary(asset: Any) -> dict[str, str]:
    i_id = str(getattr(asset, "i_id", "") or "")
    return {"i_id_sha256_prefix": hashlib.sha256(i_id.encode("utf-8")).hexdigest()[:12] if i_id else ""}


def _percentile_95(values: list[float]) -> float | None:
    if not values:
        return None
    return sorted(values)[max(0, int((len(values) - 1) * 0.95))]


def build_qualification_summary(
    *,
    provider_alias: str,
    model: str,
    official_vision_support: str,
    json_mode_support: str,
    records: list[dict[str, Any]],
) -> dict[str, Any]:
    """Summarize sanitized per-request records without retaining model text."""
    total = len(records)
    latencies = [float(row["latency_ms"]) for row in records if row.get("latency_ms") is not None]
    prompt_tokens = [int(row["prompt_tokens"]) for row in records if isinstance(row.get("prompt_tokens"), int)]
    completion_tokens = [int(row["completion_tokens"]) for row in records if isinstance(row.get("completion_tokens"), int)]
    success_count = sum(1 for row in records if row.get("transport_success"))
    timeout_count = sum(1 for row in records if row.get("error_category") == "timeout_error")
    truncated_count = sum(1 for row in records if row.get("error_category") == "truncated_response")
    schema_success_count = sum(1 for row in records if row.get("schema_parse_success"))
    high_risk_admitted_count = sum(int(row.get("high_risk_admitted_count") or 0) for row in records)
    qualified = bool(
        total
        and success_count == total
        and schema_success_count == total
        and timeout_count == 0
        and truncated_count == 0
        and high_risk_admitted_count == 0
    )
    return {
        "provider_alias": provider_alias,
        "model": model,
        "official_vision_support": official_vision_support,
        "json_mode_support": json_mode_support,
        "run_count": total,
        "success_count": success_count,
        "timeout_count": timeout_count,
        "truncated_count": truncated_count,
        "empty_response_count": sum(1 for row in records if row.get("error_category") == "empty_response"),
        "non_json_count": sum(1 for row in records if row.get("error_category") == "non_json_response"),
        "schema_error_count": sum(1 for row in records if row.get("error_category") == "schema_error"),
        "provider_error_count": sum(1 for row in records if row.get("error_category") == "provider_error"),
        "authentication_error_count": sum(1 for row in records if row.get("error_category") == "authentication_error"),
        "rate_limit_error_count": sum(1 for row in records if row.get("error_category") == "rate_limit_error"),
        "unsupported_parameter_count": sum(1 for row in records if row.get("error_category") == "unsupported_parameter"),
        "stable_json_rate": {"numerator": schema_success_count, "denominator": total, "rate": schema_success_count / total if total else 0.0},
        "observation_schema_rate": {"numerator": schema_success_count, "denominator": total, "rate": schema_success_count / total if total else 0.0},
        "median_latency_ms": statistics.median(latencies) if latencies else None,
        "p95_latency_ms": _percentile_95(latencies),
        "average_prompt_tokens": statistics.mean(prompt_tokens) if prompt_tokens else None,
        "average_completion_tokens": statistics.mean(completion_tokens) if completion_tokens else None,
        "content_present_count": sum(1 for row in records if row.get("content_present")),
        "finish_reason_distribution": dict(sorted(Counter(str(row.get("finish_reason") or "missing").lower() for row in records).items())),
        "high_risk_admitted_count": high_risk_admitted_count,
        "reasoning_content_consumed_count": 0,
        "qualified": qualified,
    }


def qualify(
    *,
    media_role: str,
    limit: int,
    runs_per_model: int,
    timeout_seconds: int,
    provider_alias: str,
    model_env: str,
    api_base_env: str,
    api_key_env: str,
    official_vision_support: str,
    json_mode_support: str,
    max_tokens: int,
    max_observations: int,
) -> dict[str, Any]:
    connection = ProductMediaVlmConnection(
        api_base=os.environ.get(api_base_env, ""),
        api_key=os.environ.get(api_key_env, ""),
        model=os.environ.get(model_env, ""),
    )
    db = SessionLocal()
    guard = ReadOnlyDatabaseGuard(db)
    try:
        guard.enable()
        before = _formal_kb_state_fingerprint(db)
        result: dict[str, Any] = {
            "schema_version": "product_media_vlm_qualification_v1",
            "shadow_only": True,
            "provider_alias": provider_alias,
            "model": connection.model,
            "official_vision_support": official_vision_support,
            "json_mode_support": json_mode_support,
            "connection_configured": {
                "api_base_configured": _configured(connection.api_base),
                "api_key_configured": _configured(connection.api_key),
                "model_configured": _configured(connection.model),
            },
            "media_read_success": False,
            "media_asset_id": 0,
            "product_identity": {},
            "records": [],
            "summary": {},
            "database_query_only": guard.enabled,
            "formal_kb_state_unchanged": False,
            "formal_kb_write_attempt_count": 0,
            "can_change_can_send_count": 0,
        }
        if not all(result["connection_configured"].values()):
            result["summary"] = build_qualification_summary(
                provider_alias=provider_alias,
                model=connection.model,
                official_vision_support=official_vision_support,
                json_mode_support=json_mode_support,
                records=[],
            )
            return result
        assets = _current_approved_media_query(db, media_role).limit(max(1, limit)).all()
        asset = None
        image: tuple[bytes, str] | None = None
        for candidate in assets:
            if media_asset_eligibility(candidate):
                continue
            try:
                image = resolve_product_media_image(candidate, timeout_seconds=timeout_seconds)
            except Exception:
                image = None
            if image:
                asset = candidate
                break
        if asset is None or image is None:
            result["summary"] = build_qualification_summary(
                provider_alias=provider_alias,
                model=connection.model,
                official_vision_support=official_vision_support,
                json_mode_support=json_mode_support,
                records=[],
            )
            return result
        result.update({
            "media_read_success": True,
            "media_asset_id": int(getattr(asset, "id", 0) or 0),
            "product_identity": _identity_summary(asset),
        })
        extractor = ProductMediaObservationExtractor()
        observed_sha = hashlib.sha256(image[0]).hexdigest()
        request_variant = "product_media_response_format" if json_mode_support == "yes" else "plain_json_prompt"
        for _ in range(runs_per_model):
            started = time.perf_counter()
            parsed, transport = run_product_media_vlm_transport(
                asset,
                image[0],
                image[1],
                timeout_seconds=timeout_seconds,
                connection=connection,
                request_variant=request_variant,
                max_tokens=max_tokens,
                max_observations=max_observations,
            )
            record = dict(transport)
            record["latency_ms"] = round((time.perf_counter() - started) * 1000, 2)
            record["transport_success"] = parsed is not None
            record["high_risk_admitted_count"] = 0
            if parsed is not None:
                inspected = extractor._parse_response(
                    asset,
                    parsed,
                    observed_media_sha256=observed_sha,
                    hash_comparison_status="qualification_not_compared",
                )
                record["high_risk_admitted_count"] = sum(
                    1 for item in inspected["observations"] if item.risk_class == "high"
                )
                record["high_risk_rejected_count"] = sum(
                    1 for item in inspected["rejected_evidence"] if item.get("reason") == "out_of_scope_high_risk"
                )
            result["records"].append(record)
        result["summary"] = build_qualification_summary(
            provider_alias=provider_alias,
            model=connection.model,
            official_vision_support=official_vision_support,
            json_mode_support=json_mode_support,
            records=result["records"],
        )
        return result
    finally:
        after = _formal_kb_state_fingerprint(db)
        if "result" in locals():
            result["formal_kb_state_unchanged"] = before == after
            result["formal_kb_write_attempt_count"] = guard.write_attempt_count
        guard.close()
        db.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="Small read-only VLM qualification matrix.")
    parser.add_argument("--media-role", default="size_image")
    parser.add_argument("--limit", type=int, default=1)
    parser.add_argument("--runs-per-model", type=int, default=3, choices=range(1, 6))
    parser.add_argument("--timeout-seconds", type=int, default=45, choices=range(1, 46))
    parser.add_argument("--max-tokens", type=int, default=512, choices=range(32, 4097))
    parser.add_argument("--max-observations", type=int, default=5, choices=range(1, 11))
    parser.add_argument("--provider-alias", default="configured-vlm")
    parser.add_argument("--model-env", default="COPILOT_VLM_MODEL")
    parser.add_argument("--api-base-env", default="COPILOT_VLM_API_BASE")
    parser.add_argument("--api-key-env", default="COPILOT_VLM_API_KEY")
    parser.add_argument("--official-vision-support", choices=("yes", "no", "unknown"), default="unknown")
    parser.add_argument("--json-mode-support", choices=("yes", "no", "unknown"), default="unknown")
    parser.add_argument("--json-output", default="outputs/product_media_vlm_qualification.json")
    args = parser.parse_args()
    result = qualify(
        media_role=str(args.media_role),
        limit=max(1, int(args.limit)),
        runs_per_model=int(args.runs_per_model),
        timeout_seconds=int(args.timeout_seconds),
        provider_alias=str(args.provider_alias),
        model_env=str(args.model_env),
        api_base_env=str(args.api_base_env),
        api_key_env=str(args.api_key_env),
        official_vision_support=str(args.official_vision_support),
        json_mode_support=str(args.json_mode_support),
        max_tokens=int(args.max_tokens),
        max_observations=int(args.max_observations),
    )
    output = PROJECT_ROOT / args.json_output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(sanitize_obj(result), ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({
        "provider_alias": result["provider_alias"],
        "model": result["model"],
        "media_read_success": result["media_read_success"],
        "qualified": result["summary"].get("qualified"),
        "database_query_only": result["database_query_only"],
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
