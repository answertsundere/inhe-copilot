"""Build an explicit, hash-verified manifest of acceptance report roles."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.api.runtime_routes import _source_tree_sha256 as _runtime_source_tree_sha256  # noqa: E402
from app.services.real_accuracy_gold_set_service import validate_gold_dataset  # noqa: E402


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _git_commit() -> str:
    try:
        return subprocess.check_output(
            ["git", "-C", str(PROJECT_ROOT), "rev-parse", "HEAD"],
            text=True,
            encoding="utf-8",
            stderr=subprocess.DEVNULL,
        ).strip()
    except (OSError, subprocess.SubprocessError):
        return "unavailable"


def _source_tree_sha256() -> str:
    return _runtime_source_tree_sha256()


def _report_entry(value: str, *, require_json: bool, with_reason: bool = False) -> dict[str, Any]:
    raw_path, separator, reason = value.partition("::")
    if with_reason and (not separator or not reason.strip()):
        raise ValueError("superseded_report_reason_required")
    path = Path(raw_path).expanduser().resolve()
    if not path.is_file():
        raise ValueError(f"report_not_found:{path.name}")
    raw = path.read_bytes()
    json_valid = True
    try:
        json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        json_valid = False
    if require_json and not json_valid:
        raise ValueError(f"authoritative_report_json_invalid:{path.name}")
    entry: dict[str, Any] = {
        "file_name": path.name,
        "sha256": _sha256(raw),
        "size_bytes": len(raw),
        "json_valid": json_valid,
    }
    if with_reason:
        entry["reason"] = reason.strip()
    return entry


def _report_index_hash(manifest: dict[str, Any]) -> str:
    payload = {
        key: manifest[key]
        for key in ("authoritative_reports", "attempt_reports", "superseded_reports")
    }
    return _sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8"))


def _feature_flags(json_value: str, values: list[str]) -> dict[str, Any]:
    parsed = json.loads(json_value)
    if not isinstance(parsed, dict):
        raise ValueError("feature_flags_object_required")
    for value in values:
        name, separator, raw = value.partition("=")
        if not separator or not name.strip() or raw.strip().lower() not in {"true", "false"}:
            raise ValueError("feature_flag_invalid")
        parsed[name.strip()] = raw.strip().lower() == "true"
    return dict(sorted(parsed.items()))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--phase", required=True)
    parser.add_argument("--dataset", required=True)
    parser.add_argument("--authoritative-report", action="append", default=[])
    parser.add_argument("--attempt-report", action="append", default=[])
    parser.add_argument("--superseded-report", action="append", default=[])
    parser.add_argument("--acceptance-status", required=True)
    parser.add_argument("--feature-flags-json", default="{}")
    parser.add_argument("--feature-flag", action="append", default=[])
    parser.add_argument("--provider", default="not_run")
    parser.add_argument("--model", default="not_run")
    parser.add_argument("--json-output", required=True)
    args = parser.parse_args(argv)
    try:
        dataset_path = Path(args.dataset).expanduser().resolve()
        dataset = json.loads(dataset_path.read_text(encoding="utf-8"))
        findings = validate_gold_dataset(dataset)
        if findings:
            raise ValueError("gold_dataset_validation_failed")
        feature_flags = _feature_flags(args.feature_flags_json, args.feature_flag)
        all_values = list(args.authoritative_report) + list(args.attempt_report) + [
            value.partition("::")[0] for value in args.superseded_report
        ]
        resolved = [str(Path(value).expanduser().resolve()).lower() for value in all_values]
        if len(resolved) != len(set(resolved)):
            raise ValueError("report_role_duplicate")
        manifest = {
            "schema_version": "authoritative-output-manifest-v1",
            "phase": args.phase,
            "runtime_commit": _git_commit(),
            "source_tree_sha256": _source_tree_sha256(),
            "dataset": {
                "dataset_id": dataset.get("dataset_id"),
                "dataset_version": dataset.get("dataset_version"),
                "content_sha256": (dataset.get("manifest") or {}).get("content_sha256"),
                "case_count": len(dataset.get("cases") or []),
            },
            "feature_flags": feature_flags,
            "provider": args.provider,
            "model": args.model,
            "authoritative_reports": [
                _report_entry(value, require_json=True) for value in args.authoritative_report
            ],
            "attempt_reports": [
                _report_entry(value, require_json=False) for value in args.attempt_report
            ],
            "superseded_reports": [
                _report_entry(value, require_json=False, with_reason=True) for value in args.superseded_report
            ],
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "acceptance_status": args.acceptance_status,
        }
        manifest["report_sha256"] = _report_index_hash(manifest)
        output = Path(args.json_output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({
            "acceptance_status": manifest["acceptance_status"],
            "authoritative_report_count": len(manifest["authoritative_reports"]),
            "attempt_report_count": len(manifest["attempt_reports"]),
            "superseded_report_count": len(manifest["superseded_reports"]),
            "report_sha256": manifest["report_sha256"],
        }, ensure_ascii=False))
        return 0
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(json.dumps({"status": "blocked", "reason": str(exc)}, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
