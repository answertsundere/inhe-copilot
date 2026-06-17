# -*- coding: utf-8 -*-
"""
安全导入脚本 - 将 JST 商品数据导入 kb_product

数据源: products_20260609.xlsx (items + skus 两个工作表)
目标: kb_product 表

用法:
    # Dry-run (默认，不写库)
    python scripts/import_kb_products.py --file data/imports/products_20260609.xlsx --dry-run

    # 正式导入
    python scripts/import_kb_products.py --file data/imports/products_20260609.xlsx --apply

    # 限定少量商品试导入
    python scripts/import_kb_products.py --file data/imports/products_20260609.xlsx --dry-run --product-ids YH01K01B01S05,YH04K14B01S03

    # 回滚指定批次
    python scripts/import_kb_products.py --rollback --batch-id xxx

安全原则:
    1. 默认 dry-run，不写库
    2. 使用 i_id 幂等 upsert
    3. 空白新值不覆盖旧值
    4. 新建为 draft，不自动发布
    5. 已发布商品事实变化 → pending_review
    6. 所有变更写入 kb_change_log
"""

import argparse
import csv
import hashlib
import json
import os
import sys
from datetime import datetime
from typing import Optional

import pandas as pd

# 项目路径
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(SCRIPT_DIR)
sys.path.insert(0, PROJECT_DIR)

from app import db as db_module
from app.models.kb_tables import KBProduct, KBChangeLog
from app.repositories.kb_product_repository import _compute_completeness


def _init_db():
    db_module.init_db()


def _session():
    return db_module.SessionLocal()


# ─── 常量 ───

IMPORT_ACTOR = "product_import"

# 事实性字段：这些字段变化时，published 商品需要转 pending_review
FACTUAL_FIELDS = {"specs", "sku_list", "product_name", "brand",
                  "category_l1", "category_l2", "category_l3"}

# 非事实性字段：这些变化不触发 pending_review
NON_FACTUAL_FIELDS = {"import_batch_id", "updated_by"}


# ─── 字段映射定义 ───

# Items 表列 → kb_product 直接字段
ITEMS_DIRECT_MAP = {
    "i_id": "i_id",
    "name": "product_name",
    "brand": "brand",
}

# Items 表列 → specs_json 内部键
ITEMS_SPECS_MAP = {
    "weight": "weight",
    "unit": "unit",
    "item_type": "item_type",
    "h": "height",
    "l": "length",
    "w": "width",
}

# Items 表列 → logistics_json 内部键
ITEMS_LOGISTICS_MAP = {
    "weight": "package_weight",
    "h": "package_height",
    "l": "package_length",
    "w": "package_width",
    "unit": "unit",
}

# SKUs 表列 → sku_list 内部键
SKU_MAP = {
    "sku_id": "sku_id",
    "name": "sku_name",
    "properties_value": "properties",
    "sale_price": "sale_price",
    "cost_price": "cost_price",
    "sku_code": "sku_code",
    "enabled": "enabled",
}

# Items 表列 → 分类映射
CATEGORY_MAP = {
    "c_name": "category_l1",
}

# Items 表中不映射的元数据列
METADATA_COLUMNS = {
    "remark", "pic", "pics", "shelf_life", "s_price", "c_id",
    "modified", "f_json", "autoid", "co_id", "market_price",
    "vc_name", "created", "storeage", "registration_certificate_no",
    "c_price",
}

# SKUs 表中不映射的列
SKU_UNMAPPED = {
    "supplier_i_id", "other_1", "other_2", "other_3", "other_4",
    "other_5", "other_6", "other_7", "other_8", "other_9", "other_10",
    "other_price_1", "other_price_2", "other_price_3", "other_price_4",
    "other_price_5", "color", "production_licence", "productionbatch_format",
    "supplier_id", "supplier_name", "supplier_sku_id", "pic", "pic_big",
    "labels", "stock_type", "stock_disabled", "is_series_number",
    "short_name", "category", "creator", "brand", "item_type", "remark",
    "shelf_life", "c_id", "weight", "h", "l", "w", "enabled",
}


# ─── Optional DingTalk enrichment ───

def _dingtalk_config_from_env() -> dict:
    keys = {
        "client_id": "DINGTALK_CLIENT_ID",
        "client_secret": "DINGTALK_CLIENT_SECRET",
        "operator_id": "DINGTALK_OPERATOR_ID",
        "base_id": "DINGTALK_BASE_ID",
        "sheet_id": "DINGTALK_SHEET_ID",
    }
    config = {name: os.environ.get(env_name, "").strip() for name, env_name in keys.items()}
    missing = [env_name for name, env_name in keys.items() if not config[name]]
    if missing:
        raise RuntimeError("Missing DingTalk environment variables: " + ", ".join(missing))
    return config


