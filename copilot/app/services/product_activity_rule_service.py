"""Product activity rules with customer-safe output boundaries."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from typing import Any


FORBIDDEN_INTERNAL_TERMS = (
    "\u56db\u7ea7\u63a7\u4ef7",
    "\u96364",
    "\u5927\u4fc3\u4ef7",
    "\u5927\u4fc3\u4ef7_\u96364",
    "\u5185\u90e8\u4ef7",
    "\u63a7\u4ef7",
    "\u6210\u672c\u4ef7",
    "\u5e95\u4ef7",
    "\u6bdb\u5229",
    "\u5229\u6da6",
)

_PRODUCT_KEYS = (
    "\u5546\u54c1\u540d",
    "\u4ea7\u54c1\u540d",
    "\u54c1\u540d",
    "\u5546\u54c1",
    "\u4ea7\u54c1",
    "\u70b9\u51fb\u67e5\u770b\u94fe\u63a5\u8be6\u60c5",
)
_IID_KEYS = ("\u5546\u54c1\u7f16\u7801", "i_id", "iid", "\u6b3e\u53f7")
_SKU_KEYS = ("sku", "SKU", "\u89c4\u683c\u7f16\u7801")
_BENEFIT_KEYS = (
    "\u4f18\u60e0",
    "\u6d3b\u52a8",
    "\u4f18\u60e0\u5238",
    "\u7ea2\u5305",
    "\u6652\u56fe",
    "\u597d\u8bc4",
    "\u8d60\u54c1",
    "\u4ef7\u4fdd",
)
_INTERNAL_KEYS = (
    "\u56db\u7ea7\u63a7\u4ef7",
    "\u96364",
    "\u5927\u4fc3\u4ef7",
    "\u63a7\u4ef7",
    "\u5185\u90e8\u4ef7",
    "\u6210\u672c",
    "\u5e95\u4ef7",
)
_DATE_START_KEYS = ("\u5f00\u59cb", "\u751f\u6548", "start")
_DATE_END_KEYS = ("\u7ed3\u675f", "\u5931\u6548", "end")


def flatten_field_value(value: Any) -> str:
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
        return " ".join(flatten_field_value(v) for v in value.values() if v is not None).strip()
    if isinstance(value, list):
        return " ".join(flatten_field_value(item) for item in value if item is not None).strip()
    return str(value).strip()


def normalize_activity_record(
    fields: dict[str, Any],
    *,
    source_record_id: str = "",
    source_sheet_id: str = "",
) -> dict[str, Any]:
    flat = {str(key): flatten_field_value(value) for key, value in (fields or {}).items()}
    product_name = _first_value(flat, _PRODUCT_KEYS)
    i_id = _first_value(flat, _IID_KEYS)
    sku_code = _first_value(flat, _SKU_KEYS)
    raw_benefits = _collect_values(flat, _BENEFIT_KEYS)
    internal = _collect_internal(flat)
    benefit_text = "\n".join(item for item in raw_benefits if item).strip()
    customer_visible_benefit = sanitize_customer_text(benefit_text)
    condition_text = _condition_text(flat)
    title = _title(product_name, customer_visible_benefit, fields)
    activity_type = classify_activity_type(f"{title}\n{condition_text}\n{benefit_text}")
    customer_reply = build_customer_reply(product_name, customer_visible_benefit, condition_text)
    safe = bool(customer_reply) and is_customer_safe_text(customer_reply)
    status = "active" if safe else "pending_review"
    content_hash = _hash({
        "product_name": product_name,
        "i_id": i_id,
        "sku_code": sku_code,
        "activity_type": activity_type,
        "condition_text": condition_text,
        "customer_visible_benefit": customer_visible_benefit,
        "internal": internal,
        "source_sheet_id": source_sheet_id,
        "source_record_id": source_record_id,
    })
    return {
        "product_id": None,
        "i_id": i_id,
        "sku_code": sku_code,
        "product_name": product_name,
        "activity_type": activity_type,
        "title": title,
        "condition_text": condition_text,
        "customer_visible_benefit": customer_visible_benefit,
        "customer_reply": customer_reply,
        "internal_price_field": internal.get("price_field", ""),
        "internal_price_value": internal.get("price_value"),
        "internal_only": internal,
        "start_at": _parse_date(_first_value(flat, _DATE_START_KEYS)),
        "end_at": _parse_date(_first_value(flat, _DATE_END_KEYS)),
        "status": status,
        "risk_level": "low" if safe else "medium",
        "auto_reply_allowed": safe,
        "source": "dingtalk_activity_sheet",
        "source_record_id": source_record_id,
        "source_sheet_id": source_sheet_id,
        "content_hash": content_hash,
        "raw_fields": flat,
    }


def sanitize_customer_text(text: str) -> str:
    value = str(text or "").strip()
    if not value:
        return ""
    explicit_safe_phrases = re.findall(
        r"(?:\u6652\u56fe\u597d\u8bc4[\uff0c,\u3001\s]*)?\u9886\u53d6?\s*\d+(?:\.\d+)?\s*\u5143(?:\u7ea2\u5305|\u4f18\u60e0\u5238|\u5238)"
        r"|\d+(?:\.\d+)?\s*\u5143(?:\u7ea2\u5305|\u4f18\u60e0\u5238|\u5238)",
        value,
    )
    value = re.sub(
        r"[\u7ed9\u5230\u53c2\u8003\u6309\s]*[^\n\uff1b;,\uff0c\u3002]*("
        + "|".join(re.escape(term) for term in FORBIDDEN_INTERNAL_TERMS)
        + r")[^\n\uff1b;,\uff0c\u3002]*",
        "",
        value,
    )
    for term in FORBIDDEN_INTERNAL_TERMS:
        value = value.replace(term, "")
    segments = [
        re.sub(r"\s+", " ", segment).strip(" \t\n\r\uff0c,;；")
        for segment in re.split(r"[\n\uff1b;。]+", value)
    ]
    keep = []
    for segment in segments:
        if not segment:
            continue
        if any(term in segment for term in FORBIDDEN_INTERNAL_TERMS):
            continue
        if (
            re.search(r"\d+(?:\.\d+)?\s*\u5143", segment)
            or any(cue in segment for cue in ("\u4f18\u60e0\u5238", "\u7ea2\u5305", "\u8d60\u54c1", "\u4ef7\u4fdd", "\u4fdd\u4ef7"))
        ):
            keep.append(segment)
    for phrase in explicit_safe_phrases:
        if phrase and not any(phrase in existing for existing in keep):
            keep.append(phrase)
    return "\n".join(_dedupe(keep)).strip()


def is_customer_safe_text(text: str) -> bool:
    value = str(text or "")
    return bool(value.strip()) and not any(term in value for term in FORBIDDEN_INTERNAL_TERMS)


def classify_activity_type(text: str) -> str:
    value = str(text or "")
    if "\u4f18\u60e0\u5238" in value or "\u9886\u5238" in value:
        return "coupon"
    if "\u7ea2\u5305" in value or "\u6652\u56fe" in value or "\u597d\u8bc4" in value:
        return "review_rebate"
    if "\u8d60\u54c1" in value or "\u793c\u54c1" in value:
        return "gift"
    if "\u4ef7\u4fdd" in value or "\u4fdd\u4ef7" in value:
        return "price_protection"
    return "other"


def build_customer_reply(product_name: str, benefit: str, condition_text: str = "") -> str:
    benefit = sanitize_customer_text(benefit)
    if not benefit:
        return ""
    prefix = f"\u8fd9\u6b3e\u300c{product_name}\u300d\u76ee\u524d\u53ef\u53c2\u8003\u7684\u6d3b\u52a8\u662f\uff1a" if product_name else "\u76ee\u524d\u53ef\u53c2\u8003\u7684\u6d3b\u52a8\u662f\uff1a"
    lines = [prefix]
    lines.extend(f"- {line}" for line in benefit.splitlines() if line.strip())
    if condition_text and is_customer_safe_text(condition_text):
        lines.append(f"\u5177\u4f53\u4ee5\u4e0b\u5355\u9875\u9762\u548c\u5ba2\u670d\u6838\u5bf9\u4e3a\u51c6\uff0c{condition_text}")
    else:
        lines.append("\u5177\u4f53\u4ee5\u4e0b\u5355\u9875\u9762\u548c\u5ba2\u670d\u6838\u5bf9\u4e3a\u51c6\u3002")
    reply = "\n".join(lines).strip()
    return reply if is_customer_safe_text(reply) else ""


def upsert_activity_rule(db, ActivityModel, normalized: dict[str, Any]):
    now = datetime.utcnow()
    query = db.query(ActivityModel).filter(
        ActivityModel.source_sheet_id == normalized.get("source_sheet_id", ""),
        ActivityModel.source_record_id == normalized.get("source_record_id", ""),
    )
    row = query.first() if normalized.get("source_record_id") else None
    if not row:
        row = ActivityModel()
        action = "created"
        db.add(row)
    else:
        action = "unchanged" if row.content_hash == normalized.get("content_hash", "") else "updated"

    for key in (
        "product_id",
        "i_id",
        "sku_code",
        "product_name",
        "activity_type",
        "title",
        "condition_text",
        "customer_visible_benefit",
        "customer_reply",
        "internal_price_field",
        "internal_price_value",
        "start_at",
        "end_at",
        "status",
        "risk_level",
        "auto_reply_allowed",
        "source",
        "source_record_id",
        "source_sheet_id",
        "content_hash",
    ):
        setattr(row, key, normalized.get(key))
    row.set_internal_only(normalized.get("internal_only") or {})
    row.set_raw_fields(normalized.get("raw_fields") or {})
    row.last_seen_at = now
    row.updated_at = now
    if not row.created_at:
        row.created_at = now
    return row, action


def get_active_activity_rules_for_product(db, ActivityModel, identity: dict[str, Any], limit: int = 5) -> list[dict[str, Any]]:
    from sqlalchemy import or_

    now = datetime.utcnow()
    q = db.query(ActivityModel).filter(
        ActivityModel.status == "active",
        ActivityModel.auto_reply_allowed == True,  # noqa: E712
        or_(ActivityModel.start_at.is_(None), ActivityModel.start_at <= now),
        or_(ActivityModel.end_at.is_(None), ActivityModel.end_at >= now),
    )
    product_id = identity.get("product_id")
    i_id = str(identity.get("i_id") or "").strip()
    requested_sku = str(identity.get("sku") or identity.get("sku_family") or "").strip()
    product_name = str(identity.get("product_name") or "").strip()
    conds = []
    if product_id is not None:
        conds.append(ActivityModel.product_id == product_id)
    if i_id:
        conds.append(ActivityModel.i_id == i_id)
    if requested_sku:
        conds.append(ActivityModel.sku_code == requested_sku)
    if not conds and product_name:
        conds.append(ActivityModel.product_name == product_name)
    if not conds:
        return []
    rows = q.filter(or_(*conds)).order_by(ActivityModel.updated_at.desc()).all()
    contexts = []
    for row in rows:
        if not _activity_rule_matches_identity(row, identity):
            continue
        item = row.customer_context()
        if is_customer_safe_text(item.get("customer_reply", "")):
            contexts.append(item)
        if len(contexts) >= limit:
            break
    return contexts


def _activity_rule_matches_identity(row: Any, identity: dict[str, Any]) -> bool:
    requested_product_id = identity.get("product_id")
    requested_i_id = str(identity.get("i_id") or "").strip().casefold()
    requested_sku = str(identity.get("sku") or identity.get("sku_family") or "").strip().casefold()
    requested_name = str(identity.get("product_name") or "").strip().casefold()

    row_product_id = getattr(row, "product_id", None)
    row_i_id = str(getattr(row, "i_id", "") or "").strip().casefold()
    row_sku = str(getattr(row, "sku_code", "") or "").strip().casefold()
    row_name = str(getattr(row, "product_name", "") or "").strip().casefold()

    shared_strong_identity = False
    if requested_product_id is not None and row_product_id is not None:
        if str(requested_product_id).strip() != str(row_product_id).strip():
            return False
        shared_strong_identity = True
    if requested_i_id and row_i_id:
        if requested_i_id != row_i_id:
            return False
        shared_strong_identity = True
    if requested_sku and row_sku:
        if requested_sku != row_sku:
            return False
        shared_strong_identity = True

    request_has_strong_identity = bool(
        requested_product_id is not None or requested_i_id or requested_sku
    )
    if request_has_strong_identity:
        return shared_strong_identity
    return bool(requested_name and row_name and requested_name == row_name)


def _first_value(flat: dict[str, str], keys: tuple[str, ...]) -> str:
    for key, value in flat.items():
        key_text = key.lower()
        if any(token.lower() in key_text for token in keys):
            if str(value or "").strip():
                return str(value).strip()
    return ""


def _collect_values(flat: dict[str, str], keys: tuple[str, ...]) -> list[str]:
    values = []
    for key, value in flat.items():
        key_text = key.lower()
        if any(token.lower() in key_text for token in keys) and str(value or "").strip():
            values.append(str(value).strip())
    return _dedupe(values)


def _collect_internal(flat: dict[str, str]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in flat.items():
        key_text = key.lower()
        if any(token.lower() in key_text for token in _INTERNAL_KEYS):
            result.setdefault("fields", {})[key] = value
            if not result.get("price_field"):
                result["price_field"] = key
                result["price_value"] = _parse_number(value)
    return result


def _condition_text(flat: dict[str, str]) -> str:
    values = []
    for key, value in flat.items():
        if any(token in key for token in ("\u6761\u4ef6", "\u95e8\u69db", "\u5907\u6ce8", "\u9650\u5236")):
            safe = sanitize_customer_text(value)
            if safe:
                values.append(safe)
    return "\n".join(_dedupe(values)).strip()


def _title(product_name: str, benefit: str, fields: dict[str, Any]) -> str:
    explicit = _first_value({str(k): flatten_field_value(v) for k, v in fields.items()}, ("\u6807\u9898", "\u540d\u79f0"))
    if explicit and is_customer_safe_text(explicit):
        return explicit[:255]
    activity = classify_activity_type(benefit)
    label = {
        "coupon": "\u4f18\u60e0\u5238",
        "review_rebate": "\u6652\u56fe\u597d\u8bc4\u6d3b\u52a8",
        "gift": "\u8d60\u54c1\u6d3b\u52a8",
        "price_protection": "\u4ef7\u4fdd\u89c4\u5219",
    }.get(activity, "\u6d3b\u52a8\u89c4\u5219")
    return f"{product_name} {label}".strip()[:255]


def _parse_date(value: str):
    text = str(value or "").strip()
    if not text:
        return None
    if re.fullmatch(r"\d{10,13}", text):
        number = int(text)
        if number > 10_000_000_000:
            number = number // 1000
        return datetime.utcfromtimestamp(number)
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%Y/%m/%d", "%Y.%m.%d"):
        try:
            return datetime.strptime(text[:19], fmt)
        except ValueError:
            continue
    return None


def _parse_number(value: Any):
    match = re.search(r"-?\d+(?:\.\d+)?", str(value or ""))
    return float(match.group(0)) if match else None


def _hash(value: dict[str, Any]) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _dedupe(values: list[str]) -> list[str]:
    seen = set()
    result = []
    for value in values:
        key = str(value).strip()
        if key and key not in seen:
            seen.add(key)
            result.append(key)
    return result
