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
from app.services.knowledge_gap_publish_transaction_service import KnowledgeGapPublishTransactionService


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
        transaction_service = KnowledgeGapPublishTransactionService()
        plan = transaction_service.build_plan(item)
        plan_validation = transaction_service.validate_plan(plan)
        block_reasons = (
            self._block_reasons(item)
            + _clean_list(plan.get("block_reasons"))
            + _clean_list(plan_validation.get("errors"))
        )
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
            "plan_validation": plan_validation,
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
        metadata["last_publish_simulation_plan"] = plan
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

    def _block_reasons(self, item) -> list[str]:
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
        return reasons

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
