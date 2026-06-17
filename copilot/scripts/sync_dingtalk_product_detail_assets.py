#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Sync media assets from DingTalk product-detail SKU sheet.

Default mode is dry-run. Use --apply to write kb_media_asset.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime
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


LOW_RISK_AUTO_APPROVE_TYPES = {"sku_image", "size_image", "pack_guide_image", "install_video"}


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


def derive_parent_iid(fields: dict[str, Any]) -> str:
    flat = {str(k): flatten(v) for k, v in fields.items()}
    category_code = str(flat.get("\u7c7b\u76ee\u7f16\u53f7") or "").strip().upper()
    style_code = ""
    for key, value in flat.items():
        if "\u6b3e\u5f0f\u7f16\u53f7" in key:
            style_code = str(value or "").strip().upper()
            break
    import re

    if re.fullmatch(r"YH\d{2,3}", category_code or "") and re.fullmatch(r"K\d{1,3}", style_code or ""):
        return f"{category_code}{style_code}"
    return ""


def extract_urls(value: Any) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    if isinstance(value, dict):
        url = str(value.get("url") or value.get("link") or "").strip()
        if url:
            rows.append({
                "url": url,
                "title": str(value.get("text") or value.get("filename") or value.get("name") or "").strip(),
                "resource_id": str(value.get("resourceId") or value.get("id") or "").strip(),
            })
    elif isinstance(value, list):
        for item in value:
            rows.extend(extract_urls(item))
    elif isinstance(value, str) and value.startswith(("http://", "https://")):
        rows.append({"url": value.strip(), "title": "", "resource_id": ""})
    return rows


def build_asset_rows(fields: dict[str, Any], product: Any | None, record_id: str) -> list[dict[str, Any]]:
    i_id = getattr(product, "i_id", "") or derive_parent_iid(fields)
    product_id = getattr(product, "id", None)
    product_name = getattr(product, "product_name", "") or flatten(fields.get("\u4ea7\u54c1\u540d\u79f0\u7ed1\u5b9a"))
    combo = flatten(fields.get("\u89c4\u683c"))
    color = flatten(fields.get("\u989c\u8272"))
    sku_code = i_id
    scope_values = [item for item in (combo, color) if item]
    rows: list[dict[str, Any]] = []

    def add_many(field_name: str, asset_type: str, purpose: str, scenarios: list[str], title_suffix: str):
        for idx, item in enumerate(extract_urls(fields.get(field_name))):
            title_bits = [product_name, combo, color, title_suffix]
            rows.append({
                "product_id": product_id,
                "i_id": i_id,
                "sku_code": sku_code,
                "product_name": product_name,
                "asset_type": asset_type,
                "asset_title": " ".join(part for part in title_bits if part).strip()[:255],
                "asset_url": item["url"],
                "source": "dingtalk_product_detail",
                "source_doc_id": f"dt_product_detail:{record_id}:{field_name}:{idx}",
                "match_confidence": 0.9 if product else 0.65,
                "match_reason": "product_detail_sheet_iid" if product else "product_detail_sheet_unmatched",
                "scene_tags": scenarios,
                "source_raw": {
                    "media_purpose": purpose,
                    "answer_scenarios": scenarios,
                    "auto_send_level": "auto",
                    "applicable_style": {
                        "scope_type": "combo" if scope_values else "all",
                        "scope_values": scope_values,
                        "scope_note": " / ".join(scope_values),
                    },
                    "source_field": field_name,
                    "record_id": record_id,
                    "combo": combo,
                    "color": color,
                    "resource_id": item.get("resource_id", ""),
                    "asset_title_original": item.get("title", ""),
                },
            })

    add_many("SKU\u56fe", "sku_image", "appearance_image", ["ask_photo", "appearance", "dimensions"], "\u5546\u54c1\u56fe")
    add_many("\u7ec6\u8282\u5c3a\u5bf8", "size_image", "size_image", ["dimensions", "detachable"], "\u5c3a\u5bf8\u56fe")
    add_many("\u6253\u5305\u6307\u5357", "pack_guide_image", "packing_list_image", ["packing_list", "accessories"], "\u6253\u5305/\u914d\u4ef6\u56fe")

    for field_name in ("\u5b89\u88c5\u89c6\u9891(\u6296\u97f3)", "\u5b89\u88c5\u89c6\u9891(B\u7ad9)"):
        for idx, item in enumerate(extract_urls(fields.get(field_name))):
            rows.append({
                "product_id": product_id,
                "i_id": i_id,
                "sku_code": sku_code,
                "product_name": product_name,
                "asset_type": "install_video",
                "asset_title": " ".join(part for part in (product_name, combo, "\u5b89\u88c5\u89c6\u9891") if part).strip()[:255],
                "asset_url": item["url"],
                "source": "dingtalk_product_detail",
                "source_doc_id": f"dt_product_detail:{record_id}:{field_name}:{idx}",
                "match_confidence": 0.9 if product else 0.65,
                "match_reason": "product_detail_sheet_iid" if product else "product_detail_sheet_unmatched",
                "scene_tags": ["installation", "drilling"],
                "source_raw": {
                    "media_purpose": "install_video",
                    "answer_scenarios": ["installation", "drilling"],
                    "auto_send_level": "auto",
                    "applicable_style": {
                        "scope_type": "combo" if scope_values else "all",
                        "scope_values": scope_values,
                        "scope_note": " / ".join(scope_values),
                    },
                    "source_field": field_name,
                    "record_id": record_id,
                    "combo": combo,
                    "color": color,
                    "resource_id": item.get("resource_id", ""),
                    "asset_title_original": item.get("title", ""),
                },
            })
    return [row for row in rows if row.get("asset_url") and row.get("i_id")]


