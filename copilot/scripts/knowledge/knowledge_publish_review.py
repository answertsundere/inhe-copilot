"""
知识发布审核队列生成脚本

扫描 knowledge_base.db 中 status='draft' 的知识条目，
根据内容完整性、高风险事实、冲突检测、来源可信度等规则分类为：
  - auto_publish_candidate: 可自动发布
  - manual_review_required: 需人工审核
  - reject_or_rewrite: 建议驳回或重写

输出: data/knowledge_publish_review_queue.jsonl + stdout 摘要

用法:
  python -m scripts.knowledge.knowledge_publish_review
  python -m scripts.knowledge.knowledge_publish_review --db path/to/other.db
"""

import argparse
import json
import os
import re
import sqlite3
import sys
from collections import defaultdict

# ---------------------------------------------------------------------------
# 项目根目录加入 sys.path（若需复用 app 模块可直接 import）
# ---------------------------------------------------------------------------
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

# 高风险产品事实关键词
HIGH_RISK_FACT_KEYWORDS = [
    "材质", "尺寸", "承重", "适用年龄", "洗涤", "安全",
    "检测报告", "厚度", "重量", "实木", "防水", "可水洗",
]

# 不确定性/猜测性关键词（句首/独立出现）
SPECULATION_PATTERNS = [
    r"(?:^|[。！？\n])\s*可能",
    r"(?:^|[。！？\n])\s*大概",
    r"(?:^|[。！？\n])\s*应该",
    r"(?:^|[。！？\n])\s*猜测",
    r"(?:^|[。！？\n])\s*估计",
]

# 分类标签
CLASS_AUTO = "auto_publish_candidate"
CLASS_MANUAL = "manual_review_required"
CLASS_REJECT = "reject_or_rewrite"


# ---------------------------------------------------------------------------
# 工具函数
# ---------------------------------------------------------------------------

def _parse_json_safe(raw: str, default=None):
    """安全解析 JSON 字符串"""
    if not raw:
        return default if default is not None else []
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return default if default is not None else []


def _contains_high_risk_facts(content: str) -> bool:
    """检查内容是否包含高风险产品事实关键词"""
    if not content:
        return False
    return any(kw in content for kw in HIGH_RISK_FACT_KEYWORDS)


def _looks_like_speculation(content: str) -> bool:
    """检查内容是否包含猜测性表述（句首级别的可能/大概/应该/猜测/估计）"""
    if not content:
        return False
    for pattern in SPECULATION_PATTERNS:
        if re.search(pattern, content):
            return True
    return False


def _has_product_identity(product_scope: list, sku_scope: list) -> bool:
    """检查是否有产品身份信息（非空 scope）"""
    product_ok = bool(product_scope and product_scope != [""])
    sku_ok = bool(sku_scope and sku_scope != [""])
    return product_ok or sku_ok


def _has_scope_cross_contamination(product_scope: list) -> bool:
    """
    检查 product_scope 是否存在跨品类污染。
    当 product_scope 同时包含明显不同品类的产品（3 个以上不同名称）时视为可疑。
    """
    if not product_scope or len(product_scope) <= 2:
        return False
    # 简单启发式：超过 3 个不同产品名称可能存在交叉污染
    unique = set(p.strip() for p in product_scope if p and p.strip())
    return len(unique) > 3


# ---------------------------------------------------------------------------
# 核心逻辑
# ---------------------------------------------------------------------------

