"""Build evaluation-set contracts from reviewed training samples.

Reviewed training samples are supervisor judgements. Converting them to an
evaluation set must not publish them as knowledge or treat screenshots as
verified answers.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from app.db import SessionLocal
from app.models.kb_tables import KBTrainingSample
from app.services.eval_sanitizer_service import sanitize_obj, sanitize_text


REVIEWED_STATUS = "\u5df2\u786e\u8ba4"
EVAL_SET_STATUS = "\u8bc4\u6d4b\u96c6"


QUESTION_TYPE_TO_FACT_TYPE = {
    "\u6750\u8d28\u5b89\u5168": "material_safety",
    "\u5b89\u88c5": "installation",
    "\u5c3a\u5bf8": "dimensions",
    "\u914d\u4ef6": "installation",
    "\u7269\u6d41": "delivery_status",
    "\u552e\u540e": "aftersales_policy",
    "\u6d3b\u52a8": "promotion_policy",
    "\u8d28\u68c0": "quality_issue",
    "\u5e74\u9f84\u9002\u914d": "age_range",
}


@dataclass(frozen=True)
class EvalSetConversionResult:
    converted: int
    skipped: int
    items: list[dict[str, Any]]

    def to_dict(self) -> dict[str, Any]:
        return sanitize_obj({
            "converted": self.converted,
            "skipped": self.skipped,
            "items": self.items,
        })


def _plain_text(value: str | None) -> str:
    text = re.sub(r"<br\s*/?>", "\n", value or "", flags=re.I)
    text = re.sub(r"</(p|div|li)>", "\n", text, flags=re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return sanitize_text(text)


def _is_image_only_quote(text: str) -> bool:
    compact = re.sub(r"\s+", "", text or "")
    without_image_mark = re.sub(r"\[\u56fe\u7247[^\]]*\]", "", compact)
    without_urls = re.sub(r"https?://\S+", "", without_image_mark)
    return bool("\u56fe\u7247" in compact or "img" in compact.lower()) and len(without_urls) < 8


def _split_guidance(text: str) -> list[str]:
    cleaned = _plain_text(text)
    if not cleaned:
        return []
    parts = re.split(r"[\u3002\uff1b;\uff01!\n]+", cleaned)
    return [part.strip() for part in parts if part.strip()][:8]


def _contains_image_reference(sample: KBTrainingSample) -> bool:
    values = [
        sample.customer_quote,
        sample.full_context,
        sample.csr_actual_reply,
        sample.correct_answer,
        sample.media_links_json,
    ]
    if sample.attachments:
        return True
    return any("\u56fe\u7247" in (value or "") or "<img" in (value or "").lower() for value in values)


def build_media_references(sample: KBTrainingSample) -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = []
    for attachment in sample.attachments or []:
        refs.append({
            "kind": "attachment",
            "attachment_id": attachment.id,
            "field_name": sanitize_text(attachment.field_name),
            "filename": sanitize_text(attachment.original_filename),
            "mime_type": sanitize_text(attachment.mime_type),
            "role": "conversation_evidence_for_vision_eval",
        })
    return refs


def build_eval_contract(sample: KBTrainingSample) -> dict[str, Any]:
    customer_quote = _plain_text(sample.customer_quote)
    supervisor_evaluation = _plain_text(sample.correct_answer or sample.notes)
    csr_actual_reply = _plain_text(sample.csr_actual_reply)
    full_context = _plain_text(sample.full_context)
    guidance = supervisor_evaluation
    has_image = _contains_image_reference(sample)
    image_only = _is_image_only_quote(customer_quote)
    must_do = _split_guidance(guidance)
    must_not_do: list[str] = []
    if csr_actual_reply and supervisor_evaluation:
        must_not_do.append(
            "\u4e0d\u8981\u76f4\u63a5\u7167\u6284\u88ab\u4e3b\u7ba1\u8bc4\u4ef7\u8fc7\u7684\u95ee\u9898\u56de\u590d"
        )
    if "\u4e0d\u5e94\u8be5" in supervisor_evaluation:
        must_not_do.append(
            "\u907f\u514d\u4e3b\u7ba1\u8bc4\u4ef7\u4e2d\u660e\u786e\u6307\u51fa\u7684\u4e0d\u5f53\u5904\u7406\u65b9\u5f0f"
        )
    can_auto_score = bool(customer_quote and must_do and not image_only)
    needs_manual_structuring = not bool(customer_quote and must_do)
    return sanitize_obj({
        "source": "training_sample_review",
        "source_sample_id": sample.id,
        "customer_message": customer_quote,
        "full_context_preview": full_context[:500],
        "original_csr_reply": csr_actual_reply,
        "supervisor_evaluation": supervisor_evaluation,
        "conversation_context_text": full_context,
        "conversation_turns": [],
        "expected_agent_turns": [],
        "media_references": build_media_references(sample),
        "expected_question_type": sanitize_text(sample.question_type),
        "expected_fact_type": QUESTION_TYPE_TO_FACT_TYPE.get(sanitize_text(sample.question_type), ""),
        "must_do": must_do,
        "must_not_do": must_not_do,
        "risk_level": sanitize_text(sample.risk_level),
        "needs_order_context": bool(sanitize_text(sample.order_no)),
        "needs_product_context": bool(sanitize_text(sample.product_title) or sanitize_text(sample.sku)),
        "needs_media_understanding": bool(sample.need_media or has_image),
        "needs_image_description": bool(has_image),
        "can_auto_score": can_auto_score,
        "needs_manual_structuring": needs_manual_structuring or image_only,
        "manual_structuring_reason": (
            "image_only_sample_needs_text_description"
            if image_only else
            "missing_customer_question_or_supervisor_guidance"
            if needs_manual_structuring else ""
        ),
        "created_at": datetime.utcnow().isoformat(),
    })


def _can_convert(contract: dict[str, Any]) -> tuple[bool, str]:
    conversation_turns = contract.get("conversation_turns")
    expected_turns = contract.get("expected_agent_turns")
    has_conversation_contract = isinstance(conversation_turns, list) and isinstance(expected_turns, list) and bool(expected_turns)
    if has_conversation_contract:
        for turn in expected_turns:
            if not isinstance(turn, dict):
                return False, "invalid_expected_turn"
            if not turn.get("expected_reply"):
                return False, "missing_expected_reply"
        return True, ""
    if not contract.get("customer_message"):
        return False, "missing_customer_message"
    if not contract.get("supervisor_evaluation"):
        return False, "missing_supervisor_guidance"
    if not contract.get("must_do"):
        return False, "missing_supervisor_guidance"
    return True, ""


class TrainingSampleEvalSetService:
    """Convert reviewed training samples into evaluation-set contracts."""

    def preview_sample(self, sample_id: int, *, db=None) -> dict[str, Any]:
        own_db = db is None
        session = db or SessionLocal()
        try:
            sample = session.query(KBTrainingSample).filter(KBTrainingSample.id == int(sample_id)).one_or_none()
            if not sample:
                return {"sample_id": sample_id, "converted": False, "reason": "not_found"}
            contract = build_eval_contract(sample)
            can_convert, reason = _can_convert(contract)
            return {
                "sample_id": sample.id,
                "converted": False,
                "reason": "" if can_convert else reason,
                "contract": contract,
            }
        finally:
            if own_db:
                session.close()

    def convert_curated_sample(
        self,
        sample_id: int,
        *,
        contract: dict[str, Any],
        db=None,
    ) -> dict[str, Any]:
        own_db = db is None
        session = db or SessionLocal()
        try:
            sample = session.query(KBTrainingSample).filter(KBTrainingSample.id == int(sample_id)).one_or_none()
            if not sample:
                return {"sample_id": sample_id, "converted": False, "reason": "not_found"}
            curated_contract = sanitize_obj({
                **contract,
                "source": "training_sample_manual_eval_curation",
                "source_sample_id": sample.id,
                "original_review_status": sanitize_text(sample.review_status),
                "curated_at": datetime.utcnow().isoformat(),
            })
            can_convert, reason = _can_convert(curated_contract)
            if not can_convert:
                return {
                    "sample_id": sample.id,
                    "converted": False,
                    "reason": reason,
                    "contract": curated_contract,
                }
            sample.review_status = EVAL_SET_STATUS
            sample.eval_created_at = datetime.utcnow()
            sample.set_eval_contract(curated_contract)
            session.add(sample)
            if own_db:
                session.commit()
            return {
                "sample_id": sample.id,
                "converted": True,
                "reason": "",
                "review_status": EVAL_SET_STATUS,
                "contract": curated_contract,
            }
        finally:
            if own_db:
                session.close()

    def convert_reviewed(
        self,
        *,
        sample_ids: list[int] | None = None,
        limit: int | None = None,
        dry_run: bool = False,
    ) -> EvalSetConversionResult:
        db = SessionLocal()
        try:
            query = db.query(KBTrainingSample)
            if sample_ids:
                query = query.filter(KBTrainingSample.id.in_([int(x) for x in sample_ids]))
            else:
                query = query.filter(KBTrainingSample.review_status == REVIEWED_STATUS)
            query = query.order_by(KBTrainingSample.updated_at.desc(), KBTrainingSample.id.desc())
            if limit:
                query = query.limit(max(int(limit), 1))
            items: list[dict[str, Any]] = []
            converted = 0
            skipped = 0
            for sample in query.all():
                result = self.preview_sample(sample.id, db=db)
                items.append(result)
                skipped += 1
            return EvalSetConversionResult(converted=converted, skipped=skipped, items=items)
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()