def _dt_get_token(config: dict):
    import requests as _requests

    resp = _requests.post(
        "https://api.dingtalk.com/v1.0/oauth2/accessToken",
        json={"appKey": config["client_id"], "appSecret": config["client_secret"]},
        timeout=30,
    )
    data = resp.json()
    if resp.status_code != 200 or "accessToken" not in data:
        raise RuntimeError(f"获取钉钉 Token 失败: {data}")
    return data["accessToken"]


def read_dingtalk_products() -> dict:
    """
    读取钉钉多维表格全量商品数据。
    返回 {product_name: {specs字段}} 的映射字典。
    """
    print("正在读取钉钉多维表格...")
    import requests as _requests
    import time as _time

    config = _dingtalk_config_from_env()
    token = _dt_get_token(config)

    url = f"https://api.dingtalk.com/v1.0/notable/bases/{config['base_id']}/sheets/{config['sheet_id']}/records/list"
    headers = {"x-acs-dingtalk-access-token": token, "Content-Type": "application/json"}
    params = {"operatorId": config["operator_id"]}

    all_records = []
    next_token = None

    while True:
        body = {"maxResults": 100}
        if next_token:
            body["nextToken"] = next_token
        resp = _requests.post(url, headers=headers, params=params, json=body, timeout=60)
        data = resp.json()
        if resp.status_code != 200:
            print(f"  钉钉 API 错误: {data}")
            break
        records = data.get("records", [])
        all_records.extend(records)
        next_token = data.get("nextToken")
        if not next_token:
            break
        _time.sleep(0.15)

    print(f"  钉钉记录数: {len(all_records)}")

    # 构建按名称索引的映射
    name_map = {}  # product_name → dingtalk data
    for rec in all_records:
        f = rec.get("fields", {})
        name = _dt_clean(str(f.get("产品旧名称", "")))
        if not name:
            # 尝试英文品名匹配
            continue

        caizhi_list = f.get("材质") or []
        caizhi = ", ".join(m.get("name", "") for m in caizhi_list if isinstance(m, dict))

        entry = {
            "huohao": _dt_clean(str(f.get("商品货号/证书货号", ""))),
            "age_range": _dt_clean(str(f.get("适用年龄", ""))),
            "material": caizhi,
            "load_capacity": _dt_clean(str(f.get("承重", ""))),
            "warranty_period": _dt_clean(str(f.get("质保期限", ""))),
            "series": (f.get("系列") or {}).get("name", ""),
            "stage": (f.get("阶段") or {}).get("name", ""),
            "source_type": (f.get("自产/外采") or {}).get("name", ""),
            "en_name": _dt_clean(str(f.get("英语品名", ""))),
        }
        name_map[name] = entry

    print(f"  钉钉有效名称映射: {len(name_map)} 条")
    return name_map


def _dt_clean(val: str) -> str:
    if not val or val.lower() in ("nan", "none", "null"):
        return ""
    return val.strip()


# ─── 数据读取 ───

def read_excel(file_path: str, sheet: Optional[str] = None):
    """读取 Excel 的 items 和 skus 工作表"""
    sheets = {}
    if sheet:
        df = pd.read_excel(file_path, sheet_name=sheet, dtype=str)
        sheets[sheet] = df
    else:
        xls = pd.read_excel(file_path, sheet_name=None, dtype=str)
        for name, df in xls.items():
            sheets[name] = df

    items_df = sheets.get("items")
    skus_df = sheets.get("skus")

    if items_df is None:
        raise ValueError("Excel 中缺少 'items' 工作表")

    return items_df, skus_df


def clean_value(val):
    """清洗单个值：去空格，统一空值表示"""
    if val is None:
        return None
    if isinstance(val, float) and (val != val):  # NaN
        return None
    s = str(val).strip()
    if s.lower() in ("nan", "none", "null", ""):
        return None
    return s


# ─── 构建 SKU 列表 ───

def build_sku_list(skus_df: Optional[pd.DataFrame], i_id: str) -> list:
    """为指定 i_id 构建 SKU 列表"""
    if skus_df is None or "i_id" not in skus_df.columns:
        return []

    rows = skus_df[skus_df["i_id"] == i_id]
    sku_list = []

    for _, row in rows.iterrows():
        sku = {}
        for src_col, target_key in SKU_MAP.items():
            val = clean_value(row.get(src_col))
            if val is not None:
                sku[target_key] = val
        if sku.get("sku_id"):
            sku_list.append(sku)

    # 按 sku_id 去重（保留第一个）
    seen = set()
    unique = []
    for sku in sku_list:
        sid = sku.get("sku_id", "")
        if sid not in seen:
            seen.add(sid)
            unique.append(sku)

    return unique


# ─── 构建商品记录 ───

