#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Audit DingTalk product-detail fields missing from kb_product cards.

This script is read-only. It never writes the database.
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


FIELD_TARGETS = {
    "material": ("\u6750\u8d28", "\u6750\u6599", "\u7528\u6599", "material"),
    "dimensions": ("\u5c3a\u5bf8", "\u957f\u5bbd\u9ad8", "\u89c4\u683c", "size", "dimension"),
    "load_capacity": ("\u627f\u91cd", "\u8f7d\u91cd", "\u5bb9\u91cf"),
    "age_range": ("\u9002\u7528\u5e74\u9f84", "\u6708\u9f84", "\u5e74\u9f84"),
    "installation": ("\u5b89\u88c5", "\u7ec4\u88c5", "\u6253\u5b54", "\u8bf4\u660e\u4e66"),
    "detachable": ("\u53ef\u62c6", "\u62c6\u5378", "\u62c6\u88c5"),
    "odor": ("\u6c14\u5473", "\u5473\u9053", "\u5f02\u5473", "\u65e0\u5473"),
    "cleaning_care": ("\u6e05\u6d17", "\u6e05\u6d01", "\u4fdd\u517b", "\u6c34\u6d17"),
    "accessories": ("\u914d\u4ef6", "\u6e05\u5355", "\u96f6\u4ef6", "parts"),
    "certification_report": ("\u8d28\u68c0", "\u5408\u683c\u8bc1", "\u8ba4\u8bc1", "\u68c0\u6d4b"),
    "install_video": ("\u5b89\u88c5\u89c6\u9891", "\u89c6\u9891"),
    "sku_image": ("SKU\u56fe", "\u5546\u54c1\u56fe", "\u5c3a\u5bf8\u56fe"),
    "activity": ("\u6d3b\u52a8", "\u4f18\u60e0", "\u4f18\u60e0\u5238", "\u7ea2\u5305"),
}


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
    headers = {"x-acs-dingtalk-access-token": token, "Content-Type": "application/json"}
    records: list[dict[str, Any]] = []
    next_token = None
    while True:
        body = {"maxResults": 100}
        if next_token:
            body["nextToken"] = next_token
        resp = requests.post(url, headers=headers, params={"operatorId": operator_id}, json=body, timeout=60)
        if resp.status_code != 200:
            raise RuntimeError(f"DingTalk records/list failed: {resp.status_code} {resp.text[:300]}")
        data = resp.json()
        records.extend(data.get("records") or [])
        next_token = data.get("nextToken")
        if not next_token:
            break
        time.sleep(0.2)
    return records


def flatten(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (int, float, bool)):
        return str(value).strip()
    if isinstance(value, dict):
        for key in ("text", "name", "title", "link", "url"):
            if value.get(key):
                return str(value.get(key)).strip()
        return " ".join(flatten(v) for v in value.values() if v is not None).strip()
    if isinstance(value, list):
        return " ".join(flatten(v) for v in value if v is not None).strip()
    return str(value).strip()


def normalize_detail_record(fields: dict[str, Any]) -> dict[str, Any]:
    flat = {str(k): flatten(v) for k, v in (fields or {}).items()}
    i_id = first_value(flat, ("\u5546\u54c1\u7f16\u7801", "i_id", "iid", "\u6b3e\u53f7"))
    if not i_id:
        i_id = derive_parent_iid(flat)
    result = {
        "product_name": first_value(flat, ("\u5546\u54c1\u540d", "\u4ea7\u54c1\u540d", "\u54c1\u540d")),
        "i_id": i_id,
        "sku_code": first_value(flat, ("\u89c4\u683c\u7f16\u7801",)),
        "fields": {},
    }
    for target, tokens in FIELD_TARGETS.items():
        values = []
        for key, value in flat.items():
            key_text = key.lower()
            if value and any(token.lower() in key_text for token in tokens):
                values.append({"source_field": key, "value": value[:300]})
        if values:
            result["fields"][target] = values
    return result


def first_value(flat: dict[str, str], tokens: tuple[str, ...]) -> str:
    for key, value in flat.items():
        key_text = key.lower()
        if any(token.lower() in key_text for token in tokens) and value and is_identity_value(value):
            return value.strip()
    return ""


