"""Write a sanitized, read-only readiness report for semantic object grounding."""

from __future__ import annotations

import argparse
import json
import platform
import shutil
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from app.services.eval_sanitizer_service import sanitize_obj  # noqa: E402
from app.services.semantic_object_grounding_provider_service import semantic_object_runtime_status  # noqa: E402


def _directory_summary(path: Path, *, label: str) -> dict[str, Any]:
    if not path.is_dir():
        return {"label": label, "exists": False, "candidate_model_entry_count": 0}
    candidates = [item for item in path.iterdir() if "grounding" in item.name.lower() or "florence" in item.name.lower()]
    return {"label": label, "exists": True, "candidate_model_entry_count": len(candidates)}


def _disk_summary(path: Path, *, label: str) -> dict[str, Any]:
    try:
        usage = shutil.disk_usage(path)
        return {"label": label, "free_bytes": usage.free, "total_bytes": usage.total}
    except OSError:
        return {"label": label, "free_bytes": None, "total_bytes": None}


def build_readiness_report() -> dict[str, Any]:
    runtime = semantic_object_runtime_status()
    cache_root = Path.home() / ".cache" / "huggingface" / "hub"
    return {
        "schema_version": "semantic_object_runtime_readiness_v1",
        "python_version": platform.python_version(),
        "platform": platform.system(),
        "semantic_runtime": runtime,
        "model_storage": [
            _directory_summary(cache_root, label="huggingface_hub_cache"),
            _directory_summary(Path("D:/AIModels"), label="ai_models"),
        ],
        "disk": [_disk_summary(Path("C:/"), label="system_drive"), _disk_summary(Path("D:/"), label="data_drive")],
        "provider_route": "groundingdino" if runtime["modules"]["groundingdino"] else "florence2_fallback" if runtime["modules"]["transformers"] else "provider_not_configured",
        "shadow_only": True,
        "formal_kb_write_attempt_count": 0,
        "can_change_can_send": False,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json-output", default="outputs/semantic_object_runtime_readiness.json")
    args = parser.parse_args(argv)
    output = PROJECT_ROOT / args.json_output
    output.parent.mkdir(parents=True, exist_ok=True)
    report = build_readiness_report()
    output.write_text(json.dumps(sanitize_obj(report), ensure_ascii=True, indent=2), encoding="utf-8")
    print(json.dumps({"provider_route": report["provider_route"], "modules": report["semantic_runtime"]["modules"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
