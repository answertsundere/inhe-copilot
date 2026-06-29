"""Operational task grouping for real conversation replay quality buckets."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.services.eval_sanitizer_service import sanitize_obj, sanitize_text, stable_hash
from app.services.real_conversation_quality_bucket_service import (
    AGENT_ERROR,
    AUTO_SENDABLE,
    CONTEXT_GAP,
    KNOWLEDGE_GAP,
    SAFE_HANDOFF,
    UNSCORED_OR_NOISE,
    bucket_from_trace,
)


ACTIONABLE_BUCKETS = {KNOWLEDGE_GAP, AGENT_ERROR, SAFE_HANDOFF}
BUCKETS = (AUTO_SENDABLE, SAFE_HANDOFF, CONTEXT_GAP, KNOWLEDGE_GAP, AGENT_ERROR, UNSCORED_OR_NOISE)

AGENT_ERROR_OWNER_BY_FAILURE = {
    "query_fact_type_missing": "query_understanding",
    "unrequested_product_fact": "answer_composition",
    "semantic_mismatch": "final_audit",
    "unsupported_media_claim": "media_guard",
    "intent_contract_mismatch": "agent_engineering",
    "evidence_misuse": "evidence_rerank",
    "wrong_topic_reply": "final_audit",
}

KNOWLEDGE_OWNER_BY_FIX_AREA = {
    "knowledge_rag": "knowledge_ops",
    "product_data": "knowledge_ops",
    "product_identity_product_data": "knowledge_ops",
    "media_pipeline": "media_ops",
    "media_ops": "media_ops",
    "activity_rule": "activity_ops",
    "promotion_ops": "activity_ops",
    "sop_policy": "sop_ops",
    "human_policy_risk_boundary": "human_policy",
}


@dataclass(frozen=True)
class QualityTaskGenerationResult:
    run_uid: str
    generated: int
    updated: int
    skipped: int
    groups_seen: int
    skipped_groups: list[dict[str, Any]]
    repair_tasks: dict[str, Any]
    knowledge_gap_tasks: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return sanitize_obj({
            "run_uid": self.run_uid,
            "generated": self.generated,
            "updated": self.updated,
            "skipped": self.skipped,
            "skipped_existing": self.updated,
            "groups_seen": self.groups_seen,
            "skipped_groups": self.skipped_groups,
            "repair_tasks": self.repair_tasks,
            "knowledge_gap_tasks": self.knowledge_gap_tasks,
        })


def _count_by(items: list[dict[str, Any]], key: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in items:
        value = sanitize_text(item.get(key)) or "unknown"
        counts[value] = counts.get(value, 0) + 1
    return counts


def _unique_texts(values: list[str]) -> list[str]:
    result = []
    seen = set()
    for value in values:
        cleaned = sanitize_text(value)
        if cleaned and cleaned not in seen:
            seen.add(cleaned)
            result.append(cleaned)
    return result


def _query_fact_type(trace) -> str:
    direct = sanitize_text(getattr(trace, "query_fact_type", ""))
    if direct:
        return direct
    understanding = trace.get_turn_understanding() if trace else {}
    if not isinstance(understanding, dict):
        return ""
    return sanitize_text(
        understanding.get("effective_query_fact_type")
        or understanding.get("query_fact_type")
        or understanding.get("expected_query_fact_type")
    )


def _product_group_key(trace, bucket: str) -> str:
    if bucket != KNOWLEDGE_GAP or not trace:
        return ""
    identity = trace.get_product_identity()
    if not isinstance(identity, dict):
        return ""
    return sanitize_text(
        identity.get("item_id")
        or identity.get("sku_code")
        or identity.get("sku_id")
        or identity.get("display_product_name")
        or identity.get("product_title")
        or ""
    )


def _failure_dicts(failures: list[Any]) -> list[dict[str, Any]]:
    rows = []
    for failure in failures:
        rows.append({
            "failure_type": sanitize_text(getattr(failure, "failure_type", "")),
            "severity": sanitize_text(getattr(failure, "severity", "")),
            "suggested_fix_area": sanitize_text(getattr(failure, "suggested_fix_area", "")),
            "suggested_owner": sanitize_text(getattr(failure, "suggested_owner", "")),
            "message": sanitize_text(getattr(failure, "message", "") or getattr(failure, "explanation", "")),
        })
    return rows


def _primary_failure_type(bucket: str, failures: list[dict[str, Any]], trace) -> str:
    for failure in failures:
        value = sanitize_text(failure.get("failure_type"))
        if value:
            return value
    if bucket == SAFE_HANDOFF or bool(getattr(trace, "requires_human_review", False)):
        return "needs_human_review"
    return "none"


def _fix_area(bucket: str, failures: list[dict[str, Any]], primary_failure_type: str) -> str:
    for failure in failures:
        value = sanitize_text(failure.get("suggested_fix_area"))
        if value:
            return value
    if bucket == KNOWLEDGE_GAP:
        return "knowledge_rag"
    if bucket == AGENT_ERROR:
        if primary_failure_type == "unsupported_media_claim":
            return "media_guard"
        if primary_failure_type == "unrequested_product_fact":
            return "answer_composition"
        if primary_failure_type in {"semantic_mismatch", "wrong_topic_reply"}:
            return "final_audit"
        return "agent_engineering"
    if bucket == SAFE_HANDOFF:
        return "human_policy_risk_boundary"
    return ""


def _owner(bucket: str, primary_failure_type: str, fix_area: str, failures: list[dict[str, Any]]) -> str:
    for failure in failures:
        value = sanitize_text(failure.get("suggested_owner"))
        if value:
            return value
    if bucket == AGENT_ERROR:
        return AGENT_ERROR_OWNER_BY_FAILURE.get(primary_failure_type, "agent_engineering")
    if bucket == KNOWLEDGE_GAP:
        return KNOWLEDGE_OWNER_BY_FIX_AREA.get(fix_area, "knowledge_ops")
    if bucket == SAFE_HANDOFF:
        return "human_policy"
    return "ops"


def _recommended_action(bucket: str) -> str:
    if bucket == KNOWLEDGE_GAP:
        return "Add or correct product facts, media, activity rules, or SOP evidence, then rerun replay."
    if bucket == AGENT_ERROR:
        return "Fix Agent understanding, answer composition, evidence use, or final audit logic, then run repair verification."
    if bucket == SAFE_HANDOFF:
        return "Clarify human handoff policy or risk boundary; this is not automatically treated as a wrong answer."
    if bucket == CONTEXT_GAP:
        return "Improve source conversation context extraction or mark the sample as not valid for Agent accuracy scoring."
    return "No task is generated for this bucket."


def _next_step(bucket: str) -> str:
    if bucket == KNOWLEDGE_GAP:
        return "generate_knowledge_gap_task"
    if bucket == AGENT_ERROR:
        return "generate_repair_task"
    if bucket == SAFE_HANDOFF:
        return "review_human_policy"
    if bucket == CONTEXT_GAP:
        return "fix_sample_context"
    return "none"


def _priority(bucket: str, failures: list[dict[str, Any]], sample_count: int) -> str:
    severities = {sanitize_text(item.get("severity")) for item in failures}
    if "high" in severities or bucket == AGENT_ERROR or sample_count >= 5:
        return "high"
    if sample_count <= 1:
        return "low"
    return "medium"


def _preview(value: str, limit: int = 120) -> str:
    text = sanitize_text(value)
    if len(text) <= limit:
        return text
    return f"{text[:limit]}..."


def _sample_score(sample: dict[str, Any]) -> tuple[int, int, int, int]:
    return (
        len(sample.get("failure_labels") or []),
        1 if sample.get("has_product_context") else 0,
        1 if sample.get("has_order_context") else 0,
        int(sample.get("latency_ms") or 0) + (10000 if sample.get("requires_human_review") else 0),
    )


def _representative_sample(trace, failures: list[dict[str, Any]], bucket: dict[str, Any]) -> dict[str, Any]:
    identity = trace.get_product_identity() if trace else {}
    if not isinstance(identity, dict):
        identity = {}
    labels = [sanitize_text(item.get("failure_type")) for item in failures if sanitize_text(item.get("failure_type"))]
    if not labels and trace:
        labels = [sanitize_text(value) for value in trace.get_failure_labels() if sanitize_text(value)]
    return sanitize_obj({
        "case_uid": getattr(trace, "case_uid", ""),
        "turn_uid": getattr(trace, "turn_uid", ""),
        "buyer_message_preview": _preview(getattr(trace, "buyer_message", "")),
        "agent_reply_preview": _preview(getattr(trace, "agent_reply", "")),
        "query_fact_type": _query_fact_type(trace),
        "failure_labels": labels,
        "quality_bucket_reason": bucket.get("quality_bucket_reason", ""),
        "latency_ms": int(getattr(trace, "latency_ms", 0) or 0),
        "requires_human_review": bool(getattr(trace, "requires_human_review", False)),
        "has_product_context": bool(identity),
        "has_order_context": bool(getattr(trace, "order_identity_hash", "")),
    })


class RealConversationQualityTaskService:
    """Build a dispatchable quality task view without changing Agent behavior."""

    def build_for_run(self, db, run_uid: str) -> dict[str, Any]:
        from app.models.eval_tables import EvalFailure, EvalRun, EvalTrace

        target_run_uid = sanitize_text(run_uid)
        run = db.query(EvalRun).filter(EvalRun.run_uid == target_run_uid).one_or_none()
        if run is None:
            raise ValueError("run not found")
        traces = (
            db.query(EvalTrace)
            .filter(EvalTrace.run_uid == target_run_uid)
            .order_by(EvalTrace.case_uid.asc(), EvalTrace.turn_index.asc(), EvalTrace.id.asc())
            .all()
        )
        failures = (
            db.query(EvalFailure)
            .filter(EvalFailure.run_uid == target_run_uid)
            .order_by(EvalFailure.id.asc())
            .all()
        )
        failures_by_turn: dict[str, list[Any]] = {}
        for failure in failures:
            failures_by_turn.setdefault(failure.turn_uid, []).append(failure)

        summary = {bucket: 0 for bucket in BUCKETS}
        grouped: dict[tuple[str, str, str, str, str], dict[str, Any]] = {}

        for trace in traces:
            turn_failures = failures_by_turn.get(trace.turn_uid, [])
            bucket = bucket_from_trace(trace, turn_failures)
            bucket_name = sanitize_text(bucket.get("quality_bucket")) or AGENT_ERROR
            if bucket_name not in summary:
                bucket_name = AGENT_ERROR
            summary[bucket_name] += 1
            if bucket_name not in ACTIONABLE_BUCKETS:
                continue
            failure_items = _failure_dicts(turn_failures)
            primary_failure_type = _primary_failure_type(bucket_name, failure_items, trace)
            query_fact_type = _query_fact_type(trace)
            fix_area = _fix_area(bucket_name, failure_items, primary_failure_type)
            owner = _owner(bucket_name, primary_failure_type, fix_area, failure_items)
            product_key = _product_group_key(trace, bucket_name)
            key = (bucket_name, query_fact_type, primary_failure_type, fix_area, product_key)
            if key not in grouped:
                group_hash = stable_hash("|".join(key), 12)
                grouped[key] = {
                    "task_group_uid": f"qtask_{group_hash}",
                    "run_uid": target_run_uid,
                    "quality_bucket": bucket_name,
                    "primary_failure_type": primary_failure_type,
                    "suggested_fix_area": fix_area,
                    "suggested_owner": owner,
                    "query_fact_type": query_fact_type,
                    "product_group_key": product_key,
                    "sample_count": 0,
                    "related_case_uids": [],
                    "related_turn_uids": [],
                    "representative_samples": [],
                    "all_failures": [],
                    "recommended_action": _recommended_action(bucket_name),
                    "next_step": _next_step(bucket_name),
                }
            item = grouped[key]
            item["sample_count"] += 1
            item["related_case_uids"].append(getattr(trace, "case_uid", ""))
            item["related_turn_uids"].append(getattr(trace, "turn_uid", ""))
            item["all_failures"].extend(failure_items)
            item["representative_samples"].append(_representative_sample(trace, failure_items, bucket))

        task_groups = []
        for item in grouped.values():
            item["related_case_uids"] = _unique_texts(item["related_case_uids"])
            item["related_turn_uids"] = _unique_texts(item["related_turn_uids"])
            item["representative_samples"] = sorted(
                item["representative_samples"],
                key=_sample_score,
                reverse=True,
            )[:3]
            item["priority"] = _priority(item["quality_bucket"], item["all_failures"], item["sample_count"])
            item.pop("all_failures", None)
            task_groups.append(item)
        task_groups.sort(key=lambda item: (item["quality_bucket"], item["suggested_owner"], item["primary_failure_type"]))
        return sanitize_obj({
            "run_uid": target_run_uid,
            "summary": summary,
            "counts_by_bucket": summary,
            "counts_by_owner": _count_by(task_groups, "suggested_owner"),
            "counts_by_fix_area": _count_by(task_groups, "suggested_fix_area"),
            "task_group_count": len(task_groups),
            "task_groups": task_groups,
        })

    def generate_for_run(self, db, run_uid: str, created_by: str = "") -> QualityTaskGenerationResult:
        from app.services.knowledge_gap_task_service import KnowledgeGapTaskService
        from app.services.real_conversation_repair_task_service import RealConversationRepairTaskService

        overview = self.build_for_run(db, run_uid)
        repair_turn_uids: list[str] = []
        knowledge_turn_uids: list[str] = []
        skipped_groups: list[dict[str, Any]] = []
        for group in overview["task_groups"]:
            turn_uids = [
                sanitize_text(turn_uid)
                for turn_uid in group.get("related_turn_uids", [])
                if sanitize_text(turn_uid)
            ]
            next_step = sanitize_text(group.get("next_step"))
            if next_step == "generate_repair_task":
                repair_turn_uids.extend(turn_uids)
            elif next_step == "generate_knowledge_gap_task":
                knowledge_turn_uids.extend(turn_uids)
            else:
                skipped_groups.append({
                    "task_group_uid": group.get("task_group_uid", ""),
                    "quality_bucket": group.get("quality_bucket", ""),
                    "next_step": next_step or "none",
                    "reason": "no downstream task is generated for this quality bucket",
                })
        skipped = len(skipped_groups)
        repair_result = RealConversationRepairTaskService().generate_for_run(
            db,
            run_uid=run_uid,
            created_by=created_by,
            allowed_turn_uids=_unique_texts(repair_turn_uids),
        ).to_dict()
        knowledge_result = KnowledgeGapTaskService().generate_for_run(
            db,
            run_uid=run_uid,
            created_by=created_by,
            allowed_turn_uids=_unique_texts(knowledge_turn_uids),
        ).to_dict()
        return QualityTaskGenerationResult(
            run_uid=sanitize_text(run_uid),
            generated=int(repair_result.get("generated") or 0) + int(knowledge_result.get("generated") or 0),
            updated=int(repair_result.get("updated") or 0) + int(knowledge_result.get("updated") or 0),
            skipped=skipped,
            groups_seen=int(overview.get("task_group_count") or len(overview.get("task_groups") or [])),
            skipped_groups=skipped_groups,
            repair_tasks=repair_result,
            knowledge_gap_tasks=knowledge_result,
        )
