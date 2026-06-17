#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Sync DingTalk activity rules into product-scoped customer-safe records.

Default mode is dry-run. Use --apply to write kb_product_activity_rule.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

import requests


PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

env_path = PROJECT_ROOT / ".env"
if env_path.exists():
    try:
        from dotenv import load_dotenv

        load_dotenv(dotenv_path=env_path)
    except Exception:
        pass


def get_access_token(client_id: str, client_secret: str) -> str:
    resp = requests.post(
        "https://api.dingtalk.com/v1.0/oauth2/accessToken",
        json={"appKey": client_id, "appSecret": client_secret},
        timeout=30,
    )
    data = resp.json()
    if resp.status_code != 200 or not data.get("accessToken"):
        raise RuntimeError(f"failed to get DingTalk token: {data}")
    return data["accessToken"]


def fetch_all_records(base_id: str, sheet_id: str, operator_id: str, token: str) -> list[dict[str, Any]]:
    url = f"https://api.dingtalk.com/v1.0/notable/bases/{base_id}/sheets/{sheet_id}/records/list"
    headers = {
        "x-acs-dingtalk-access-token": token,
        "Content-Type": "application/json",
    }
    records: list[dict[str, Any]] = []
    next_token = None
    while True:
        body = {"maxResults": 100}
        if next_token:
            body["nextToken"] = next_token
        resp = requests.post(
            url,
            headers=headers,
            params={"operatorId": operator_id},
            json=body,
            timeout=60,
        )
        if resp.status_code != 200:
            raise RuntimeError(f"DingTalk records/list failed: {resp.status_code} {resp.text[:300]}")
        data = resp.json()
        records.extend(data.get("records") or [])
        next_token = data.get("nextToken")
        if not next_token:
            break
        time.sleep(0.2)
    return records


def find_product(db, KBProduct, normalized: dict[str, Any]):
    i_id = str(normalized.get("i_id") or "").strip()
    sku_code = str(normalized.get("sku_code") or "").strip()
    product_name = str(normalized.get("product_name") or "").strip()
    if i_id:
        product = db.query(KBProduct).filter(KBProduct.i_id == i_id).first()
        if product:
            return product
    if sku_code:
        product = db.query(KBProduct).filter(KBProduct.i_id == sku_code).first()
        if product:
            return product
        for product in db.query(KBProduct).all():
            sku_text = json.dumps(product.get_sku_list(), ensure_ascii=False)
            if sku_code.upper() in sku_text.upper():
                return product
    if product_name:
        product = db.query(KBProduct).filter(KBProduct.product_name == product_name).first()
        if product:
            return product
        for product in db.query(KBProduct).filter(KBProduct.status == "published").all():
            if product_name in product.product_name or product.product_name in product_name:
                return product
    return None


def build_report_item(normalized: dict[str, Any], action: str, matched_product: Any = None) -> dict[str, Any]:
    return {
        "action": action,
        "status": normalized.get("status"),
        "auto_reply_allowed": normalized.get("auto_reply_allowed"),
        "matched_product_id": getattr(matched_product, "id", None),
        "i_id": normalized.get("i_id", ""),
        "sku_code": normalized.get("sku_code", ""),
        "product_name": normalized.get("product_name", ""),
        "activity_type": normalized.get("activity_type", ""),
        "title": normalized.get("title", ""),
        "customer_visible_benefit": normalized.get("customer_visible_benefit", ""),
        "has_internal_price": bool(normalized.get("internal_price_field")),
        "internal_price_field": normalized.get("internal_price_field", ""),
        "source_record_id": normalized.get("source_record_id", ""),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Sync DingTalk activity rules into kb_product_activity_rule")
    parser.add_argument("--apply", action="store_true", help="Write DB changes. Without this flag, dry-run only.")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument(
        "--base-id",
        default=os.environ.get("COPILOT_DT_ACTIVITY_BASE_ID") or os.environ.get("COPILOT_DT_BASE_ID", ""),
    )
    parser.add_argument("--sheet-id", default=os.environ.get("COPILOT_DT_ACTIVITY_SHEET_ID", "nlpDg8l"))
    parser.add_argument("--operator-id", default=os.environ.get("COPILOT_DT_OPERATOR_ID", ""))
    parser.add_argument("--output", default=str(PROJECT_ROOT / "reports" / "dingtalk_activity_rules_report.json"))
    args = parser.parse_args()

    missing = [
        name
        for name, value in (
            ("COPILOT_DT_CLIENT_ID", os.environ.get("COPILOT_DT_CLIENT_ID", "")),
            ("COPILOT_DT_CLIENT_SECRET", os.environ.get("COPILOT_DT_CLIENT_SECRET", "")),
            ("COPILOT_DT_OPERATOR_ID", args.operator_id),
            ("COPILOT_DT_BASE_ID", args.base_id),
        )
        if not value
    ]
    if missing:
        raise SystemExit(f"missing DingTalk env: {', '.join(missing)}")

    from app.db import SessionLocal, init_db
    from app.models.kb_tables import KBProduct, KBProductActivityRule
    from app.services.product_activity_rule_service import normalize_activity_record, upsert_activity_rule

    token = get_access_token(os.environ["COPILOT_DT_CLIENT_ID"], os.environ["COPILOT_DT_CLIENT_SECRET"])
    records = fetch_all_records(args.base_id, args.sheet_id, args.operator_id, token)
    if args.limit:
        records = records[: args.limit]

    init_db()
    db = SessionLocal()
    report = {
        "mode": "apply" if args.apply else "dry_run",
        "sheet_id": args.sheet_id,
        "total_records": len(records),
        "created": 0,
        "updated": 0,
        "unchanged": 0,
        "active_ready": 0,
        "pending_review": 0,
        "matched_product": 0,
        "unmatched_product": 0,
        "internal_price_records": 0,
        "items": [],
    }
    try:
        for record in records:
            normalized = normalize_activity_record(
                record.get("fields") or {},
                source_record_id=str(record.get("id") or record.get("recordId") or ""),
                source_sheet_id=args.sheet_id,
            )
            product = find_product(db, KBProduct, normalized)
            if product:
                normalized["product_id"] = product.id
                normalized["i_id"] = normalized.get("i_id") or product.i_id
                normalized["product_name"] = normalized.get("product_name") or product.product_name
                report["matched_product"] += 1
            else:
                report["unmatched_product"] += 1

            if normalized.get("status") == "active":
                report["active_ready"] += 1
            else:
                report["pending_review"] += 1
            if normalized.get("internal_price_field"):
                report["internal_price_records"] += 1

            if args.apply:
                _, action = upsert_activity_rule(db, KBProductActivityRule, normalized)
                report[action] += 1
            else:
                action = "dry_run"
            report["items"].append(build_report_item(normalized, action, product))
        if args.apply:
            db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k != "items"}, ensure_ascii=False, indent=2))
    print(f"report: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
