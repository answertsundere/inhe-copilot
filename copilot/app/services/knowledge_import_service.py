"""
知识导入服务 - Excel/CSV 导入
支持 .xlsx / .xls / .csv
"""

import hashlib
import csv
import io
import re
import uuid
from datetime import datetime
from typing import List, Optional

from app.repositories.knowledge_entry_repository import KnowledgeEntryRepository


# ---------- Sheet → source_type 映射 ----------
SHEET_TO_SOURCE_TYPE = {
    "商品总览（增强版）": "product_facts",
    "金牌客服问答（增强版）": "faq",
    "物流发货常见问答（增强版）": "shipping_policy",
    "安装指导常见问答（增强版）": "installation_guide",
    "售后退换货常见问答（增强版）": "aftersales_policy",
    "客诉处理常见问答（增强版）": "high_risk_sop",
    "发票与价保常见问答（增强版）": "aftersales_policy",
    "推销与关联推荐话术（增强版）": "response_templates",
    "平台规则速查（增强版）": "forbidden_rules",
    "安全与质保常见问答（增强版）": "product_facts",
    "特殊场景处理指南（增强版）": "high_risk_sop",
    "客服用语规范速查（增强版）": "response_templates",
    "高风险SOP手册": "high_risk_sop",
    "真实客服案例库": "real_cases",
    "反馈学习数据": "feedback_records",
}

# 模糊匹配规则（keyword → source_type）
_SHEET_FUZZY_RULES = [
    ("商品总览", "product_facts"),
    ("金牌客服", "faq"),
    ("物流发货", "shipping_policy"),
    ("安装指导", "installation_guide"),
    ("售后退换", "aftersales_policy"),
    ("客诉处理", "high_risk_sop"),
    ("发票", "aftersales_policy"),
    ("价保", "aftersales_policy"),
    ("推销", "response_templates"),
    ("推荐话术", "response_templates"),
    ("平台规则", "forbidden_rules"),
    ("安全与质保", "product_facts"),
    ("特殊场景", "high_risk_sop"),
    ("客服规范", "response_templates"),
    ("用语规范", "response_templates"),
    ("高风险SOP", "high_risk_sop"),
    ("真实案例", "real_cases"),
    ("客服案例", "real_cases"),
    ("反馈学习", "feedback_records"),
]


# ---------- 列名映射（按优先级排序，先匹配先返回）----------
_TITLE_KEYS = ["场景描述", "客户问题", "问题", "标准问题", "常见问法", "商品名称", "SOP编号", "案例编号", "question", "title"]
_CONTENT_KEYS = ["金牌回答", "正确回复", "标准回复模板", "答案", "标准回复", "回复", "话术", "answer", "content", "步骤1：第一时间响应"]
_INTENT_KEYS = ["意图", "intent", "场景", "scenario", "主要意图"]
_RISK_KEYS = ["风险等级", "risk_level", "是否高风险"]
_AUTO_REPLY_KEYS = ["可自动回复", "auto_reply_allowed", "是否可自动回复"]
_HUMAN_REVIEW_KEYS = ["需人工审核", "human_review_required", "是否需人工审核"]

# product_facts 专用 title 列名（优先级高于通用 _TITLE_KEYS）
_PRODUCT_FACTS_TITLE_KEYS = ["商品名称", "产品名称", "SKU名称", "款式名称", "内部商品名", "商品名", "title"]

