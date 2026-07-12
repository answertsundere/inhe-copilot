"""Run bounded, read-only Product Media Observation v3 extraction offline."""

from __future__ import annotations

import argparse
import base64
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
from app.services.product_media_preprocessing_service import preprocess_product_media_image
from app.services.product_media_observation_v3_service import (
    ProductMediaObservationV3Extractor, parse_v3_model_json, v3_model_prompt,
)


def _image_data_url(data: bytes, extension: str) -> str:
    suffix = extension.lower().lstrip(".")
    mime = "image/jpeg" if suffix in {"jpg", "jpeg"} else f"image/{suffix or 'png'}"
    return f"data:{mime};base64,{base64.b64encode(data).decode('ascii')}"


def _runner(*, base_url: str, api_key: str, model: str, max_tokens: int, max_observations: int):
    client = OpenAI(base_url=base_url.rstrip("/") + "/", api_key=api_key)
    prompt = v3_model_prompt(max_observations=max_observations)

    def run(_asset, image: bytes, extension: str, timeout_seconds: int):
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": "Return strict JSON only."},
                {"role": "user", "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": _image_data_url(image, extension)}},
                ]},
            ],
            temperature=0,
            max_tokens=max_tokens,
            timeout=timeout_seconds,
        )
        choice = (response.choices or [None])[0]
        content = getattr(getattr(choice, "message", None), "content", "")
        return parse_v3_model_json(content)

    return run


def run(*, limit: int, timeout_seconds: int, max_tokens: int, max_observations: int,
        base_url: str, api_key: str, model: str) -> dict:
    db = SessionLocal()
    guard = ReadOnlyDatabaseGuard(db)
    try:
        guard.enable()
        assets = _current_approved_media_query(db, "size_image").limit(max(1, limit)).all()
        extractor = ProductMediaObservationV3Extractor(_runner(
            base_url=base_url, api_key=api_key, model=model, max_tokens=max_tokens, max_observations=max_observations,
        ))
        rows = []
        for asset in assets:
            image_result = extractor.extract_asset(asset, timeout_seconds=timeout_seconds)
            rows.append(image_result)
    finally:
        guard.close()
        db.close()
    observations = [item for row in rows for item in row["observations"]]
    rejected = [item for row in rows for item in row["rejected_evidence"]]
    return {
        "summary": {
            "schema_version": "product_media_observation_v3_shadow_report",
            "shadow_only": True,
            "database_query_only": guard.enabled,
            "formal_kb_write_attempt_count": guard.write_attempt_count,
            "scanned_count": len(rows),
            "observation_count": len(observations),
            "rejected_count": len(rejected),
            "subject_scope_counts": dict(sorted(Counter(item["subject_scope"] for item in observations).items())),
            "observation_type_counts": dict(sorted(Counter(item["observation_type"] for item in observations).items())),
            "rejected_reason_counts": dict(sorted(Counter(item["reason"] for item in rejected).items())),
            "can_change_can_send_count": sum(1 for item in observations if item["can_change_can_send"]),
        },
        "results": rows,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, required=True)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--api-key-env", default="COPILOT_VLM_API_KEY")
    parser.add_argument("--timeout-seconds", type=int, default=45)
    parser.add_argument("--max-tokens", type=int, default=1024)
    parser.add_argument("--max-observations", type=int, default=5)
    parser.add_argument("--json-output", required=True)
    args = parser.parse_args()
    api_key = os.getenv(args.api_key_env, "")
    if not api_key:
        parser.error("configured API key environment variable is required")
    report = run(
        limit=args.limit, timeout_seconds=args.timeout_seconds, max_tokens=args.max_tokens,
        max_observations=args.max_observations, base_url=args.base_url, api_key=api_key, model=args.model,
    )
    output = PROJECT_ROOT / args.json_output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report["summary"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