def build_product_record(row: pd.Series, sku_list: list) -> dict:
    """从 items 行 + SKU 列表构建一个完整的 kb_product 记录"""
    record = {}

    # 直接字段
    for src_col, target_field in ITEMS_DIRECT_MAP.items():
        val = clean_value(row.get(src_col))
        if val is not None:
            record[target_field] = val

    # 分类: c_name 映射为 jst_category (JST 内部分类)
    # 对于新建商品同时作为 category_l1 备选
    c_name = clean_value(row.get("c_name"))
    if c_name:
        record["jst_category"] = c_name

    # specs_json
    specs = {}
    for src_col, target_key in ITEMS_SPECS_MAP.items():
        val = clean_value(row.get(src_col))
        if val is not None:
            specs[target_key] = val
    if specs:
        record["specs"] = specs

    # logistics_json
    logistics = {}
    for src_col, target_key in ITEMS_LOGISTICS_MAP.items():
        val = clean_value(row.get(src_col))
        if val is not None:
            logistics[target_key] = val
    if logistics:
        record["logistics"] = logistics

    # SKU 列表
    if sku_list:
        record["sku_list"] = sku_list

    return record


def _apply_dingtalk_enrichment(new_data: dict, dt_entry: dict):
    """Merge optional DingTalk fields into product JSON payloads."""
    specs = dict(new_data.get("specs") or {})
    warranty = dict(new_data.get("warranty") or {})
    for src, dst in (
        ("age_range", "age_range"),
        ("material", "material"),
        ("load_capacity", "load_capacity"),
        ("series", "series"),
        ("stage", "stage"),
        ("source_type", "source_type"),
        ("en_name", "en_name"),
        ("huohao", "certificate_item_no"),
    ):
        val = clean_value(dt_entry.get(src))
        if val:
            specs[dst] = val
    warranty_period = clean_value(dt_entry.get("warranty_period"))
    if warranty_period:
        warranty["period"] = warranty_period
    if specs:
        new_data["specs"] = specs
    if warranty:
        new_data["warranty"] = warranty


# ─── 差异对比 ───

def diff_product(existing: KBProduct, new_data: dict) -> dict:
    """
    对比新旧数据，返回差异信息。
    空白新值不覆盖旧值。
    区分"增量补充"(仅新增键)和"事实变更"(修改已有键值)。
    """
    changed_fields = []
    changes = {}
    is_factual_change = False

    # 直接字段对比（跳过 category_l1：已有商品使用 DB 中的精心分类）
    direct_fields = {"product_name", "brand", "category_l2", "category_l3"}
    for field in direct_fields:
        new_val = new_data.get(field)
        if new_val is None or str(new_val).strip() == "":
            continue
        old_val = getattr(existing, field, "") or ""
        if str(new_val).strip() != str(old_val).strip():
            changed_fields.append(field)
            changes[field] = {"old": old_val, "new": new_val}
            if field in FACTUAL_FIELDS:
                is_factual_change = True

    # JSON 字段对比
    json_fields = {
        "specs": ("get_specs", "specs"),
        "logistics": ("get_logistics", "logistics"),
        "warranty": ("get_warranty", "warranty"),
        "sku_list": ("get_sku_list", "sku_list"),
    }
    for target_key, (getter_name, data_key) in json_fields.items():
        new_val = new_data.get(data_key)
        if new_val is None:
            continue

        old_val = getattr(existing, getter_name)()
        if old_val is None:
            old_val = {} if target_key != "sku_list" else []

        if target_key == "sku_list":
            merged = _merge_sku_list(old_val, new_val)
            if merged != old_val:
                changed_fields.append(target_key)
                changes[target_key] = {"old": old_val, "new": merged}
                # SKU 新增属于增量补充，不触发 pending_review
                # 仅当已有 SKU 的核心属性被修改时才算事实变更
                if _has_sku_modification(old_val, new_val):
                    is_factual_change = True
        else:
            merged = _merge_json_dict(old_val, new_val)
            if merged != old_val:
                changed_fields.append(target_key)
                changes[target_key] = {"old": old_val, "new": merged}
                # 区分增量补充 vs 事实变更
                # 仅新增键(如添加 dimensions)不算事实变更
                # 修改已有键值才算事实变更
                if target_key in FACTUAL_FIELDS:
                    if _has_value_modification(old_val, new_val):
                        is_factual_change = True

    return {
        "changed_fields": changed_fields,
        "changes": changes,
        "is_factual_change": is_factual_change,
        "is_changed": len(changed_fields) > 0,
    }


def _merge_json_dict(old_dict: dict, new_dict: dict) -> dict:
    """合并 JSON dict：新值覆盖旧值，空白新值不覆盖"""
    merged = dict(old_dict)  # 保留旧值
    for k, v in new_dict.items():
        if v is None or (isinstance(v, str) and v.strip() == ""):
            continue
        merged[k] = v
    return merged


def _has_value_modification(old_dict: dict, new_dict: dict) -> bool:
    """检查是否有已有键的值被修改（不包括新增键）"""
    for k, v in new_dict.items():
        if v is None or (isinstance(v, str) and v.strip() == ""):
            continue
        if k in old_dict and str(old_dict[k]).strip() != str(v).strip():
            return True
    return False