# product_facts 结构化字段（用于生成 content）
_PRODUCT_FACTS_CONTENT_FIELDS = [
    ("商品名", ["商品名称", "产品名称", "SKU名称", "款式名称", "内部商品名", "商品名"]),
    ("SKU", ["SKU", "sku_code", "商品编码", "SKU编码", "平台商品编码", "产品编码"]),
    ("材质", ["材质", "材质/用料", "用料", "主要材质"]),
    ("尺寸", ["尺寸", "产品尺寸", "规格尺寸", "外形尺寸", "长宽高"]),
    ("承重", ["承重", "承重/容量", "容量", "载重", "负重"]),
    ("适用年龄", ["适用年龄", "年龄范围", "推荐年龄", "适合年龄", "年龄段"]),
    ("颜色/规格", ["颜色/规格", "颜色", "规格", "颜色规格", "色系", "配色"]),
    ("配件", ["配件", "配件清单", "包装清单", "包含配件", "标配"]),
    ("安装方式", ["安装方式", "安装说明", "安装要求", "是否需要安装"]),
    ("质保", ["质保", "质保期", "保修", "保修期", "保修年限"]),
    ("包装", ["包装", "包装方式", "包装清单"]),
    ("物流属性", ["物流属性", "物流方式", "发货时效", "快递方式", "运费说明"]),
    ("注意事项", ["注意事项", "注意", "温馨提示", "使用注意", "安全提示"]),
]

# SKU 列名（用于去重 + scope 绑定）
_SKU_KEYS = ["SKU", "sku_code", "商品编码", "SKU编码", "平台商品编码", "产品编码", "商品条码", "关联SKU"]

# 商品范围列名（用于 scope 绑定）
_PRODUCT_SCOPE_KEYS = ["关联商品", "商品名称", "产品名称", "款式名称", "内部商品名", "商品名"]

# 三级分类列名
_CATEGORY_L1_KEYS = ["一级类目"]
_CATEGORY_L2_KEYS = ["二级类目"]
_CATEGORY_L3_KEYS = ["三级类目"]
_SEARCH_KEYWORDS_KEYS = ["分类关键词", "检索关键词", "search_keywords"]
_SCENE_TAG_KEYS = ["适用场景", "场景标签", "scene_tag"]
_PLATFORM_COL_KEYS = ["平台", "适用平台", "platform"]
_PRODUCT_LINE_KEYS = ["关联产品线", "产品线", "product_line"]


def _parse_scope_list(val: str) -> list:
    """把逗号分隔的字符串拆成列表，过滤空值"""
    if not val:
        return []
    return [v.strip() for v in str(val).split(",") if v.strip()]

# 高风险 source_type 集合
_HIGH_RISK_SOURCE_TYPES = {"high_risk_sop", "forbidden_rules"}


def _resolve_source_type(sheet_name: str) -> str:
    """精确匹配 → 模糊匹配 → 空字符串"""
    if not sheet_name:
        return ""
    st = SHEET_TO_SOURCE_TYPE.get(sheet_name.strip())
    if st:
        return st
    for keyword, mapped in _SHEET_FUZZY_RULES:
        if keyword in sheet_name:
            return mapped
    return ""


def _find_key(raw: dict, candidates: list) -> Optional[str]:
    """在 raw 中按优先级查找候选列名，返回第一个匹配的值"""
    for c in candidates:
        for k, v in raw.items():
            if k is None:
                continue
            if str(k).strip() == c:
                return str(v).strip() if v is not None else ""
    return None


def _find_any_key(raw: dict, candidates: list) -> Optional[str]:
    """在 raw 中查找候选列名（任意一个匹配即可），返回第一个匹配的值"""
    for c in candidates:
        for k, v in raw.items():
            if k is None:
                continue
            if str(k).strip() == c:
                return str(v).strip() if v is not None else ""
    return None


def _compute_content_hash(title: str, content: str) -> str:
    text = f"{title.strip()}|{content.strip()}"
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:32]


def _bool_from_cell(v) -> bool:
    """把 Excel/CSV 中的布尔值字符串转为 bool"""
    if v is None:
        return False
    if isinstance(v, bool):
        return v
    s = str(v).strip().lower()
    return s in ("是", "yes", "true", "1", "y", "√")


def _risk_from_cell(v, source_type: str) -> str:
    """提取风险等级，高风险 source_type 强制 high"""
    if source_type in _HIGH_RISK_SOURCE_TYPES:
        return "high"
    if v is None:
        return "low"
    s = str(v).strip()
    if s in ("高", "high", "极高"):
        return "high"
    if s in ("中", "medium"):
        return "medium"
    return "low"