def classify_entry(
    entry: dict,
    chunk_count: int,
    conflict_ids: list,
) -> tuple:
    """
    对单个条目进行分类。

    返回 (classification, reasons: list[str])
    """
    reasons = []

    content = entry.get("content", "") or ""
    product_scope = _parse_json_safe(entry.get("product_scope_json", "[]"))
    sku_scope = _parse_json_safe(entry.get("sku_scope_json", "[]"))
    source_type = entry.get("source_type", "") or ""
    source_confidence = entry.get("source_confidence")
    if source_confidence is None:
        source_confidence = 0.5
    fact_review_status = entry.get("fact_review_status") or ""

    has_high_risk = _contains_high_risk_facts(content)
    is_speculation = _looks_like_speculation(content)
    has_identity = _has_product_identity(product_scope, sku_scope)
    has_cross_contamination = _has_scope_cross_contamination(product_scope)
    has_conflicts = len(conflict_ids) > 0
    has_chunks = chunk_count > 0
    scope_defined = bool(product_scope and product_scope != []) or bool(sku_scope and sku_scope != [])
    content_complete = bool(content and len(content.strip()) >= 10)

    # ---- reject_or_rewrite 规则（优先级最高） ----
    if is_speculation:
        reasons.append("content_contains_speculation: 内容包含猜测性表述（可能/大概/应该/猜测/估计）")

    if not has_identity:
        reasons.append("no_product_identity: product_scope 和 sku_scope 均为空，无法定位产品")

    if has_cross_contamination:
        reasons.append(f"scope_cross_contamination: product_scope 包含 {len(set(product_scope))} 个不同产品，可能存在跨品类污染")

    if not content_complete:
        reasons.append("content_incomplete: 内容为空或过短（<10 字符）")

    if source_confidence < 0.3:
        reasons.append(f"source_unverifiable: source_confidence={source_confidence:.2f}，来源可信度过低")

    if fact_review_status == "rejected":
        reasons.append("fact_review_rejected: 事实审核状态为 rejected")

    # 如果有 reject 级别的理由 -> reject_or_rewrite
    if reasons:
        return CLASS_REJECT, reasons

    # ---- manual_review_required 规则 ----
    if has_high_risk:
        reasons.append("has_high_risk_facts: 内容包含高风险产品事实关键词（材质/尺寸/承重等）")

    if not scope_defined:
        reasons.append("scope_unclear: product_scope 和 sku_scope 均未定义")

    if not has_chunks:
        reasons.append("no_chunks: 尚未生成分片（knowledge_chunks 无记录）")

    if has_conflicts:
        reasons.append(f"has_conflicts: 与条目 {conflict_ids} 存在同名/同 scope 冲突")

    if not source_type:
        reasons.append("source_type_missing: 未指定来源类型")

    if source_confidence < 0.6:
        reasons.append(f"source_confidence_low: source_confidence={source_confidence:.2f}，来源可信度偏低")

    if fact_review_status == "pending":
        reasons.append("fact_review_pending: 事实审核待处理")

    if entry.get("human_review_required"):
        reasons.append("human_review_required: 条目标记为需人工审核")

    if reasons:
        return CLASS_MANUAL, reasons

    # ---- auto_publish_candidate ----
    # source 清晰、内容完整、scope 已定义、无冲突、无高风险事实
    auto_reasons = []
    if has_chunks:
        auto_reasons.append("has_chunks: 已生成检索分片")
    if scope_defined:
        auto_reasons.append("scope_defined: 产品/SKU 范围已定义")
    if source_type:
        auto_reasons.append(f"source_type={source_type}: 来源类型明确")
    if source_confidence >= 0.8:
        auto_reasons.append(f"source_confidence={source_confidence:.2f}: 来源可信度高")
    if not has_high_risk:
        auto_reasons.append("no_high_risk_facts: 无高风险产品事实")
    if not has_conflicts:
        auto_reasons.append("no_conflicts: 无同名冲突")

    return CLASS_AUTO, auto_reasons