def find_product(db, KBProduct, fields: dict[str, Any]):
    i_id = derive_parent_iid(fields)
    if i_id:
        product = db.query(KBProduct).filter(KBProduct.i_id == i_id).first()
        if product:
            return product
    return None


def upsert_asset(db, KBMediaAsset, row: dict[str, Any], *, auto_approve_low_risk: bool) -> str:
    from scripts.import_dingtalk_media_assets import compute_content_hash, parse_url_expires

    now = datetime.utcnow()
    content_hash = compute_content_hash(row["i_id"], row["sku_code"], row["asset_type"], row["asset_url"])
    url_expires_at = parse_url_expires(row["asset_url"])
    refresh_status = "ok" if (not url_expires_at or url_expires_at > now) else "needs_refresh"
    asset = db.query(KBMediaAsset).filter(KBMediaAsset.content_hash == content_hash).first()
    action = "updated" if asset else "created"
    if not asset:
        asset = KBMediaAsset(
            created_by="sync_product_detail_assets",
            status="pending_review",
            audit_status="unreviewed",
            usable_for_agent=0,
            content_hash=content_hash,
        )
        db.add(asset)

    for key in (
        "product_id",
        "i_id",
        "sku_code",
        "product_name",
        "asset_type",
        "asset_title",
        "asset_url",
        "source",
        "source_doc_id",
        "match_confidence",
        "match_reason",
    ):
        setattr(asset, key, row[key])
    asset.set_source_raw({**(asset.get_source_raw() or {}), **row.get("source_raw", {})})
    asset.set_scene_tags(row.get("scene_tags", []))
    asset.url_expires_at = url_expires_at
    asset.refresh_status = refresh_status
    asset.last_seen_at = now
    asset.source_updated_at = now
    asset.updated_by = "sync_product_detail_assets"

    if (
        auto_approve_low_risk
        and row["asset_type"] in LOW_RISK_AUTO_APPROVE_TYPES
        and refresh_status == "ok"
        and asset.status in {"pending_review", "approved"}
    ):
        asset.status = "approved"
        asset.audit_status = "reviewed"
        asset.usable_for_agent = 1
        asset.reviewed_by = "dingtalk_product_detail_auto_approve"
    return action