class ImportPreviewItem:
    def __init__(self, row_number, title, source_type, risk_level, warnings, raw_data):
        self.row_number = row_number
        self.title = title
        self.source_type = source_type
        self.risk_level = risk_level
        self.warnings = warnings
        self.raw_data = raw_data
        self.duplicate = False


class KnowledgeImportService:
    """知识导入服务"""

    @staticmethod
    def parse_excel_preview(file_path: str, source_type_override: str = "") -> dict:
        """
        解析 Excel/CSV 并返回预览数据，不写入数据库。
        """
        suffix = (file_path or "").lower()
        batch_id = f"import_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}"
        preview_items = []
        total_rows = 0
        errors = []

        # ---------- CSV ----------
        if suffix.endswith(".csv"):
            try:
                with open(file_path, "r", encoding="utf-8-sig", newline="") as f:
                    reader = csv.reader(f)
                    rows = list(reader)
                if not rows:
                    return _empty_preview(batch_id, "CSV 文件为空")
                headers = rows[0]
                data_rows = rows[1:]
                sheet_name = "CSV"
                mapped_source = source_type_override or ""
                for idx, row in enumerate(data_rows, start=2):
                    total_rows += 1
                    if not any(cell.strip() for cell in row if cell):
                        continue
                    raw = {h: v for h, v in zip(headers, row)}
                    item, err = _build_preview_item(raw, idx, sheet_name, mapped_source, batch_id)
                    if err:
                        errors.append(err)
                    if item:
                        preview_items.append(item)
            except Exception as e:
                return _empty_preview(batch_id, str(e))

        # ---------- Excel ----------
        else:
            try:
                import openpyxl
                wb = openpyxl.load_workbook(file_path, data_only=True)
            except ImportError:
                return _empty_preview(batch_id, "openpyxl 未安装")
            except Exception as e:
                return _empty_preview(batch_id, str(e))

            for sheet_name in wb.sheetnames:
                mapped_source = _resolve_source_type(sheet_name)
                if not mapped_source and not source_type_override:
                    continue

                ws = wb[sheet_name]
                first_row = next(ws.iter_rows(min_row=1, max_row=1, values_only=True), None)
                if not first_row:
                    continue
                headers = [str(cell).strip() if cell is not None else "" for cell in first_row]
                if not any(headers):
                    continue

                for idx, row in enumerate(ws.iter_rows(min_row=2, values_only=True), start=2):
                    total_rows += 1
                    if not any(cell is not None and str(cell).strip() for cell in row):
                        continue
                    raw = {h: v for h, v in zip(headers, row) if h}
                    item, err = _build_preview_item(raw, idx, sheet_name, mapped_source or source_type_override, batch_id)
                    if err:
                        errors.append(err)
                    if item:
                        preview_items.append(item)

        # ---------- 去重检查（预览阶段）----------
        _deduplicate_preview(preview_items)

        # ---------- 统计 ----------
        valid_items = [i for i in preview_items if not i.get("errors")]
        failed_items = [i for i in preview_items if i.get("errors")]
        duplicate_items = [i for i in preview_items if i.get("duplicate_candidate")]
        variant_items = [i for i in preview_items if i.get("possible_variant")]
        high_risk_items = [i for i in preview_items if i.get("risk_level") in ("high", "critical")]
        product_facts_generated = [i for i in preview_items if i.get("source_type") == "product_facts" and i.get("content_generated")]

        # sheet 级统计
        sheets_summary = {}
        for item in preview_items:
            sheet = item.get("source_sheet", "")
            if sheet not in sheets_summary:
                sheets_summary[sheet] = {"total": 0, "valid": 0, "failed": 0, "duplicate": 0, "possible_variant": 0}
            sheets_summary[sheet]["total"] += 1
            if item.get("errors"):
                sheets_summary[sheet]["failed"] += 1
            else:
                sheets_summary[sheet]["valid"] += 1
            if item.get("duplicate_candidate"):
                sheets_summary[sheet]["duplicate"] += 1
            if item.get("possible_variant"):
                sheets_summary[sheet]["possible_variant"] += 1

        warnings = []
        for item in preview_items:
            for w in item.get("warnings", []):
                warnings.append(f"Row {item.get('row_number')} ({item.get('source_sheet')}): {w}")

        return {
            "batch_id": batch_id,
            "total_rows": total_rows,
            "preview_items": preview_items,
            "items": valid_items,
            "valid_count": len(valid_items),
            "failed_count": len(failed_items),
            "duplicate_count": len(duplicate_items),
            "possible_variant_count": len(variant_items),
            "product_facts_generated_content_count": len(product_facts_generated),
            "high_risk_count": len(high_risk_items),
            "sheets_summary": sheets_summary,
            "warnings": warnings,
            "errors": errors,
        }

    @staticmethod
    def import_from_preview(preview_items: List[dict], user: str = "", batch_id: str = "", allow_duplicates: bool = False) -> dict:
        """
        根据预览数据写入数据库（默认 draft）。
        只导入 valid 的行。
        """
        success = 0
        failed = 0
        errors = []
        warnings = []
        created_ids = []
        audit_logs = []

        for item in preview_items:
            try:
                title = item.get("title", "").strip()
                content = item.get("content", "").strip()

                # 只导入有效行
                if item.get("errors"):
                    failed += 1
                    errors.append({"row": item.get("row_number"), "reason": "; ".join(item["errors"])})
                    continue

                if not title or not content:
                    failed += 1
                    errors.append({"row": item.get("row_number"), "reason": "标题或内容为空"})
                    continue

                # 数据库去重检查
                dup = KnowledgeEntryRepository.check_duplicate(title, item.get("source_type", ""), content)
                if dup:
                    if not allow_duplicates:
                        failed += 1
                        errors.append({"row": item.get("row_number"), "reason": f"与已有条目重复 (ID={dup.id})"})
                        continue
                    else:
                        warnings.append(f"Row {item.get('row_number')}: 与已有条目重复 (ID={dup.id})，但允许重复已导入")

                # 跳过 preview 标记的重复（除非允许）
                if item.get("duplicate_candidate") and not allow_duplicates:
                    failed += 1
                    errors.append({"row": item.get("row_number"), "reason": "与同批次条目重复，已跳过"})
                    continue

                source_type = item.get("source_type", "")
                risk_level = item.get("risk_level", "low")

                # 高风险强制设置
                auto_reply_allowed = item.get("auto_reply_allowed", True)
                human_review_required = item.get("human_review_required", False)
                if source_type in _HIGH_RISK_SOURCE_TYPES or risk_level in ("high", "critical"):
                    auto_reply_allowed = False
                    human_review_required = True
                    if risk_level not in ("high", "critical"):
                        risk_level = "high"

                entry = KnowledgeEntryRepository.create(
                    source_type=source_type,
                    title=title,
                    content=content,
                    intent=item.get("intent", "general"),
                    category=item.get("category_l1", ""),
                    category_l3=item.get("category_l3", ""),
                    search_keywords=item.get("search_keywords", ""),
                    scene_tag=item.get("scene_tag", ""),
                    product_line=item.get("product_line", ""),
                    product_scope=item.get("product_scope", []),
                    sku_scope=item.get("sku_scope", []),
                    risk_level=risk_level,
                    auto_reply_allowed=auto_reply_allowed,
                    human_review_required=human_review_required,
                    created_by=user,
                    source_sheet=item.get("source_sheet", ""),
                    row_number=item.get("row_number", 0),
                    import_batch_id=batch_id,
                )
                success += 1
                created_ids.append(entry.id)
                audit_logs.append({
                    "entry_id": entry.id,
                    "action": "import",
                    "old_status": "",
                    "new_status": "draft",
                    "performed_by": user,
                    "details": f"从 {item.get('source_sheet','')} 第 {item.get('row_number',0)} 行导入",
                })
            except Exception as e:
                failed += 1
                errors.append({"row": item.get("row_number"), "reason": str(e)})

        return {
            "batch_id": batch_id,
            "success": success,
            "failed": failed,
            "errors": errors,
            "created_ids": created_ids,
            "audit_logs": audit_logs,
        }


