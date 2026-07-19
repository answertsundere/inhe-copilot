"""Answer Memory Layer MVP.

This service stores and retrieves reviewed answer patterns as shadow/reference
evidence. It intentionally does not write formal knowledge tables and does not
decide final sendability.
"""

from __future__ import annotations

import html
import re
from collections import Counter
from datetime import datetime
from typing import Any

from sqlalchemy import or_

from app.db import SessionLocal
from app.services.eval_sanitizer_service import sanitize_obj, sanitize_product_title, sanitize_text, stable_hash
from app.services.fact_type_service import classify_query_fact_type


HIGH_RISK_FACT_TYPES = {
    "age_range",
    "child_suitability",
    "child_safety",
    "certification_report",
    "material",
    "odor",
    "pinch_safety",
    "safety_small_parts",
    "load_capacity",
    "stability",
}

FACT_TYPE_FORBIDDEN_CLAIMS = {
    "material_safety": ["无毒", "有证书", "有检测报告"],
    "age_range": ["适合几岁", "绝对安全", "保护宝宝安全"],
    "child_safety": ["绝对安全", "保护宝宝安全", "不会伤到"],
    "certification_report": ["有证书", "有检测报告", "通过认证"],
    "material": ["无毒", "食品级", "绝对安全"],
    "odor": ["完全无味", "没有味道"],
    "load_capacity": ["一定承重", "随便放"],
    "stability": ["绝对不会倒", "不会倒"],
}

SCENARIO_ALIASES = {
    "售后": "aftersales",
    "安装": "installation",
    "活动": "promotion",
    "优惠": "promotion",
    "物流": "logistics",
    "商品": "product_fact",
    "其他": "general",
}


