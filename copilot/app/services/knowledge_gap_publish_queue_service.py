"""Review-approved publish queue for knowledge gap drafts.

This queue is an audited handoff record only. It never writes formal product,
knowledge, media, policy, or rule tables.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from app.services.eval_sanitizer_service import sanitize_obj, sanitize_text
from app.services.knowledge_gap_task_service import _metadata_with_status_history


QUEUE_STATUSES = {"queued", "exported", "rejected", "cancelled"}
QUEUE_EXPORT_STATUSES = {"not_exported", "exported"}
REVIEW_DECISIONS = {"approve_for_queue", "reject", "request_changes"}
PUBLISHABLE_TARGETS = {
    "product_profile",
    "kb_product",
    "kb_media_asset",
    "aftersales_policy",
    "activity_rules",
}


def _new_queue_uid() -> str:
    return f"kgpub_{uuid.uuid4().hex[:12]}"


def _truthy(value) -> bool:
    if value is True:
        return True
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y", "checked"}
    return False


def _checklist_passed(payload: dict[str, Any]) -> bool:
    checklist = payload.get("review_checklist")
    if not isinstance(checklist, dict) or not checklist:
        return False
    return all(_truthy(value) for value in checklist.values())


def _source_reference_is_customer_only(value: str) -> bool:
    text = sanitize_text(value).strip().lower()
    if not text:
        return True
    customer_terms = ("客服", "客户说", "customer said", "cs said", "chat reply")
    return any(term in text for term in customer_terms) and not any(
        marker in text for marker in ("http", "doc", "sheet", "manual", "report", "url", "file", "page", "质检", "资料")
    )


def _require_dict(value, field_name: str) -> dict[str, Any]:
    if not isinstance(value, dict) or not value:
        raise ValueError(f"{field_name} is required")
    return value


def _require_list(value, field_name: str) -> list[Any]:
    if not isinstance(value, list) or not value:
        raise ValueError(f"{field_name} is required")
    return value


def _validate_product_field_payload(payload: dict[str, Any]) -> None:
    product_identity = payload.get("product_identity") or {
        "product_id": payload.get("product_id"),
        "item_id": payload.get("item_id"),
        "sku": payload.get("sku"),
        "sku_code": payload.get("sku_code"),
    }
    if not isinstance(product_identity, dict) or not any(sanitize_text(v) for v in product_identity.values()):
        raise ValueError("product identity is required")
    fields = _require_dict(payload.get("fields"), "fields")
    if not any(sanitize_text(value) for value in fields.values()):
        raise ValueError("fields must include at least one verified value")
    source_reference = sanitize_text(payload.get("source_reference"))
    if _source_reference_is_customer_only(source_reference):
        raise ValueError("source_reference must be a verified source, not only a customer service reply")
    if not sanitize_text(payload.get("sku_scope")):
        raise ValueError("sku_scope is required")
    if not _truthy(payload.get("reviewer_confirmation")):
        raise ValueError("reviewer_confirmation is required")


def _validate_media_payload(payload: dict[str, Any]) -> None:
    for field in ["asset_type", "media_purpose", "asset_source_note"]:
        if not sanitize_text(payload.get(field)):
            raise ValueError(f"{field} is required")
    _require_list(payload.get("answer_scenarios"), "answer_scenarios")
    if not sanitize_text(payload.get("bind_to_item_id") or payload.get("bind_to_sku")):
        raise ValueError("bind_to_item_id or bind_to_sku is required")
    if not _truthy(payload.get("reviewer_confirms_upload_required")):
        raise ValueError("reviewer_confirms_upload_required is required")


def _contains_unconditional_compensation(payload: dict[str, Any]) -> bool:
    text = " ".join(
        sanitize_text(value).lower()
        for value in [
            payload.get("policy_text"),
            " ".join(str(item) for item in payload.get("allowed_actions") or []),
        ]
    )
    risky_terms = (
        "无条件退款",
        "无条件退",
        "无条件补偿",
        "直接赔",
        "unconditional refund",
        "unconditional compensation",
        "always refund",
    )
    return any(term in text for term in risky_terms)


def _validate_aftersales_payload(payload: dict[str, Any]) -> None:
    for field in ["scenario", "policy_text", "escalation_boundary"]:
        if not sanitize_text(payload.get(field)):
            raise ValueError(f"{field} is required")
    _require_list(payload.get("required_customer_inputs"), "required_customer_inputs")
    _require_list(payload.get("allowed_actions"), "allowed_actions")
    if _contains_unconditional_compensation(payload) and not (
        _truthy(payload.get("explicitly_verified")) and sanitize_text(payload.get("policy_source_reference"))
    ):
        raise ValueError("unconditional refund/reship/compensation requires explicit verified policy source")
    if not _truthy(payload.get("reviewer_confirmation")):
        raise ValueError("reviewer_confirmation is required")


def _validate_promotion_payload(payload: dict[str, Any]) -> None:
    for field in [
        "promotion_scope",
        "platform",
        "time_scope",
        "rule_text",
        "refund_after_participation_rule",
        "policy_source_reference",
    ]:
        if not sanitize_text(payload.get(field)):
            raise ValueError(f"{field} is required")
    if not _truthy(payload.get("reviewer_confirmation")):
        raise ValueError("reviewer_confirmation is required")


def _validate_verified_payload(draft_type: str, payload: dict[str, Any]) -> None:
    if not _checklist_passed(payload):
        raise ValueError("review_checklist must be confirmed")
    if draft_type == "product_field_draft":
        _validate_product_field_payload(payload)
        return
    if draft_type == "media_asset_request":
        _validate_media_payload(payload)
        return
    if draft_type == "aftersales_policy_draft":
        _validate_aftersales_payload(payload)
        return
    if draft_type == "promotion_policy_draft":
        _validate_promotion_payload(payload)
        return
    raise ValueError("draft target is not publishable")


def _queue_payload_from_review(content: dict[str, Any], review_payload: dict[str, Any]) -> dict[str, Any]:
    verified_payload = review_payload.get("verified_payload")
    if isinstance(verified_payload, dict) and verified_payload:
        return sanitize_obj(verified_payload)
    return sanitize_obj(content.get("publish_payload") or {})


def _readiness_snapshot(content: dict[str, Any], review_payload: dict[str, Any]) -> dict[str, Any]:
    return sanitize_obj({
        "publish_readiness": content.get("publish_readiness"),
        "draft_type": content.get("draft_type"),
        "business_publish_target": content.get("business_publish_target") or content.get("target_system"),
        "reviewer_checklist": content.get("reviewer_checklist") or [],
        "submitted_review_checklist": review_payload.get("review_checklist") or {},
    })


class KnowledgeGapPublishQueueService:
    def review_draft(
        self,
        db,
        *,
        task_uid: str,
        draft_uid: str,
        payload: dict[str, Any],
        reviewer: str = "",
    ) -> dict[str, Any] | None:
        from app.models.eval_tables import KnowledgeGapDraft, KnowledgeGapPublishQueue, KnowledgeGapTask

        clean_task_uid = sanitize_text(task_uid)
        clean_draft_uid = sanitize_text(draft_uid)
        task = db.query(KnowledgeGapTask).filter(KnowledgeGapTask.task_uid == clean_task_uid).one_or_none()
        if task is None:
            return None
        draft = (
            db.query(KnowledgeGapDraft)
            .filter(KnowledgeGapDraft.task_uid == clean_task_uid, KnowledgeGapDraft.draft_uid == clean_draft_uid)
            .one_or_none()
        )
        if draft is None:
            raise ValueError("knowledge gap draft not found")

        decision = sanitize_text(payload.get("decision"))
        if decision not in REVIEW_DECISIONS:
            raise ValueError("invalid draft review decision")
        reviewer_name = sanitize_text(payload.get("reviewer") or reviewer)
        review_note = sanitize_text(payload.get("review_note"))

        if decision in {"reject", "request_changes"}:
            draft.review_status = "rejected" if decision == "reject" else "request_changes"
            draft.reviewer = reviewer_name
            draft.reviewed_at = datetime.utcnow()
            draft.rejection_reason = review_note
            next_status = "rejected" if decision == "reject" else "drafting"
            task.status = next_status
            task.set_metadata(sanitize_obj(_metadata_with_status_history(
                task,
                status=next_status,
                changed_by=reviewer_name,
                note=review_note,
            )))
            db.commit()
            return sanitize_obj({"task": task.to_dict(), "draft": draft.to_dict(), "queue_item": None})

        content = draft.get_draft_content()
        draft_type = sanitize_text(content.get("draft_type") or draft.draft_type)
        publish_target = sanitize_text(content.get("business_publish_target") or content.get("target_system"))
        if publish_target not in PUBLISHABLE_TARGETS:
            raise ValueError("draft target is not publishable")
        readiness = sanitize_text(content.get("publish_readiness"))
        verified_payload = payload.get("verified_payload")
        if readiness != "ready_for_review":
            if not isinstance(verified_payload, dict) or not verified_payload:
                raise ValueError("verified_payload is required for this draft readiness")
            if "review_checklist" not in verified_payload and isinstance(payload.get("review_checklist"), dict):
                verified_payload = {**verified_payload, "review_checklist": payload.get("review_checklist")}
            _validate_verified_payload(draft_type, verified_payload)
        elif isinstance(verified_payload, dict) and verified_payload:
            if "review_checklist" not in verified_payload and isinstance(payload.get("review_checklist"), dict):
                verified_payload = {**verified_payload, "review_checklist": payload.get("review_checklist")}
            _validate_verified_payload(draft_type, verified_payload)
        if isinstance(verified_payload, dict) and verified_payload:
            payload = {**payload, "verified_payload": verified_payload}

        existing = (
            db.query(KnowledgeGapPublishQueue)
            .filter(
                KnowledgeGapPublishQueue.task_uid == task.task_uid,
                KnowledgeGapPublishQueue.draft_uid == draft.draft_uid,
                KnowledgeGapPublishQueue.status.in_(["queued", "exported"]),
            )
            .order_by(KnowledgeGapPublishQueue.id.asc())
            .first()
        )
        if existing is not None:
            draft.review_status = "approved_for_queue"
            task.status = "queued_for_publish"
            db.commit()
            return sanitize_obj({"task": task.to_dict(), "draft": draft.to_dict(), "queue_item": existing.to_dict()})

        metadata = task.get_metadata()
        queue_item = KnowledgeGapPublishQueue(
            queue_uid=_new_queue_uid(),
            task_uid=task.task_uid,
            draft_uid=draft.draft_uid,
            source_run_uid=sanitize_text(metadata.get("source_run_uid")),
            publish_target=publish_target,
            reviewer=reviewer_name,
            review_note=review_note,
            risk_level=sanitize_text(task.risk_level) or "medium",
            status="queued",
            export_status="not_exported",
        )
        queue_item.set_payload(_queue_payload_from_review(content, payload))
        queue_item.set_readiness_snapshot(_readiness_snapshot(content, payload))
        queue_item.set_metadata({
            "decision": decision,
            "draft_type": draft_type,
            "verified_payload_provided": isinstance(verified_payload, dict) and bool(verified_payload),
        })
        db.add(queue_item)

        draft.review_status = "approved_for_queue"
        draft.reviewer = reviewer_name
        draft.reviewed_at = datetime.utcnow()
        task.status = "queued_for_publish"
        task.set_metadata(sanitize_obj(_metadata_with_status_history(
            task,
            status="queued_for_publish",
            changed_by=reviewer_name,
            note=review_note,
        )))
        db.commit()
        return sanitize_obj({"task": task.to_dict(), "draft": draft.to_dict(), "queue_item": queue_item.to_dict()})

    def list_queue(self, db, *, filters: dict[str, str] | None = None, limit: int = 100) -> dict[str, Any]:
        from app.models.eval_tables import KnowledgeGapPublishQueue

        filters = filters or {}
        query = db.query(KnowledgeGapPublishQueue).order_by(
            KnowledgeGapPublishQueue.created_at.desc(),
            KnowledgeGapPublishQueue.id.desc(),
        )
        for attr in ["status", "publish_target", "risk_level", "reviewer", "task_uid"]:
            value = sanitize_text(filters.get(attr))
            if value:
                query = query.filter(getattr(KnowledgeGapPublishQueue, attr) == value)
        rows = query.limit(max(1, min(int(limit or 100), 500))).all()
        return sanitize_obj({
            "items": [row.to_dict() for row in rows],
            "summary": {
                "total": len(rows),
                "by_status": self._count(rows, "status"),
                "by_publish_target": self._count(rows, "publish_target"),
                "by_export_status": self._count(rows, "export_status"),
            },
        })

    def export_preview(self, db, queue_uid: str) -> dict[str, Any] | None:
        from app.models.eval_tables import KnowledgeGapPublishQueue

        item = db.query(KnowledgeGapPublishQueue).filter(KnowledgeGapPublishQueue.queue_uid == sanitize_text(queue_uid)).one_or_none()
        if item is None:
            return None
        return sanitize_obj({
            "queue_item": item.to_dict(),
            "payload_preview": item.get_payload(),
            "dry_run": True,
            "writes_formal_tables": False,
        })

    def update_queue_item(self, db, queue_uid: str, payload: dict[str, Any], *, operator: str = "") -> dict[str, Any] | None:
        from app.models.eval_tables import KnowledgeGapPublishQueue

        item = db.query(KnowledgeGapPublishQueue).filter(KnowledgeGapPublishQueue.queue_uid == sanitize_text(queue_uid)).one_or_none()
        if item is None:
            return None
        status = sanitize_text(payload.get("status"))
        if status == "published":
            raise ValueError("formal publish is not supported by this queue")
        if status not in QUEUE_STATUSES:
            raise ValueError("invalid publish queue status")
        item.status = status
        metadata = item.get_metadata()
        metadata.setdefault("status_history", [])
        metadata["status_history"].append(sanitize_obj({
            "status": status,
            "operator": sanitize_text(payload.get("operator") or operator),
            "note": sanitize_text(payload.get("note")),
            "changed_at": datetime.utcnow().isoformat(),
        }))
        item.set_metadata(metadata)
        if status == "exported":
            item.export_status = "exported"
            item.exported_at = datetime.utcnow()
        db.commit()
        return sanitize_obj(item.to_dict())

    @staticmethod
    def _count(rows, attr: str) -> dict[str, int]:
        result: dict[str, int] = {}
        for row in rows:
            value = sanitize_text(getattr(row, attr, "")) or "unknown"
            result[value] = result.get(value, 0) + 1
        return result
