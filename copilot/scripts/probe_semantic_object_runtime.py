"""Run one fail-closed semantic-object runtime probe without writing observations."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path
from typing import Any, Callable

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from app.services.eval_sanitizer_service import sanitize_obj
from app.services.semantic_object_grounding_provider_service import (
    GENERIC_CLASS_QUERIES,
    execute_semantic_object_provider,
    preferred_semantic_object_provider,
)
from app.services.vision_grounding_provider_qualification_service import is_normalized_bbox

_ALLOWED_QUERY_TERMS = set(GENERIC_CLASS_QUERIES) | {term for values in GENERIC_CLASS_QUERIES.values() for term in values}


def _sanitize_error(value: Any) -> str:
    text = str(value or "").replace("\\", "/")
    text = text.replace(str(PROJECT_ROOT).replace("\\", "/"), "<project>")
    return text[:240]


def parse_generic_queries(value: str) -> tuple[str, ...]:
    terms = tuple(item.strip().lower() for item in str(value or "").split(",") if item.strip())
    if not terms or any(item not in _ALLOWED_QUERY_TERMS for item in terms):
        raise ValueError("probe_queries_must_use_generic_category_terms")
    return terms


def probe_class_queries(queries: tuple[str, ...]) -> dict[str, tuple[str, ...]]:
    """Keep the provider's generic query-to-scope mapping during a probe."""
    return {
        object_type: tuple(query for query in values if query in queries)
        for object_type, values in GENERIC_CLASS_QUERIES.items()
        if any(query in queries for query in values)
    }


def run_probe(
    *, provider_name: str, image_path: Path, queries: tuple[str, ...],
    infer: Callable[[bytes, dict[str, tuple[str, ...]]], list[dict[str, Any]]] | None = None,
) -> dict[str, Any]:
    started = time.perf_counter()
    provider = preferred_semantic_object_provider(requested_provider=provider_name)
    base = {
        "schema_version": "semantic_object_runtime_probe_v1", "provider_name": provider.get("provider_name"),
        "model_name": provider.get("model_name") or "", "runtime_available": bool(provider.get("configured")),
        "weights_available": bool(provider.get("configured")), "queries": list(queries),
        "execution_success": False, "bbox_count": 0, "normalized_bbox_count": 0,
        "labels": [], "confidence": [], "error_type": "", "error_message_sanitized": "",
        "shadow_only": True, "formal_kb_write_attempt_count": 0, "can_change_can_send": False,
    }
    if not provider.get("configured"):
        base.update({"error_type": "provider_not_configured", "error_message_sanitized": _sanitize_error(", ".join(provider.get("missing_requirements") or ["semantic_object_provider_unavailable"]))})
        base["latency_ms"] = round((time.perf_counter() - started) * 1000, 2)
        return base
    try:
        image_data = image_path.read_bytes()
    except OSError as exc:
        base.update({"error_type": "image_read_failed", "error_message_sanitized": _sanitize_error(type(exc).__name__)})
        base["latency_ms"] = round((time.perf_counter() - started) * 1000, 2)
        return base
    result = execute_semantic_object_provider(
        provider=provider, image_data=image_data, image_sha256=hashlib.sha256(image_data).hexdigest(),
        image_size=None, panels=None, ocr_items=[], class_queries=probe_class_queries(queries), infer=infer,
    )
    objects = list(result.get("objects") or [])
    base.update({
        "execution_success": not result.get("execution_error") and not result.get("schema_error"),
        "bbox_count": len(objects), "normalized_bbox_count": sum(1 for item in objects if is_normalized_bbox(item.get("bbox"))),
        "labels": [str(item.get("object_label") or "") for item in objects],
        "confidence": [item.get("confidence") for item in objects],
        "error_type": result.get("execution_error") or result.get("schema_error") or "",
        "error_message_sanitized": _sanitize_error((result.get("diagnostics") or [{}])[0].get("reason")),
        "latency_ms": round((time.perf_counter() - started) * 1000, 2),
    })
    return base


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--provider", choices=("groundingdino", "florence2"), required=True)
    parser.add_argument("--image", required=True)
    parser.add_argument("--queries", default="product,packaging,component,accessory")
    parser.add_argument("--json-output", default="outputs/semantic_object_runtime_probe.json")
    args = parser.parse_args(argv)
    report = run_probe(provider_name=args.provider, image_path=Path(args.image), queries=parse_generic_queries(args.queries))
    output = PROJECT_ROOT / args.json_output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(sanitize_obj(report), ensure_ascii=True, indent=2), encoding="utf-8")
    print(json.dumps({key: report[key] for key in ("provider_name", "runtime_available", "weights_available", "execution_success", "error_type")}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