def is_identity_value(value: str) -> bool:
    text = str(value or "").strip()
    if not text or "http://" in text or "https://" in text or "resourceId" in text:
        return False
    if len(text) > 120:
        return False
    return True


def derive_parent_iid(flat: dict[str, str]) -> str:
    category_code = ""
    style_code = ""
    for key, value in flat.items():
        if key == "\u7c7b\u76ee\u7f16\u53f7":
            category_code = str(value or "").strip().upper()
        if "\u6b3e\u5f0f\u7f16\u53f7" in key:
            style_code = str(value or "").strip().upper()
    if re_match_iid_part(category_code) and re_match_style(style_code):
        return f"{category_code}{style_code}"
    return ""


def re_match_iid_part(value: str) -> bool:
    import re

    return bool(re.fullmatch(r"YH\d{2,3}", value or ""))


def re_match_style(value: str) -> bool:
    import re

    return bool(re.fullmatch(r"K\d{1,3}", value or ""))


def find_product(db, KBProduct, item: dict[str, Any]):
    if item.get("i_id"):
        product = db.query(KBProduct).filter(KBProduct.i_id == item["i_id"]).first()
        if product:
            return product
    sku = item.get("sku_code") or ""
    if sku:
        for product in db.query(KBProduct).all():
            if sku.upper() in json.dumps(product.get_sku_list(), ensure_ascii=False).upper():
                return product
    name = item.get("product_name") or ""
    if name:
        product = db.query(KBProduct).filter(KBProduct.product_name == name).first()
        if product:
            return product
        for product in db.query(KBProduct).filter(KBProduct.status == "published").all():
            if name in product.product_name or product.product_name in name:
                return product
    return None


def product_has_field(product, target: str) -> bool:
    values = {}
    values.update(product.get_specs())
    values.update(product.get_logistics())
    values.update(product.get_warranty())
    text = json.dumps(values, ensure_ascii=False).lower()
    return any(token.lower() in text for token in FIELD_TARGETS.get(target, ()))


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit product-detail sheet coverage in kb_product")
    parser.add_argument(
        "--base-id",
        default=os.environ.get("COPILOT_DT_PRODUCT_DETAIL_BASE_ID") or os.environ.get("COPILOT_DT_BASE_ID", ""),
    )
    parser.add_argument("--sheet-id", default=os.environ.get("COPILOT_DT_PRODUCT_DETAIL_SHEET_ID", "tEVE1jb"))
    parser.add_argument("--operator-id", default=os.environ.get("COPILOT_DT_OPERATOR_ID", ""))
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--output", default=str(PROJECT_ROOT / "reports" / "dingtalk_product_detail_audit.json"))
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

    from app.db import SessionLocal
    from app.models.kb_tables import KBProduct

    token = get_access_token(os.environ["COPILOT_DT_CLIENT_ID"], os.environ["COPILOT_DT_CLIENT_SECRET"])
    records = fetch_all_records(args.base_id, args.sheet_id, args.operator_id, token)
    if args.limit:
        records = records[: args.limit]

    db = SessionLocal()
    report = {
        "mode": "read_only_audit",
        "sheet_id": args.sheet_id,
        "total_records": len(records),
        "matched_product": 0,
        "unmatched_product": 0,
        "missing_field_counts": {},
        "items": [],
    }
    try:
        for record in records:
            item = normalize_detail_record(record.get("fields") or {})
            product = find_product(db, KBProduct, item)
            if not product:
                report["unmatched_product"] += 1
                report["items"].append({**item, "matched_product_id": None, "missing_targets": list(item["fields"].keys())})
                continue
            report["matched_product"] += 1
            missing_targets = []
            for target in item["fields"]:
                if not product_has_field(product, target):
                    missing_targets.append(target)
                    report["missing_field_counts"][target] = report["missing_field_counts"].get(target, 0) + 1
            if missing_targets:
                report["items"].append({
                    "matched_product_id": product.id,
                    "matched_i_id": product.i_id,
                    "matched_product_name": product.product_name,
                    "sheet_product_name": item.get("product_name", ""),
                    "sheet_i_id": item.get("i_id", ""),
                    "missing_targets": missing_targets,
                    "suggested_values": {target: item["fields"][target][:3] for target in missing_targets},
                })
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