def _has_sku_modification(old_list: list, new_list: list) -> bool:
    """检查是否有已有 SKU 的核心属性被修改（不包括新增 SKU）"""
    old_by_id = {s.get("sku_id", ""): s for s in old_list if s.get("sku_id")}
    core_fields = {"sku_name", "sale_price"}
    for new_sku in new_list:
        sid = new_sku.get("sku_id", "")
        if sid and sid in old_by_id:
            old_sku = old_by_id[sid]
            for field in core_fields:
                old_v = str(old_sku.get(field, "")).strip()
                new_v = str(new_sku.get(field, "")).strip()
                if new_v and old_v and old_v != new_v:
                    return True
    return False
    return merged


def _merge_sku_list(old_list: list, new_list: list) -> list:
    """合并 SKU 列表：按 sku_id 匹配，新 SKU 追加，已有 SKU 合并"""
    old_by_id = {}
    for sku in old_list:
        sid = sku.get("sku_id") or sku.get("sku_code", "")
        if sid:
            old_by_id[sid] = dict(sku)

    for new_sku in new_list:
        sid = new_sku.get("sku_id") or new_sku.get("sku_code", "")
        if not sid:
            continue
        if sid in old_by_id:
            # 合并：新值中的非空键覆盖旧值
            for k, v in new_sku.items():
                if v is not None and str(v).strip() != "":
                    old_by_id[sid][k] = v
        else:
            old_by_id[sid] = dict(new_sku)

    return list(old_by_id.values())


def _sku_change_counts_from_lists(old_list: list, new_list: list) -> dict:
    old_by_id = {
        (s.get("sku_id") or s.get("sku_code") or ""): dict(s)
        for s in (old_list or [])
        if s.get("sku_id") or s.get("sku_code")
    }
    new_by_id = {
        (s.get("sku_id") or s.get("sku_code") or ""): dict(s)
        for s in (new_list or [])
        if s.get("sku_id") or s.get("sku_code")
    }
    added = set(new_by_id) - set(old_by_id)
    updated = set()
    for sid in set(old_by_id) & set(new_by_id):
        old_sku = old_by_id[sid]
        new_sku = new_by_id[sid]
        for key, value in new_sku.items():
            if value is None or str(value).strip() == "":
                continue
            if str(old_sku.get(key, "")).strip() != str(value).strip():
                updated.add(sid)
                break
    return {"new_skus": len(added), "updated_skus": len(updated)}


def _sku_change_counts(diff_result: dict) -> dict:
    change = diff_result.get("changes", {}).get("sku_list")
    if not change:
        return {"new_skus": 0, "updated_skus": 0}
    return _sku_change_counts_from_lists(change.get("old", []), change.get("new", []))


# ─── 状态决策 ───

def decide_new_status(existing_status: str, diff_result: dict) -> str:
    """决定商品更新后的状态"""
    if not diff_result["is_changed"]:
        return existing_status

    if existing_status == "published" and diff_result["is_factual_change"]:
        return "pending_review"

    return existing_status


# ─── 报告生成 ───

def compute_file_hash(file_path: str) -> str:
    h = hashlib.sha256()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()[:16]


def generate_batch_id() -> str:
    return f"kb_import_{datetime.now().strftime('%Y%m%d_%H%M%S')}"


def build_report(batch_id: str, file_path: str, results: list,
                 source_hash: str, unmapped_items: list,
                 warnings: list, errors: list) -> dict:
    """构建完整报告"""
    summary = {
        "create": 0, "update": 0, "unchanged": 0, "conflict": 0, "failed": 0,
        "new_skus": 0, "updated_skus": 0,
        "to_pending_review": 0,
        "missing_iid": 0, "missing_name": 0,
        "qa_drafts": 0, "sop_drafts": 0, "knowledge_drafts": 0,
    }

    for r in results:
        action = r.get("action", "failed")
        if action in summary:
            summary[action] += 1
        summary["new_skus"] += int(r.get("new_skus") or 0)
        summary["updated_skus"] += int(r.get("updated_skus") or 0)
        if r.get("will_pending_review"):
            summary["to_pending_review"] += 1
        if action == "failed" and r.get("error") == "缂哄皯 i_id":
            summary["missing_iid"] += 1
        if r.get("missing_name"):
            summary["missing_name"] += 1

    return {
        "batch_id": batch_id,
        "source_file": os.path.basename(file_path),
        "source_hash": source_hash,
        "generated_at": datetime.now().isoformat(),
        "total_rows": len(results),
        "summary": summary,
        "unmapped_fields": unmapped_items,
        "warnings": warnings,
        "errors": errors,
        "details": results,
    }


