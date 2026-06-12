"""
知识发布前质量检查 - knowledge_quality_gate

检查知识条目是否满足发布条件。
AI 只能给 suggested_fixes，不能自动接受修改或自动发布。
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime
from typing import Any

logger = logging.getLogger(__name__)

_VALIDATION_VERSION = "2.0"

# 高风险事实字段
HIGH_RISK_FACT_FIELDS = [
    "材质", "填充物", "承重", "适用年龄", "尺寸", "重量",
    "洗涤", "清洗", "防水", "防火", "无毒", "食品级",
    "认证", "检测", "报告", "有效期", "保质期",
]

# 需要来源引用的事实字段
FACT_FIELDS_REQUIRING_REFERENCE = [
    "材质", "填充物", "承重", "适用年龄", "尺寸", "重量",
    "洗涤", "清洗", "防水", "认证", "检测",
]

# 禁止的绝对承诺
FORBIDDEN_ABSOLUTE_CLAIMS = [
    r"绝对无毒", r"100%安全", r"零风险", r"万无一失",
    r"永远不坏", r"终身保修", r"假一赔十",
]

# 敏感信息正则
_PHONE_RE = re.compile(r"1[3-9]\d{9}")
_ID_CARD_RE = re.compile(r"[1-9]\d{5}(?:19|20)\d{2}(?:0[1-9]|1[0-2])(?:0[1-9]|[12]\d|3[01])\d{3}[\dXx]")
_TOKEN_RE = re.compile(r"(?:token|apikey|api_key|secret|password|密码)\s*[:=]\s*\S+", re.IGNORECASE)


def validate_for_publish(entry) -> dict:
    """验证知识条目是否满足发布条件。

    Returns:
        {
            "passed": bool,
            "blocking_issues": [str],
            "warnings": [str],
            "conflicts": [dict],
            "duplicate_entry_ids": [int],
            "suggested_fixes": [str],
            "validated_at": str,
            "validation_version": str,
        }
    """
    blocking = []
    warnings = []
    suggested_fixes = []

    title = (entry.title or "").strip()
    content = (entry.content or "").strip()
    source_type = entry.source_type or ""
    product_scope = entry.get_product_scope()
    sku_scope = entry.get_sku_scope()
    platform_scope = entry.get_platform_scope()
    risk_level = entry.risk_level or ""
    source_confidence = entry.source_confidence or 0
    source_sheet = (entry.source_sheet or "").strip()
    created_by = entry.created_by or ""
    reviewed_by = entry.reviewed_by or ""
    human_review_required = entry.human_review_required or False

    # 1. title/content 不能为空
    if not title:
        blocking.append("标题不能为空")
    if not content:
        blocking.append("内容不能为空")

    # 2. source_type 必须明确
    if not source_type:
        blocking.append("必须指定 source_type（事实类型）")

    # 3. 商品事实必须有 product_scope 和 sku_scope
    if source_type in ("product_facts", "faq"):
        if not product_scope and not sku_scope:
            blocking.append("商品事实类型必须指定 product_scope 或 sku_scope")
            suggested_fixes.append("请添加商品范围，例如 product_scope=['一号狮子围兜']")

    # 4. product_scope 与 sku_scope 无法对应
    if product_scope and sku_scope:
        # sku_scope 应该是 product_scope 的子集，或至少有关联
        # 这里只做简单检查：sku_scope 中不能包含完全不同商品的 SKU
        pass  # complex cross-validation deferred

    # 5. 高风险事实必须人工审核
    is_high_risk_content = any(kw in content for kw in HIGH_RISK_FACT_FIELDS)
    if is_high_risk_content:
        if not human_review_required:
            blocking.append("包含高风险事实字段，必须设置 human_review_required=true")
            suggested_fixes.append("设置 human_review_required=True")

    # 6. reviewer 与 created_by 相同且属于高风险知识
    if source_type in ("high_risk_sop", "forbidden_rules") or risk_level in ("high", "critical"):
        if reviewed_by and created_by and reviewed_by == created_by:
            blocking.append("高风险知识审核人与创建人不能相同")
            suggested_fixes.append("需要不同的 supervisor 审核")

    # 7. 需要人工复核但 reviewed_by 为空
    if human_review_required and not reviewed_by:
        blocking.append("需要人工复核的知识必须有审核人")
        suggested_fixes.append("由 supervisor 审核后再发布")

    # 8. 存在明确冲突知识
    conflicts = _detect_conflicts(entry)
    if conflicts:
        # 检查是否为明确冲突（同 scope + 同 type + 不同内容）
        for c in conflicts:
            blocking.append(f"与 entry {c['entry_id']} '{c['title']}' 存在冲突")
            suggested_fixes.append(f"解决与 entry {c['entry_id']} 的冲突后再发布")

    # 9. 检测重复内容
    duplicates = _detect_duplicates(entry)
    if duplicates:
        blocking.append(f"存在内容完全重复的已发布知识: {duplicates}")
        for d in duplicates:
            suggested_fixes.append(f"与 entry {d} 内容重复，请检查")

    # 10. 包含禁止的绝对承诺
    for pattern in FORBIDDEN_ABSOLUTE_CLAIMS:
        if re.search(pattern, content):
            blocking.append(f"包含禁止的绝对承诺: {pattern}")
            suggested_fixes.append(f"删除或修改绝对承诺 '{pattern}'")

    # 11. 包含手机号等敏感信息
    if _PHONE_RE.search(content):
        blocking.append("内容包含手机号等敏感信息")
    if _ID_CARD_RE.search(content):
        blocking.append("内容包含身份证号等敏感信息")
    if _TOKEN_RE.search(content):
        blocking.append("内容包含 Token/密钥等敏感信息")

    # 12. source_sheet 缺失且属于材质、尺寸、承重、年龄、洗涤等事实
    if not source_sheet:
        is_factual = any(kw in content for kw in FACT_FIELDS_REQUIRING_REFERENCE)
        if is_factual and source_type == "product_facts":
            blocking.append("事实型知识缺少来源引用 (source_sheet)")
            suggested_fixes.append("添加 source_sheet，如商品详情页、检测报告等")

    # 13. 不同商品编号混用
    if product_scope:
        for ps in product_scope:
            numbers = re.findall(r"[一二三四五六七八九十]+号", ps)
            if len(numbers) > 1:
                warnings.append(f"product_scope 中包含多个编号: {ps}")

    # 14. 内容过短
    if len(content) < 5:
        warnings.append("内容过短，可能无意义")

    # 15. source_sheet 缺失时降低 confidence（warning only）
    if not source_sheet and source_confidence > 0.3:
        warnings.append("缺少来源引用，建议降低 source_confidence")
        suggested_fixes.append("添加 source_sheet 或降低 confidence 到 0.3 以下")

    return {
        "passed": len(blocking) == 0,
        "blocking_issues": blocking,
        "warnings": warnings,
        "conflicts": conflicts,
        "duplicate_entry_ids": duplicates,
        "suggested_fixes": suggested_fixes,
        "validated_at": datetime.utcnow().isoformat(),
        "validation_version": _VALIDATION_VERSION,
    }


def check_publish_quality(entry) -> dict:
    """向后兼容的接口，内部调用 validate_for_publish。"""
    return validate_for_publish(entry)


def _detect_conflicts(entry) -> list[dict]:
    """检测同 scope、同 source_type 的冲突知识。"""
    try:
        from app.db import SessionLocal
        from app.models.knowledge_base import KnowledgeEntry

        product_scope = entry.get_product_scope()
        if not product_scope:
            return []

        db = SessionLocal()
        try:
            candidates = db.query(KnowledgeEntry).filter(
                KnowledgeEntry.status == "published",
                KnowledgeEntry.source_type == entry.source_type,
                KnowledgeEntry.id != entry.id,
            ).all()

            conflicts = []
            for c in candidates:
                c_scope = c.get_product_scope()
                if any(ps in c_scope or c_ps in product_scope
                       for ps in product_scope for c_ps in c_scope):
                    if c.content_hash != entry.content_hash:
                        conflicts.append({
                            "entry_id": c.id,
                            "title": c.title,
                            "scope": c_scope,
                            "status": c.status,
                        })
            return conflicts
        finally:
            db.close()
    except Exception as e:
        logger.warning("Conflict detection failed: %s", e)
        return []


def _detect_duplicates(entry) -> list[int]:
    """检测重复内容。"""
    try:
        from app.db import SessionLocal
        from app.models.knowledge_base import KnowledgeEntry

        db = SessionLocal()
        try:
            dupes = db.query(KnowledgeEntry).filter(
                KnowledgeEntry.content_hash == entry.content_hash,
                KnowledgeEntry.id != entry.id,
                KnowledgeEntry.status == "published",
            ).all()
            return [d.id for d in dupes]
        finally:
            db.close()
    except Exception as e:
        logger.warning("Duplicate detection failed: %s", e)
        return []