def _empty_preview(batch_id: str, error: str) -> dict:
    return {
        "batch_id": batch_id,
        "total_rows": 0,
        "preview_items": [],
        "valid_count": 0,
        "failed_count": 0,
        "duplicate_count": 0,
        "possible_variant_count": 0,
        "product_facts_generated_content_count": 0,
        "high_risk_count": 0,
        "sheets_summary": {},
        "warnings": [],
        "errors": [error],
    }


def _deduplicate_preview(preview_items: list):
    """
    预览阶段去重与变体识别。
    - content_hash 完全一致 → duplicate
    - sku_code 完全一致 → duplicate
    - title 相同 + content 不同 → possible_variant
    """
    seen_hashes = {}   # content_hash -> item
    seen_skus = {}     # sku_code -> item
    seen_titles = {}   # (source_type, title) -> item

    for item in preview_items:
        h = item.get("content_hash", "")
        sku = item.get("sku_code", "")
        t = item.get("title", "")
        st = item.get("source_type", "")

        # 1. content_hash 完全一致
        if h and h in seen_hashes:
            item["duplicate_candidate"] = True
            item["warnings"].append("content_hash 与已处理条目完全一致")
            continue

        # 2. sku_code 完全一致（仅限 product_facts）
        if sku and sku in seen_skus:
            item["duplicate_candidate"] = True
            item["warnings"].append(f"SKU({sku}) 与已处理条目重复")
            continue

        # 记录已见
        if h:
            seen_hashes[h] = item
        if sku:
            seen_skus[sku] = item

        # 3. title 相同但 content 不同 → possible_variant
        if t and st:
            key = (st, t)
            if key in seen_titles:
                prev = seen_titles[key]
                if item.get("content_hash") != prev.get("content_hash"):
                    item["possible_variant"] = True
                    item["warnings"].append("title 相同但 content 不同，可能为变体/不同规格")
                    # 同时标记之前的条目
                    if not prev.get("duplicate_candidate"):
                        prev["possible_variant"] = True
                        prev["warnings"].append("title 相同但 content 不同，可能为变体/不同规格")
            else:
                seen_titles[key] = item


