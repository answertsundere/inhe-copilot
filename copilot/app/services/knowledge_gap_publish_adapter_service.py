"""Dry-run adapters for reviewed knowledge gap publish queue items.

This layer validates publish payloads and returns a preview only. It never
inserts, updates, or deletes formal product, knowledge, media, policy, or rule
records.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from app.services.eval_sanitizer_service import sanitize_obj, sanitize_text


DRY_RUN_ALLOWED_STATUSES = {"queued", "exported"}
DRY_RUN_STATUS_NOT_RUN = "not_run"
DRY_RUN_STATUS_PASSED = "passed"
DRY_RUN_STATUS_FAILED = "failed"

_LONG_NUMBER_RE = re.compile(r"\b\d{10,}\b")
_PHONE_RE = re.compile(r"\b1[3-9]\d{9}\b")
_SIGNED_URL_RE = re.compile(
    r"(?i)(Expires|Signature|OSSAccessKeyId|security-token|x-oss-signature|X-Amz-Signature|token|secret|key)="
)
_TOKEN_RE = re.compile(r"(?i)\b(token|secret|api[_-]?key|access[_-]?key|signature|authorization)\b\s*[:=]")
_BASE64_RE = re.compile(r"^[A-Za-z0-9+/=\s]{160,}$")


def _truthy(value: Any) -> bool:
    if value is True:
        return True
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y", "checked"}
    return False


def _clean_dict(value: Any) -> dict[str, Any]:
    return sanitize_obj(value) if isinstance(value, dict) else {}


def _clean_list(value: Any) -> list[Any]:
    return sanitize_obj(value) if isinstance(value, list) else []


def _has_text(value: Any) -> bool:
    return bool(sanitize_text(value))


def _first_text(*values: Any) -> str:
    for value in values:
        text = sanitize_text(value)
        if text:
            return text
    return ""


def _field_names(value: Any) -> list[str]:
    if isinstance(value, dict):
        return [sanitize_text(key) for key in value if sanitize_text(key)]
    if isinstance(value, list):
        return [sanitize_text(item) for item in value if sanitize_text(item)]
    return []


def _payload_has_sensitive_content(value: Any) -> bool:
    if isinstance(value, dict):
        for key, item in value.items():
            key_text = sanitize_text(key).lower()
            if any(marker in key_text for marker in (
                "phone",
                "mobile",
                "tel",
                "order",
                "tracking",
                "address",
                "token",
                "secret",
                "signature",
                "base64",
                "authorization",
            )):
                return True
            if _payload_has_sensitive_content(item):
                return True
        return False
    if isinstance(value, list):
        return any(_payload_has_sensitive_content(item) for item in value)
    text = str(value or "")
    if not text:
        return False
    if _PHONE_RE.search(text) or _LONG_NUMBER_RE.search(text):
        return True
    if _SIGNED_URL_RE.search(text) or _TOKEN_RE.search(text):
        return True
    return len(text) > 512 and bool(_BASE64_RE.fullmatch(text))


def _identity(payload: dict[str, Any]) -> dict[str, Any]:
    product_identity = payload.get("product_identity")
    if isinstance(product_identity, dict):
        result = dict(product_identity)
    else:
        result = {}
    for source, target in [
        ("item_id", "item_id"),
        ("i_id", "item_id"),
        ("sku", "sku_code"),
        ("sku_code", "sku_code"),
        ("bind_to_sku", "sku_code"),
        ("bind_to_item_id", "item_id"),
        ("product_title", "product_title"),
    ]:
        if _has_text(payload.get(source)) and not _has_text(result.get(target)):
            result[target] = payload.get(source)
    return sanitize_obj(result)


def _match_product(db, identity: dict[str, Any], product_title: str = "") -> tuple[bool, str]:
    try:
        from app.models.kb_tables import KBProduct
    except Exception:
        return False, ""

    item_id = _first_text(identity.get("item_id"), identity.get("i_id"))
    sku_code = _first_text(identity.get("sku_code"), identity.get("sku"))
    title = _first_text(product_title, identity.get("product_title"), identity.get("display_product_name"))
    query = db.query(KBProduct)
    if item_id:
        row = query.filter(KBProduct.i_id == item_id).one_or_none()
        if row:
            return True, item_id
    if sku_code:
        rows = query.all()
        for row in rows:
            if sku_code in [sanitize_text(item) for item in (row.get_sku_list() or [])]:
                return True, sku_code
    if title:
        row = query.filter(KBProduct.product_name == title).one_or_none()
        if row:
            return True, title
    return False, item_id or sku_code or title


def _result(
    *,
    ok: bool,
    publish_target: str,
    adapter: str,
    schema_valid: bool,
    ready_for_publish: bool,
    block_reasons: list[str] | None = None,
    warnings: list[str] | None = None,
    diff_preview: dict[str, Any] | None = None,
    required_manual_checks: list[str] | None = None,
    item=None,
) -> dict[str, Any]:
    return sanitize_obj({
        "ok": ok,
        "publish_target": publish_target,
        "adapter": adapter,
        "writes_formal_tables": False,
        "schema_valid": schema_valid,
        "ready_for_publish": ready_for_publish,
        "block_reasons": block_reasons or [],
        "warnings": warnings or [],
        "diff_preview": diff_preview or {},
        "required_manual_checks": required_manual_checks or [],
        "source_queue_uid": getattr(item, "queue_uid", ""),
        "source_task_uid": getattr(item, "task_uid", ""),
        "source_draft_uid": getattr(item, "draft_uid", ""),
    })


class PublishAdapterDryRunService:
    def dry_run(self, db, queue_uid: str, *, operator: str = "") -> dict[str, Any] | None:
        from app.models.eval_tables import KnowledgeGapPublishQueue

        item = (
            db.query(KnowledgeGapPublishQueue)
            .filter(KnowledgeGapPublishQueue.queue_uid == sanitize_text(queue_uid))
            .one_or_none()
        )
        if item is None:
            return None
        if item.status not in DRY_RUN_ALLOWED_STATUSES:
            raise ValueError(f"{item.status} queue items cannot run publish dry-run")

        payload = _clean_dict(item.get_payload())
        result = self._run_adapter(db, item, payload)
        dry_run_status = (
            DRY_RUN_STATUS_PASSED
            if result.get("ok") is True and result.get("ready_for_publish") is True
            else DRY_RUN_STATUS_FAILED
        )
        item.publish_dry_run_status = dry_run_status
        item.set_publish_dry_run_result(result)
        item.set_publish_block_reasons(result.get("block_reasons") or [])
        item.ready_for_publish = bool(result.get("ready_for_publish"))
        item.last_dry_run_at = datetime.utcnow()
        item.dry_run_by = sanitize_text(operator)
        metadata = item.get_metadata()
        metadata["last_publish_dry_run"] = {
            "status": dry_run_status,
            "operator": item.dry_run_by,
            "checked_at": item.last_dry_run_at.isoformat(),
            "ready_for_publish": item.ready_for_publish,
        }
        item.set_metadata(metadata)
        db.commit()
        return sanitize_obj({"queue_item": item.to_dict(), "dry_run": result})

    def _run_adapter(self, db, item, payload: dict[str, Any]) -> dict[str, Any]:
        target = sanitize_text(getattr(item, "publish_target", ""))
        if target == "product_profile":
            return self._dry_run_product_profile(db, item, payload)
        if target == "kb_product":
            return self._dry_run_kb_product(db, item, payload)
        if target == "kb_media_asset":
            return self._dry_run_media_asset(item, payload)
        if target == "activity_rules":
            return self._dry_run_activity_rules(item, payload)
        if target == "aftersales_policy":
            return self._dry_run_aftersales_policy(item, payload)
        if target == "context_extractor":
            return self._dry_run_context_extractor(item, payload)
        return _result(
            ok=False,
            publish_target=target,
            adapter="unknown",
            schema_valid=False,
            ready_for_publish=False,
            block_reasons=["unsupported publish target"],
            item=item,
        )

    def _dry_run_product_profile(self, db, item, payload: dict[str, Any]) -> dict[str, Any]:
        blocks: list[str] = []
        identity = _identity(payload)
        fields = _clean_dict(payload.get("fields"))
        item_id_or_sku = _first_text(identity.get("item_id"), identity.get("sku_code"))
        if not identity:
            blocks.append("product_identity is required")
        if not item_id_or_sku:
            blocks.append("item_id or sku_code is required")
        if not fields:
            blocks.append("fields is required")
        elif not any(_has_text(value) for value in fields.values()):
            blocks.append("fields must include at least one value")
        if _payload_has_sensitive_content(payload):
            blocks.append("payload contains sensitive or unstable private data")
        matched, match_key = _match_product(db, identity)
        if not match_key:
            blocks.append("cannot locate product without item_id, sku_code, or product title")

        schema_valid = not blocks
        return _result(
            ok=schema_valid,
            publish_target="product_profile",
            adapter="product_profile",
            schema_valid=schema_valid,
            ready_for_publish=schema_valid,
            block_reasons=blocks,
            diff_preview={
                "target_table": "kb_product",
                "match_key": match_key,
                "would_create": schema_valid and not matched,
                "would_update": schema_valid and matched,
                "fields": _field_names(fields),
            },
            required_manual_checks=["confirm source document and SKU scope before formal publish"],
            item=item,
        )

    def _dry_run_kb_product(self, db, item, payload: dict[str, Any]) -> dict[str, Any]:
        blocks: list[str] = []
        identity = _identity(payload)
        product_title = _first_text(payload.get("product_title"), payload.get("title"))
        has_facts = bool(_clean_dict(payload.get("facts")) or _clean_dict(payload.get("fields")) or _has_text(payload.get("evidence_text")))
        if not identity and not product_title:
            blocks.append("product_identity or product_title is required")
        if not has_facts:
            blocks.append("facts, fields, or evidence_text is required")
        if not _has_text(payload.get("source_reference")):
            blocks.append("source_reference is required")
        if not _has_text(payload.get("fact_type")):
            blocks.append("fact_type is required")
        matched, match_key = _match_product(db, identity, product_title)
        if not match_key:
            match_key = product_title

        schema_valid = not blocks
        fields = _field_names(payload.get("facts")) + _field_names(payload.get("fields"))
        if _has_text(payload.get("evidence_text")):
            fields.append("evidence_text")
        return _result(
            ok=schema_valid,
            publish_target="kb_product",
            adapter="kb_product",
            schema_valid=schema_valid,
            ready_for_publish=schema_valid,
            block_reasons=blocks,
            diff_preview={
                "target_table": "knowledge_chunks",
                "match_key": match_key,
                "would_create": schema_valid and not matched,
                "would_update": schema_valid and matched,
                "fields": fields,
            },
            required_manual_checks=["confirm fact type and source reference"],
            item=item,
        )

    def _dry_run_media_asset(self, item, payload: dict[str, Any]) -> dict[str, Any]:
        blocks: list[str] = []
        for field in ["asset_type", "media_purpose", "asset_source_note"]:
            if not _has_text(payload.get(field)):
                blocks.append(f"{field} is required")
        identity = _identity(payload)
        if not _first_text(identity.get("sku_code"), identity.get("item_id"), identity.get("product_title")):
            blocks.append("bind_to_sku, item_id, or product_identity is required")
        has_uploaded_asset = _has_text(payload.get("asset_url")) or _has_text(payload.get("uploaded_asset_id"))
        if not has_uploaded_asset:
            blocks.append("needs_media_upload: asset_url or uploaded_asset_id is required")
        if _has_text(payload.get("conversation_media_reference")) and not has_uploaded_asset:
            blocks.append("conversation_media_reference cannot be treated as approved usable media")

        schema_valid = all(" is required" not in reason for reason in blocks)
        ready_for_publish = schema_valid and has_uploaded_asset and not _payload_has_sensitive_content(
            {"asset_url": payload.get("asset_url"), "uploaded_asset_id": payload.get("uploaded_asset_id")}
        )
        if has_uploaded_asset and not ready_for_publish:
            blocks.append("media reference contains sensitive or unstable URL data")
        return _result(
            ok=ready_for_publish,
            publish_target="kb_media_asset",
            adapter="kb_media_asset",
            schema_valid=schema_valid,
            ready_for_publish=ready_for_publish,
            block_reasons=blocks,
            diff_preview={
                "target_table": "kb_media_asset_request",
                "match_key": _first_text(identity.get("sku_code"), identity.get("item_id"), identity.get("product_title")),
                "would_create": True,
                "would_update": False,
                "fields": ["asset_type", "media_purpose", "asset_source_note", "bind_to_sku"],
            },
            required_manual_checks=["confirm media ownership and upload status"],
            item=item,
        )

    def _dry_run_activity_rules(self, item, payload: dict[str, Any]) -> dict[str, Any]:
        blocks: list[str] = []
        for field in ["platform", "time_scope", "rule_text", "promotion_scope"]:
            if not _has_text(payload.get(field)):
                blocks.append(f"{field} is required")
        time_scope = sanitize_text(payload.get("time_scope")).lower()
        rule_text = sanitize_text(payload.get("rule_text")).lower()
        if any(term in f"{time_scope} {rule_text}" for term in (
            "forever",
            "permanent",
            "always valid",
            "always applies",
            "\u6c38\u4e45\u6709\u6548",
            "\u957f\u671f\u6709\u6548",
            "\u4e00\u76f4\u6709\u6548",
        )):
            blocks.append("permanent validity must not be used as a default promotion rule")
        schema_valid = not blocks
        return _result(
            ok=schema_valid,
            publish_target="activity_rules",
            adapter="activity_rules",
            schema_valid=schema_valid,
            ready_for_publish=schema_valid,
            block_reasons=blocks,
            diff_preview={
                "target_table": "kb_product_activity_rule",
                "match_key": _first_text(payload.get("promotion_scope"), payload.get("platform")),
                "would_create": schema_valid,
                "would_update": False,
                "fields": ["platform", "time_scope", "rule_text", "promotion_scope"],
            },
            required_manual_checks=["confirm campaign period and applicable scope"],
            item=item,
        )

    def _dry_run_aftersales_policy(self, item, payload: dict[str, Any]) -> dict[str, Any]:
        blocks: list[str] = []
        for field in ["scenario", "policy_text", "escalation_boundary"]:
            if not _has_text(payload.get(field)):
                blocks.append(f"{field} is required")
        if not _clean_list(payload.get("required_customer_inputs")):
            blocks.append("required_customer_inputs is required")
        allowed_actions = [sanitize_text(action).lower() for action in _clean_list(payload.get("allowed_actions"))]
        if not allowed_actions:
            blocks.append("allowed_actions is required")
        risky_actions = {
            "refund",
            "reship",
            "return",
            "replacement",
            "compensation",
            "\u9000\u6b3e",
            "\u8865\u53d1",
            "\u9000\u8d27",
            "\u6362\u8d27",
            "\u8d54\u507f",
        }
        if any(any(term in action for term in risky_actions) for action in allowed_actions) and not (
            _truthy(payload.get("human_policy_confirmation"))
            or _truthy(payload.get("manual_policy_confirmation"))
            or _truthy(payload.get("reviewer_confirmation"))
            or _truthy(payload.get("explicitly_verified"))
        ):
            blocks.append("refund, reship, return, or compensation actions require human policy confirmation")
        schema_valid = not blocks
        return _result(
            ok=schema_valid,
            publish_target="aftersales_policy",
            adapter="aftersales_policy",
            schema_valid=schema_valid,
            ready_for_publish=schema_valid,
            block_reasons=blocks,
            diff_preview={
                "target_table": "aftersales_policy_staging",
                "match_key": _first_text(payload.get("scenario")),
                "would_create": schema_valid,
                "would_update": False,
                "fields": [
                    "scenario",
                    "policy_text",
                    "required_customer_inputs",
                    "allowed_actions",
                    "escalation_boundary",
                ],
            },
            required_manual_checks=["confirm human escalation boundary"],
            item=item,
        )

    def _dry_run_context_extractor(self, item, payload: dict[str, Any]) -> dict[str, Any]:
        return _result(
            ok=False,
            publish_target="context_extractor",
            adapter="context_extractor",
            schema_valid=True,
            ready_for_publish=False,
            block_reasons=["context extractor gaps require engineering work, not knowledge publishing"],
            warnings=["create an engineering task; do not publish this payload to formal knowledge tables"],
            diff_preview={
                "target_table": "engineering_task_queue",
                "match_key": _first_text(payload.get("context_field"), getattr(item, "task_uid", "")),
                "would_create": True,
                "would_update": False,
                "fields": _field_names(payload) or ["context_extraction_contract"],
            },
            required_manual_checks=["assign to agent engineering owner"],
            item=item,
        )
