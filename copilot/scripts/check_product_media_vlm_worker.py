"""Read-only health/readiness snapshot for the offline product-media worker."""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import requests

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _get(base_url: str, path: str) -> tuple[bool, object]:
    try:
        response = requests.get(f"{base_url.rstrip('/')}{path}", timeout=5)
        if response.status_code >= 400:
            return False, {"status": response.status_code}
        try:
            return True, response.json()
        except ValueError:
            return True, {}
    except requests.Timeout:
        return False, {"category": "timeout_error"}
    except requests.ConnectionError:
        return False, {"category": "connection_error"}


def snapshot(base_url: str) -> dict:
    health_ok, _ = _get(base_url, "/health")
    models_ok, models = _get(base_url, "/v1/models")
    load_ok, load = _get(base_url, "/load")
    model_ids = [str(item.get("id") or "") for item in (models.get("data") or [])] if isinstance(models, dict) else []
    return {
        "worker_scope": "offline_shadow_only",
        "checked_at_epoch_ms": int(time.time() * 1000),
        "health_ok": health_ok,
        "ready": bool(health_ok and models_ok and model_ids),
        "model_ids": model_ids,
        "load_available": load_ok,
        "load": load if isinstance(load, dict) else {},
        "active_request_count": None,
        "queue_depth": None,
        "last_failure_category": "",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8001")
    parser.add_argument("--json-output", default="outputs/product_media_vlm_worker_health.json")
    args = parser.parse_args(argv)
    report = snapshot(args.base_url)
    output = PROJECT_ROOT / args.json_output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"health_ok": report["health_ok"], "ready": report["ready"], "model_count": len(report["model_ids"])}, ensure_ascii=False))
    return 0 if report["ready"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