def run(db_path: str, output_path: str):
    """执行扫描并生成审核队列"""

    if not os.path.exists(db_path):
        print(f"错误: 数据库文件不存在: {db_path}")
        sys.exit(1)

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    # ------------------------------------------------------------------
    # 1. 查询所有 draft 条目
    # ------------------------------------------------------------------
    cursor.execute("""
        SELECT id, title, content, source_type, source_confidence,
               product_scope_json, sku_scope_json, fact_review_status,
               status, human_review_required, created_by
        FROM knowledge_entries
        WHERE status = 'draft'
        ORDER BY id
    """)
    draft_rows = cursor.fetchall()

    if not draft_rows:
        print("没有 status='draft' 的知识条目。")
        conn.close()
        return

    # ------------------------------------------------------------------
    # 2. 查询每个 entry 的 chunk 数量
    # ------------------------------------------------------------------
    cursor.execute("""
        SELECT entry_id, COUNT(*) AS cnt
        FROM knowledge_chunks
        GROUP BY entry_id
    """)
    chunk_counts = {row["entry_id"]: row["cnt"] for row in cursor.fetchall()}

    # ------------------------------------------------------------------
    # 3. 构建 product_scope -> [entry_id] 索引，用于冲突检测
    # ------------------------------------------------------------------
    scope_index = defaultdict(list)   # product_name -> [entry_id, ...]
    title_index = defaultdict(list)   # normalized_title -> [entry_id, ...]

    for row in draft_rows:
        entry_id = row["id"]
        p_scope = _parse_json_safe(row["product_scope_json"])
        for p in p_scope:
            if p and p.strip():
                scope_index[p.strip()].append(entry_id)

        title_normalized = (row["title"] or "").strip().lower()
        if title_normalized:
            title_index[title_normalized].append(entry_id)

    # ------------------------------------------------------------------
    # 4. 逐条分类
    # ------------------------------------------------------------------
    results = []
    summary = {
        "total_draft": len(draft_rows),
        CLASS_AUTO: 0,
        CLASS_MANUAL: 0,
        CLASS_REJECT: 0,
        "high_risk_fact_count": 0,
        "conflict_groups": 0,
    }

    for row in draft_rows:
        entry_id = row["id"]
        p_scope = _parse_json_safe(row["product_scope_json"])
        s_scope = _parse_json_safe(row["sku_scope_json"])
        title_normalized = (row["title"] or "").strip().lower()

        # chunk 数量
        cnt = chunk_counts.get(entry_id, 0)

        # 冲突检测：同 product_scope 或相似 title
        conflict_ids = set()

        # 按 product_scope 查找冲突（排除自身）
        for p in p_scope:
            if p and p.strip():
                for other_id in scope_index.get(p.strip(), []):
                    if other_id != entry_id:
                        conflict_ids.add(other_id)

        # 按 title 查找冲突（排除自身）
        if title_normalized:
            for other_id in title_index.get(title_normalized, []):
                if other_id != entry_id:
                    conflict_ids.add(other_id)

        conflict_ids = sorted(conflict_ids)

        entry_dict = dict(row)
        classification, reasons = classify_entry(
            entry=entry_dict,
            chunk_count=cnt,
            conflict_ids=conflict_ids,
        )

        has_high_risk = _contains_high_risk_facts(row["content"] or "")
        if has_high_risk:
            summary["high_risk_fact_count"] += 1

        record = {
            "entry_id": entry_id,
            "title": row["title"] or "",
            "status": row["status"],
            "classification": classification,
            "reasons": reasons,
            "product_scope": p_scope,
            "sku_scope": s_scope,
            "chunk_count": cnt,
            "source_type": row["source_type"] or "",
            "source_confidence": row["source_confidence"] if row["source_confidence"] is not None else 0.5,
            "has_high_risk_facts": has_high_risk,
            "conflict_entry_ids": conflict_ids,
        }

        results.append(record)
        summary[classification] += 1

    # 统计冲突组数
    seen_conflict_pairs = set()
    conflict_group_count = 0
    for r in results:
        for cid in r["conflict_entry_ids"]:
            pair = tuple(sorted([r["entry_id"], cid]))
            if pair not in seen_conflict_pairs:
                seen_conflict_pairs.add(pair)
                conflict_group_count += 1
    summary["conflict_groups"] = conflict_group_count

    conn.close()

    # ------------------------------------------------------------------
    # 5. 写入 JSONL
    # ------------------------------------------------------------------
    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    with open(output_path, "w", encoding="utf-8") as f:
        for record in results:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    # ------------------------------------------------------------------
    # 6. 打印摘要
    # ------------------------------------------------------------------
    print("=" * 60)
    print("知识发布审核队列 - 扫描报告")
    print("=" * 60)
    print(f"数据库: {db_path}")
    print(f"输出文件: {output_path}")
    print(f"")
    print(f"扫描条目总数 (status=draft): {summary['total_draft']}")
    print(f"")
    print(f"分类统计:")
    print(f"  auto_publish_candidate : {summary[CLASS_AUTO]}")
    print(f"  manual_review_required : {summary[CLASS_MANUAL]}")
    print(f"  reject_or_rewrite      : {summary[CLASS_REJECT]}")
    print(f"")
    print(f"高风险事实条目数: {summary['high_risk_fact_count']}")
    print(f"冲突组数: {summary['conflict_groups']}")
    print(f"")

    # 打印各类别详情
    for cls, label in [
        (CLASS_AUTO, "自动发布候选"),
        (CLASS_MANUAL, "需人工审核"),
        (CLASS_REJECT, "建议驳回/重写"),
    ]:
        items = [r for r in results if r["classification"] == cls]
        if items:
            print(f"--- {label} ({len(items)}) ---")
            for item in items:
                scope_str = ", ".join(item["product_scope"][:3]) if item["product_scope"] else "(空)"
                reasons_short = "; ".join(item["reasons"][:2])
                if len(item["reasons"]) > 2:
                    reasons_short += f" ... +{len(item['reasons']) - 2}"
                print(f"  #{item['entry_id']} {item['title'][:40]:<40s} | scope=[{scope_str}] | {reasons_short}")
            print()

    print("=" * 60)
    print(f"审核队列已写入: {output_path}")
    print("注意: 本脚本不执行任何发布操作，仅生成审核队列。")
    print("=" * 60)


def main():
    parser = argparse.ArgumentParser(description="扫描 draft 知识条目，生成发布审核队列")
    parser.add_argument(
        "--db",
        default=os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
            "data", "knowledge_base.db",
        ),
        help="SQLite 数据库路径 (默认: data/knowledge_base.db)",
    )
    parser.add_argument(
        "--output",
        default=os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
            "data", "knowledge_publish_review_queue.jsonl",
        ),
        help="输出 JSONL 路径 (默认: data/knowledge_publish_review_queue.jsonl)",
    )
    args = parser.parse_args()
    run(args.db, args.output)


if __name__ == "__main__":
    main()
