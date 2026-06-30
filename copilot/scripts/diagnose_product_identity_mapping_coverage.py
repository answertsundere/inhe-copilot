"""Diagnose ProductIdentityMapping coverage for real replay traces.

This script is read-only. It counts platform identity signals in replay traces
and checks whether those signals can already resolve through trusted mappings.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill
from sqlalchemy import or_

from app.db import SessionLocal, init_db
from app.models.eval_tables import EvalRun, EvalTrace
from app.models.kb_tables import ProductIdentityMapping
from app.services.eval_sanitizer_service import sanitize_obj, sanitize_text


def _latest_run_uid(db) -> str:
    run = (
        db.query(EvalRun)
        .filter(EvalRun.source_type == "real_conversation", EvalRun.status == "completed")
        .order_by(EvalRun.created_at.desc(), EvalRun.id.desc())
        .first()
    )
    return run.run_uid if run else ""


def _first_text(*values: Any) -> str:
    for value in values:
        text = sanitize_text(str(value or "")).strip()
        if text:
            return text
    return ""


def _first_raw(*values: Any) -> str:
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return ""


def _safe_url(value: str) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    try:
        parts = urlsplit(raw)
        if parts.scheme:
            return sanitize_text(f"{parts.scheme}://{parts.netloc}{parts.path}")
    except Exception:
        pass
    return sanitize_text(raw)


def _url_host(value: str) -> str:
    try:
        return sanitize_text(urlsplit(str(value or "")).netloc.lower())
    except Exception:
        return ""


def _is_redacted_id(value: str) -> bool:
    return "[LONG_ID_REDACTED:" in str(value or "")


def _trace_identity(trace: EvalTrace) -> dict[str, str]:
    raw = trace.get_raw_response() or {}
    answer_trace = trace.get_answer_trace() or {}
    product_identity = trace.get_product_identity() or {}
    real_from_product_identity = product_identity.get("real_context_product_identity") if isinstance(product_identity, dict) else {}
    containers = [
        real_from_product_identity if isinstance(real_from_product_identity, dict) else {},
        raw.get("real_context_product_identity") if isinstance(raw, dict) and isinstance(raw.get("real_context_product_identity"), dict) else {},
        answer_trace.get("real_context_product_identity") if isinstance(answer_trace, dict) and isinstance(answer_trace.get("real_context_product_identity"), dict) else {},
        product_identity if isinstance(product_identity, dict) else {},
    ]
    item_id = _first_text(*(c.get("item_id") for c in containers))
    item_hash = _first_text(*(c.get("item_id_hash") for c in containers))
    product_url = _safe_url(_first_raw(*(c.get("product_url") for c in containers)))
    return {
        "platform_item_id": "" if _is_redacted_id(item_id) else item_id,
        "platform_item_id_hash": item_hash,
        "product_url": product_url,
        "product_url_host": _url_host(product_url),
        "platform_product_title": _first_text(*(c.get("product_title") for c in containers), *(c.get("display_product_name") for c in containers)),
        "order_product_title": _first_text(*(c.get("order_product_title") for c in containers)),
        "i_id": _first_text(*(c.get("i_id") for c in containers), product_identity.get("i_id") if isinstance(product_identity, dict) else ""),
        "sku_code": _first_text(*(c.get("sku_code") for c in containers), product_identity.get("sku_code") if isinstance(product_identity, dict) else ""),
    }


def _mapping_status(db, identity: dict[str, str]) -> tuple[bool, str]:
    filters = []
    if identity.get("platform_item_id"):
        filters.append(ProductIdentityMapping.platform_item_id == identity["platform_item_id"])
    if identity.get("platform_item_id_hash"):
        filters.append(ProductIdentityMapping.platform_item_id_hash == identity["platform_item_id_hash"])
    if identity.get("product_url_host") and (identity.get("platform_item_id") or identity.get("platform_item_id_hash")):
        filters.append(ProductIdentityMapping.product_url_host == identity["product_url_host"])
    if not filters:
        return False, "no_mapping_identity_signal"
    rows = (
        db.query(ProductIdentityMapping)
        .filter(ProductIdentityMapping.status.in_(["active", "verified", "confirmed"]))
        .filter(or_(*filters))
        .limit(20)
        .all()
    )
    if not rows:
        return False, "not_found"
    product_ids = {row.kb_product_id for row in rows if row.kb_product_id}
    if len(product_ids) > 1:
        return False, "ambiguous"
    return True, "exact_item_hash" if identity.get("platform_item_id_hash") else "exact_platform_item_id"


def collect_coverage(run_uid: str = "", db_factory=None) -> dict[str, Any]:
    db_factory = db_factory or SessionLocal
    db = db_factory()
    try:
        target_run_uid = sanitize_text(run_uid) or _latest_run_uid(db)
        traces = (
            db.query(EvalTrace)
            .filter(EvalTrace.run_uid == target_run_uid)
            .order_by(EvalTrace.case_uid.asc(), EvalTrace.turn_index.asc(), EvalTrace.id.asc())
            .all()
            if target_run_uid
            else []
        )
        counts = Counter()
        methods = Counter()
        rows: list[dict[str, Any]] = []
        unique_hashes: set[str] = set()
        unique_hosts: set[str] = set()
        for trace in traces:
            identity = _trace_identity(trace)
            has_platform = any(identity.get(key) for key in ("platform_item_id", "platform_item_id_hash", "product_url"))
            has_title = bool(identity.get("platform_product_title") or identity.get("order_product_title"))
            if has_platform:
                counts["turns_with_platform_identity"] += 1
            if identity.get("platform_item_id"):
                counts["turns_with_item_id"] += 1
            if identity.get("platform_item_id_hash"):
                counts["turns_with_item_hash"] += 1
                unique_hashes.add(identity["platform_item_id_hash"])
            if identity.get("product_url"):
                counts["turns_with_product_url"] += 1
            if has_title and not has_platform:
                counts["turns_with_product_title_only"] += 1
            if identity.get("product_url_host"):
                unique_hosts.add(identity["product_url_host"])
            mapped, method = _mapping_status(db, identity)
            if has_platform and mapped:
                counts["turns_already_mapped"] += 1
                methods[method] += 1
            elif has_platform:
                counts["turns_unmapped"] += 1
                methods["not_found" if method == "not_found" else method] += 1
            elif has_title:
                methods["title_only_not_used"] += 1
            rows.append(sanitize_obj({
                "run_uid": trace.run_uid,
                "case_uid": trace.case_uid,
                "turn_uid": trace.turn_uid,
                "turn_index": trace.turn_index,
                **identity,
                "mapping_status": "mapped" if mapped else "unmapped",
                "match_method": method if has_platform or has_title else "no_identity_signal",
            }))
        return sanitize_obj({
            "ok": True,
            "run_uid": target_run_uid,
            "replay_turn_count": len(traces),
            "turns_with_platform_identity": counts["turns_with_platform_identity"],
            "turns_with_item_id": counts["turns_with_item_id"],
            "turns_with_item_hash": counts["turns_with_item_hash"],
            "turns_with_product_url": counts["turns_with_product_url"],
            "turns_with_product_title_only": counts["turns_with_product_title_only"],
            "turns_already_mapped": counts["turns_already_mapped"],
            "turns_unmapped": counts["turns_unmapped"],
            "unmapped_unique_item_hash_count": len(unique_hashes),
            "unmapped_unique_product_url_host_count": len(unique_hosts),
            "candidate_match_count_by_method": dict(methods),
            "rows": rows,
        })
    finally:
        db.close()


def write_excel(result: dict[str, Any], output: str) -> str:
    headers = [
        "run_uid",
        "case_uid",
        "turn_uid",
        "turn_index",
        "platform_item_id",
        "platform_item_id_hash",
        "product_url",
        "product_url_host",
        "platform_product_title",
        "order_product_title",
        "mapping_status",
        "match_method",
    ]
    workbook = Workbook()
    ws = workbook.active
    ws.title = "coverage"
    ws.append(headers)
    for cell in ws[1]:
        cell.font = Font(bold=True)
        cell.fill = PatternFill("solid", fgColor="D9EAF7")
    for row in result.get("rows", []):
        ws.append([row.get(key, "") for key in headers])
    for idx, header in enumerate(headers, start=1):
        ws.column_dimensions[ws.cell(row=1, column=idx).column_letter].width = max(14, min(42, len(header) + 4))
    Path(output).parent.mkdir(parents=True, exist_ok=True)
    workbook.save(output)
    return output


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    today = datetime.now().strftime("%Y%m%d")
    parser = argparse.ArgumentParser(description="Diagnose product identity mapping coverage.")
    parser.add_argument("--run-uid", default="")
    parser.add_argument("--json-output", default=f"outputs/product_identity_mapping_coverage_{today}.json")
    parser.add_argument("--excel-output", default=str(Path.home() / "Desktop" / f"商品身份映射覆盖诊断_{today}.xlsx"))
    args = parser.parse_args()
    init_db()
    result = collect_coverage(args.run_uid)
    if args.json_output:
        output = Path(args.json_output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps({k: v for k, v in result.items() if k != "rows"}, ensure_ascii=False, indent=2), encoding="utf-8")
    if args.excel_output:
        write_excel(result, args.excel_output)
    print(json.dumps({k: v for k, v in result.items() if k != "rows"}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
