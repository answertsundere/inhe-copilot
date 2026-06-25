"""Generate review-only drafts for knowledge gap tasks."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from app.services.eval_sanitizer_service import sanitize_obj, sanitize_text


FACT_DRAFT_TYPES = {
    "product_fact_gap": "product_fact",
    "media_asset_gap": "media_request",
    "activity_rule_gap": "activity_rule",
    "service_rule_gap": "service_rule",
    "human_policy_gap": "service_rule",
    "agent_logic_gap": "faq",
}


def _new_draft_uid() -> str:
    return f"kgdraft_{uuid.uuid4().hex[:12]}"


def _draft_type_for(task) -> str:
    return FACT_DRAFT_TYPES.get(sanitize_text(task.gap_type), "faq")


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


def _suggested_content(task, draft_type: str) -> str:
    fact_type = sanitize_text(task.query_fact_type) or "对应问题"
    if draft_type == "media_request":
        return (
            f"需要补充 {task.media_needed_type or '对应图片/视频/说明书'}，并标注适用商品、SKU、版本、"
            "审核状态和可发送范围。未审核前不能承诺可直接发送。"
        )
    if draft_type == "activity_rule":
        return "需要补充活动/福利规则，包括适用商品、活动时间、参与条件、退款/退货后的处理口径。"
    if draft_type == "service_rule":
        return "需要补充售后或服务规则，包括触发条件、需要客户提供的信息、处理边界和人工复核条件。"
    if draft_type == "product_fact":
        return f"需要补充商品 {fact_type} 的可核验证据，例如商品资料、规格表、检测资料或页面截图。"
    return f"需要补充高频问法对应的 FAQ 草稿，并关联 {fact_type} 的证据来源。"


def _uncertain_items(task, draft_type: str) -> list[str]:
    items = [
        "当前草稿来自失败样本归因，不代表已核验事实。",
        "发布前需要人工确认证据来源、适用商品范围和风险边界。",
    ]
    if sanitize_text(task.risk_level) == "high":
        items.append("高风险问题不得生成绝对安全、绝对有效或确定赔付承诺。")
    if draft_type == "media_request":
        items.append("素材必须确认可发送、链接有效、款式对应，不能使用聊天历史里的临时 URL 作为正式素材。")
    return items


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
        content = sanitize_obj({
            "task_uid": task.task_uid,
            "gap_type": task.gap_type,
            "query_fact_type": task.query_fact_type,
            "draft_type": draft_type,
            "source_samples": _safe_sample_list(samples),
            "suggested_content": _suggested_content(task, draft_type),
            "uncertain_items": _uncertain_items(task, draft_type),
            "required_review": [
                "客服/主管确认内容是否真实",
                "确认是否需要补图、视频、说明书或检测报告",
                "确认发布目标仅为 staging，不能直接进入正式知识库",
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