def _build_preview_item(raw: dict, row_number: int, sheet_name: str, mapped_source: str, batch_id: str):
    """从一行原始数据构建 preview item，返回 (item, error_str)"""
    # ---------- product_facts 专用 title ----------
    if mapped_source == "product_facts":
        title = _find_key(raw, _PRODUCT_FACTS_TITLE_KEYS) or ""
    else:
        title = _find_key(raw, _TITLE_KEYS) or ""

    content = _find_key(raw, _CONTENT_KEYS) or ""
    intent = _find_key(raw, _INTENT_KEYS) or "general"
    risk_level = _risk_from_cell(_find_key(raw, _RISK_KEYS), mapped_source)
    auto_reply_allowed = _bool_from_cell(_find_key(raw, _AUTO_REPLY_KEYS))
    human_review_required = _bool_from_cell(_find_key(raw, _HUMAN_REVIEW_KEYS))

    # 提取 sku_code（用于去重）
    sku_code = _find_any_key(raw, _SKU_KEYS) or ""

    # 提取商品范围 / SKU 范围（用于 scope 绑定）
    product_scope = _parse_scope_list(_find_any_key(raw, _PRODUCT_SCOPE_KEYS) or "")
    sku_scope = _parse_scope_list(_find_any_key(raw, _SKU_KEYS) or "")
    # 如果 product_facts 没有显式关联商品，尝试用 title 回退
    if not product_scope and mapped_source == "product_facts" and title:
        product_scope = [title.strip()]

    # 提取三级分类和元数据
    category_l1 = _find_any_key(raw, _CATEGORY_L1_KEYS) or ""
    category_l2 = _find_any_key(raw, _CATEGORY_L2_KEYS) or ""
    category_l3 = _find_any_key(raw, _CATEGORY_L3_KEYS) or ""
    search_keywords = _find_any_key(raw, _SEARCH_KEYWORDS_KEYS) or ""
    scene_tag = _find_any_key(raw, _SCENE_TAG_KEYS) or ""
    platform_col = _find_any_key(raw, _PLATFORM_COL_KEYS) or ""
    product_line = _find_any_key(raw, _PRODUCT_LINE_KEYS) or ""

    # ---------- title 回退 ----------
    if not title:
        fallback_keys = _PRODUCT_FACTS_TITLE_KEYS if mapped_source == "product_facts" else _TITLE_KEYS
        for k, v in raw.items():
            if k and str(k).strip() in fallback_keys and v:
                title = str(v).strip()
                break

    # ---------- content 回退 ----------
    if not content:
        for k, v in raw.items():
            if k and str(k).strip() in _CONTENT_KEYS and v:
                content = str(v).strip()
                break

    # ---------- 结构化 content 生成 ----------
    content_generated = False

    # product_facts 结构化生成
    if mapped_source == "product_facts":
        parts = []
        for label, key_candidates in _PRODUCT_FACTS_CONTENT_FIELDS:
            val = _find_any_key(raw, key_candidates)
            if val:
                parts.append(f"{label}：{val}")
        if parts:
            content = "\n".join(parts)
            content_generated = True

    # SOP 手册：合并多个步骤
    if mapped_source == "high_risk_sop" and not content:
        steps = []
        for k, v in raw.items():
            if k and str(k).strip().startswith("步骤") and v:
                steps.append(f"{k}: {v}")
        if steps:
            content = "\n".join(steps)

    # 案例库
    if mapped_source == "real_cases":
        if not title:
            title = raw.get("场景描述", "") or raw.get("案例编号", "")
        if not content:
            parts = []
            for k in ("客户原始对话", "正确回复", "错误回复", "主管评语", "最终处理结果"):
                if raw.get(k):
                    parts.append(f"{k}: {raw[k]}")
            content = "\n".join(parts)

    # ---------- 校验 ----------
    warnings = []
    errors = []
    if not title:
        errors.append("缺少标题/问题字段")
    if not content:
        errors.append("缺少内容/答案字段")

    # ---------- 高风险强制设置 ----------
    if mapped_source in _HIGH_RISK_SOURCE_TYPES:
        risk_level = "high"
        auto_reply_allowed = False
        human_review_required = True
        warnings.append("高风险 source_type，将强制人工审核")
    elif risk_level in ("high", "critical"):
        auto_reply_allowed = False
        human_review_required = True
        warnings.append("高风险等级，将强制人工审核")

    content_hash = _compute_content_hash(title, content) if title and content else ""

    item = {
        "source_sheet": sheet_name,
        "row_number": row_number,
        "source_type": mapped_source,
        "title": title,
        "content": content,
        "content_preview": (content or "")[:200],
        "intent": intent,
        "risk_level": risk_level,
        "auto_reply_allowed": auto_reply_allowed,
        "human_review_required": human_review_required,
        "sku_code": sku_code,
        "product_scope": product_scope,
        "sku_scope": sku_scope,
        "category_l1": category_l1,
        "category_l2": category_l2,
        "category_l3": category_l3,
        "search_keywords": search_keywords,
        "scene_tag": scene_tag,
        "platform_col": platform_col,
        "product_line": product_line,
        "warnings": warnings,
        "errors": errors,
        "duplicate_candidate": False,
        "possible_variant": False,
        "content_hash": content_hash,
        "content_generated": content_generated,
        "import_batch_id": batch_id,
        "raw": {k: v for k, v in raw.items() if v is not None},
    }

    return item, None
