"""
知识库质量检查服务
对 knowledge_entries / knowledge_chunks 进行多维度质量检查
"""

import json
from datetime import datetime, timedelta
from typing import List, Dict, Any

from sqlalchemy import func

from app.db import SessionLocal
from app.models.knowledge_base import KnowledgeEntry, KnowledgeChunk, KnowledgeFeedback


class KnowledgeQualityService:
    """知识库质量检查服务"""

    # 内容长度阈值
    CONTENT_TOO_SHORT = 10
    CONTENT_TOO_LONG = 2000

    # 超时天数
    DRAFT_STALE_DAYS = 7
    PENDING_REVIEW_STALE_DAYS = 3
    RISKY_CONVENIENCE_PHRASES = (
        "\u5b89\u88c5\u5f88\u65b9\u4fbf",
        "\u5b89\u88c5\u975e\u5e38\u65b9\u4fbf",
        "\u5b89\u88c5\u5f88\u7b80\u5355",
        "\u5b89\u88c5\u7b80\u5355",
        "\u64cd\u4f5c\u5f88\u7b80\u5355",
        "\u5f88\u5bb9\u6613\u5b89\u88c5",
        "\u8f7b\u677e\u5b89\u88c5",
        "\u4e0d\u9700\u8981\u989d\u5916\u5de5\u5177",
        "\u65e0\u9700\u989d\u5916\u5de5\u5177",
        "\u4e00\u822c15-20\u5206\u949f\u5c31\u80fd\u5b8c\u6210\u5b89\u88c5",
        "15-20\u5206\u949f\u5c31\u80fd\u5b8c\u6210\u5b89\u88c5",
    )

    @staticmethod
    def _get_db():
        return SessionLocal()

    @classmethod
    def generate_report(cls) -> Dict[str, Any]:
        """生成完整质量报告"""
        db = cls._get_db()
        try:
            entries = db.query(KnowledgeEntry).all()
            chunks = db.query(KnowledgeChunk).all()
            return cls._analyze(entries, chunks, db)
        finally:
            db.close()

    @classmethod
    def get_risky_convenience_claims(cls) -> Dict[str, Any]:
        """List knowledge rows that contain risky convenience promises."""
        db = cls._get_db()
        try:
            findings: List[Dict[str, Any]] = []
            for entry in db.query(KnowledgeEntry).all():
                text = " ".join([entry.title or "", entry.content or ""])
                matches = cls._matched_risky_convenience_phrases(text)
                if matches:
                    findings.append(cls._risky_claim_item(
                        table="knowledge_entries",
                        row_id=entry.id,
                        source_type=entry.source_type or "",
                        title=entry.title or "",
                        status=entry.status or "",
                        risk_level=entry.risk_level or "",
                        fact_type=entry.fact_type or "",
                        auto_reply_allowed=entry.auto_reply_allowed,
                        human_review_required=entry.human_review_required,
                        source_sheet=entry.source_sheet or "",
                        row_number=entry.row_number or entry.id,
                        matched_phrases=matches,
                    ))

            try:
                from app.models.kb_tables import KBQA
                qa_rows = db.query(KBQA).all()
            except Exception:
                qa_rows = []
            for qa in qa_rows:
                text = " ".join([qa.question or "", qa.answer or ""])
                matches = cls._matched_risky_convenience_phrases(text)
                if matches:
                    findings.append(cls._risky_claim_item(
                        table="kb_qa",
                        row_id=qa.id,
                        source_type=qa.source_type or "faq",
                        title=qa.question or "",
                        status=qa.status or "",
                        risk_level=qa.risk_level or "",
                        fact_type="",
                        auto_reply_allowed=qa.auto_reply,
                        human_review_required=qa.human_review,
                        source_sheet=qa.import_batch_id or "",
                        row_number=qa.id,
                        matched_phrases=matches,
                    ))

            by_table: Dict[str, int] = {}
            by_phrase: Dict[str, int] = {}
            for item in findings:
                by_table[item["table"]] = by_table.get(item["table"], 0) + 1
                for phrase in item["matched_phrases"]:
                    by_phrase[phrase] = by_phrase.get(phrase, 0) + 1
            return {
                "items": findings,
                "count": len(findings),
                "summary": {
                    "total": len(findings),
                    "by_table": by_table,
                    "by_phrase": by_phrase,
                },
            }
        finally:
            db.close()

    @classmethod
    def _matched_risky_convenience_phrases(cls, text: str) -> List[str]:
        return [phrase for phrase in cls.RISKY_CONVENIENCE_PHRASES if phrase in (text or "")]

    @classmethod
    def _risky_claim_item(
        cls,
        *,
        table: str,
        row_id: int,
        source_type: str,
        title: str,
        status: str,
        risk_level: str,
        fact_type: str,
        auto_reply_allowed: bool,
        human_review_required: bool,
        source_sheet: str,
        row_number: int,
        matched_phrases: List[str],
    ) -> Dict[str, Any]:
        return {
            "table": table,
            "id": row_id,
            "entry_id": row_id if table == "knowledge_entries" else None,
            "source_type": source_type,
            "title": title,
            "status": status,
            "risk_level": risk_level,
            "fact_type": fact_type,
            "auto_reply_allowed": bool(auto_reply_allowed),
            "human_review_required": bool(human_review_required),
            "source_sheet": source_sheet,
            "row_number": row_number,
            "matched_phrases": matched_phrases,
            "suggested_action": "\u6539\u4e3a\u201c\u53c2\u8003\u8bf4\u660e\u4e66/\u5b89\u88c5\u89c6\u9891\u6309\u6b65\u9aa4\u64cd\u4f5c\uff0c\u5177\u4f53\u4ee5\u5b9e\u9645\u914d\u4ef6\u548c\u9875\u9762\u4e3a\u51c6\u201d",
        }

    @classmethod
    def _analyze(cls, entries: List[KnowledgeEntry], chunks: List[KnowledgeChunk], db) -> Dict[str, Any]:
        issues: List[Dict[str, Any]] = []

        # 预计算 chunk 映射
        entry_chunk_counts: Dict[int, int] = {}
        for c in chunks:
            entry_chunk_counts[c.entry_id] = entry_chunk_counts.get(c.entry_id, 0) + 1

        # 预计算 feedback 统计
        entry_feedback_stats = cls._load_feedback_stats(db)

        # 预计算 duplicate/variant
        title_content_map: Dict[str, List[KnowledgeEntry]] = {}
        for e in entries:
            key = f"{e.source_type}::{e.title}"
            title_content_map.setdefault(key, []).append(e)

        now = datetime.utcnow()

        for entry in entries:
            # 1. 缺 source_type
            if not entry.source_type or entry.source_type.strip() == "":
                issues.append(cls._issue(entry, "high", "missing_source_type",
                    "source_type 为空",
                    "补充 source_type 分类"))

            # 2. 缺 intent / intent == general（仅对非 real_cases/feedback_records 要求）
            if entry.source_type not in ("real_cases", "feedback_records"):
                if not entry.intent or entry.intent.strip() in ("", "general"):
                    issues.append(cls._issue(entry, "low", "missing_intent",
                        f"intent 为空或 general",
                        "根据知识内容设置正确的意图标签"))

            # 3. 缺 title
            if not entry.title or entry.title.strip() == "":
                issues.append(cls._issue(entry, "high", "missing_title",
                    "标题为空",
                    "补充标题/问题描述"))

            # 4. content 过短
            content_len = len(entry.content or "")
            if content_len > 0 and content_len < cls.CONTENT_TOO_SHORT:
                issues.append(cls._issue(entry, "medium", "content_too_short",
                    f"content 过短 ({content_len} 字符)",
                    "补充详细内容，确保回答完整"))

            # 5. content 过长
            if content_len > cls.CONTENT_TOO_LONG:
                issues.append(cls._issue(entry, "low", "content_too_long",
                    f"content 过长 ({content_len} 字符)",
                    "考虑拆分为多个条目或精简内容"))

            # source_type 专项检查
            st = entry.source_type or ""

            # 6. product_facts 缺材质/尺寸/承重/适用年龄/配件
            if st == "product_facts":
                missing_fields = cls._check_product_facts_fields(entry.content or "")
                if missing_fields:
                    issues.append(cls._issue(entry, "medium", "product_facts_incomplete",
                        f"缺少字段: {', '.join(missing_fields)}",
                        f"补充 {'/'.join(missing_fields)} 信息"))

            # 7. product_facts 缺 sku_code / product_scope
            if st == "product_facts":
                if not entry.get_sku_scope() and not entry.get_product_scope():
                    issues.append(cls._issue(entry, "low", "product_facts_missing_scope",
                        "未设置 SKU 或商品范围",
                        "补充 SKU 编码或商品名称范围"))

            # 8. shipping_policy 缺发货时效 / 适用范围
            if st == "shipping_policy":
                if not cls._has_shipping_keywords(entry.content or ""):
                    issues.append(cls._issue(entry, "medium", "shipping_policy_incomplete",
                        "未检测到发货时效或快递说明",
                        "补充发货时效、快递方式或适用范围"))

            # 9. aftersales_policy 缺适用条件 / 禁止承诺
            if st == "aftersales_policy":
                if not cls._has_aftersales_keywords(entry.content or ""):
                    issues.append(cls._issue(entry, "medium", "aftersales_policy_incomplete",
                        "未检测到适用条件或禁止承诺说明",
                        "补充适用条件、退换货规则或禁止承诺"))

            # 10. high_risk_sop 未设置 human_review_required=true
            if st == "high_risk_sop":
                if not entry.human_review_required:
                    issues.append(cls._issue(entry, "high", "high_risk_missing_review",
                        "high_risk_sop 未设置 human_review_required",
                        "强制设为 human_review_required=true"))

            # 11. high_risk_sop 的 auto_reply_allowed 不应为 true
            if st == "high_risk_sop":
                if entry.auto_reply_allowed:
                    issues.append(cls._issue(entry, "high", "high_risk_auto_reply_enabled",
                        "high_risk_sop 允许自动回复",
                        "强制关闭 auto_reply_allowed"))

            # 12. forbidden_rules 没有禁用关键词
            if st == "forbidden_rules":
                if not entry.forbidden_usage and not cls._has_forbidden_keywords(entry.content or ""):
                    issues.append(cls._issue(entry, "medium", "forbidden_rules_empty",
                        "forbidden_rules 未标记禁用关键词或内容",
                        "在 forbidden_usage 或 content 中补充禁用说明"))

            # 16. 没有生成 chunk 的 published 知识
            if entry.status == "published":
                chunk_count = entry_chunk_counts.get(entry.id, 0)
                if chunk_count == 0:
                    issues.append(cls._issue(entry, "high", "published_no_chunks",
                        "已发布但未生成检索分片",
                        "重新发布或触发索引重建"))

            # 17. draft 超过 7 天未提交审核
            if entry.status == "draft":
                updated = entry.updated_at or entry.created_at
                if updated and (now - updated).days > cls.DRAFT_STALE_DAYS:
                    issues.append(cls._issue(entry, "medium", "draft_stale",
                        f"草稿已滞留 {(now - updated).days} 天",
                        "提交审核或删除废弃草稿"))

            # 18. pending_review 超过 3 天未审核
            if entry.status == "pending_review":
                updated = entry.updated_at or entry.created_at
                if updated and (now - updated).days > cls.PENDING_REVIEW_STALE_DAYS:
                    issues.append(cls._issue(entry, "medium", "pending_review_stale",
                        f"待审核已滞留 {(now - updated).days} 天",
                        "主管尽快审核或驳回"))

            # 19. published 但从未被命中的知识
            if entry.status == "published":
                fb = entry_feedback_stats.get(entry.id, {})
                if fb.get("total", 0) == 0:
                    issues.append(cls._issue(entry, "low", "published_never_hit",
                        "已发布但无命中记录",
                        "检查意图标签是否准确，或考虑归档"))

            # 20. 高频命中但客服经常修改的知识
            if entry.status == "published":
                fb = entry_feedback_stats.get(entry.id, {})
                total = fb.get("total", 0)
                edited = fb.get("edited", 0)
                if total >= 5 and edited / total > 0.5:
                    issues.append(cls._issue(entry, "medium", "frequently_edited",
                        f"命中 {total} 次但客服修改率 {int(edited/total*100)}%",
                        "优化知识内容，减少客服修改需求"))

        # 13/14. possible_variant / duplicate_candidate 检测
        variant_issues, duplicate_issues = cls._detect_variants_and_duplicates(entries, title_content_map)
        issues.extend(variant_issues)
        issues.extend(duplicate_issues)

        # Summary
        summary = cls._build_summary(entries, issues, entry_chunk_counts, entry_feedback_stats)

        return {
            "summary": summary,
            "issues": issues,
        }

    @classmethod
    def _issue(cls, entry: KnowledgeEntry, severity: str, issue_type: str,
               message: str, suggested_fix: str) -> Dict[str, Any]:
        return {
            "severity": severity,
            "entry_id": entry.id,
            "title": entry.title or "(无标题)",
            "source_type": entry.source_type or "",
            "status": entry.status,
            "issue_type": issue_type,
            "message": message,
            "suggested_fix": suggested_fix,
        }

    @classmethod
    def _load_feedback_stats(cls, db) -> Dict[int, Dict[str, int]]:
        """加载每个 entry 的 feedback 统计"""
        from sqlalchemy import case
        rows = db.query(
            KnowledgeFeedback.entry_id,
            func.count(KnowledgeFeedback.id).label("total"),
            func.sum(case((KnowledgeFeedback.csr_edited.is_(True), 1), else_=0)).label("edited"),
            func.sum(case((KnowledgeFeedback.csr_accepted.is_(True), 1), else_=0)).label("accepted"),
        ).group_by(KnowledgeFeedback.entry_id).all()

        stats = {}
        for row in rows:
            stats[row.entry_id] = {
                "total": row.total or 0,
                "edited": row.edited or 0,
                "accepted": row.accepted or 0,
            }
        return stats

    @classmethod
    def _detect_variants_and_duplicates(cls, entries: List[KnowledgeEntry],
                                        title_content_map: Dict[str, List[KnowledgeEntry]]) -> tuple:
        variant_issues = []
        duplicate_issues = []

        # content_hash -> entries
        hash_map: Dict[str, List[KnowledgeEntry]] = {}
        for e in entries:
            h = e.content_hash or ""
            if h:
                hash_map.setdefault(h, []).append(e)

        seen_duplicates = set()
        for h, group in hash_map.items():
            if len(group) > 1:
                for e in group[1:]:
                    key = (e.id, "duplicate_candidate")
                    if key not in seen_duplicates:
                        seen_duplicates.add(key)
                        duplicate_issues.append(cls._issue(
                            e, "medium", "duplicate_candidate",
                            f"与 entry {group[0].id} content_hash 重复",
                            "合并或删除重复条目"
                        ))

        seen_variants = set()
        for key, group in title_content_map.items():
            if len(group) > 1:
                hashes = {e.content_hash for e in group if e.content_hash}
                if len(hashes) > 1:
                    for e in group:
                        vkey = (e.id, "possible_variant")
                        if vkey not in seen_variants:
                            seen_variants.add(vkey)
                            variant_issues.append(cls._issue(
                                e, "low", "possible_variant",
                                f"与 {len(group)-1} 个条目标题相同但内容不同",
                                "确认是否为不同规格变体，如是则补充 SKU 区分"
                            ))

        return variant_issues, duplicate_issues

    @classmethod
    def _build_summary(cls, entries: List[KnowledgeEntry], issues: List[Dict],
                       entry_chunk_counts: Dict[int, int],
                       feedback_stats: Dict[int, Dict[str, int]]) -> Dict[str, int]:
        status_counts = {}
        for e in entries:
            status_counts[e.status] = status_counts.get(e.status, 0) + 1

        severity_counts = {}
        issue_type_counts = {}
        for i in issues:
            severity_counts[i["severity"]] = severity_counts.get(i["severity"], 0) + 1
            issue_type_counts[i["issue_type"]] = issue_type_counts.get(i["issue_type"], 0) + 1

        published_no_chunks = sum(
            1 for e in entries
            if e.status == "published" and entry_chunk_counts.get(e.id, 0) == 0
        )

        return {
            "total_entries": len(entries),
            "published": status_counts.get("published", 0),
            "draft": status_counts.get("draft", 0),
            "pending_review": status_counts.get("pending_review", 0),
            "archived": status_counts.get("archived", 0),
            "rejected": status_counts.get("rejected", 0),
            "missing_required_fields": issue_type_counts.get("missing_source_type", 0)
                + issue_type_counts.get("missing_title", 0)
                + issue_type_counts.get("missing_intent", 0),
            "product_facts_incomplete": issue_type_counts.get("product_facts_incomplete", 0)
                + issue_type_counts.get("product_facts_missing_scope", 0),
            "high_risk_misconfigured": issue_type_counts.get("high_risk_missing_review", 0)
                + issue_type_counts.get("high_risk_auto_reply_enabled", 0),
            "chunks_missing": published_no_chunks,
            "possible_variants": issue_type_counts.get("possible_variant", 0),
            "duplicates": issue_type_counts.get("duplicate_candidate", 0),
            "high_issues": severity_counts.get("high", 0),
            "medium_issues": severity_counts.get("medium", 0),
            "low_issues": severity_counts.get("low", 0),
        }

    # ---------- 字段检查工具 ----------

    @classmethod
    def _check_product_facts_fields(cls, content: str) -> List[str]:
        """检查 product_facts 是否缺少关键字段"""
        required = {
            "材质": ["材质", "用料", "材料"],
            "尺寸": ["尺寸", "规格", "大小", "长宽高"],
            "承重": ["承重", "载重", "负重", "容量"],
            "适用年龄": ["适用年龄", "年龄", "推荐年龄", "适合年龄"],
            "配件": ["配件", "包含", "清单", "标配"],
        }
        missing = []
        for field, keywords in required.items():
            if not any(kw in content for kw in keywords):
                missing.append(field)
        return missing

    @classmethod
    def _has_shipping_keywords(cls, content: str) -> bool:
        keywords = ["发货", "时效", "快递", "物流", "送达", "到货", "配送", "运费", "包邮", "天", "小时"]
        return any(kw in content for kw in keywords)

    @classmethod
    def _has_aftersales_keywords(cls, content: str) -> bool:
        keywords = ["退换", "退货", "换货", "保修", "质保", "售后", "退款", "条件", "禁止", "承诺", "不支持"]
        return any(kw in content for kw in keywords)

    @classmethod
    def _has_forbidden_keywords(cls, content: str) -> bool:
        keywords = ["禁止", "严禁", "不得", "不能", "不要", "勿", "不允许", "违规"]
        return any(kw in content for kw in keywords)


    # ============ 数据清洗工具 ============

    @classmethod
    def get_product_facts_incomplete(cls) -> List[Dict[str, Any]]:
        """列出所有 product_facts_incomplete 条目，用于运营补全"""
        db = cls._get_db()
        try:
            entries = db.query(KnowledgeEntry).filter(KnowledgeEntry.source_type == "product_facts").all()
            results = []
            for entry in entries:
                missing = cls._check_product_facts_fields(entry.content or "")
                has_scope = bool(entry.get_sku_scope() or entry.get_product_scope())
                if missing or not has_scope:
                    results.append({
                        "entry_id": entry.id,
                        "title": entry.title or "",
                        "sku_scope": entry.get_sku_scope(),
                        "product_scope": entry.get_product_scope(),
                        "missing_fields": missing,
                        "missing_scope": not has_scope,
                        "current_content": entry.content or "",
                        "status": entry.status,
                        "suggested_fix_template": cls._build_product_facts_template(entry, missing),
                    })
            return results
        finally:
            db.close()

    @classmethod
    def _build_product_facts_template(cls, entry: KnowledgeEntry, missing: List[str]) -> str:
        """生成 product_facts 建议补全模板"""
        lines = []
        if entry.content:
            lines.append(entry.content)
        for field in missing:
            lines.append(f"{field}：【请补充】")
        if not entry.get_sku_scope():
            lines.append("SKU：【请补充】")
        return "\n".join(lines)

    @classmethod
    def get_duplicate_review_list(cls) -> Dict[str, List[Dict[str, Any]]]:
        """返回 duplicate_candidate 和 possible_variant 列表"""
        db = cls._get_db()
        try:
            entries = db.query(KnowledgeEntry).all()

            # content_hash -> entries
            hash_map: Dict[str, List[KnowledgeEntry]] = {}
            for e in entries:
                h = e.content_hash or ""
                if h:
                    hash_map.setdefault(h, []).append(e)

            # title+source_type -> entries
            title_map: Dict[str, List[KnowledgeEntry]] = {}
            for e in entries:
                key = f"{e.source_type}::{e.title}"
                title_map.setdefault(key, []).append(e)

            duplicates = []
            seen_dup = set()
            for h, group in hash_map.items():
                if len(group) > 1:
                    for e in group:
                        if e.id not in seen_dup:
                            seen_dup.add(e.id)
                            duplicates.append(cls._entry_dup_info(e, "duplicate_candidate", group))

            variants = []
            seen_var = set()
            for key, group in title_map.items():
                if len(group) > 1:
                    hashes = {e.content_hash for e in group if e.content_hash}
                    if len(hashes) > 1:
                        for e in group:
                            if e.id not in seen_var:
                                seen_var.add(e.id)
                                variants.append(cls._entry_dup_info(e, "possible_variant", group))

            return {
                "duplicate_candidates": duplicates,
                "possible_variants": variants,
            }
        finally:
            db.close()

    @classmethod
    def _entry_dup_info(cls, entry: KnowledgeEntry, relation_type: str, group: List[KnowledgeEntry]) -> Dict[str, Any]:
        return {
            "entry_id": entry.id,
            "title": entry.title or "",
            "source_type": entry.source_type,
            "sku_scope": entry.get_sku_scope(),
            "product_scope": entry.get_product_scope(),
            "content_hash": entry.content_hash or "",
            "source_sheet": entry.source_sheet or "",
            "row_number": entry.row_number,
            "status": entry.status,
            "relation_type": relation_type,
            "group_size": len(group),
            "group_entry_ids": [e.id for e in group],
        }

    @classmethod
    def get_publish_candidates(cls) -> Dict[str, Any]:
        """生成建议优先发布的黄金知识集候选列表"""
        db = cls._get_db()
        try:
            entries = db.query(KnowledgeEntry).all()
            chunks = db.query(KnowledgeChunk).all()
            entry_chunk_counts = {}
            for c in chunks:
                entry_chunk_counts[c.entry_id] = entry_chunk_counts.get(c.entry_id, 0) + 1

            # 先计算 issues，用于排除有 high severity 的条目
            report = cls._analyze(entries, chunks, db)
            bad_entry_ids = set()
            for issue in report["issues"]:
                if issue["severity"] == "high":
                    bad_entry_ids.add(issue["entry_id"])
                if issue["issue_type"] in ("duplicate_candidate",):
                    bad_entry_ids.add(issue["entry_id"])

            # 按 source_type 分组打分
            candidates_by_type: Dict[str, List[Dict]] = {}
            for entry in entries:
                if entry.status != "draft":
                    continue
                if entry.id in bad_entry_ids:
                    continue

                score = cls._score_candidate(entry, entry_chunk_counts)
                st = entry.source_type or "other"
                candidates_by_type.setdefault(st, []).append({
                    "entry_id": entry.id,
                    "title": entry.title or "",
                    "source_type": st,
                    "risk_level": entry.risk_level,
                    "intent": entry.intent,
                    "content_length": len(entry.content or ""),
                    "has_product_scope": bool(entry.get_product_scope()),
                    "has_sku_scope": bool(entry.get_sku_scope()),
                    "has_chunks": entry_chunk_counts.get(entry.id, 0) > 0,
                    "score": score,
                })

            # 按 source_type 排序并取 Top N
            limits = {
                "shipping_policy": 20,
                "product_facts": 50,
                "installation_guide": 10,
                "aftersales_policy": 20,
                "high_risk_sop": 10,
                "forbidden_rules": 10,
                "faq": 30,
                "response_templates": 20,
            }

            result = {}
            total = 0
            for st, items in candidates_by_type.items():
                items.sort(key=lambda x: -x["score"])
                limit = limits.get(st, 20)
                selected = items[:limit]
                result[st] = selected
                total += len(selected)

            return {
                "total_candidates": total,
                "by_source_type": result,
                "limits": limits,
            }
        finally:
            db.close()

    @classmethod
    def _score_candidate(cls, entry: KnowledgeEntry, chunk_counts: Dict[int, int]) -> int:
        """候选条目打分，越高越优先"""
        score = 0
        # source_type 重要性
        priority = {
            "high_risk_sop": 100,
            "forbidden_rules": 90,
            "shipping_policy": 80,
            "aftersales_policy": 70,
            "installation_guide": 60,
            "product_facts": 50,
            "faq": 40,
            "response_templates": 30,
        }
        score += priority.get(entry.source_type, 20)

        # content 完整度
        content_len = len(entry.content or "")
        if content_len >= 100:
            score += 30
        elif content_len >= 50:
            score += 20
        elif content_len >= 20:
            score += 10

        # risk_level
        if entry.risk_level == "high":
            score += 20
        elif entry.risk_level == "medium":
            score += 10

        # 有 product_scope / sku_scope
        if entry.get_product_scope():
            score += 10
        if entry.get_sku_scope():
            score += 10

        # 已有 chunk（说明曾经 publish 过）
        if chunk_counts.get(entry.id, 0) > 0:
            score += 15

        # 有明确 intent
        if entry.intent and entry.intent != "general":
            score += 10

        return score
