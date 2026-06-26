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


def build_eval_contract(sample: KBTrainingSample) -> dict[str, Any]:
    customer_quote = _plain_text(sample.customer_quote)
    supervisor_evaluation = _plain_text(sample.correct_answer or sample.notes)
    image_only = _is_image_only_quote(customer_quote)
    customer_said = "" if image_only else customer_quote
    return sanitize_obj({
        "customer_said": customer_said,
        "suggested_answer": supervisor_evaluation,
    })


def _can_convert(contract: dict[str, Any]) -> tuple[bool, str]:
    if not _plain_text(contract.get("customer_said")):
        return False, "missing_customer_said"
    if not _plain_text(contract.get("suggested_answer")):
        return False, "missing_suggested_answer"
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
                "customer_said": _plain_text(contract.get("customer_said")),
                "suggested_answer": _plain_text(contract.get("suggested_answer")),
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
