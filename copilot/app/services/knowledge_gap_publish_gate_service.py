"""Server-side publish simulation gate for reviewed knowledge gap queue items.

This service is intentionally not a formal publisher. It validates the final
handoff contract, writes an audit record, and returns a transaction plan with
``writes_formal_tables=False``.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from app.services.eval_sanitizer_service import sanitize_obj, sanitize_text


BLOCKED_QUEUE_STATUSES = {"superseded", "rejected", "cancelled"}


def _new_audit_uid() -> str:
    return f"kgpub_audit_{uuid.uuid4().hex[:12]}"


def _clean_dict(value: Any) -> dict[str, Any]:
    return sanitize_obj(value) if isinstance(value, dict) else {}


def _clean_list(value: Any) -> list[Any]:
    return sanitize_obj(value) if isinstance(value, list) else []


def _field_names(value: Any) -> list[str]:
    if isinstance(value, dict):
        return [sanitize_text(key) for key in value if sanitize_text(key)]
    if isinstance(value, list):
        return [sanitize_text(item) for item in value if sanitize_text(item)]
    return []


def _first_text(*values: Any) -> str:
    for value in values:
        text = sanitize_text(value)
        if text:
            return text
    return ""


def _identity(payload: dict[str, Any]) -> dict[str, Any]:
    product_identity = payload.get("product_identity")
    result = dict(product_identity) if isinstance(product_identity, dict) else {}
    for source, target in [
        ("item_id", "item_id"),
        ("i_id", "item_id"),
        ("sku", "sku_code"),
        ("sku_code", "sku_code"),
        ("bind_to_sku", "sku_code"),
        ("bind_to_item_id", "item_id"),
        ("product_title", "product_title"),
    ]:
        if _first_text(payload.get(source)) and not _first_text(result.get(target)):
            result[target] = payload.get(source)
    return sanitize_obj(result)


def _base_plan(target: str, operations: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    return sanitize_obj({
        "mode": "simulation",
        "target": sanitize_text(target),
        "operations": operations or [],
        "requires_transaction": True,
        "requires_post_publish_retest": True,
        "rollback_supported": False,
    })


def _payload_summary(payload: dict[str, Any]) -> dict[str, Any]:
    return sanitize_obj({
        "top_level_fields": _field_names(payload),
        "product_identity_fields": _field_names(payload.get("product_identity")),
        "field_names": _field_names(payload.get("fields")),
        "has_uploaded_asset_id": bool(_first_text(payload.get("uploaded_asset_id"))),
        "has_asset_url": bool(_first_text(payload.get("asset_url"))),
    })


class KnowledgeGapPublishGateService:
    def simulate_publish(self, db, queue_uid: str, *, operator: str = "") -> dict[str, Any] | None:
        from app.models.eval_tables import KnowledgeGapPublishQueue

        item = (
            db.query(KnowledgeGapPublishQueue)
            .filter(KnowledgeGapPublishQueue.queue_uid == sanitize_text(queue_uid))
            .one_or_none()
        )
        if item is None:
            return None

        payload = _clean_dict(item.get_payload())
        block_reasons = self._block_reasons(item, payload)
        plan = _base_plan(item.publish_target) if block_reasons else self._transaction_plan(item, payload)
        status = "blocked" if block_reasons else "passed"
        action = "blocked" if block_reasons else "transaction_plan_created"
        validation_result = {
            "queue_uid": item.queue_uid,
            "publish_target": item.publish_target,
            "block_reasons": block_reasons,
            "payload_summary": _payload_summary(payload),
            "publish_dry_run_status": item.publish_dry_run_status,
            "ready_for_publish": bool(item.ready_for_publish),
            "pre_publish_retest_status": item.pre_publish_retest_status,
            "approved_to_publish": bool(item.approved_to_publish),
            "approval_status": item.approval_status,
            "payload_fingerprint": item.payload_fingerprint,
            "locked_payload_fingerprint": item.locked_payload_fingerprint,
        }
        audit = self._write_audit(
            db,
            item,
            operator=sanitize_text(operator),
            action=action,
            status=status,
            reason="; ".join(block_reasons),
            transaction_plan=plan,
            validation_result=validation_result,
        )
        metadata = item.get_metadata()
        metadata["last_publish_simulation_audit"] = {
            "audit_uid": audit.audit_uid,
            "status": audit.status,
            "action": audit.action,
            "reason": audit.reason,
            "created_at": audit.created_at.isoformat() if audit.created_at else None,
            "writes_formal_tables": False,
        }
        item.set_metadata(metadata)
        item.updated_at = datetime.utcnow()
        db.commit()

        return sanitize_obj({
            "ok": not block_reasons,
            "status": status,
            "writes_formal_tables": False,
            "queue_uid": item.queue_uid,
            "task_uid": item.task_uid,
            "draft_uid": item.draft_uid,
            "publish_target": item.publish_target,
            "block_reasons": block_reasons,
            "transaction_plan": plan,
            "audit_uid": audit.audit_uid,
            "queue_item": item.to_dict(),
        })

    def latest_audit_summary(self, db, queue_uid: str) -> dict[str, Any]:
        from app.models.eval_tables import KnowledgeGapPublishAudit

        audit = (
            db.query(KnowledgeGapPublishAudit)
            .filter(KnowledgeGapPublishAudit.queue_uid == sanitize_text(queue_uid))
            .order_by(KnowledgeGapPublishAudit.created_at.desc(), KnowledgeGapPublishAudit.id.desc())
            .first()
        )
        if audit is None:
            return {}
        return sanitize_obj({
            "audit_uid": audit.audit_uid,
            "action": audit.action,
            "status": audit.status,
            "reason": audit.reason,
            "writes_formal_tables": bool(audit.writes_formal_tables),
            "transaction_plan": audit.get_transaction_plan(),
            "created_at": audit.created_at.isoformat() if audit.created_at else None,
        })

    def _block_reasons(self, item, payload: dict[str, Any]) -> list[str]:
        reasons: list[str] = []
        status = sanitize_text(item.status)
        if status in BLOCKED_QUEUE_STATUSES:
            reasons.append(f"{status} queue items cannot be simulated for publish")
        if item.publish_dry_run_status != "passed":
            reasons.append("publish dry-run must pass before publish simulation")
        if not bool(item.ready_for_publish):
            reasons.append("queue item is not ready_for_publish")
        if item.pre_publish_retest_status != "passed":
            reasons.append("pre-publish retest must pass before publish simulation")
        if not bool(item.approved_to_publish):
            reasons.append("queue item is not approved_to_publish")
        if sanitize_text(item.approval_status) != "approved_to_publish":
            reasons.append("approval_status must be approved_to_publish")
        if not sanitize_text(item.locked_payload_fingerprint):
            reasons.append("locked_payload_fingerprint is required")
        if sanitize_text(item.locked_payload_fingerprint) and sanitize_text(item.payload_fingerprint) != sanitize_text(item.locked_payload_fingerprint):
            reasons.append("payload changed after approval")

        target = sanitize_text(item.publish_target)
        if target == "context_extractor":
            reasons.append("context_extractor is an engineering task and cannot be published to a knowledge store")
        if target == "kb_media_asset" and not (
            _first_text(payload.get("uploaded_asset_id")) or _first_text(payload.get("asset_url"))
        ):
            reasons.append("kb_media_asset publish simulation requires uploaded_asset_id or asset_url")
        return reasons

    def _transaction_plan(self, item, payload: dict[str, Any]) -> dict[str, Any]:
        target = sanitize_text(item.publish_target)
        if target == "product_profile":
            identity = _identity(payload)
            return _base_plan(target, [{
                "operation": "upsert",
                "target_table": "kb_product",
                "match_key": _first_text(identity.get("item_id"), identity.get("sku_code"), identity.get("product_title")),
                "fields": _field_names(payload.get("fields")),
            }])
        if target == "kb_product":
            identity = _identity(payload)
            return _base_plan(target, [{
                "operation": "create_or_update_fact",
                "target_table": "kb_product_facts",
                "match_key": "product_identity + fact_type",
                "fields": [
                    key for key in ["fact_type", "evidence_text", "source_reference"]
                    if _first_text(payload.get(key))
                ] + _field_names(identity),
            }])
        if target == "kb_media_asset":
            return _base_plan(target, [{
                "operation": "upsert_media_asset",
                "target_table": "kb_media_asset",
                "match_key": _first_text(payload.get("uploaded_asset_id"), payload.get("asset_url")),
                "fields": [
                    key for key in [
                        "asset_type",
                        "media_purpose",
                        "bind_to_sku",
                        "uploaded_asset_id",
                        "asset_url",
                    ]
                    if _first_text(payload.get(key))
                ],
            }])
        if target == "activity_rules":
            return _base_plan(target, [{
                "operation": "upsert_activity_rule",
                "target_table": "activity_rules",
                "match_key": _first_text(payload.get("platform"), payload.get("promotion_scope")),
                "fields": [
                    key for key in ["platform", "time_scope", "promotion_scope", "rule_text"]
                    if payload.get(key) is not None
                ],
            }])
        if target == "aftersales_policy":
            return _base_plan(target, [{
                "operation": "upsert_policy_rule",
                "target_table": "aftersales_policy",
                "match_key": _first_text(payload.get("scenario"), payload.get("policy_code")),
                "fields": [
                    key for key in [
                        "scenario",
                        "policy_text",
                        "required_customer_inputs",
                        "allowed_actions",
                        "escalation_boundary",
                    ]
                    if payload.get(key) is not None
                ],
            }])
        return _base_plan(target)

    def _write_audit(
        self,
        db,
        item,
        *,
        operator: str,
        action: str,
        status: str,
        reason: str,
        transaction_plan: dict[str, Any],
        validation_result: dict[str, Any],
    ):
        from app.models.eval_tables import KnowledgeGapPublishAudit

        audit = KnowledgeGapPublishAudit(
            audit_uid=_new_audit_uid(),
            queue_uid=item.queue_uid,
            task_uid=item.task_uid,
            draft_uid=item.draft_uid,
            publish_target=item.publish_target,
            payload_fingerprint=item.payload_fingerprint,
            locked_payload_fingerprint=item.locked_payload_fingerprint,
            operator=sanitize_text(operator),
            action=sanitize_text(action),
            status=sanitize_text(status),
            reason=sanitize_text(reason),
            writes_formal_tables=False,
        )
        audit.set_transaction_plan(transaction_plan)
        audit.set_validation_result(validation_result)
        db.add(audit)
        db.flush()
        return audit