def main() -> int:
    parser = argparse.ArgumentParser(description="Sync product-detail media assets into kb_media_asset")
    parser.add_argument("--apply", action="store_true", help="Write DB changes. Default is dry-run.")
    parser.add_argument("--auto-approve-low-risk", action="store_true")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--type", dest="asset_type", default="")
    parser.add_argument("--i-id", dest="i_id", default="", help="Only sync one parent product i_id")
    parser.add_argument("--product-id", dest="product_id", type=int, default=0, help="Only sync one kb_product id")
    parser.add_argument("--base-id", default=os.environ.get("COPILOT_DT_PRODUCT_DETAIL_BASE_ID") or os.environ.get("COPILOT_DT_BASE_ID", ""))
    parser.add_argument("--sheet-id", default=os.environ.get("COPILOT_DT_PRODUCT_DETAIL_SHEET_ID", "tEVE1jb"))
    parser.add_argument("--operator-id", default=os.environ.get("COPILOT_DT_OPERATOR_ID", ""))
    parser.add_argument("--output", default=str(PROJECT_ROOT / "reports" / "dingtalk_product_detail_assets_report.json"))
    args = parser.parse_args()

    missing = [
        name
        for name, value in (
            ("COPILOT_DT_CLIENT_ID", os.environ.get("COPILOT_DT_CLIENT_ID", "")),
            ("COPILOT_DT_CLIENT_SECRET", os.environ.get("COPILOT_DT_CLIENT_SECRET", "")),
            ("COPILOT_DT_OPERATOR_ID", args.operator_id),
            ("COPILOT_DT_PRODUCT_DETAIL_BASE_ID", args.base_id),
        )
        if not value
    ]
    if missing:
        raise SystemExit(f"missing DingTalk env: {', '.join(missing)}")

    from app.db import SessionLocal, init_db
    from app.models.kb_tables import KBMediaAsset, KBProduct

    token = get_access_token(os.environ["COPILOT_DT_CLIENT_ID"], os.environ["COPILOT_DT_CLIENT_SECRET"])
    records = fetch_all_records(args.base_id, args.sheet_id, args.operator_id, token)
    if args.limit:
        records = records[: args.limit]

    init_db()
    db = SessionLocal()
    report = {
        "mode": "apply" if args.apply else "dry_run",
        "sheet_id": args.sheet_id,
        "records": len(records),
        "matched_product": 0,
        "unmatched_product": 0,
        "candidate_assets": 0,
        "created": 0,
        "updated": 0,
        "approved": 0,
        "by_type": {},
        "items": [],
    }
    try:
        for record in records:
            fields = record.get("fields") or {}
            product = find_product(db, KBProduct, fields)
            if product:
                report["matched_product"] += 1
            else:
                report["unmatched_product"] += 1
            rows = build_asset_rows(fields, product, str(record.get("id") or record.get("recordId") or ""))
            if args.asset_type:
                rows = [row for row in rows if row["asset_type"] == args.asset_type]
            if args.i_id:
                rows = [row for row in rows if str(row.get("i_id") or "") == args.i_id]
            if args.product_id:
                rows = [row for row in rows if int(row.get("product_id") or 0) == args.product_id]
            for row in rows:
                report["candidate_assets"] += 1
                report["by_type"][row["asset_type"]] = report["by_type"].get(row["asset_type"], 0) + 1
                if args.apply:
                    action = upsert_asset(db, KBMediaAsset, row, auto_approve_low_risk=args.auto_approve_low_risk)
                    report[action] += 1
                    if args.auto_approve_low_risk and row["asset_type"] in LOW_RISK_AUTO_APPROVE_TYPES:
                        report["approved"] += 1
                else:
                    action = "dry_run"
                if len(report["items"]) < 100:
                    report["items"].append({
                        "action": action,
                        "product_id": row.get("product_id"),
                        "i_id": row.get("i_id"),
                        "product_name": row.get("product_name"),
                        "asset_type": row.get("asset_type"),
                        "asset_title": row.get("asset_title"),
                        "source_doc_id": row.get("source_doc_id"),
                        "scope": row.get("source_raw", {}).get("applicable_style", {}),
                    })
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
