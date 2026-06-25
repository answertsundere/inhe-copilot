"""Aggregate real replay failures into knowledge/media gap tasks."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from app.services.eval_sanitizer_service import sanitize_obj, sanitize_text


MEDIA_FACT_TYPES = {"installation", "visual_asset", "media_reference", "dimensions", "space_fit", "detachable"}
PROMOTION_FACT_TYPES = {"promotion", "promotion_policy", "activity_rule", "coupon", "discount", "gift_policy"}
SERVICE_FACT_TYPES = {"aftersales", "aftersales_policy", "after_sales", "stock_shipping", "delivery_not_received"}
HIGH_RISK_FACT_TYPES = {"certification_report", "pinch_safety", "safety_small_parts", "material", "aftersales_policy"}
HIGH_RISK_FAILURES = {"unsafe_claim", "unsupported_media_claim", "tool_policy_blocked"}


@dataclass
class KnowledgeGapGenerationResult:
    run_uid: str
    generated: int
    updated: int
    skipped_correct: int
    tasks: list[dict[str, Any]]

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_uid": self.run_uid,
            "generated": self.generated,
            "updated": self.updated,
            "skipped_correct": self.skipped_correct,
            "tasks": self.tasks,
        }


def _new_task_uid() -> str:
    return f"kgap_{uuid.uuid4().hex[:12]}"


def _latest_run_uid(db) -> str:
    from app.models.eval_tables import EvalRun

    run = (
        db.query(EvalRun)
        .filter(EvalRun.source_type == "real_conversation")
        .order_by(EvalRun.created_at.desc(), EvalRun.id.desc())
        .first()
    )
    return run.run_uid if run else ""


def _latest_reviews_by_turn(reviews) -> dict[str, Any]:
    latest: dict[str, Any] = {}
    for review in reviews:
        latest[review.turn_uid] = review
    return latest


def _unique(values: list[str], limit: int | None = None) -> list[str]:
    result: list[str] = []
    seen = set()
    for raw in values:
        value = sanitize_text(raw)
        if value and value not in seen:
            seen.add(value)
            result.append(value)
        if limit and len(result) >= limit:
            break
    return result


def _trace_identity(trace) -> dict[str, str]:
    identity = trace.get_product_identity() if trace else {}
    if not isinstance(identity, dict):
        identity = {}
    return {
        "product_title": sanitize_text(
            identity.get("display_product_name")
            or identity.get("product_title")
            or identity.get("order_product_title")
            or identity.get("title")
            or ""
        ),
        "item_id": sanitize_text(identity.get("item_id") or identity.get("i_id") or ""),
        "sku_code": sanitize_text(identity.get("sku_code") or identity.get("sku_id") or ""),
    }


def _query_fact_type(failure, trace) -> str:
    if trace and sanitize_text(trace.query_fact_type):
        return sanitize_text(trace.query_fact_type)
    metadata = failure.get_metadata() if failure else {}
    return sanitize_text(metadata.get("query_fact_type") or metadata.get("fact_type") or "")


def _gap_type_for(failure_type: str, query_fact_type: str, fix_area: str) -> str:
    if failure_type == "unsupported_media_claim" or fix_area == "media_pipeline":
        return "media_asset_gap"
    if query_fact_type in PROMOTION_FACT_TYPES or fix_area in {"activity_rules", "promotion_ops"}:
        return "activity_rule_gap"
    if query_fact_type in SERVICE_FACT_TYPES or fix_area in {"service_rules", "aftersales_policy"}:
        return "service_rule_gap"
    if failure_type in {"rag_miss", "query_fact_type_missing"}:
        return "product_fact_gap"
    if failure_type in {"needs_human_review", "context_insufficient"} or fix_area == "human_policy_risk_boundary":
        return "human_policy_gap"
    if failure_type in {"semantic_mismatch", "wrong_topic_reply", "intent_contract_mismatch"}:
        return "agent_logic_gap"
    return "product_fact_gap"


def _missing_evidence_type(gap_type: str, query_fact_type: str) -> str:
    if gap_type == "media_asset_gap":
        if query_fact_type == "dimensions":
            return "image_or_dimension_chart"
        if query_fact_type == "installation":
            return "installation_video_or_manual"
        return "approved_media_asset"
    if gap_type == "activity_rule_gap":
        return "activity_or_benefit_rule"
    if gap_type == "service_rule_gap":
        return "service_or_aftersales_rule"
    if gap_type == "human_policy_gap":
        return "human_review_policy"
    if gap_type == "agent_logic_gap":
        return "agent_contract_or_audit_rule"
    return f"{query_fact_type or 'product'}_fact"


def _media_needed_type(gap_type: str, query_fact_type: str) -> str:
    if gap_type != "media_asset_gap":
        return ""
    if query_fact_type == "installation":
        return "video_or_manual"
    if query_fact_type in {"dimensions", "space_fit"}:
        return "image"
    return "approved_media"


def _risk_level(failure_type: str, query_fact_type: str, severities: list[str]) -> str:
    if "high" in severities or failure_type in HIGH_RISK_FAILURES or query_fact_type in HIGH_RISK_FACT_TYPES:
        return "high"
    if "low" in severities and len(set(severities)) == 1:
        return "low"
    return "medium"


def _priority(risk_level: str, sample_count: int) -> str:
    if risk_level == "high" or sample_count >= 5:
        return "high"
    if sample_count <= 1:
        return "low"
    return "medium"


def _summary(gap_type: str, query_fact_type: str, sample_count: int) -> str:
    readable_fact = query_fact_type or "unknown_fact"
    return sanitize_text(f"{sample_count} real replay sample(s) need {gap_type} for {readable_fact}.")


class KnowledgeGapTaskService:
    """Create and manage knowledge gap tasks from replay failures."""

    def generate_for_run(self, db, run_uid: str | None = None, created_by: str = "") -> KnowledgeGapGenerationResult:
        from app.models.eval_tables import (
            EvalFailure,
            EvalReview,
            EvalTrace,
            KnowledgeGapTask,
            KnowledgeGapTaskSample,
        )

        target_run_uid = sanitize_text(run_uid) or _latest_run_uid(db)
        if not target_run_uid:
            return KnowledgeGapGenerationResult("", 0, 0, 0, [])

        failures = (
            db.query(EvalFailure)
            .filter(EvalFailure.run_uid == target_run_uid)
            .order_by(EvalFailure.id.asc())
            .all()
        )
        traces = {
            trace.turn_uid: trace
            for trace in db.query(EvalTrace).filter(EvalTrace.run_uid == target_run_uid).all()
        }
        reviews = (
            db.query(EvalReview)
            .filter(EvalReview.run_uid == target_run_uid)
            .order_by(EvalReview.id.asc())
            .all()
        )
        latest_reviews = _latest_reviews_by_turn(reviews)
        correct_turns = {
            turn_uid
            for turn_uid, review in latest_reviews.items()
            if sanitize_text(review.decision) == "correct"
        }

        grouped: dict[tuple[str, str, str, str, str, str, str, str], dict[str, Any]] = {}
        skipped_correct = 0
        for failure in failures:
            if failure.turn_uid in correct_turns:
                skipped_correct += 1
                continue
            trace = traces.get(failure.turn_uid)
            query_fact_type = _query_fact_type(failure, trace)
            fix_area = sanitize_text(failure.suggested_fix_area) or "manual_triage"
            owner = sanitize_text(failure.suggested_owner) or "knowledge_ops"
            failure_type = sanitize_text(failure.failure_type) or "manual_review"
            gap_type = _gap_type_for(failure_type, query_fact_type, fix_area)
            identity = _trace_identity(trace)
            key = (
                gap_type,
                identity["item_id"],
                identity["sku_code"],
                identity["product_title"],
                query_fact_type,
                failure_type,
                fix_area,
                owner,
            )
            item = grouped.setdefault(key, {
                "identity": identity,
                "query_fact_type": query_fact_type,
                "failure_type": failure_type,
                "fix_area": fix_area,
                "owner": owner,
                "gap_type": gap_type,
                "case_uids": [],
                "turn_uids": [],
                "buyer_questions": [],
                "agent_replies": [],
                "reference_replies": [],
                "severities": [],
                "samples": [],
            })
            item["case_uids"].append(failure.case_uid)
            item["turn_uids"].append(failure.turn_uid)
            item["severities"].append(sanitize_text(failure.severity) or "medium")
            if trace:
                item["buyer_questions"].append(trace.buyer_message)
                item["agent_replies"].append(trace.agent_reply)
                item["reference_replies"].append(trace.reference_human_reply)
                item["samples"].append({
                    "run_uid": trace.run_uid,
                    "case_uid": trace.case_uid,
                    "turn_uid": trace.turn_uid,
                    "buyer_message": trace.buyer_message,
                    "agent_reply": trace.agent_reply,
                    "reference_human_reply": trace.reference_human_reply,
                    "failure_type": failure_type,
                    "query_fact_type": query_fact_type,
                    "trace_summary": {
                        "required_fact_types": trace.get_required_fact_types(),
                        "selected_evidence_count": len(trace.get_selected_evidence()),
                        "rejected_evidence_count": len(trace.get_rejected_evidence()),
                        "requires_human_review": bool(trace.requires_human_review),
                        "failure_message": failure.message or failure.explanation,
                    },
                })

        generated = 0
        updated = 0
        tasks = []
        for key, item in grouped.items():
            gap_type, item_id, sku_code, product_title, query_fact_type, failure_type, fix_area, owner = key
            task = (
                db.query(KnowledgeGapTask)
                .filter(
                    KnowledgeGapTask.gap_type == gap_type,
                    KnowledgeGapTask.item_id == item_id,
                    KnowledgeGapTask.sku_code == sku_code,
                    KnowledgeGapTask.product_title == product_title,
                    KnowledgeGapTask.query_fact_type == query_fact_type,
                    KnowledgeGapTask.failure_type == failure_type,
                    KnowledgeGapTask.suggested_fix_area == fix_area,
                    KnowledgeGapTask.suggested_owner == owner,
                    KnowledgeGapTask.status.in_(["open", "drafting", "pending_review", "approved", "rejected"]),
                )
                .order_by(KnowledgeGapTask.id.asc())
                .first()
            )
            if task is None:
                task = KnowledgeGapTask(task_uid=_new_task_uid())
                generated += 1
                db.add(task)
            else:
                updated += 1

            case_uids = _unique(item["case_uids"])
            turn_uids = _unique(item["turn_uids"])
            risk_level = _risk_level(failure_type, query_fact_type, item["severities"])
            task.gap_type = gap_type
            task.product_title = product_title
            task.item_id = item_id
            task.sku_code = sku_code
            task.query_fact_type = query_fact_type
            task.failure_type = failure_type
            task.suggested_fix_area = fix_area
            task.suggested_owner = owner
            task.missing_evidence_type = _missing_evidence_type(gap_type, query_fact_type)
            task.media_needed_type = _media_needed_type(gap_type, query_fact_type)
            task.risk_level = risk_level
            task.sample_count = len(turn_uids)
            task.priority = _priority(risk_level, len(turn_uids))
            if not task.status:
                task.status = "open"
            task.summary = _summary(gap_type, query_fact_type, len(turn_uids))
            task.set_related_case_uids(case_uids)
            task.set_related_turn_uids(turn_uids)
            task.set_latest_buyer_questions(_unique(item["buyer_questions"], 5))
            task.set_latest_agent_replies(_unique(item["agent_replies"], 5))
            task.set_latest_original_cs_replies(_unique(item["reference_replies"], 5))
            task.set_metadata(sanitize_obj({
                "created_by": created_by,
                "source": "real_conversation_replay",
                "missing_evidence_type": task.missing_evidence_type,
                "media_needed_type": task.media_needed_type,
            }))
            db.flush()

            db.query(KnowledgeGapTaskSample).filter(KnowledgeGapTaskSample.task_uid == task.task_uid).delete()
            for sample in item["samples"]:
                row = KnowledgeGapTaskSample(
                    task_uid=task.task_uid,
                    run_uid=sanitize_text(sample["run_uid"]),
                    case_uid=sanitize_text(sample["case_uid"]),
                    turn_uid=sanitize_text(sample["turn_uid"]),
                    buyer_message=sanitize_text(sample["buyer_message"]),
                    agent_reply=sanitize_text(sample["agent_reply"]),
                    reference_human_reply=sanitize_text(sample["reference_human_reply"]),
                    failure_type=sanitize_text(sample["failure_type"]),
                    query_fact_type=sanitize_text(sample["query_fact_type"]),
                )
                row.set_trace_summary(sanitize_obj(sample["trace_summary"]))
                db.add(row)
            tasks.append(task)

        db.commit()
        return KnowledgeGapGenerationResult(
            run_uid=target_run_uid,
            generated=generated,
            updated=updated,
            skipped_correct=skipped_correct,
            tasks=[sanitize_obj(task.to_dict()) for task in tasks],
        )

    def list_tasks(self, db, *, filters: dict[str, str] | None = None, limit: int = 100) -> dict[str, Any]:
        from app.models.eval_tables import KnowledgeGapDraft, KnowledgeGapTask

        filters = filters or {}
        query = db.query(KnowledgeGapTask).order_by(KnowledgeGapTask.updated_at.desc(), KnowledgeGapTask.id.desc())
        for attr in ["status", "gap_type", "query_fact_type", "suggested_fix_area", "suggested_owner", "risk_level"]:
            value = sanitize_text(filters.get(attr))
            if value:
                query = query.filter(getattr(KnowledgeGapTask, attr) == value)
        product = sanitize_text(filters.get("product"))
        if product:
            query = query.filter(KnowledgeGapTask.product_title.like(f"%{product}%"))
        rows = query.limit(max(1, min(int(limit or 100), 500))).all()
        draft_counts: dict[str, int] = {}
        for task_uid, count in db.query(KnowledgeGapDraft.task_uid, KnowledgeGapDraft.id).all():
            draft_counts[task_uid] = draft_counts.get(task_uid, 0) + 1
        return {
            "items": [sanitize_obj({**row.to_dict(), "draft_count": draft_counts.get(row.task_uid, 0)}) for row in rows],
            "summary": self.summary(db),
        }

    def get_task_detail(self, db, task_uid: str) -> dict[str, Any] | None:
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
        drafts = (
            db.query(KnowledgeGapDraft)
            .filter(KnowledgeGapDraft.task_uid == task.task_uid)
            .order_by(KnowledgeGapDraft.created_at.desc(), KnowledgeGapDraft.id.desc())
            .all()
        )
        return sanitize_obj({
            "task": task.to_dict(),
            "samples": [row.to_dict() for row in samples],
            "drafts": [row.to_dict() for row in drafts],
        })

    def update_task(self, db, task_uid: str, payload: dict[str, Any]) -> dict[str, Any] | None:
        from app.models.eval_tables import KnowledgeGapTask

        task = db.query(KnowledgeGapTask).filter(KnowledgeGapTask.task_uid == sanitize_text(task_uid)).one_or_none()
        if task is None:
            return None
        for field in ["status", "priority", "suggested_owner", "summary"]:
            if field in payload:
                setattr(task, field, sanitize_text(payload.get(field)))
        db.commit()
        return sanitize_obj(task.to_dict())

    def summary(self, db) -> dict[str, int]:
        from app.models.eval_tables import KnowledgeGapDraft, KnowledgeGapTask

        tasks = db.query(KnowledgeGapTask).all()
        drafts = db.query(KnowledgeGapDraft).all()
        return {
            "open_count": sum(1 for row in tasks if row.status == "open"),
            "high_risk_count": sum(1 for row in tasks if row.risk_level == "high"),
            "media_gap_count": sum(1 for row in tasks if row.gap_type == "media_asset_gap"),
            "product_fact_gap_count": sum(1 for row in tasks if row.gap_type == "product_fact_gap"),
            "draft_count": len(drafts),
            "pending_review_count": sum(1 for row in drafts if row.review_status == "pending_review"),
            "verified_count": sum(1 for row in tasks if row.status == "verified"),
        }
