"""Run privacy-safe, backup-based formal knowledge write diagnostics."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from app.services.formal_knowledge_database_guard_service import (  # noqa: E402
    backup_sqlite_database,
    compare_formal_knowledge_fingerprints,
    fingerprint_formal_knowledge_tables,
    formal_kb_audit_hmac_key,
)


def _json_request(url: str, *, payload: dict[str, Any] | None = None, timeout: int = 30) -> tuple[int, dict[str, Any]]:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload is not None else None
    request = Request(url, data=body, headers={"Content-Type": "application/json"})
    try:
        with urlopen(request, timeout=timeout) as response:
            parsed = json.loads(response.read().decode("utf-8"))
            return int(response.status), parsed if isinstance(parsed, dict) else {}
    except HTTPError as exc:
        return int(exc.code), {}
    except (OSError, URLError, ValueError):
        return 0, {}


def _dml_records(path: Path, start_offset: int) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8") as handle:
        handle.seek(start_offset)
        return [json.loads(line) for line in handle if line.strip()]


def _public_fingerprint(fingerprint: dict[str, Any]) -> dict[str, Any]:
    return {
        **{key: value for key, value in fingerprint.items() if key != "formal_tables"},
        "formal_tables": [
            {key: value for key, value in table.items() if key != "rows"}
            for table in fingerprint.get("formal_tables") or []
        ],
    }


def run(args) -> dict[str, Any]:
    database = Path(args.database)
    if args.source_db and not database.exists():
        backup_sqlite_database(Path(args.source_db), database)
    if not database.exists():
        raise ValueError("diagnostic_database_missing")
    key = formal_kb_audit_hmac_key()
    if not key:
        raise ValueError("formal_kb_audit_hmac_key_required")
    dml_path = Path(args.dml_diagnostics) if args.dml_diagnostics else Path()
    dml_offset = dml_path.stat().st_size if args.dml_diagnostics and dml_path.exists() else 0
    before = fingerprint_formal_knowledge_tables(database, hmac_key=key)
    probe: dict[str, Any] = {"mode": args.mode, "http_statuses": []}

    if args.mode == "idle":
        time.sleep(args.duration)
    elif args.mode == "health":
        for endpoint in ("/api/health", "/api/runtime/readiness", "/api/runtime/version"):
            status, _ = _json_request(args.base_url.rstrip("/") + endpoint, timeout=args.timeout)
            probe["http_statuses"].append({"endpoint": endpoint, "status": status})
    elif args.mode == "analyze":
        if not args.analyze_payload:
            raise ValueError("analyze_payload_required")
        payload = json.loads(Path(args.analyze_payload).read_text(encoding="utf-8"))
        status, response = _json_request(
            args.base_url.rstrip("/") + "/api/analyze", payload=payload, timeout=args.timeout
        )
        probe["http_statuses"].append({"endpoint": "/api/analyze", "status": status})
        probe["response_contract"] = {
            "reply_nonempty": bool(str(response.get("suggested_reply") or response.get("reply") or "").strip()),
            "can_send": bool(response.get("can_send")),
            "requires_human_review": bool(response.get("requires_human_review")),
            "reply_status": str(response.get("reply_status") or ""),
        }

    after = fingerprint_formal_knowledge_tables(database, hmac_key=key)
    diff = compare_formal_knowledge_fingerprints(before, after)
    dml_rows = _dml_records(dml_path, dml_offset) if args.dml_diagnostics else []
    return {
        "schema_version": "formal-knowledge-write-owner-diagnostic/v1",
        "database": database.name,
        "query_only_expected": True,
        "probe": probe,
        "before": _public_fingerprint(before),
        "after": _public_fingerprint(after),
        "diff": diff,
        "dml_attempt_count": len(dml_rows),
        "formal_kb_write_count": int(diff["changed_row_count"]),
        "dml_operation_counts": dict(sorted(Counter(row.get("operation") for row in dml_rows).items())),
        "dml_table_counts": dict(sorted(Counter(row.get("table") for row in dml_rows).items())),
        "dml_events": dml_rows,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", required=True)
    parser.add_argument("--source-db", default="")
    parser.add_argument("--mode", choices=("snapshot", "idle", "health", "analyze"), default="snapshot")
    parser.add_argument("--base-url", default="http://127.0.0.1:5012")
    parser.add_argument("--duration", type=int, default=30)
    parser.add_argument("--timeout", type=int, default=180)
    parser.add_argument("--analyze-payload", default="")
    parser.add_argument("--dml-diagnostics", default="")
    parser.add_argument("--json-output", required=True)
    args = parser.parse_args()
    try:
        report = run(args)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(json.dumps({"status": "invalid_run", "reason": str(exc)}, ensure_ascii=False))
        return 2
    output = Path(args.json_output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({
        "mode": args.mode,
        "changed_row_count": report["diff"]["changed_row_count"],
        "dml_attempt_count": report["dml_attempt_count"],
    }, ensure_ascii=False))
    return 0 if not report["diff"]["changed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