def plain_text(value: Any) -> str:
    text = str(value or "")
    text = re.sub(r"<script\b[^>]*>.*?</script>", " ", text, flags=re.I | re.S)
    text = re.sub(r"<style\b[^>]*>.*?</style>", " ", text, flags=re.I | re.S)
    text = re.sub(r"<img\b[^>]*>", " [图片] ", text, flags=re.I)
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.I)
    text = re.sub(r"</p\s*>", "\n", text, flags=re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def has_readable_question(value: Any) -> bool:
    text = plain_text(value)
    if not text:
        return False
    reduced = re.sub(r"https?://\S+", "", text, flags=re.I)
    reduced = re.sub(r"\[[^\]]*图片[^\]]*\]", "", reduced)
    reduced = reduced.replace("图片消息", "").strip()
    return bool(re.search(r"[\u4e00-\u9fffA-Za-z0-9]{2,}", reduced))


def hash_order_id(value: Any) -> str:
    raw = str(value or "").strip()
    return stable_hash(raw, 16) if raw else ""


def infer_scenario_type(sample: dict[str, Any], query_fact_type: str = "") -> str:
    question_type = sanitize_text(sample.get("question_type"))
    for token, scenario in SCENARIO_ALIASES.items():
        if token in question_type:
            return scenario
    if query_fact_type in {"installation", "accessory_usage", "accessory_availability", "structure_function"}:
        return "installation"
    if query_fact_type in {"promotion_policy", "gift_policy", "price_negotiation"}:
        return "promotion"
    if query_fact_type in {"aftersales_policy", "return_pickup", "stock_shipping"}:
        return "aftersales"
    return "general"


def risk_for_fact_type(query_fact_type: str, sample: dict[str, Any]) -> str:
    explicit = sanitize_text(sample.get("risk_level")).lower()
    if explicit in {"high", "medium", "low"}:
        return explicit
    if sanitize_text(query_fact_type) in HIGH_RISK_FACT_TYPES:
        return "high"
    return "medium"


def _quality_from_review_status(review_status: str) -> str:
    status = sanitize_text(review_status).lower()
    if status in {"已确认", "confirmed", "reviewed", "approved"}:
        return "verified_answer"
    return "reference_reply"


def _memory_uid(sample: dict[str, Any], query_fact_type: str, approved_answer: str, reference_reply: str) -> str:
    raw = "|".join(
        [
            str(sample.get("id") or ""),
            sanitize_text(sample.get("product_title")),
            sanitize_text(sample.get("sku")),
            query_fact_type,
            stable_hash(approved_answer or reference_reply, 16),
        ]
    )
    return f"aam_{stable_hash(raw, 20)}"


def build_memory_from_training_sample(sample: dict[str, Any]) -> dict[str, Any] | None:
    question = sanitize_text(plain_text(sample.get("customer_quote")))
    correct_answer = sanitize_text(plain_text(sample.get("correct_answer")))
    if not correct_answer or not has_readable_question(question):
        return None
    fact = classify_query_fact_type(question, intent="")
    query_fact_type = sanitize_text(fact.get("query_fact_type"))
    scenario_type = infer_scenario_type(sample, query_fact_type)
    risk_level = risk_for_fact_type(query_fact_type, sample)
    answer_quality = _quality_from_review_status(str(sample.get("review_status") or ""))
    review_status = "verified_answer" if answer_quality == "verified_answer" else "reference_reply"
    requires_human_review = True
    forbidden_claims = list(FACT_TYPE_FORBIDDEN_CLAIMS.get(query_fact_type, []))
    return sanitize_obj(
        {
            "memory_uid": _memory_uid(sample, query_fact_type, correct_answer, ""),
            "product_i_id": "",
            "sku_code": sample.get("sku") or "",
            "product_title": sanitize_product_title(sample.get("product_title")),
            "product_family": "",
            "scenario_type": scenario_type,
            "query_fact_type": query_fact_type,
            "customer_question_pattern": question[:500],
            "approved_answer": correct_answer if answer_quality == "verified_answer" else "",
            "reference_reply": "" if answer_quality == "verified_answer" else correct_answer,
            "required_fact_types": [query_fact_type] if query_fact_type else [],
            "required_evidence_roles": [],
            "forbidden_claims": forbidden_claims,
            "risk_level": risk_level,
            "review_status": review_status,
            "answer_quality": answer_quality,
            "can_auto_send": False,
            "requires_human_review": requires_human_review,
            "source_type": "reviewed_training_sample",
            "source_id": str(sample.get("id") or ""),
            "source_conversation_id": f"training_sample_reviewed_{sample.get('id')}",
            "source_order_id_hash": hash_order_id(sample.get("order_no")),
            "reviewer": "training_sample_review",
            "metadata": {
                "review_status": sample.get("review_status") or "",
                "question_type": sample.get("question_type") or "",
                "fact_type_source": fact.get("source"),
                "fact_type_confidence": fact.get("confidence"),
                "has_plain_order_id": False,
                "history_answer_is_product_fact": False,
                "formal_knowledge_write": False,
                "created_from": "training_sample_snapshot",
            },
        }
    )


def _apply_memory(row, payload: dict[str, Any]) -> None:
    row.product_i_id = sanitize_text(payload.get("product_i_id"))
    row.sku_code = sanitize_text(payload.get("sku_code"))
    row.product_title = sanitize_product_title(payload.get("product_title"))
    row.product_family = sanitize_text(payload.get("product_family"))
    row.scenario_type = sanitize_text(payload.get("scenario_type"))
    row.query_fact_type = sanitize_text(payload.get("query_fact_type"))
    row.customer_question_pattern = sanitize_text(payload.get("customer_question_pattern"))
    row.approved_answer = sanitize_text(payload.get("approved_answer"))
    row.reference_reply = sanitize_text(payload.get("reference_reply"))
    row.set_required_fact_types(payload.get("required_fact_types") or [])
    row.set_required_evidence_roles(payload.get("required_evidence_roles") or [])
    row.set_forbidden_claims(payload.get("forbidden_claims") or [])
    row.risk_level = sanitize_text(payload.get("risk_level") or "medium")
    row.review_status = sanitize_text(payload.get("review_status") or "reference_reply")
    row.answer_quality = sanitize_text(payload.get("answer_quality") or "candidate")
    row.can_auto_send = False
    row.requires_human_review = bool(payload.get("requires_human_review", True))
    row.source_type = sanitize_text(payload.get("source_type"))
    row.source_id = sanitize_text(payload.get("source_id"))
    row.source_conversation_id = sanitize_text(payload.get("source_conversation_id"))
    row.source_order_id_hash = sanitize_text(payload.get("source_order_id_hash"))
    row.reviewer = sanitize_text(payload.get("reviewer"))
    row.set_metadata(payload.get("metadata") or {})


class AnswerMemoryService:
    def import_training_samples(
        self,
        samples: list[dict[str, Any]],
        *,
        apply: bool = False,
        db_factory=None,
    ) -> dict[str, Any]:
        from app.models.eval_tables import AgentAnswerMemory

        db_factory = db_factory or SessionLocal
        db = db_factory()
        scanned = 0
        importable = 0
        skipped: list[dict[str, Any]] = []
        imported_uids: list[str] = []
        high_risk = 0
        auto_send_false = 0
        try:
            for sample in samples:
                scanned += 1
                payload = build_memory_from_training_sample(sample)
                if not payload:
                    skipped.append({"source_id": str(sample.get("id") or ""), "reason": "missing_correct_answer_or_readable_question"})
                    continue
                importable += 1
                if payload["risk_level"] == "high":
                    high_risk += 1
                if payload["can_auto_send"] is False:
                    auto_send_false += 1
                memory_uid = payload["memory_uid"]
                imported_uids.append(memory_uid)
                if apply:
                    row = db.query(AgentAnswerMemory).filter(AgentAnswerMemory.memory_uid == memory_uid).one_or_none()
                    if row is None:
                        row = AgentAnswerMemory(memory_uid=memory_uid)
                    _apply_memory(row, payload)
                    db.add(row)
            if apply:
                db.commit()
            else:
                db.rollback()
            return sanitize_obj(
                {
                    "ok": True,
                    "dry_run": not apply,
                    "scanned_count": scanned,
                    "importable_count": importable,
                    "skipped_count": len(skipped),
                    "skipped_reasons": skipped[:100],
                    "high_risk_count": high_risk,
                    "default_can_auto_send_false_count": auto_send_false,
                    "imported_memory_uids": imported_uids,
                    "writes_formal_knowledge": False,
                    "auto_send_enabled": False,
                }
            )
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def search_answer_memory(
        self,
        *,
        product_i_id: str = "",
        sku_code: str = "",
        product_title: str = "",
        query_fact_type: str = "",
        scenario_type: str = "",
        customer_message: str = "",
        limit: int = 5,
        db_factory=None,
    ) -> list[dict[str, Any]]:
        from app.models.eval_tables import AgentAnswerMemory

        db_factory = db_factory or SessionLocal
        db = db_factory()
        try:
            query = db.query(AgentAnswerMemory)
            if query_fact_type:
                query = query.filter(AgentAnswerMemory.query_fact_type == sanitize_text(query_fact_type))
            identity_filters = []
            if product_i_id:
                identity_filters.append(AgentAnswerMemory.product_i_id == sanitize_text(product_i_id))
            if sku_code:
                identity_filters.append(AgentAnswerMemory.sku_code == sanitize_text(sku_code))
            if product_title:
                identity_filters.append(AgentAnswerMemory.product_title == sanitize_product_title(product_title))
            reference_only = False
            if identity_filters:
                query = query.filter(or_(*identity_filters))
            else:
                reference_only = True
                if scenario_type:
                    query = query.filter(AgentAnswerMemory.scenario_type == sanitize_text(scenario_type))
            rows = (
                query.order_by(AgentAnswerMemory.updated_at.desc(), AgentAnswerMemory.id.desc())
                .limit(max(1, min(int(limit or 5), 20)))
                .all()
            )
            return [self._to_search_result(row, customer_message=customer_message, reference_only=reference_only) for row in rows]
        finally:
            db.close()

    def _to_search_result(self, row, *, customer_message: str = "", reference_only: bool = False) -> dict[str, Any]:
        answer_text = sanitize_text(row.approved_answer or row.reference_reply)
        score = self._match_score(row, customer_message, reference_only=reference_only)
        return sanitize_obj(
            {
                "memory_uid": row.memory_uid,
                "match_score": score,
                "answer_text": answer_text,
                "required_fact_types": row.get_required_fact_types(),
                "required_evidence_roles": row.get_required_evidence_roles(),
                "forbidden_claims": row.get_forbidden_claims(),
                "risk_level": row.risk_level,
                "can_auto_send": False,
                "requires_human_review": bool(row.requires_human_review),
                "review_status": row.review_status,
                "answer_quality": row.answer_quality,
                "source_type": row.source_type,
                "source_id": row.source_id,
                "scenario_type": row.scenario_type,
                "query_fact_type": row.query_fact_type,
                "reference_only": bool(reference_only or not (row.product_i_id or row.sku_code or row.product_title)),
                "history_answer_is_product_fact": False,
            }
        )

    @staticmethod
    def _match_score(row, customer_message: str, *, reference_only: bool) -> float:
        score = 1.0
        if row.approved_answer:
            score += 1.0
        if row.query_fact_type:
            score += 1.0
        if row.product_i_id or row.sku_code or row.product_title:
            score += 1.0
        if reference_only:
            score -= 0.5
        tokens = [token for token in re.split(r"\s+", plain_text(customer_message)) if token]
        haystack = row.customer_question_pattern
        if tokens:
            overlap = sum(1 for token in tokens if token and token in haystack)
            score += min(1.0, overlap / max(1, len(tokens)))
        return round(max(0.0, score), 3)

    def trace_training_samples(
        self,
        samples: list[dict[str, Any]],
        *,
        limit: int = 200,
        db_factory=None,
    ) -> dict[str, Any]:
        rows: list[dict[str, Any]] = []
        hit_count = 0
        quality_counts: Counter[str] = Counter()
        for sample in samples[: max(1, min(int(limit or 200), 5000))]:
            question = sanitize_text(plain_text(sample.get("customer_quote")))
            fact = classify_query_fact_type(question, intent="")
            query_fact_type = sanitize_text(fact.get("query_fact_type"))
            scenario_type = infer_scenario_type(sample, query_fact_type)
            hits = self.search_answer_memory(
                product_i_id="",
                sku_code=sample.get("sku") or "",
                product_title=sample.get("product_title") or "",
                query_fact_type=query_fact_type,
                scenario_type=scenario_type,
                customer_message=question,
                limit=5,
                db_factory=db_factory,
            )
            if hits:
                hit_count += 1
                quality_counts[hits[0].get("answer_quality") or "unknown"] += 1
            rows.append(
                sanitize_obj(
                    {
                        "sample_id": sample.get("id"),
                        "query_fact_type": query_fact_type,
                        "scenario_type": scenario_type,
                        "has_answer_memory_hit": bool(hits),
                        "hit_count": len(hits),
                        "top_hit": hits[0] if hits else None,
                        "has_required_facts": bool(hits and hits[0].get("required_fact_types")),
                        "grounded_reasoning_reference": bool(hits),
                        "can_change_can_send": False,
                    }
                )
            )
        return sanitize_obj(
            {
                "scanned_count": len(rows),
                "hit_count": hit_count,
                "miss_count": len(rows) - hit_count,
                "quality_counts": dict(quality_counts),
                "can_change_can_send": False,
                "rows": rows,
            }
        )
