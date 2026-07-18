"""Build a privacy-safe, non-combined three-tier business accuracy matrix."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.services.business_accuracy_matrix_service import build_business_accuracy_matrix  # noqa: E402
from app.services.real_accuracy_gold_set_service import validate_gold_dataset  # noqa: E402
from app.services.real_accuracy_privacy_service import scan_privacy_output  # noqa: E402


def _load(path: str) -> dict[str, Any]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("json_object_required")
    return value


def _runtime_metadata(database: str) -> dict[str, Any]:
    try:
        commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=PROJECT_ROOT, text=True).strip()
    except (OSError, subprocess.CalledProcessError):
        commit = ""
    metadata = {
        "runtime_commit": commit,
        "formal_evidence_convergence_enabled": os.environ.get("COPILOT_FORMAL_EVIDENCE_CONVERGENCE_ENABLED", "").strip().lower() in {"1", "true", "yes", "on"},
    }
    if database:
        path = Path(database).expanduser().resolve()
        if not path.is_file():
            raise ValueError("runtime_database_unavailable")
        with path.open("rb") as handle:
            metadata["runtime_database_sha256"] = hashlib.file_digest(handle, "sha256").hexdigest()
    return metadata


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gold-set", required=True)
    parser.add_argument("--tier-a-baseline", required=True)
    parser.add_argument("--tier-b-report", required=True)
    parser.add_argument("--tier-c-smoke", required=True)
    parser.add_argument("--tier-c-full", required=True)
    parser.add_argument("--json-output", required=True)
    parser.add_argument("--runtime-database", default="")
    args = parser.parse_args(argv)
    try:
        gold = _load(args.gold_set)
        findings = validate_gold_dataset(gold)
        if findings or (gold.get("privacy") or {}).get("privacy_scan_status") != "passed":
            raise ValueError("gold_set_privacy_validation_failed")
        report = build_business_accuracy_matrix(
            tier_a_dataset=gold,
            tier_a_baseline=_load(args.tier_a_baseline),
            tier_b_report=_load(args.tier_b_report),
            tier_c_smoke=_load(args.tier_c_smoke),
            tier_c_full=_load(args.tier_c_full),
            runtime=_runtime_metadata(args.runtime_database),
        )
        privacy = scan_privacy_output(report)
        if privacy:
            raise ValueError("matrix_privacy_scan_failed")
        output = Path(args.json_output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({
            "tier_a_status": (report.get("tier_a_real_gold") or {}).get("status"),
            "tier_b_cases": (report.get("tier_b_real_derived_capability") or {}).get("case_count"),
            "tier_c_full": ((report.get("tier_c_synthetic_safety") or {}).get("full") or {}).get("executed"),
        }, ensure_ascii=False))
        return 0
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(json.dumps({"status": "blocked", "reason": str(exc)}, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
