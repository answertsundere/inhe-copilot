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

_MISSING_CONTEXT_VALUES = {
    "",
    "-",
    "无",
    "暂无",
    "未知",
    "未填写",
    "未提供",
    "未结构化",
    "无，售前咨询不需要订单号。",
}

_AFTERSALES_TERMS = (
    "售后",
    "订单",
    "物流",
    "签收",
    "退货",
    "退款",
    "换货",
    "补发",
    "少件",
    "发错",
    "不一致",
    "破损",
)
_PRESALES_TERMS = ("售前", "颜色", "材质", "尺寸", "活动", "优惠", "福利", "现货")
_INSTALLATION_TERMS = ("安装", "说明书", "视频", "配件", "螺丝", "顶板", "防倒器")


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
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = [re.sub(r"[ \t\f\v]+", " ", line).strip() for line in text.split("\n")]
    text = "\n".join(line for line in lines if line)
    return sanitize_text(text)


def _usable_context_value(value: str | None) -> bool:
    text = _plain_text(value)
    if not text:
        return False
    compact = re.sub(r"\s+", "", text)
    return compact not in {re.sub(r"\s+", "", item) for item in _MISSING_CONTEXT_VALUES}


def _field_value_from_text(text: str, labels: tuple[str, ...]) -> str:
    for label in labels:
        match = re.search(rf"{re.escape(label)}\s*[：:]\s*([^\n\r]+)", text)
        if match:
            return match.group(1).strip()
    return ""


def _has_context_field(sample: KBTrainingSample, contract: dict[str, Any], *, field: str) -> bool:
    customer_said = _plain_text(contract.get("customer_said"))
    if field == "order":
        return _usable_context_value(sample.order_no) or _usable_context_value(
            _field_value_from_text(customer_said, ("订单号", "订单"))
        )
    if field == "sku":
        return _usable_context_value(sample.sku) or _usable_context_value(
            _field_value_from_text(customer_said, ("SKU", "商品编码", "商品代码", "规格编码"))
        )
    if field == "product":
        return _usable_context_value(sample.product_title) or _usable_context_value(
            _field_value_from_text(customer_said, ("商品标题", "商品名称", "商品"))
        ) or bool(re.search(r"https?://\S+", customer_said))
    return False


def _sample_topic_text(sample: KBTrainingSample, contract: dict[str, Any]) -> str:
    return " ".join(
        _plain_text(value)
        for value in (
            sample.question_type,
            sample.difficulty_reason,
            sample.customer_quote,
            sample.full_context,
            contract.get("customer_said"),
        )
    )


def _requires_aftersales_identity(sample: KBTrainingSample, contract: dict[str, Any]) -> bool:
    topic = _sample_topic_text(sample, contract)
    return any(term in topic for term in _AFTERSALES_TERMS)


def _requires_product_identity(sample: KBTrainingSample, contract: dict[str, Any]) -> bool:
    topic = _sample_topic_text(sample, contract)
    return any(term in topic for term in _PRESALES_TERMS + _INSTALLATION_TERMS)


def _has_curated_dialogue_context(customer_said: str) -> bool:
    if not customer_said:
        return False
    lines = [line.strip() for line in customer_said.splitlines() if line.strip()]
    if len(lines) >= 2:
        return True
    return bool(re.search(r"(买家|客户|客服|主管|Buyer|Customer|Agent|Supervisor)\s*[：:]", customer_said, re.I))


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


def _can_convert(sample: KBTrainingSample, contract: dict[str, Any]) -> tuple[bool, str]:
    customer_said = _plain_text(contract.get("customer_said"))
    raw_customer_said = str(contract.get("customer_said") or "")
    if not customer_said:
        return False, "missing_customer_said"
    if not _plain_text(contract.get("suggested_answer")):
        return False, "missing_suggested_answer"
    if not _has_curated_dialogue_context(raw_customer_said):
        return False, "missing_curated_dialogue_context"
    has_order_or_sku = _has_context_field(sample, contract, field="order") or _has_context_field(sample, contract, field="sku")
    if _requires_aftersales_identity(sample, contract) and not has_order_or_sku:
        return False, "missing_aftersales_order_or_sku"
    has_product_identity = has_order_or_sku or _has_context_field(sample, contract, field="product")
    if _requires_product_identity(sample, contract) and not has_product_identity:
        return False, "missing_product_identity"
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
            can_convert, reason = _can_convert(sample, contract)
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
            can_convert, reason = _can_convert(sample, curated_contract)
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
