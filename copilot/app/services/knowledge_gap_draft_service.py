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
    "activity_rule_gap": "policy_rule_draft",
    "promotion_policy_gap": "policy_rule_draft",
    "service_rule_gap": "policy_rule_draft",
    "aftersales_policy_gap": "policy_rule_draft",
    "human_policy_gap": "policy_rule_draft",
    "context_extraction_gap": "context_extraction_issue",
    "evidence_routing_gap": "context_extraction_issue",
    "agent_logic_gap": "context_extraction_issue",
}


def _new_draft_uid() -> str:
    return f"kgdraft_{uuid.uuid4().hex[:12]}"


def _draft_type_for(task) -> str:
    return FACT_DRAFT_TYPES.get(sanitize_text(task.gap_type), "context_extraction_issue")


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


def _suggested_content(task, draft_type: str) -> str:
    fact_type = sanitize_text(task.query_fact_type) or "对应问题"
    required_evidence_type = _required_evidence_type(task)
    if draft_type == "media_asset_request":
        return (
            f"请上传并审核 {required_evidence_type or 'approved media asset'}，标注适用商品、SKU、版本和可发送范围。"
            "未审核前不能承诺可直接发送，不生成临时视频链接。"
        )
    if draft_type == "policy_rule_draft":
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
    if draft_type == "policy_rule_draft":
        return "policy drafts require supervisor review before publishing"
    return "context or evidence mapping issues require engineering review"


class KnowledgeGapDraftService:
    def generate_draft(self, db, task_uid: str, *, generated_by: str = "ai") -> dict[str, Any] | None:
        from app.models.eval_tables import KnowledgeGapDraft, KnowledgeGapTask, KnowledgeGapTaskSample

        task = db.query(KnowledgeGapTask).filter(KnowledgeGapTask.task_uid == sanitize_text(task_uid)).one_or_none()
        if task is None:
            return None
        samples = (
            db.query(KnowledgeGapTaskSample)
            .filter(KnowledgeGapTaskSample.task_uid == task.task_uid)
            .order_by(KnowledgeGapTaskSample.id.asc())
            .all()
        )
        draft_type = _draft_type_for(task)
        metadata = task.get_metadata()
        suggested_content = _suggested_content(task, draft_type)
        content = sanitize_obj({
            "task_uid": task.task_uid,
            "gap_type": task.gap_type,
            "gap_category": metadata.get("gap_category") or task.gap_type,
            "query_fact_type": task.query_fact_type,
            "draft_type": draft_type,
            "proposed_title": f"{task.gap_type}: {task.query_fact_type or task.missing_evidence_type}",
            "proposed_answer": "" if draft_type == "media_asset_request" else suggested_content,
            "proposed_rule": suggested_content if draft_type == "policy_rule_draft" else "",
            "required_review_fields": metadata.get("missing_fields") or [],
            "evidence_requirements": {
                "required_evidence_type": _required_evidence_type(task),
                "target_system": _target_system(task),
            },
            "source_sample_uids": task.get_related_turn_uids(),
            "risk_level": task.risk_level,
            "publish_blocked_reason": _publish_blocked_reason(draft_type),
            "source_samples": _safe_sample_list(samples),
            "suggested_content": suggested_content,
            "uncertain_items": _uncertain_items(task, draft_type),
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
        task.status = "drafting"
        db.commit()
        return sanitize_obj(draft.to_dict())

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
