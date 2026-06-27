"""Generate review-only staging drafts for knowledge gap tasks."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from app.services.eval_sanitizer_service import sanitize_obj, sanitize_text


FACT_DRAFT_TYPES = {
    "product_fact_gap": "product_field_draft",
    "product_field_gap": "product_field_draft",
    "media_asset_gap": "media_asset_request",
    "activity_rule_gap": "promotion_policy_draft",
    "promotion_policy_gap": "promotion_policy_draft",
    "service_rule_gap": "aftersales_policy_draft",
    "aftersales_policy_gap": "aftersales_policy_draft",
    "human_policy_gap": "aftersales_policy_draft",
    "context_extraction_gap": "context_extraction_issue",
    "evidence_routing_gap": "context_extraction_issue",
    "agent_logic_gap": "context_extraction_issue",
}

REVIEW_DECISION_DRAFT_TYPES = {
    "fill_product_field": "product_field_draft",
    "upload_media_asset": "media_asset_request",
    "write_aftersales_policy": "aftersales_policy_draft",
    "write_promotion_policy": "promotion_policy_draft",
    "fix_context_extraction": "context_extraction_issue",
    "improve_evidence_mapping": "context_extraction_issue",
}
POLICY_DRAFT_TYPES = {"policy_rule_draft", "aftersales_policy_draft", "promotion_policy_draft"}


def _new_draft_uid() -> str:
    return f"kgdraft_{uuid.uuid4().hex[:12]}"


def _draft_type_for(task) -> str:
    metadata = task.get_metadata()
    review_decision = sanitize_text(metadata.get("review_decision"))
    if review_decision == "ignore_false_positive":
        raise ValueError("ignored knowledge gap tasks do not need staging drafts")
    return REVIEW_DECISION_DRAFT_TYPES.get(
        review_decision,
        FACT_DRAFT_TYPES.get(sanitize_text(task.gap_type), "context_extraction_issue"),
    )


def _safe_sample_list(samples) -> list[dict[str, str]]:
    result = []
    for sample in samples[:5]:
        result.append({
            "turn_uid": sanitize_text(sample.turn_uid),
            "buyer_message": sanitize_text(sample.buyer_message),
            "agent_reply": sanitize_text(sample.agent_reply),
            "reference_human_reply": sanitize_text(sample.reference_human_reply),
        })
    return result


def _required_evidence_type(task) -> str:
    metadata = task.get_metadata()
    return sanitize_text(metadata.get("required_evidence_type") or task.missing_evidence_type)


def _target_system(task) -> str:
    metadata = task.get_metadata()
    return sanitize_text(metadata.get("target_system") or "")


def _has_verified_evidence(task) -> bool:
    metadata = task.get_metadata()
    if metadata.get("verified_evidence") or metadata.get("verified_evidence_items"):
        return True
    return sanitize_text(metadata.get("evidence_status")).lower() == "verified"


def _product_identity(task) -> dict[str, str]:
    return sanitize_obj({
        "product_title": sanitize_text(task.product_title),
        "item_id_masked": _mask_identifier(sanitize_text(task.item_id)),
        "sku_code": sanitize_text(task.sku_code),
    })


def _mask_identifier(value: str) -> str:
    text = sanitize_text(value)
    if len(text) <= 4:
        return text
    return f"{text[:2]}***{text[-2:]}"


def _representative_questions(samples) -> list[str]:
    return [sanitize_text(sample.buyer_message) for sample in samples[:5] if sanitize_text(sample.buyer_message)]


def _business_publish_target(draft_type: str) -> str:
    if draft_type == "product_field_draft":
        return "product_profile"
    if draft_type == "media_asset_request":
        return "kb_media_asset"
    if draft_type == "aftersales_policy_draft":
        return "aftersales_policy"
    if draft_type == "promotion_policy_draft":
        return "activity_rules"
    return "context_extractor_issue"


def _publish_readiness(task, draft_type: str) -> str:
    if draft_type == "product_field_draft":
        return "ready_for_review" if _has_verified_evidence(task) else "needs_data"
    if draft_type == "media_asset_request":
        return "needs_media_upload"
    if draft_type in POLICY_DRAFT_TYPES:
        return "needs_policy_confirmation"
    return "blocked"


def _requested_field_schema(task) -> list[dict[str, str]]:
    metadata = task.get_metadata()
    fields = metadata.get("missing_fields") or [task.query_fact_type or task.missing_evidence_type]
    result = []
    for field in fields:
        name = sanitize_text(field)
        if not name:
            continue
        result.append({
            "field_name": name,
            "value": "",
            "source": "",
            "applies_to_all_skus": "",
        })
    return result


def _media_asset_type(task) -> str:
    required = _required_evidence_type(task)
    if "video" in required:
        return "video"
    if "image" in required or "photo" in required:
        return "image"
    return required or "approved_media_asset"


def _publish_payload(task, draft_type: str, samples) -> dict[str, Any]:
    metadata = task.get_metadata()
    representative_questions = _representative_questions(samples)
    product_identity = _product_identity(task)
    required_evidence_type = _required_evidence_type(task)
    if draft_type == "product_field_draft":
        return sanitize_obj({
            "product_identity": product_identity,
            "missing_fields": metadata.get("missing_fields") or [],
            "requested_field_schema": _requested_field_schema(task),
            "representative_questions": representative_questions,
            "source_task_uid": task.task_uid,
        })
    if draft_type == "media_asset_request":
        return sanitize_obj({
            "asset_type": _media_asset_type(task),
            "media_purpose": sanitize_text(task.query_fact_type) or required_evidence_type,
            "answer_scenarios": representative_questions,
            "product_identity": product_identity,
            "bind_to_sku": sanitize_text(task.sku_code),
            "bind_to_item_id_masked": _mask_identifier(sanitize_text(task.item_id)),
            "required_status": "approved",
            "required_usable": True,
            "source_task_uid": task.task_uid,
        })
    if draft_type == "aftersales_policy_draft":
        return sanitize_obj({
            "scenario": sanitize_text(task.query_fact_type) or "aftersales_policy",
            "policy_question": representative_questions[:3],
            "suggested_customer_action": "",
            "required_boundary_review": True,
            "source_samples": _safe_sample_list(samples),
            "source_task_uid": task.task_uid,
        })
    if draft_type == "promotion_policy_draft":
        return sanitize_obj({
            "promotion_question": representative_questions[:3],
            "platform": "",
            "product_scope": "",
            "time_scope": "",
            "refund_after_participation_rule": "",
            "required_boundary_review": True,
            "source_task_uid": task.task_uid,
        })
    return sanitize_obj({
        "missing_context_fields": metadata.get("missing_fields") or [task.missing_evidence_type],
        "source_page": (metadata.get("current_context_summary") or {}).get("source_page", ""),
        "extractor_component": metadata.get("target_system") or "context_extractor",
        "representative_samples": _safe_sample_list(samples),
        "suggested_engineering_action": metadata.get("recommended_action") or "fix_context_extraction",
        "source_task_uid": task.task_uid,
    })


def _reviewer_checklist(task, draft_type: str) -> list[str]:
    if draft_type == "product_field_draft":
        return [
            "Confirm product and SKU scope",
            "Fill the missing field value from verified evidence",
            "Record the evidence source",
            "Confirm whether the value applies to all SKUs",
        ]
    if draft_type == "media_asset_request":
        return [
            "Upload an approved usable asset",
            "Confirm asset type and applicable product/SKU",
            "Confirm the asset can be sent to customers",
            "Do not use temporary chat URLs as formal assets",
        ]
    if draft_type == "aftersales_policy_draft":
        return [
            "Confirm whether photos are required",
            "Confirm whether order information is required",
            "Confirm platform scope",
            "Confirm refund, reshipment, or compensation boundaries",
        ]
    if draft_type == "promotion_policy_draft":
        return [
            "Confirm platform and activity time scope",
            "Confirm applicable product scope",
            "Confirm refund-after-participation boundary",
            "Do not invent benefit amount or promotion rule",
        ]
    return [
        "Confirm missing context fields",
        "Assign to data or engineering owner",
        "Confirm extractor component and source page",
    ]


def _suggested_content(task, draft_type: str) -> str:
    fact_type = sanitize_text(task.query_fact_type) or "对应问题"
    required_evidence_type = _required_evidence_type(task)
    if draft_type == "media_asset_request":
        return (
            f"请上传并审核 {required_evidence_type or 'approved media asset'}，标注适用商品、SKU、版本和可发送范围。"
            "未审核前不能承诺可直接发送，不生成临时视频链接。"
        )
    if draft_type in POLICY_DRAFT_TYPES:
        return (
            f"请补充 {required_evidence_type or fact_type} 的待审规则草稿，包含触发条件、客户需提供的信息、"
            "处理边界和人工复核条件。不得编造承诺。"
        )
    if draft_type == "product_field_draft":
        return (
            f"请补充商品 {fact_type} 的可核验证据，例如商品资料、规格表、检测资料或页面截图。"
            "没有 verified evidence 前禁止发布。"
        )
    return "请修复真实回放上下文抽取或证据映射，补齐商品、SKU、item_id、订单或媒体上下文字段。"


def _uncertain_items(task, draft_type: str) -> list[str]:
    items = [
        "当前草稿来自失败样本归因，不代表已核验事实。",
        "发布前需要人工确认证据来源、适用商品范围和风险边界。",
        "不得把原客服回复直接当作事实证据。",
    ]
    if sanitize_text(task.risk_level) == "high":
        items.append("高风险问题不得生成绝对安全、绝对有效或确定赔付承诺。")
    if draft_type == "media_asset_request":
        items.append("素材必须确认可发送、链接有效、款式对应，不能使用聊天历史里的临时 URL 作为正式素材。")
    return items


def _publish_blocked_reason(draft_type: str) -> str:
    if draft_type == "product_field_draft":
        return "product field drafts require verified evidence before publishing"
    if draft_type == "media_asset_request":
        return "media assets must be uploaded and approved before use"
    if draft_type in POLICY_DRAFT_TYPES:
        return "policy drafts require supervisor review before publishing"
    return "context or evidence mapping issues require engineering review"


class KnowledgeGapDraftService:
    def generate_draft(
        self,
        db,
        task_uid: str,
        *,
        generated_by: str = "ai",
        force_regenerate: bool = False,
    ) -> dict[str, Any] | None:
        from app.models.eval_tables import KnowledgeGapDraft, KnowledgeGapTask, KnowledgeGapTaskSample

        task = db.query(KnowledgeGapTask).filter(KnowledgeGapTask.task_uid == sanitize_text(task_uid)).one_or_none()
        if task is None:
            return None
        if not force_regenerate:
            existing = (
                db.query(KnowledgeGapDraft)
                .filter(KnowledgeGapDraft.task_uid == task.task_uid)
                .order_by(KnowledgeGapDraft.created_at.desc(), KnowledgeGapDraft.id.desc())
                .first()
            )
            if existing is not None:
                return sanitize_obj(existing.to_dict())
        samples = (
            db.query(KnowledgeGapTaskSample)
            .filter(KnowledgeGapTaskSample.task_uid == task.task_uid)
            .order_by(KnowledgeGapTaskSample.id.asc())
            .all()
        )
        draft_type = _draft_type_for(task)
        metadata = task.get_metadata()
        suggested_content = _suggested_content(task, draft_type)
        publish_readiness = _publish_readiness(task, draft_type)
        business_publish_target = _business_publish_target(draft_type)
        publish_blocked_reason = "" if publish_readiness == "ready_for_review" else _publish_blocked_reason(draft_type)
        content = sanitize_obj({
            "task_uid": task.task_uid,
            "gap_type": task.gap_type,
            "gap_category": metadata.get("gap_category") or task.gap_type,
            "query_fact_type": task.query_fact_type,
            "draft_type": draft_type,
            "proposed_title": f"{task.gap_type}: {task.query_fact_type or task.missing_evidence_type}",
            "proposed_answer": "" if draft_type == "media_asset_request" else suggested_content,
            "proposed_rule": suggested_content if draft_type in POLICY_DRAFT_TYPES else "",
            "required_review_fields": metadata.get("missing_fields") or [],
            "publish_readiness": publish_readiness,
            "business_publish_target": business_publish_target,
            "target_system": business_publish_target,
            "publish_payload": _publish_payload(task, draft_type, samples),
            "evidence_requirements": {
                "required_evidence_type": _required_evidence_type(task),
                "target_system": _target_system(task),
                "verified_evidence_required": draft_type == "product_field_draft",
                "has_verified_evidence": _has_verified_evidence(task),
            },
            "source_sample_uids": task.get_related_turn_uids(),
            "risk_level": task.risk_level,
            "publish_blocked_reason": publish_blocked_reason,
            "source_samples": _safe_sample_list(samples),
            "suggested_content": suggested_content,
            "uncertain_items": _uncertain_items(task, draft_type),
            "reviewer_checklist": _reviewer_checklist(task, draft_type),
            "required_review": [
                "客服或主管确认内容是否真实",
                "确认是否需要补图、视频、说明书、检测报告或规则来源",
                "确认发布目标仍为 staging，不能直接进入正式知识库",
            ],
            "prohibited_claims": [
                "不得写 0 风险、绝对安全、完全无害",
                "不得承诺未审核素材可直接发送",
                "不得把原客服回复当作事实证据",
            ],
        })

        draft = KnowledgeGapDraft(
            draft_uid=_new_draft_uid(),
            task_uid=task.task_uid,
            draft_type=draft_type,
            generated_by=sanitize_text(generated_by) or "ai",
            review_status="pending_review",
            publish_target="staging",
        )
        draft.set_draft_content(content)
        db.add(draft)
        from app.services.knowledge_gap_task_service import _metadata_with_status_history

        task.status = "draft_ready"
        task.set_metadata(sanitize_obj(_metadata_with_status_history(
            task,
            status="draft_ready",
            changed_by=sanitize_text(generated_by) or "ai",
            note="staging draft generated",
        )))
        db.commit()
        return sanitize_obj(draft.to_dict())

    def mark_ready(self, db, task_uid: str, *, reviewer: str = "") -> dict[str, Any] | None:
        from app.models.eval_tables import KnowledgeGapDraft, KnowledgeGapTask

        task = db.query(KnowledgeGapTask).filter(KnowledgeGapTask.task_uid == sanitize_text(task_uid)).one_or_none()
        if task is None:
            return None
        draft = (
            db.query(KnowledgeGapDraft)
            .filter(KnowledgeGapDraft.task_uid == task.task_uid)
            .order_by(KnowledgeGapDraft.created_at.desc(), KnowledgeGapDraft.id.desc())
            .first()
        )
        if draft is None:
            raise ValueError("knowledge gap draft not found")
        content = draft.get_draft_content()
        if sanitize_text(content.get("publish_readiness")) != "ready_for_review":
            raise ValueError("draft is not ready for review")
        draft.review_status = "ready_for_review"
        draft.reviewer = sanitize_text(reviewer)
        draft.reviewed_at = datetime.utcnow()
        task.status = "pending_review"
        db.commit()
        return sanitize_obj({"task": task.to_dict(), "draft": draft.to_dict()})

    def approve(self, db, task_uid: str, *, reviewer: str = "") -> dict[str, Any] | None:
        from app.models.eval_tables import KnowledgeGapDraft, KnowledgeGapTask

        task = db.query(KnowledgeGapTask).filter(KnowledgeGapTask.task_uid == sanitize_text(task_uid)).one_or_none()
        if task is None:
            return None
        drafts = (
            db.query(KnowledgeGapDraft)
            .filter(KnowledgeGapDraft.task_uid == task.task_uid, KnowledgeGapDraft.review_status == "pending_review")
            .all()
        )
        now = datetime.utcnow()
        for draft in drafts:
            draft.review_status = "approved"
            draft.reviewer = sanitize_text(reviewer)
            draft.reviewed_at = now
            draft.publish_target = "staging"
        task.status = "approved"
        db.commit()
        return sanitize_obj({"task": task.to_dict(), "drafts": [draft.to_dict() for draft in drafts]})

    def reject(self, db, task_uid: str, *, reviewer: str = "", reason: str = "") -> dict[str, Any] | None:
        from app.models.eval_tables import KnowledgeGapDraft, KnowledgeGapTask

        task = db.query(KnowledgeGapTask).filter(KnowledgeGapTask.task_uid == sanitize_text(task_uid)).one_or_none()
        if task is None:
            return None
        drafts = (
            db.query(KnowledgeGapDraft)
            .filter(KnowledgeGapDraft.task_uid == task.task_uid, KnowledgeGapDraft.review_status == "pending_review")
            .all()
        )
        now = datetime.utcnow()
        for draft in drafts:
            draft.review_status = "rejected"
            draft.reviewer = sanitize_text(reviewer)
            draft.reviewed_at = now
            draft.rejection_reason = sanitize_text(reason)
        task.status = "rejected"
        db.commit()
        return sanitize_obj({"task": task.to_dict(), "drafts": [draft.to_dict() for draft in drafts]})