def save_reports(report: dict, report_dir: str):
    """保存 JSON、CSV、Markdown 报告"""
    os.makedirs(report_dir, exist_ok=True)
    base = report["batch_id"]

    # JSON
    json_path = os.path.join(report_dir, f"{base}_report.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    # CSV
    csv_path = os.path.join(report_dir, f"{base}_report.csv")
    with open(csv_path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=[
            "i_id", "product_name", "db_id", "current_status", "action",
            "changed_fields", "sku_changes", "new_skus", "updated_skus", "completeness_before",
            "completeness_after", "new_status", "source_sheet", "source_row",
            "error",
        ])
        writer.writeheader()
        for d in report.get("details", []):
            writer.writerow({k: d.get(k, "") for k in writer.fieldnames})

    # Markdown
    md_path = os.path.join(report_dir, f"{base}_report.md")
    with open(md_path, "w", encoding="utf-8") as f:
        s = report["summary"]
        f.write(f"# 导入 Dry-Run 报告\n\n")
        f.write(f"- **批次号**: {report['batch_id']}\n")
        f.write(f"- **源文件**: {report['source_file']}\n")
        f.write(f"- **文件哈希**: {report['source_hash']}\n")
        f.write(f"- **生成时间**: {report['generated_at']}\n")
        f.write(f"- **数据总行数**: {report['total_rows']}\n\n")

        f.write(f"## 统计摘要\n\n")
        f.write(f"| 指标 | 数量 |\n|---|---|\n")
        f.write(f"| 新增商品 | {s['create']} |\n")
        f.write(f"| 更新商品 | {s['update']} |\n")
        f.write(f"| 无变化 | {s['unchanged']} |\n")
        f.write(f"| 冲突 | {s['conflict']} |\n")
        f.write(f"| 失败 | {s['failed']} |\n")
        f.write(f"| 将转 pending_review | {s['to_pending_review']} |\n")
        f.write(f"| 新增 SKU | {s['new_skus']} |\n")
        f.write(f"| 更新 SKU | {s['updated_skus']} |\n\n")

        if report.get("warnings"):
            f.write(f"## 警告\n\n")
            for w in report["warnings"]:
                f.write(f"- ⚠️ {w}\n")
            f.write("\n")

        if report.get("errors"):
            f.write(f"## 错误\n\n")
            for e in report["errors"]:
                f.write(f"- ❌ {e}\n")
            f.write("\n")

        if report.get("unmapped_fields"):
            f.write(f"## 未映射字段\n\n")
            for u in report["unmapped_fields"]:
                f.write(f"- {u}\n")
            f.write("\n")

        # 风险商品列表
        pending = [d for d in report.get("details", []) if d.get("will_pending_review")]
        if pending:
            f.write(f"## 将从 published → pending_review 的商品 ({len(pending)})\n\n")
            f.write(f"| i_id | 商品名 | 变更字段 |\n|---|---|---|\n")
            for d in pending[:50]:
                f.write(f"| {d['i_id']} | {d['product_name']} | {d.get('changed_fields','')} |\n")
            if len(pending) > 50:
                f.write(f"\n> 仅显示前 50 条，共 {len(pending)} 条\n")
            f.write("\n")

    return json_path, csv_path, md_path


# ─── 主流程 ───

def run_import(
    file_path: str,
    dry_run: bool = True,
    apply: bool = False,
    product_ids: Optional[list] = None,
    limit: Optional[int] = None,
    batch_id: Optional[str] = None,
    report_dir: Optional[str] = None,
    sheet: Optional[str] = None,
    dingtalk_enrich: bool = False,
    confirm_full_import: bool = False,
):
    if dry_run and apply:
        dry_run = False

    if not apply:
        dry_run = True

    is_dry_run = not apply

    if not batch_id:
        batch_id = generate_batch_id()

    if not report_dir:
        report_dir = os.path.join(PROJECT_DIR, "data", "imports", "reports")

    print(f"=== 商品知识导入 {'DRY-RUN' if is_dry_run else 'APPLY'} ===")
    print(f"批次号: {batch_id}")
    print(f"源文件: {file_path}")
    print(f"模式: {'dry-run (不写库)' if is_dry_run else '正式导入'}")
    print()

    # 读取数据
    source_hash = compute_file_hash(file_path)
    print(f"文件哈希: {source_hash}")

    items_df, skus_df = read_excel(file_path, sheet)
    print(f"Items: {len(items_df)} 行, {len(items_df.columns)} 列")
    print(f"SKUs:  {len(skus_df) if skus_df is not None else 0} 行, {skus_df.shape[1] if skus_df is not None else 0} 列")

    if apply and not confirm_full_import and not limit and not product_ids and len(items_df) > 50:
        raise RuntimeError(
            "Refusing full apply for more than 50 rows without --confirm-full-import. "
            "Use --limit or --product-ids for a small batch first."
        )

    # 收集未映射字段
    unmapped_items_cols = []
    for col in items_df.columns:
        if col not in ITEMS_DIRECT_MAP and col not in ITEMS_SPECS_MAP and \
           col not in ITEMS_LOGISTICS_MAP and col not in CATEGORY_MAP and \
           col not in METADATA_COLUMNS:
            unmapped_items_cols.append(f"items.{col}")

    unmapped_skus_cols = []
    if skus_df is not None:
        for col in skus_df.columns:
            if col not in SKU_MAP and col not in SKU_UNMAPPED and col != "i_id":
                unmapped_skus_cols.append(f"skus.{col}")

    unmapped = unmapped_items_cols + unmapped_skus_cols

    # 筛选商品
    if product_ids:
        pid_set = set(product_ids)
        items_df = items_df[items_df["i_id"].isin(pid_set)]
        print(f"限定商品: {len(items_df)} 条")

    if limit:
        items_df = items_df.head(limit)
        print(f"限量: {len(items_df)} 条")

    # 初始化数据库
    _init_db()
    db = _session()

    # 加载现有 i_id 映射
    existing_map = {}
    for p in db.query(KBProduct).all():
        existing_map[p.i_id] = p

    print(f"数据库现有商品: {len(existing_map)}")

    # 读取钉钉多维表格作为可选补充数据源
    dt_map = read_dingtalk_products() if dingtalk_enrich else {}
    dt_enriched_count = 0

    print()

    # 逐行处理
    results = []
    warnings = []
    errors = []
    seen_iids = set()

    if skus_df is not None and "sku_id" in skus_df.columns and "i_id" in skus_df.columns:
        sku_owner = {}
        for sku_idx, sku_row in skus_df.iterrows():
            sid = clean_value(sku_row.get("sku_id"))
            owner = clean_value(sku_row.get("i_id"))
            if not sid or not owner:
                continue
            if sid in sku_owner and sku_owner[sid] != owner:
                warnings.append(
                    f"SKU conflict: sku_id={sid} belongs to both {sku_owner[sid]} and {owner} "
                    f"(skus row {sku_idx + 2})"
                )
            else:
                sku_owner[sid] = owner

    for idx, (_, row) in enumerate(items_df.iterrows()):
        i_id = clean_value(row.get("i_id"))
        if not i_id:
            results.append({
                "i_id": "", "product_name": "", "db_id": None,
                "current_status": None, "action": "failed",
                "changed_fields": [], "sku_changes": "",
                "new_skus": 0, "updated_skus": 0,
                "completeness_before": None, "completeness_after": None,
                "new_status": None, "will_pending_review": False,
                "source_sheet": "items", "source_row": idx + 2,
                "error": "缺少 i_id",
            })
            continue

        if i_id in seen_iids:
            results.append({
                "i_id": i_id, "product_name": clean_value(row.get("name")) or "",
                "db_id": None, "current_status": None, "action": "conflict",
                "changed_fields": [], "sku_changes": "", "new_skus": 0, "updated_skus": 0,
                "completeness_before": None, "completeness_after": None,
                "new_status": None, "will_pending_review": False,
                "source_sheet": "items", "source_row": idx + 2,
                "error": "duplicate i_id in source file",
            })
            continue
        seen_iids.add(i_id)

        name = clean_value(row.get("name"))
        if not name:
            warnings.append(f"行 {idx+2}: i_id={i_id} 缺少商品名称")

        # 构建 SKU 列表
        sku_list = build_sku_list(skus_df, i_id)

        # 构建新数据 (来自 xlsx)
        new_data = build_product_record(row, sku_list)

        # 用钉钉数据覆盖/补充 specs 和 warranty (钉钉为权威来源)
        dt_entry = dt_map.get(name) if name else None
        if dt_entry:
            dt_enriched_count += 1
            _apply_dingtalk_enrichment(new_data, dt_entry)

        # 查找已有记录
        existing = existing_map.get(i_id)

        if existing is None:
            # 新增
            record = {
                "i_id": i_id,
                "product_name": new_data.get("product_name", ""),
                "brand": new_data.get("brand", ""),
                "category_l1": new_data.get("jst_category", ""),
                "action": "create",
                "db_id": None,
                "current_status": None,
                "new_status": "draft",
                "changed_fields": [],
                "sku_changes": f"+{len(sku_list)} SKUs",
                "new_skus": len(sku_list),
                "updated_skus": 0,
                "completeness_before": None,
                "completeness_after": None,
                "will_pending_review": False,
                "source_sheet": "items",
                "source_row": idx + 2,
            }

            if not is_dry_run:
                try:
                    product = KBProduct(
                        i_id=i_id,
                        product_name=new_data.get("product_name", ""),
                        brand=new_data.get("brand", ""),
                        category_l1=new_data.get("jst_category", ""),
                        category_l2="",
                        category_l3="",
                        status="draft",
                        created_by=IMPORT_ACTOR,
                        updated_by=IMPORT_ACTOR,
                        import_batch_id=batch_id,
                    )
                    if new_data.get("specs"):
                        product.set_specs(new_data["specs"])
                    if new_data.get("logistics"):
                        product.set_logistics(new_data["logistics"])
                    if new_data.get("sku_list"):
                        product.set_sku_list(new_data["sku_list"])

                    db.add(product)
                    db.flush()

                    # 计算完整度 (×100 保持一致)
                    score, missing = _compute_completeness(product)
                    product.completeness_score = round(score * 100, 1)
                    product.set_missing_fields(missing)
                    record["completeness_after"] = product.completeness_score

                    # 变更日志
                    _log_import(db, product, "create", batch_id, {})

                    db.commit()
                    record["db_id"] = product.id
                    existing_map[i_id] = product
                except Exception as e:
                    db.rollback()
                    record["action"] = "failed"
                    record["error"] = str(e)
                    errors.append(f"创建 {i_id} 失败: {e}")

            results.append(record)

        else:
            # 更新
            old_score = existing.completeness_score
            diff_result = diff_product(existing, new_data)
            new_status = decide_new_status(existing.status, diff_result)
            sku_counts = _sku_change_counts(diff_result)

            record = {
                "i_id": i_id,
                "product_name": new_data.get("product_name", existing.product_name),
                "db_id": existing.id,
                "current_status": existing.status,
                "action": "unchanged" if not diff_result["is_changed"] else "update",
                "new_status": new_status,
                "changed_fields": diff_result["changed_fields"],
                "sku_changes": _describe_sku_changes(diff_result),
                "new_skus": sku_counts["new_skus"],
                "updated_skus": sku_counts["updated_skus"],
                "completeness_before": old_score,
                "completeness_after": None,
                "will_pending_review": (existing.status == "published" and
                                        new_status == "pending_review"),
                "source_sheet": "items",
                "source_row": idx + 2,
            }

            if not is_dry_run and diff_result["is_changed"]:
                try:
                    # 保存旧值快照
                    before_snapshot = existing.to_dict(detail=True)

                    # 应用更新
                    for field in diff_result["changed_fields"]:
                        if field in ("specs", "logistics", "warranty", "sku_list"):
                            change = diff_result["changes"].get(field, {})
                            merged = change.get("new", {})
                            if field == "specs":
                                existing.set_specs(merged)
                            elif field == "logistics":
                                existing.set_logistics(merged)
                            elif field == "warranty":
                                existing.set_warranty(merged)
                            elif field == "sku_list":
                                existing.set_sku_list(merged)
                        elif field in ("product_name", "brand",
                                       "category_l1", "category_l2", "category_l3"):
                            change = diff_result["changes"].get(field, {})
                            new_val = change.get("new")
                            if new_val is not None:
                                setattr(existing, field, new_val)

                    existing.updated_by = IMPORT_ACTOR
                    existing.import_batch_id = batch_id
                    existing.updated_at = datetime.utcnow()

                    if new_status != existing.status:
                        existing.status = new_status

                    # 重算完整度
                    score, missing = _compute_completeness(existing)
                    existing.completeness_score = round(score * 100, 1)
                    existing.set_missing_fields(missing)
                    record["completeness_after"] = existing.completeness_score

                    # 变更日志
                    _log_import(db, existing, "update", batch_id,
                                before_snapshot, diff_result["changed_fields"],
                                new_status != record["current_status"])

                    db.commit()
                except Exception as e:
                    db.rollback()
                    record["action"] = "failed"
                    record["error"] = str(e)
                    errors.append(f"更新 {i_id} 失败: {e}")
            elif diff_result["is_changed"]:
                # dry-run 模式：预测完整度变化
                # 创建临时对象估算
                record["completeness_after"] = f"~{old_score}"  # dry-run 不精确

            results.append(record)

        # 进度
        if (idx + 1) % 200 == 0:
            print(f"  已处理 {idx + 1}/{len(items_df)} ...")

    print(f"  钉钉数据命中: {dt_enriched_count}/{len(items_df)}")

    db.close()

    # 生成报告
    report = build_report(batch_id, file_path, results, source_hash,
                          unmapped, warnings, errors)
    json_path, csv_path, md_path = save_reports(report, report_dir)

    # 打印摘要
    s = report["summary"]
    print()
    print("=== Dry-Run 摘要 ===" if is_dry_run else "=== 导入摘要 ===")
    print(f"新增商品: {s['create']}")
    print(f"更新商品: {s['update']}")
    print(f"无变化:   {s['unchanged']}")
    print(f"冲突:     {s['conflict']}")
    print(f"失败:     {s['failed']}")
    print(f"将转 pending_review: {s['to_pending_review']}")

    print()
    print("=== 报告文件 ===")
    print(f"JSON: {json_path}")
    print(f"CSV:  {csv_path}")
    print(f"MD:   {md_path}")

    return report


def _describe_sku_changes(diff_result: dict) -> str:
    """描述 SKU 变化"""
    if "sku_list" not in diff_result.get("changes", {}):
        return ""
    change = diff_result["changes"]["sku_list"]
    old = change.get("old", [])
    new = change.get("new", [])
    old_ids = {s.get("sku_id", "") for s in old}
    new_ids = {s.get("sku_id", "") for s in new}
    added = new_ids - old_ids
    removed = old_ids - new_ids
    counts = _sku_change_counts(diff_result)
    parts = []
    if added:
        parts.append(f"+{len(added)} SKU")
    if removed:
        parts.append(f"-{len(removed)} SKU")
    if counts["updated_skus"]:
        parts.append(f"~{counts['updated_skus']} SKU")
    return ", ".join(parts) if parts else ""


def _log_import(db, product: KBProduct, action: str, batch_id: str,
                before_snapshot: dict = None,
                changed_fields: list = None,
                status_changed: bool = False):
    """写入变更日志"""
    after_status = product.status
    before_status = before_snapshot.get("status", "") if before_snapshot else ""

    entry = KBChangeLog(
        target_type="kb_product",
        target_id=product.id,
        target_title=product.product_name,
        action="update" if action == "update" else "create",
        before_status=before_status,
        after_status=after_status,
        performed_by=IMPORT_ACTOR,
        change_reason=f"batch={batch_id}, official_product_data_update",
    )
    if before_snapshot:
        entry.set_snapshot(before_snapshot)
    if changed_fields:
        entry.set_changed_fields(changed_fields)

    db.add(entry)


# ─── 回滚 ───

def rollback_batch(batch_id: str):
    """回滚指定批次的导入（从 kb_change_log 恢复快照）"""
    _init_db()
    db = _session()

    logs = (db.query(KBChangeLog)
            .filter(KBChangeLog.change_reason.like(f"batch={batch_id}%"))
            .order_by(KBChangeLog.id.desc())
            .all())

    if not logs:
        print(f"未找到批次 {batch_id} 的变更记录")
        db.close()
        return

    print(f"找到 {len(logs)} 条变更记录")
    restored = 0

    for log in logs:
        try:
            if log.action == "create":
                product = db.query(KBProduct).filter(KBProduct.id == log.target_id).first()
                if product and product.import_batch_id == batch_id:
                    db.delete(product)
                    restored += 1
                continue

            if not log.snapshot_json:
                continue

            snapshot = json.loads(log.snapshot_json)
            i_id = snapshot.get("i_id")
            if not i_id:
                continue

            product = db.query(KBProduct).filter(KBProduct.i_id == i_id).first()
            if not product:
                continue

            # 恢复快照中的值
            for field in ("product_name", "brand", "category_l1", "category_l2",
                          "category_l3", "status"):
                if field in snapshot:
                    setattr(product, field, snapshot[field])

            for json_field in ("sku_list", "specs", "logistics", "warranty"):
                if json_field in snapshot:
                    setter = f"set_{json_field}"
                    getattr(product, setter)(snapshot[json_field])

            if "completeness_score" in snapshot:
                product.completeness_score = snapshot["completeness_score"]

            product.updated_by = "rollback"
            product.updated_at = datetime.utcnow()
            restored += 1
        except Exception as e:
            print(f"  恢复 {log.target_id} 失败: {e}")

    db.commit()
    db.close()
    print(f"已恢复 {restored} 条记录")


# ─── CLI ───

def main():
    parser = argparse.ArgumentParser(description="安全导入 JST 商品数据到 kb_product")
    parser.add_argument("--file", required=False, help="Excel 文件路径")
    parser.add_argument("--sheet", help="指定工作表名称")
    parser.add_argument("--dry-run", action="store_true", default=True,
                        help="仅分析不写库 (默认)")
    parser.add_argument("--apply", action="store_true", help="正式写入数据库")
    parser.add_argument("--product-ids", help="限定商品 i_id，逗号分隔")
    parser.add_argument("--limit", type=int, help="限量处理行数")
    parser.add_argument("--batch-id", help="指定批次号")
    parser.add_argument("--report-dir", help="报告输出目录")
    parser.add_argument("--rollback", action="store_true", help="回滚指定批次")
    parser.add_argument("--target-env", choices=["local", "production"],
                        default="local", help="目标环境")

    parser.add_argument("--dingtalk-enrich", action="store_true",
                        help="Optionally enrich from DingTalk; credentials must come from environment variables")
    parser.add_argument("--confirm-full-import", action="store_true",
                        help="Allow full apply without --limit or --product-ids")

    args = parser.parse_args()

    # 回滚模式
    if args.rollback:
        if not args.batch_id:
            print("回滚需要指定 --batch-id")
            sys.exit(1)
        rollback_batch(args.batch_id)
        return

    # 导入模式
    if not args.file:
        print("请指定 --file 参数")
        sys.exit(1)

    if not os.path.exists(args.file):
        print(f"文件不存在: {args.file}")
        sys.exit(1)

    if args.target_env == "production" and args.apply:
        print("⚠️  生产环境导入需要额外确认和备份")
        print("请先完成本地 dry-run 验证，然后通过正式流程执行")
        sys.exit(1)

    product_ids = None
    if args.product_ids:
        product_ids = [p.strip() for p in args.product_ids.split(",") if p.strip()]

    run_import(
        file_path=args.file,
        dry_run=args.dry_run and not args.apply,
        apply=args.apply,
        product_ids=product_ids,
        limit=args.limit,
        batch_id=args.batch_id,
        report_dir=args.report_dir,
        sheet=args.sheet,
        dingtalk_enrich=args.dingtalk_enrich,
        confirm_full_import=args.confirm_full_import,
    )


if __name__ == "__main__":
    main()
