"""Classify real replay turns into operational quality buckets."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.services.eval_sanitizer_service import sanitize_obj, sanitize_text


AUTO_SENDABLE = "auto_sendable"
SAFE_HANDOFF = "safe_handoff"
KNOWLEDGE_GAP = "knowledge_gap"
AGENT_ERROR = "agent_error"
CONTEXT_GAP = "context_gap"
UNSCORED_OR_NOISE = "unscored_or_noise"

AGENT_ERROR_LABELS = {
    "answer_incomplete",
    "encoding_corruption",
    "evidence_misuse",
    "generic_reply_to_actionable_issue",
    "intent_contract_mismatch",
    "query_fact_type_missing",
    "semantic_mismatch",
    "tool_policy_blocked",
    "unnecessary_rag_call",
    "unrequested_product_fact",
    "unsafe_claim",
    "unsupported_media_claim",
    "wrong_topic_reply",
}

KNOWLEDGE_GAP_LABELS = {
    "rag_miss",
}

CONTEXT_GAP_LABELS = {
    "context_gap",
    "context_insufficient",
    "no_product_identified",
}

KNOWLEDGE_GAP_FIX_AREAS = {
    "activity_rule",
    "knowledge_ops",
    "knowledge_rag",
    "media_ops",
    "media_pipeline",
    "product_data",
    "product_identity_product_data",
    "sop_policy",
}

SAFE_HANDOFF_LABELS = {
    "needs_human_review",
}

UNSCORED_ACTIONABILITY = {
    "acknowledgement",
    "context_update",
    "corrupted",
    "noise",
}

BUCKET_PRIORITY = {
    AUTO_SENDABLE: 10,
    SAFE_HANDOFF: 20,
    CONTEXT_GAP: 25,
    KNOWLEDGE_GAP: 30,
    AGENT_ERROR: 40,
    UNSCORED_OR_NOISE: 0,
}


@dataclass(frozen=True)
class QualityBucketResult:
    quality_bucket: str
    quality_bucket_reason: str
    quality_bucket_priority: int
    secondary_buckets: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        bucket = self.quality_bucket
        return sanitize_obj({
            "quality_bucket": bucket,
            "quality_bucket_reason": self.quality_bucket_reason,
            "quality_bucket_priority": self.quality_bucket_priority,
            "secondary_buckets": list(self.secondary_buckets),
            "is_auto_sendable": bucket == AUTO_SENDABLE,
            "is_safe_handoff": bucket == SAFE_HANDOFF,
            "is_context_gap": bucket == CONTEXT_GAP,
            "is_knowledge_gap": bucket == KNOWLEDGE_GAP,
            "is_agent_error": bucket == AGENT_ERROR,
            "should_count_in_quality_rate": bucket not in {UNSCORED_OR_NOISE, CONTEXT_GAP},
        })


def _labels(values: list[str] | tuple[str, ...] | set[str] | None) -> set[str]:
    return {sanitize_text(value) for value in (values or []) if sanitize_text(value)}


def _fix_areas(failures: list[dict[str, Any]] | None) -> set[str]:
    areas = set()
    for failure in failures or []:
        area = sanitize_text(failure.get("suggested_fix_area"))
        if area:
            areas.add(area)
    return areas


def _failure_labels(failures: list[dict[str, Any]] | None) -> set[str]:
    labels = set()
    for failure in failures or []:
        label = sanitize_text(failure.get("failure_type"))
        if label:
            labels.add(label)
    return labels


def classify_quality_bucket(
    *,
    passed: bool,
    requires_human_review: bool,
    failure_labels: list[str] | tuple[str, ...] | set[str] | None = None,
    failures: list[dict[str, Any]] | None = None,
    turn_understanding: dict[str, Any] | None = None,
) -> QualityBucketResult:
    """Return one primary quality bucket for a replay turn.

    The classifier only uses replay-level contract fields and failure labels. It
    intentionally does not inspect buyer text, product names, SKUs, or sample IDs.
    """
    understanding = turn_understanding or {}
    labels = _labels(failure_labels) | _failure_labels(failures)
    fix_areas = _fix_areas(failures)
    actionability = sanitize_text(understanding.get("turn_actionability"))
    should_score = understanding.get("should_score")
    context_sufficiency = understanding.get("context_sufficiency") if isinstance(understanding.get("context_sufficiency"), dict) else {}

    if (labels & CONTEXT_GAP_LABELS) or context_sufficiency.get("is_sufficient") is False:
        matched = sorted(labels & CONTEXT_GAP_LABELS) or list(context_sufficiency.get("missing_context_fields") or [])
        return QualityBucketResult(
            quality_bucket=CONTEXT_GAP,
            quality_bucket_reason=f"source conversation lacks required context: {', '.join(matched)}",
            quality_bucket_priority=BUCKET_PRIORITY[CONTEXT_GAP],
            secondary_buckets=tuple(sorted(_secondary_buckets(labels, fix_areas, requires_human_review))),
        )

    if labels & AGENT_ERROR_LABELS:
        matched = sorted(labels & AGENT_ERROR_LABELS)
        return QualityBucketResult(
            quality_bucket=AGENT_ERROR,
            quality_bucket_reason=f"agent error label(s): {', '.join(matched)}",
            quality_bucket_priority=BUCKET_PRIORITY[AGENT_ERROR],
            secondary_buckets=tuple(sorted(_secondary_buckets(labels, fix_areas, requires_human_review))),
        )

    if should_score is False or actionability in UNSCORED_ACTIONABILITY:
        return QualityBucketResult(
            quality_bucket=UNSCORED_OR_NOISE,
            quality_bucket_reason="turn_understanding marks this turn as not scoreable",
            quality_bucket_priority=BUCKET_PRIORITY[UNSCORED_OR_NOISE],
        )

    if labels & KNOWLEDGE_GAP_LABELS or fix_areas & KNOWLEDGE_GAP_FIX_AREAS:
        matched = sorted((labels & KNOWLEDGE_GAP_LABELS) | (fix_areas & KNOWLEDGE_GAP_FIX_AREAS))
        return QualityBucketResult(
            quality_bucket=KNOWLEDGE_GAP,
            quality_bucket_reason=f"missing knowledge/media/rule evidence: {', '.join(matched)}",
            quality_bucket_priority=BUCKET_PRIORITY[KNOWLEDGE_GAP],
            secondary_buckets=tuple(sorted(_secondary_buckets(labels, fix_areas, requires_human_review))),
        )

    if requires_human_review or labels & SAFE_HANDOFF_LABELS:
        return QualityBucketResult(
            quality_bucket=SAFE_HANDOFF,
            quality_bucket_reason="agent safely handed off without wrong-topic or unsupported-claim labels",
            quality_bucket_priority=BUCKET_PRIORITY[SAFE_HANDOFF],
        )

    if passed and not labels:
        return QualityBucketResult(
            quality_bucket=AUTO_SENDABLE,
            quality_bucket_reason="passed with no failures and no human review requirement",
            quality_bucket_priority=BUCKET_PRIORITY[AUTO_SENDABLE],
        )

    return QualityBucketResult(
        quality_bucket=AGENT_ERROR,
        quality_bucket_reason="failed replay turn without a knowledge-gap or safe-handoff signal",
        quality_bucket_priority=BUCKET_PRIORITY[AGENT_ERROR],
    )


def _secondary_buckets(labels: set[str], fix_areas: set[str], requires_human_review: bool) -> set[str]:
    buckets = set()
    if labels & AGENT_ERROR_LABELS:
        buckets.add(AGENT_ERROR)
    if labels & CONTEXT_GAP_LABELS:
        buckets.add(CONTEXT_GAP)
    if (labels & KNOWLEDGE_GAP_LABELS) or (fix_areas & KNOWLEDGE_GAP_FIX_AREAS):
        buckets.add(KNOWLEDGE_GAP)
    if requires_human_review or labels & SAFE_HANDOFF_LABELS:
        buckets.add(SAFE_HANDOFF)
    return buckets


def bucket_from_trace(trace: Any, failures: list[Any] | None = None) -> dict[str, Any]:
    raw = trace.get_raw_response() if hasattr(trace, "get_raw_response") else {}
    existing = raw.get("quality_bucket") if isinstance(raw, dict) else {}
    if isinstance(existing, dict) and existing.get("quality_bucket"):
        return sanitize_obj(existing)
    failure_dicts = []
    for failure in failures or []:
        if isinstance(failure, dict):
            failure_dicts.append(failure)
        else:
            failure_dicts.append({
                "failure_type": getattr(failure, "failure_type", ""),
                "suggested_fix_area": getattr(failure, "suggested_fix_area", ""),
            })
    return classify_quality_bucket(
        passed=bool(getattr(trace, "passed", False)),
        requires_human_review=bool(getattr(trace, "requires_human_review", False)),
        failure_labels=trace.get_failure_labels() if hasattr(trace, "get_failure_labels") else [],
        failures=failure_dicts,
        turn_understanding=trace.get_turn_understanding() if hasattr(trace, "get_turn_understanding") else {},
    ).to_dict()


def should_generate_repair_task(bucket: str) -> bool:
    return sanitize_text(bucket) == AGENT_ERROR


def should_generate_knowledge_gap_task(bucket: str) -> bool:
    return sanitize_text(bucket) in {KNOWLEDGE_GAP, CONTEXT_GAP}
