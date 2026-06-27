"""Aggregate real replay failures into knowledge/media gap tasks."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from app.services.eval_sanitizer_service import sanitize_obj, sanitize_text
from app.services.real_conversation_quality_bucket_service import bucket_from_trace, should_generate_knowledge_gap_task


MEDIA_FACT_TYPES = {"installation", "visual_asset", "media_reference"}
MEDIA_VISUAL_FACT_TYPES = {"visual_asset", "media_reference", "dimensions", "space_fit", "detachable", "accessories"}
PROMOTION_FACT_TYPES = {"promotion", "promotion_policy", "activity_rule", "coupon", "discount", "gift_policy"}
AFTERSALES_FACT_TYPES = {
    "aftersales",
    "aftersales_policy",
    "after_sales",
    "damaged_item",
    "shortage",
    "refund",
    "return_exchange",
}
LOGISTICS_CONTEXT_FACT_TYPES = {"stock_shipping", "delivery_not_received", "logistics"}
CONTEXT_FAILURE_TYPES = {"context_gap", "context_insufficient"}
MEDIA_FAILURE_TYPES = {"unsupported_media_claim"}
EVIDENCE_ROUTING_FAILURE_TYPES = {"evidence_misuse", "semantic_mismatch", "intent_contract_mismatch"}
PRODUCT_FIELD_EVIDENCE_BY_FACT_TYPE = {
    "dimensions": "product_spec",
    "space_fit": "product_spec",
    "material": "product_material",
    "load_capacity": "load_capacity",
    "gross_weight": "gross_weight",
    "weight": "gross_weight",
    "age_range": "age_range",
    "accessory_availability": "accessory_availability",
    "structure_function": "structure_function",
    "detachable": "product_spec",
    "certification_report": "certificate_report",
}
PRODUCT_FIELD_FACT_TYPES = set(PRODUCT_FIELD_EVIDENCE_BY_FACT_TYPE)
HIGH_RISK_FACT_TYPES = {"certification_report", "pinch_safety", "safety_small_parts", "material", "aftersales_policy"}
HIGH_RISK_FAILURES = {"unsafe_claim", "unsupported_media_claim", "tool_policy_blocked"}
KNOWLEDGE_TASK_AGENT_ERROR_FIX_AREAS = {"media_pipeline", "media_ops", "evidence_rerank"}
KNOWLEDGE_GAP_REVIEW_DECISIONS = {
    "fill_product_field",
    "upload_media_asset",
    "write_aftersales_policy",
    "write_promotion_policy",
    "fix_context_extraction",
    "improve_evidence_mapping",
    "ignore_false_positive",
    "needs_more_samples",
}
KNOWLEDGE_GAP_STATUSES = {
    "open",
    "triaged",
    "assigned",
    "draft_ready",
    "waiting_data",
    "rejected",
    "resolved_pending_retest",
    "verified",
    "closed",
    "drafting",
    "pending_review",
    "approved",
    "published",
}


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


def _now_iso() -> str:
    return datetime.utcnow().isoformat()


def _metadata_with_status_history(task, *, status: str, changed_by: str = "", note: str = "") -> dict[str, Any]:
    metadata = task.get_metadata()
    history = metadata.get("status_history")
    if not isinstance(history, list):
        history = []
    history.append(sanitize_obj({
        "status": status,
        "changed_by": changed_by,
        "note": note,
        "changed_at": _now_iso(),
    }))
    metadata["status_history"] = history
    return metadata


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


def _mask_identifier(value: str) -> str:
    text = sanitize_text(value)
    if len(text) <= 4:
        return text
    return f"{text[:2]}***{text[-2:]}"


def _query_fact_type(failure, trace) -> str:
    if trace and sanitize_text(trace.query_fact_type):
        return sanitize_text(trace.query_fact_type)
    metadata = failure.get_metadata() if failure else {}
    return sanitize_text(metadata.get("query_fact_type") or metadata.get("fact_type") or "")


def _evidence_state(trace) -> dict[str, Any]:
    if trace is None:
        return {
            "selected_evidence_count": 0,
            "rejected_evidence_count": 0,
            "matched_media_asset_count": 0,
            "sendable_media_asset_count": 0,
            "conversation_media_rejected_reason": "",
        }
    raw = trace.get_raw_response()
    answer_trace = trace.get_answer_trace()
    selected = trace.get_selected_evidence()
    rejected = trace.get_rejected_evidence()
    assets: list[Any] = []
    for source in (
        raw.get("recommended_assets") if isinstance(raw, dict) else None,
        raw.get("media_assets") if isinstance(raw, dict) else None,
        answer_trace.get("media_assets") if isinstance(answer_trace, dict) else None,
    ):
        if isinstance(source, list):
            assets.extend(source)
    sendable = [
        asset for asset in assets
        if isinstance(asset, dict)
        and str(asset.get("auto_send_level") or asset.get("send_level") or "auto").lower() == "auto"
    ]
    media_rejected_reason = ""
    if isinstance(raw, dict):
        media_rejected_reason = sanitize_text(
            raw.get("conversation_media_rejected_reason")
            or raw.get("media_rejected_reason")
            or ""
        )
    return {
        "selected_evidence_count": len(selected),
        "rejected_evidence_count": len(rejected),
        "matched_media_asset_count": len(assets),
        "sendable_media_asset_count": len(sendable),
        "conversation_media_rejected_reason": media_rejected_reason,
    }


def _has_product_context(identity: dict[str, str]) -> bool:
    return bool(identity.get("product_title") or identity.get("item_id") or identity.get("sku_code"))


def _is_context_gap(failure_type: str, query_fact_type: str, fix_area: str, identity: dict[str, str]) -> bool:
    if failure_type in CONTEXT_FAILURE_TYPES or fix_area in {"sample_context_extraction", "conversation_context"}:
        return True
    if not query_fact_type and not _has_product_context(identity):
        return True
    return False


def _gap_type_for(
    failure_type: str,
    query_fact_type: str,
    fix_area: str,
    identity: dict[str, str],
    evidence_state: dict[str, Any],
) -> str:
    if _is_context_gap(failure_type, query_fact_type, fix_area, identity):
        return "context_extraction_gap"
    if failure_type in MEDIA_FAILURE_TYPES or fix_area in {"media_pipeline", "media_ops"}:
        return "media_asset_gap"
    if failure_type in EVIDENCE_ROUTING_FAILURE_TYPES or fix_area in {"evidence_rerank", "final_audit_semantic_compiler"}:
        return "evidence_routing_gap"
    if query_fact_type in PROMOTION_FACT_TYPES or fix_area in {"activity_rules", "promotion_ops"}:
        return "promotion_policy_gap"
    if query_fact_type in AFTERSALES_FACT_TYPES or fix_area in {"service_rules", "aftersales_policy", "sop_policy"}:
        return "aftersales_policy_gap"
    if query_fact_type in LOGISTICS_CONTEXT_FACT_TYPES:
        return "context_extraction_gap"
    if query_fact_type in MEDIA_FACT_TYPES and int(evidence_state.get("sendable_media_asset_count") or 0) == 0:
        return "media_asset_gap"
    if query_fact_type in MEDIA_VISUAL_FACT_TYPES and failure_type == "rag_miss":
        return "media_asset_gap"
    if query_fact_type in PRODUCT_FIELD_FACT_TYPES or failure_type in {"rag_miss", "query_fact_type_missing"}:
        return "product_field_gap"
    if fix_area in {"agent_engineering", "answer_composition", "final_audit"}:
        return "evidence_routing_gap"
    return "product_field_gap"


def _missing_evidence_type(gap_type: str, query_fact_type: str) -> str:
    if gap_type == "media_asset_gap":
        if query_fact_type == "installation":
            return "installation_video"
        if query_fact_type in {"visual_asset", "media_reference"}:
            return "real_product_image"
        if query_fact_type in {"accessories", "structure_function"}:
            return "accessory_diagram"
        return "approved_media_asset"
    if gap_type == "promotion_policy_gap":
        return "promotion_rule"
    if gap_type == "aftersales_policy_gap":
        return "aftersales_rule"
    if gap_type == "context_extraction_gap":
        if query_fact_type in LOGISTICS_CONTEXT_FACT_TYPES:
            return "order_context"
        return "sku_context"
    if gap_type == "evidence_routing_gap":
        return "evidence_mapping"
    return PRODUCT_FIELD_EVIDENCE_BY_FACT_TYPE.get(query_fact_type, "product_spec")


def _media_needed_type(gap_type: str, query_fact_type: str) -> str:
    if gap_type != "media_asset_gap":
        return ""
    if query_fact_type == "installation":
        return "video_or_manual"
    if query_fact_type in {"dimensions", "space_fit"}:
        return "image"
    return "approved_media"


def _target_system(gap_type: str, query_fact_type: str) -> str:
    if gap_type == "media_asset_gap":
        return "kb_media_asset"
    if gap_type == "promotion_policy_gap":
        return "activity_rules"
    if gap_type == "aftersales_policy_gap":
        return "aftersales_policy"
    if gap_type == "context_extraction_gap":
        return "context_extractor"
    if gap_type == "evidence_routing_gap":
        return "agent_engineering"
    if query_fact_type in {"dimensions", "gross_weight", "material", "load_capacity", "age_range"}:
        return "product_profile"
    return "kb_product"


def _recommended_action(gap_type: str) -> str:
    return {
        "product_field_gap": "fill_product_field",
        "media_asset_gap": "upload_approved_media",
        "aftersales_policy_gap": "write_policy_rule",
        "promotion_policy_gap": "write_policy_rule",
        "context_extraction_gap": "fix_context_extraction",
        "evidence_routing_gap": "improve_evidence_mapping",
    }.get(gap_type, "manual_policy_review")


def _missing_fields(gap_type: str, query_fact_type: str, required_evidence_type: str, identity: dict[str, str]) -> list[str]:
    fields: list[str] = []
    if gap_type == "context_extraction_gap":
        if not identity.get("product_title"):
            fields.append("product_title")
        if not identity.get("sku_code"):
            fields.append("sku_code")
        if not identity.get("item_id"):
            fields.append("item_id")
        return fields or ["conversation_context"]
    if gap_type == "product_field_gap":
        return [query_fact_type or required_evidence_type]
    if gap_type == "media_asset_gap":
        return [required_evidence_type]
    if gap_type in {"aftersales_policy_gap", "promotion_policy_gap"}:
        return [required_evidence_type]
    return [query_fact_type or "evidence_mapping"]


def _context_summary(identity: dict[str, str], trace, evidence_state: dict[str, Any]) -> dict[str, Any]:
    return {
        "has_product_context": _has_product_context(identity),
        "has_order_context": bool(getattr(trace, "order_identity_hash", "")) if trace else False,
        "has_media_context": bool(evidence_state.get("matched_media_asset_count")),
        "product_title_preview": sanitize_text(identity.get("product_title", ""))[:80],
        "item_id_masked": _mask_identifier(identity.get("item_id", "")),
        "sku_code_exists": bool(identity.get("sku_code")),
        **evidence_state,
    }


def _run_turn_uids(db, run_uid: str) -> set[str]:
    from app.models.eval_tables import EvalTrace

    target_run_uid = sanitize_text(run_uid)
    if not target_run_uid:
        return set()
    return {
        sanitize_text(row[0])
        for row in db.query(EvalTrace.turn_uid).filter(EvalTrace.run_uid == target_run_uid).all()
    }


def _task_matches_run(task, run_uid: str, turn_uids: set[str]) -> bool:
    target_run_uid = sanitize_text(run_uid)
    if not target_run_uid:
        return True
    metadata = task.get_metadata()
    if sanitize_text(metadata.get("source_run_uid")) == target_run_uid:
        return True
    return bool(set(task.get_related_turn_uids()) & turn_uids)


def filter_tasks_by_run(db, tasks: list[Any], run_uid: str) -> list[Any]:
    """Filter knowledge gap tasks by source replay run.

    New tasks use metadata.source_run_uid. Older tasks may not have that field,
    so we fall back to related_turn_uids intersecting EvalTrace.turn_uid for the
    requested run.
    """
    target_run_uid = sanitize_text(run_uid)
    if not target_run_uid:
        return tasks
    tagged = [
        task for task in tasks
        if sanitize_text(task.get_metadata().get("source_run_uid")) == target_run_uid
    ]
    if tagged:
        return tagged
    turn_uids = _run_turn_uids(db, target_run_uid)
    return [task for task in tasks if _task_matches_run(task, target_run_uid, turn_uids)]


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


def _summary(gap_type: str, query_fact_type: str, sample_count: int, required_evidence_type: str) -> str:
    readable_fact = query_fact_type or "unknown_fact"
    return sanitize_text(
        f"{sample_count} real replay sample(s) need {gap_type} for {readable_fact}; "
        f"required evidence: {required_evidence_type}."
    )


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
        failures_by_turn: dict[str, list] = {}
        for failure in failures:
            failures_by_turn.setdefault(failure.turn_uid, []).append(failure)
        for failure in failures:
            if failure.turn_uid in correct_turns:
                skipped_correct += 1
                continue
            trace = traces.get(failure.turn_uid)
            bucket = bucket_from_trace(trace, failures_by_turn.get(failure.turn_uid, [])) if trace else {}
            query_fact_type = _query_fact_type(failure, trace)
            fix_area = sanitize_text(failure.suggested_fix_area) or "manual_triage"
            owner = sanitize_text(failure.suggested_owner) or "knowledge_ops"
            failure_type = sanitize_text(failure.failure_type) or "manual_review"
            if (
                not should_generate_knowledge_gap_task(str(bucket.get("quality_bucket") or ""))
                and failure_type not in MEDIA_FAILURE_TYPES
                and failure_type not in EVIDENCE_ROUTING_FAILURE_TYPES
                and fix_area not in KNOWLEDGE_TASK_AGENT_ERROR_FIX_AREAS
            ):
                continue
            identity = _trace_identity(trace)
            evidence_state = _evidence_state(trace)
            gap_type = _gap_type_for(failure_type, query_fact_type, fix_area, identity, evidence_state)
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
                "evidence_state": evidence_state,
                "case_uids": [],
                "turn_uids": [],
                "buyer_questions": [],
                "agent_replies": [],
                "reference_replies": [],
                "severities": [],
                "samples": [],
            })
            if not item.get("evidence_state"):
                item["evidence_state"] = evidence_state
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
            evidence_state = item.get("evidence_state") or {}
            required_evidence_type = _missing_evidence_type(gap_type, query_fact_type)
            target_system = _target_system(gap_type, query_fact_type)
            recommended_action = _recommended_action(gap_type)
            missing_fields = _missing_fields(gap_type, query_fact_type, required_evidence_type, item["identity"])
            context_summary = _context_summary(item["identity"], traces.get(turn_uids[0]) if turn_uids else None, evidence_state)
            task.gap_type = gap_type
            task.product_title = product_title
            task.item_id = item_id
            task.sku_code = sku_code
            task.query_fact_type = query_fact_type
            task.failure_type = failure_type
            task.suggested_fix_area = fix_area
            task.suggested_owner = owner
            task.missing_evidence_type = required_evidence_type
            task.media_needed_type = _media_needed_type(gap_type, query_fact_type)
            task.risk_level = risk_level
            task.sample_count = len(turn_uids)
            task.priority = _priority(risk_level, len(turn_uids))
            if not task.status:
                task.status = "open"
            task.summary = _summary(gap_type, query_fact_type, len(turn_uids), required_evidence_type)
            task.set_related_case_uids(case_uids)
            task.set_related_turn_uids(turn_uids)
            task.set_latest_buyer_questions(_unique(item["buyer_questions"], 5))
            task.set_latest_agent_replies(_unique(item["agent_replies"], 5))
            task.set_latest_original_cs_replies(_unique(item["reference_replies"], 5))
            task.set_metadata(sanitize_obj({
                "created_by": created_by,
                "source": "real_conversation_replay",
                "source_run_uid": target_run_uid,
                "gap_category": gap_type,
                "required_evidence_type": required_evidence_type,
                "target_system": target_system,
                "recommended_action": recommended_action,
                "missing_fields": missing_fields,
                "current_context_summary": context_summary,
                "missing_evidence_type": task.missing_evidence_type,
                "media_needed_type": task.media_needed_type,
                "representative_samples": [
                    {
                        "turn_uid": sample.get("turn_uid", ""),
                        "failure_type": sample.get("failure_type", ""),
                        "query_fact_type": sample.get("query_fact_type", ""),
                        "buyer_message": sample.get("buyer_message", ""),
                        "agent_reply": sample.get("agent_reply", ""),
                    }
                    for sample in item["samples"][:5]
                ],
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
        run_uid = sanitize_text(filters.get("run_uid"))
        query = db.query(KnowledgeGapTask).order_by(KnowledgeGapTask.updated_at.desc(), KnowledgeGapTask.id.desc())
        gap_category = sanitize_text(filters.get("gap_category"))
        if gap_category and not sanitize_text(filters.get("gap_type")):
            filters = {**filters, "gap_type": gap_category}
        required_evidence_type = sanitize_text(filters.get("required_evidence_type"))
        if required_evidence_type and not sanitize_text(filters.get("missing_evidence_type")):
            filters = {**filters, "missing_evidence_type": required_evidence_type}
        for attr in [
            "status",
            "gap_type",
            "query_fact_type",
            "suggested_fix_area",
            "suggested_owner",
            "risk_level",
            "missing_evidence_type",
        ]:
            value = sanitize_text(filters.get(attr))
            if value:
                query = query.filter(getattr(KnowledgeGapTask, attr) == value)
        product = sanitize_text(filters.get("product"))
        if product:
            query = query.filter(KnowledgeGapTask.product_title.like(f"%{product}%"))
        rows = query.all()
        target_system = sanitize_text(filters.get("target_system"))
        recommended_action = sanitize_text(filters.get("recommended_action"))
        if target_system or recommended_action:
            filtered_rows = []
            for row in rows:
                metadata = row.get_metadata()
                if target_system and sanitize_text(metadata.get("target_system")) != target_system:
                    continue
                if recommended_action and sanitize_text(metadata.get("recommended_action")) != recommended_action:
                    continue
                filtered_rows.append(row)
            rows = filtered_rows
        rows = filter_tasks_by_run(db, rows, run_uid)
        rows = rows[:max(1, min(int(limit or 100), 500))]
        draft_counts: dict[str, int] = {}
        for task_uid, count in db.query(KnowledgeGapDraft.task_uid, KnowledgeGapDraft.id).all():
            draft_counts[task_uid] = draft_counts.get(task_uid, 0) + 1
        return {
            "items": [sanitize_obj({**row.to_dict(), "draft_count": draft_counts.get(row.task_uid, 0)}) for row in rows],
            "summary": self.summary(db, tasks=rows, run_uid=run_uid),
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
        metadata = task.get_metadata()
        return sanitize_obj({
            "task": task.to_dict(),
            "samples": [row.to_dict() for row in samples],
            "drafts": [row.to_dict() for row in drafts],
            "review_metadata": {
                "review_decision": sanitize_text(metadata.get("review_decision")),
                "reviewer": sanitize_text(metadata.get("reviewer")),
                "review_note": sanitize_text(metadata.get("review_note")),
                "assigned_to": sanitize_text(metadata.get("assigned_to")),
                "assigned_team": sanitize_text(metadata.get("assigned_team")),
                "due_date": sanitize_text(metadata.get("due_date")),
                "reviewed_at": sanitize_text(metadata.get("reviewed_at")),
                "triage_reason": sanitize_text(metadata.get("triage_reason")),
                "next_action": sanitize_text(metadata.get("next_action")),
                "source_run_uid": sanitize_text(metadata.get("source_run_uid")),
            },
            "status_history": metadata.get("status_history") if isinstance(metadata.get("status_history"), list) else [],
            "recommended_next_action": sanitize_text(
                metadata.get("next_action")
                or metadata.get("recommended_action")
                or task.suggested_fix_area
                or task.gap_type
            ),
        })

    def update_task(self, db, task_uid: str, payload: dict[str, Any]) -> dict[str, Any] | None:
        from app.models.eval_tables import KnowledgeGapTask

        task = db.query(KnowledgeGapTask).filter(KnowledgeGapTask.task_uid == sanitize_text(task_uid)).one_or_none()
        if task is None:
            return None
        for field in ["status", "priority", "suggested_owner", "summary"]:
            if field in payload:
                setattr(task, field, sanitize_text(payload.get(field)))
        if "status" in payload:
            metadata = _metadata_with_status_history(
                task,
                status=sanitize_text(payload.get("status")),
                changed_by=sanitize_text(payload.get("changed_by") or payload.get("reviewer")),
                note=sanitize_text(payload.get("review_note") or payload.get("note")),
            )
            task.set_metadata(sanitize_obj(metadata))
        db.commit()
        return sanitize_obj(task.to_dict())

    def triage_task(self, db, task_uid: str, payload: dict[str, Any], *, reviewer: str = "") -> dict[str, Any] | None:
        from app.models.eval_tables import KnowledgeGapTask

        task = db.query(KnowledgeGapTask).filter(KnowledgeGapTask.task_uid == sanitize_text(task_uid)).one_or_none()
        if task is None:
            return None
        decision = sanitize_text(payload.get("review_decision"))
        if decision not in KNOWLEDGE_GAP_REVIEW_DECISIONS:
            raise ValueError("invalid knowledge gap review decision")

        status = sanitize_text(payload.get("status"))
        if not status:
            status = "rejected" if decision == "ignore_false_positive" else "triaged"
        if status not in KNOWLEDGE_GAP_STATUSES:
            raise ValueError("invalid knowledge gap status")

        priority = sanitize_text(payload.get("priority"))
        if priority:
            task.priority = priority
        assigned_to = sanitize_text(payload.get("assigned_to"))
        assigned_team = sanitize_text(payload.get("assigned_team"))
        if assigned_to:
            task.suggested_owner = assigned_to
        elif assigned_team:
            task.suggested_owner = assigned_team

        metadata = _metadata_with_status_history(
            task,
            status=status,
            changed_by=sanitize_text(reviewer),
            note=sanitize_text(payload.get("review_note") or payload.get("triage_reason")),
        )
        metadata.update(sanitize_obj({
            "review_decision": decision,
            "reviewer": sanitize_text(reviewer),
            "review_note": sanitize_text(payload.get("review_note")),
            "assigned_to": assigned_to,
            "assigned_team": assigned_team,
            "due_date": sanitize_text(payload.get("due_date")),
            "reviewed_at": _now_iso(),
            "triage_reason": sanitize_text(payload.get("triage_reason")),
            "next_action": sanitize_text(payload.get("next_action")),
            "source_run_uid": sanitize_text(payload.get("source_run_uid") or metadata.get("source_run_uid")),
        }))
        task.status = status
        task.set_metadata(sanitize_obj(metadata))
        db.commit()
        return sanitize_obj(task.to_dict())

    def update_status(
        self,
        db,
        task_uid: str,
        payload: dict[str, Any],
        *,
        changed_by: str = "",
    ) -> dict[str, Any] | None:
        from app.models.eval_tables import KnowledgeGapTask

        task = db.query(KnowledgeGapTask).filter(KnowledgeGapTask.task_uid == sanitize_text(task_uid)).one_or_none()
        if task is None:
            return None
        status = sanitize_text(payload.get("status"))
        if status not in KNOWLEDGE_GAP_STATUSES:
            raise ValueError("invalid knowledge gap status")
        priority = sanitize_text(payload.get("priority"))
        if priority:
            task.priority = priority
        assigned_to = sanitize_text(payload.get("assigned_to"))
        assigned_team = sanitize_text(payload.get("assigned_team"))
        if assigned_to:
            task.suggested_owner = assigned_to
        elif assigned_team:
            task.suggested_owner = assigned_team
        metadata = _metadata_with_status_history(
            task,
            status=status,
            changed_by=sanitize_text(changed_by),
            note=sanitize_text(payload.get("review_note") or payload.get("note")),
        )
        for key in ["assigned_to", "assigned_team", "due_date", "review_note", "next_action"]:
            if key in payload:
                metadata[key] = sanitize_text(payload.get(key))
        task.status = status
        task.set_metadata(sanitize_obj(metadata))
        db.commit()
        return sanitize_obj(task.to_dict())

    def summary(self, db, *, tasks: list[Any] | None = None, run_uid: str = "") -> dict[str, Any]:
        from app.models.eval_tables import KnowledgeGapDraft, KnowledgeGapTask

        selected_tasks = list(tasks) if tasks is not None else db.query(KnowledgeGapTask).all()
        task_uids = {row.task_uid for row in selected_tasks}
        if task_uids:
            drafts = db.query(KnowledgeGapDraft).filter(KnowledgeGapDraft.task_uid.in_(task_uids)).all()
        else:
            drafts = []

        def _count_by_metadata(key: str) -> dict[str, int]:
            counts: dict[str, int] = {}
            for row in selected_tasks:
                metadata = row.get_metadata()
                value = sanitize_text(metadata.get(key))
                if not value and key == "gap_category":
                    value = sanitize_text(row.gap_type)
                if not value and key == "required_evidence_type":
                    value = sanitize_text(row.missing_evidence_type)
                if not value:
                    value = "unknown"
                counts[value] = counts.get(value, 0) + 1
            return counts

        return {
            "run_uid": sanitize_text(run_uid),
            "filtered_by_run_uid": bool(sanitize_text(run_uid)),
            "total": len(selected_tasks),
            "by_gap_category": _count_by_metadata("gap_category"),
            "by_required_evidence_type": _count_by_metadata("required_evidence_type"),
            "by_target_system": _count_by_metadata("target_system"),
            "open_count": sum(1 for row in selected_tasks if row.status == "open"),
            "high_risk_count": sum(1 for row in selected_tasks if row.risk_level == "high"),
            "media_gap_count": sum(1 for row in selected_tasks if row.gap_type == "media_asset_gap"),
            "product_fact_gap_count": sum(1 for row in selected_tasks if row.gap_type in {"product_fact_gap", "product_field_gap"}),
            "product_field_gap_count": sum(1 for row in selected_tasks if row.gap_type == "product_field_gap"),
            "aftersales_policy_gap_count": sum(1 for row in selected_tasks if row.gap_type == "aftersales_policy_gap"),
            "promotion_policy_gap_count": sum(1 for row in selected_tasks if row.gap_type == "promotion_policy_gap"),
            "context_extraction_gap_count": sum(1 for row in selected_tasks if row.gap_type == "context_extraction_gap"),
            "draft_count": len(drafts),
            "pending_review_count": sum(1 for row in drafts if row.review_status == "pending_review"),
            "verified_count": sum(1 for row in selected_tasks if row.status == "verified"),
        }
