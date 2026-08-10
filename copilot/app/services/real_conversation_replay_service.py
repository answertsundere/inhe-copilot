"""Turn-by-turn replay for sanitized real conversation eval cases."""

import json
import logging
import time
import queue
import threading
import uuid
from dataclasses import dataclass
from typing import Any

from app.services.eval_sanitizer_service import sanitize_obj, sanitize_text
from app.services.real_conversation_quality_bucket_service import classify_quality_bucket
from app.services.real_conversation_turn_understanding_service import (
    RealConversationTurnUnderstandingService,
    detect_reply_topics,
)
from app.services.real_conversation_context_extractor import (
    build_agent_context_from_real_context,
    merge_real_context,
    product_candidates_from_real_context,
    summarize_real_context,
)
from app.services.real_conversation_context_sufficiency_service import assess_context_sufficiency
from app.services.real_conversation_sidecar_context_service import (
    apply_sidecar_to_context_sufficiency,
    build_sidecar_context,
)
from app.services.real_context_product_identity_service import build_conversation_media_reference, merge_product_candidates
from app.services.pgvector_shadow_trace_service import build_pgvector_shadow_trace


logger = logging.getLogger(__name__)


FAILURE_TYPES = {
    "no_product_identified",
    "rag_miss",
    "evidence_misuse",
    "answer_incomplete",
    "semantic_mismatch",
    "unsafe_claim",
    "unsupported_media_claim",
    "needs_human_review",
    "tool_policy_blocked",
    "api_error",
    "turn_understanding_missing",
    "context_insufficient",
    "context_gap",
    "wrong_topic_reply",
    "unrequested_product_fact",
    "query_fact_type_missing",
    "unnecessary_rag_call",
    "encoding_corruption",
    "intent_contract_mismatch",
    "generic_reply_to_actionable_issue",
    "accessory_usage_missed",
    "replay_turn_timeout",
}

FAILURE_REPAIR_GUIDANCE = {
    "rag_miss": {
        "suggested_fix_area": "knowledge_rag",
        "suggested_owner": "knowledge_ops",
        "explanation": "No selected evidence was available for the current product fact question.",
    },
    "evidence_misuse": {
        "suggested_fix_area": "evidence_rerank_answer_composition",
        "suggested_owner": "agent_engineering",
        "explanation": "The answer used evidence fact types that do not match the required fact types.",
    },
    "semantic_mismatch": {
        "suggested_fix_area": "final_audit_semantic_compiler",
        "suggested_owner": "agent_quality",
        "explanation": "The final answer audit reported that the reply did not satisfy the customer question.",
    },
    "unsafe_claim": {
        "suggested_fix_area": "risk_audit",
        "suggested_owner": "risk_policy",
        "explanation": "The reply contains an absolute or unsafe customer-facing claim.",
    },
    "unsupported_media_claim": {
        "suggested_fix_area": "media_pipeline",
        "suggested_owner": "media_ops",
        "explanation": "The reply promised media without a deliverable approved asset.",
    },
    "no_product_identified": {
        "suggested_fix_area": "product_identity_product_data",
        "suggested_owner": "product_data",
        "explanation": "The product identity was not resolved for the current turn.",
    },
    "tool_policy_blocked": {
        "suggested_fix_area": "tool_policy",
        "suggested_owner": "agent_engineering",
        "explanation": "Tool policy blocked the turn before the agent could complete the workflow.",
    },
    "needs_human_review": {
        "suggested_fix_area": "human_policy_risk_boundary",
        "suggested_owner": "customer_service_lead",
        "explanation": "The agent requested human review because the turn is outside the safe auto-reply boundary.",
    },
    "api_error": {
        "suggested_fix_area": "system_stability",
        "suggested_owner": "engineering",
        "explanation": "The replay call failed at the API or service layer.",
    },
    "answer_incomplete": {
        "suggested_fix_area": "answer_composition",
        "suggested_owner": "agent_engineering",
        "explanation": "The agent produced an empty or incomplete reply.",
    },
    "turn_understanding_missing": {
        "suggested_fix_area": "eval_replay_understanding",
        "suggested_owner": "agent_quality",
        "explanation": "The replay turn could not be classified before scoring.",
    },
    "context_insufficient": {
        "suggested_fix_area": "conversation_context",
        "suggested_owner": "agent_quality",
        "explanation": "The buyer turn depends on missing prior text, product, or media context.",
    },
    "context_gap": {
        "suggested_fix_area": "sample_context_extraction",
        "suggested_owner": "data_pipeline",
        "explanation": "The source conversation lacks the order, SKU, or product identity required to score this turn.",
    },
    "wrong_topic_reply": {
        "suggested_fix_area": "final_audit_semantic_compiler",
        "suggested_owner": "agent_quality",
        "explanation": "The reply expands a product topic that the current buyer turn did not ask for.",
    },
    "unrequested_product_fact": {
        "suggested_fix_area": "answer_composition",
        "suggested_owner": "agent_engineering",
        "explanation": "The answer includes product facts that were not requested by the current turn.",
    },
    "query_fact_type_missing": {
        "suggested_fix_area": "query_understanding",
        "suggested_owner": "agent_engineering",
        "explanation": "The turn was scored while query_fact_type was empty despite a product-fact reply.",
    },
    "unnecessary_rag_call": {
        "suggested_fix_area": "replay_turn_routing",
        "suggested_owner": "agent_quality",
        "explanation": "The replay turn did not require RAG, but evidence was still selected.",
    },
    "encoding_corruption": {
        "suggested_fix_area": "data_import_encoding",
        "suggested_owner": "data_pipeline",
        "explanation": "The buyer turn appears to contain corrupted text and cannot be scored reliably.",
    },
    "intent_contract_mismatch": {
        "suggested_fix_area": "query_understanding_final_trace_contract",
        "suggested_owner": "agent_engineering",
        "explanation": "The Agent final trace query_fact_type does not match the replay turn-understanding contract.",
    },
    "generic_reply_to_actionable_issue": {
        "suggested_fix_area": "answer_composition",
        "suggested_owner": "agent_quality",
        "explanation": "The Agent returned a generic fallback instead of answering an actionable buyer issue.",
    },
    "accessory_usage_missed": {
        "suggested_fix_area": "query_understanding",
        "suggested_owner": "agent_engineering",
        "explanation": "The buyer asked how to identify or use an accessory/component, but the turn was not routed to installation support.",
    },
    "replay_turn_timeout": {
        "suggested_fix_area": "replay_stability",
        "suggested_owner": "engineering",
        "explanation": "The eval replay turn hit its hard deadline and was safely routed to human review instead of blocking the run.",
    },
}

FACT_TYPE_COMPATIBILITY_GROUPS = {
    "aftersales": {"aftersales", "aftersales_policy", "after_sales"},
    "installation": {"installation", "accessory_usage"},
    "logistics": {"logistics", "order_status", "delivery_not_received"},
    "promotion": {"promotion", "promotion_policy", "activity_rule", "coupon", "discount", "gift_policy", "price_negotiation"},
}

GENERIC_FALLBACK_REPLY_TERMS = (
    "我在处理",
    "直接说具体问题",
    "重新按事实",
    "稍等确认",
    "核实后回复",
    "没帮到您",
)

SERVICE_ACTION_TERMS_BY_GROUP = {
    "aftersales": ("退款", "退货", "换货", "补发", "售后", "订单", "凭证", "照片", "寄回", "重新发", "少件", "缺件", "错发", "破损"),
    "installation": ("安装", "组装", "配件", "螺丝", "防倒器", "双面贴", "顶板", "底板", "背板", "侧板", "固定", "贴", "装"),
    "logistics": ("物流", "快递", "签收", "派送", "单号", "订单", "驿站", "网点"),
}


def repair_guidance_for_failure(failure_type: str) -> dict[str, str]:
    return dict(FAILURE_REPAIR_GUIDANCE.get(
        failure_type,
        {
            "suggested_fix_area": "manual_triage",
            "suggested_owner": "customer_service_lead",
            "explanation": "The failure type is not mapped yet and needs manual triage.",
        },
    ))


@dataclass
class ReplayOptions:
    limit_cases: int | None = None
    run_uid: str | None = None
    sample_only: bool = False
    case_uids: list[str] | None = None
    turn_uids: list[str] | None = None
    source_type: str = "real_conversation"
    run_metadata: dict[str, Any] | None = None
    eval_sidecar_context: dict[str, Any] | None = None
    eval_sidecar_mode: str = "global"
    disable_external_tools: bool = False
    external_tool_timeout_seconds: int | float = 0
    agent_turn_timeout_seconds: int | float = 0
    progress_log: bool = False
    enable_pgvector_shadow_trace: bool = False
    pgvector_shadow_top_k: int = 5


def _new_run_uid() -> str:
    return f"real_run_{uuid.uuid4().hex[:12]}"


def _agent_turn_timeout_seconds(options: "ReplayOptions") -> float:
    explicit_timeout = float(options.agent_turn_timeout_seconds or 0)
    if explicit_timeout > 0:
        return explicit_timeout
    return 0.0


def _normalize_eval_sidecar_mode(value: str, eval_sidecar_context: dict[str, Any] | None = None) -> str:
    mode = sanitize_text(value).lower()
    if mode in {"none", "global", "per_sample"}:
        return mode
    return "global" if eval_sidecar_context else "none"


def _sidecar_product_mismatch_marker(
    *,
    sidecar_context: dict[str, Any],
    real_context_identity: dict[str, Any],
    sidecar_fixture_used: bool,
) -> str:
    if not sidecar_fixture_used:
        return "unknown"
    sidecar_title = sanitize_text(sidecar_context.get("product_title") or sidecar_context.get("product_name"))
    real_title = sanitize_text(
        real_context_identity.get("product_title")
        or real_context_identity.get("order_product_title")
        or real_context_identity.get("display_product_name")
    )
    if sidecar_title and real_title:
        return "true" if sidecar_title != real_title else "false"
    return "unknown"


def _message_preview(value: str, limit: int = 80) -> str:
    text = sanitize_text(value or "").replace("\n", " ").strip()
    return text[:limit]


def _replay_progress_snapshot(
    *,
    stage: str,
    case_index: int,
    total_cases: int,
    turn_index: int,
    total_turns: int,
    case_uid: str,
    turn_uid: str,
    buyer_message: str,
) -> dict[str, Any]:
    return sanitize_obj({
        "stage": stage,
        "case_index": case_index,
        "total_cases": total_cases,
        "turn_index": turn_index,
        "total_turns": total_turns,
        "case_uid": sanitize_text(case_uid),
        "turn_uid": sanitize_text(turn_uid),
        "buyer_message_preview": _message_preview(buyer_message),
        "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    })


def _record_replay_progress(db: Any, run: Any, progress: dict[str, Any], *, progress_log: bool = False) -> None:
    progress = sanitize_obj(progress)
    if progress_log:
        logger.info("replay_progress=%s", json.dumps(progress, ensure_ascii=True))
    if run is None:
        return
    current = run.get_metadata() if hasattr(run, "get_metadata") else {}
    current["replay_progress_last"] = progress
    run.set_metadata(current)
    db.commit()


def _json_list(value) -> list:
    if isinstance(value, list):
        return value
    if value is None:
        return []
    return [value]


def _extract_query_fact_type(response: dict[str, Any]) -> str:
    evidence_debug = response.get("evidence_debug") or {}
    answer_trace = response.get("answer_trace") or {}
    return str(
        response.get("query_fact_type")
        or evidence_debug.get("query_fact_type")
        or answer_trace.get("query_fact_type")
        or ""
    )


def _fact_type_group(fact_type: str) -> str:
    value = str(fact_type or "")
    for group_name, aliases in FACT_TYPE_COMPATIBILITY_GROUPS.items():
        if value in aliases:
            return group_name
    return value


def _fact_types_compatible(expected: str, actual: str) -> bool:
    if not expected or not actual:
        return False
    return expected == actual or _fact_type_group(expected) == _fact_type_group(actual)


def _has_compatible_fact_type_overlap(left: set[str], right: set[str]) -> bool:
    return any(_fact_types_compatible(a, b) for a in left for b in right)


def get_query_fact_type_contract(
    response: dict[str, Any],
    turn_understanding: dict[str, Any] | None,
) -> dict[str, str]:
    understanding = turn_understanding or {}
    expected = str(understanding.get("expected_query_fact_type") or understanding.get("query_fact_type") or "")
    actual = str(understanding.get("actual_query_fact_type") or _extract_query_fact_type(response) or "")
    effective = expected or actual
    if not expected:
        status = "no_expected"
    elif not actual:
        status = "actual_missing"
    elif _fact_types_compatible(expected, actual):
        status = "matched"
    else:
        status = "mismatch"
    return {
        "expected_query_fact_type": expected,
        "actual_query_fact_type": actual,
        "effective_query_fact_type": effective,
        "intent_contract_status": status,
    }


def enrich_turn_understanding_with_contract(
    response: dict[str, Any],
    turn_understanding: dict[str, Any] | None,
) -> dict[str, Any]:
    enriched = dict(turn_understanding or {})
    enriched.update(get_query_fact_type_contract(response, enriched))
    return enriched


def _extract_required_fact_types(response: dict[str, Any]) -> list:
    answer_trace = response.get("answer_trace") or {}
    evidence_debug = response.get("evidence_debug") or {}
    return _json_list(
        response.get("required_fact_types")
        or answer_trace.get("required_fact_types")
        or evidence_debug.get("required_fact_types")
        or []
    )


def _extract_evidence(response: dict[str, Any]) -> tuple[list, list]:
    evidence_debug = response.get("evidence_debug") or {}
    selected = (
        evidence_debug.get("selected_evidence")
        or evidence_debug.get("evidence_selected")
        or response.get("selected_evidence")
        or _direct_answer_evidence_from_debug(evidence_debug)
        or []
    )
    rejected = (
        evidence_debug.get("rejected_evidence")
        or evidence_debug.get("evidence_rejected")
        or response.get("rejected_evidence")
        or []
    )
    return _json_list(sanitize_obj(selected)), _json_list(sanitize_obj(rejected))


def _direct_answer_evidence_from_debug(evidence_debug: dict[str, Any]) -> list:
    if not isinstance(evidence_debug, dict):
        return []
    rows: list[dict[str, Any]] = []
    for key in ("knowledge_evidence_summary", "filtered_evidence_summary"):
        items = evidence_debug.get(key)
        if isinstance(items, list):
            rows.extend(item for item in items if _is_direct_answer_evidence(item))

    summary = evidence_debug.get("product_context_pack_summary")
    if isinstance(summary, dict):
        for pack_key in ("product_first_evidence_pack", "evidence_pack"):
            pack = summary.get(pack_key)
            if not isinstance(pack, dict):
                continue
            for bucket in ("product_structured_facts", "product_scoped_chunks"):
                items = pack.get(bucket)
                if isinstance(items, list):
                    rows.extend(item for item in items if _is_direct_answer_evidence(item))
    return rows


def _is_direct_answer_evidence(item: Any) -> bool:
    if not isinstance(item, dict):
        return False
    if _is_placeholder_verification_evidence(item):
        return False
    if item.get("reference_only") is True:
        return False
    if str(item.get("gate_status") or "").lower() in {"blocked", "reference_only"}:
        return False
    for key in ("direct_answer_allowed", "can_direct_answer", "evidence_allowed_for_exact_answer"):
        if item.get(key) is False:
            return False
    # IDs are useful for traceability, but they do not prove the evidence can
    # answer the buyer. Replay scoring should only treat evidence with actual
    # customer-facing content as direct-answerable.
    return bool(
        item.get("chunk_text")
        or item.get("chunk_preview")
        or item.get("preview")
        or item.get("content")
        or item.get("fact")
    )


_PLACEHOLDER_VERIFICATION_EVIDENCE_MARKERS = (
    "\u9700\u8981\u4eba\u5de5\u6838\u5b9e",
    "\u4eba\u5de5\u590d\u6838",
    "\u672a\u5728\u73b0\u6709\u7ed3\u6784\u5316\u8d44\u6599\u4e2d\u660e\u786e",
    "\u672a\u660e\u786e",
    "\u4ee5\u5546\u54c1\u8be6\u60c5\u9875",
    "\u4ee5\u5b9e\u7269",
)


_MEDIA_DELIVERY_EVIDENCE_MARKERS = (
    "\u4e0b\u9762\u53d1",
    "\u4e0b\u9762\u53d1\u9001",
    "\u53d1\u60a8",
    "\u5df2\u53d1\u60a8",
    "\u56fe\u7247",
    "\u5c3a\u5bf8\u56fe",
    "\u89c4\u683c\u56fe",
    "\u5b89\u88c5\u56fe",
    "\u5b89\u88c5\u89c6\u9891",
    "\u89c6\u9891",
    "\u8bf4\u660e\u4e66",
)


def _evidence_text(item: Any) -> str:
    if not isinstance(item, dict):
        return ""
    return str(
        item.get("chunk_text")
        or item.get("chunk_preview")
        or item.get("preview")
        or item.get("content")
        or item.get("fact")
        or ""
    )


def _is_placeholder_verification_evidence(item: Any) -> bool:
    text = _evidence_text(item)
    if not text:
        return False
    return any(marker in text for marker in _PLACEHOLDER_VERIFICATION_EVIDENCE_MARKERS)


def _is_media_delivery_evidence(item: Any) -> bool:
    if not isinstance(item, dict):
        return False
    identity = " ".join(
        str(item.get(key) or "")
        for key in ("evidence_id", "chunk_id", "entry_id", "source_id", "source_type", "protocol_source_type")
    ).lower()
    text = _evidence_text(item)
    return (
        "kbmedia:" in identity
        or "media" in identity
        or "\u56fe" in identity
        or "\u89c6\u9891" in identity
    ) and any(marker in text for marker in _MEDIA_DELIVERY_EVIDENCE_MARKERS)


def _has_reply_media_delivery(response: dict[str, Any] | None) -> bool:
    if not isinstance(response, dict):
        return False
    for block in response.get("reply_blocks") or []:
        if not isinstance(block, dict):
            continue
        block_type = str(block.get("type") or block.get("block_type") or "").lower()
        if block_type in {"image", "video"} and (
            block.get("asset_url") or block.get("url") or block.get("media_url")
        ):
            return True
    for asset in response.get("recommended_assets") or []:
        if not isinstance(asset, dict):
            continue
        if asset.get("asset_url") or asset.get("url") or asset.get("media_url"):
            return True
    return False


def _has_direct_answerable_evidence(items: list[Any], response: dict[str, Any] | None = None) -> bool:
    has_media_delivery = _has_reply_media_delivery(response)
    for item in items or []:
        if not _is_direct_answer_evidence(item):
            continue
        if _is_media_delivery_evidence(item) and not has_media_delivery:
            continue
        return True
    return False


def _extract_product_identity(response: dict[str, Any]) -> dict:
    context_used = response.get("context_used") or {}
    evidence_debug = response.get("evidence_debug") or {}
    return sanitize_obj({
        "product_name": response.get("product_name") or context_used.get("product_name") or "",
        "sku_code": response.get("sku_code") or evidence_debug.get("sku_code") or "",
        "i_id": response.get("i_id") or evidence_debug.get("i_id") or "",
        "product_candidates_count": len(response.get("product_candidates") or []),
    })


def _real_context_for_turn(case, turn) -> dict[str, Any]:
    try:
        case_context = (case.get_metadata() or {}).get("real_context") or {}
    except Exception:
        case_context = {}
    try:
        turn_context = (turn.get_metadata() or {}).get("real_context") or {}
    except Exception:
        turn_context = {}
    return merge_real_context(case_context, turn_context)


def _is_generic_fallback_reply(reply: str) -> bool:
    value = str(reply or "")
    return any(term in value for term in GENERIC_FALLBACK_REPLY_TERMS)


def _has_explicit_service_action(reply: str, expected_query_fact_type: str) -> bool:
    value = str(reply or "")
    group = _fact_type_group(expected_query_fact_type)
    terms = SERVICE_ACTION_TERMS_BY_GROUP.get(group, ())
    return any(term in value for term in terms)


def classify_turn_failures(response: dict[str, Any], exception: Exception | None = None) -> list[dict[str, str]]:
    if exception is not None:
        return [{"failure_type": "api_error", "severity": "high", "message": sanitize_text(str(exception))}]
    failures: list[dict[str, str]] = []
    reply = str(response.get("suggested_reply") or response.get("reply") or "")
    query_fact_type = _extract_query_fact_type(response)
    selected, _ = _extract_evidence(response)
    has_answerable_evidence = _has_direct_answerable_evidence(selected, response)
    answer_trace = response.get("answer_trace") or {}
    final_audit = response.get("final_answer_audit") or response.get("final_audit") or {}
    evidence_debug = response.get("evidence_debug") or {}
    agent_turn_timed_out = bool((evidence_debug.get("agent_turn_timeout") or {}).get("timed_out"))
    if response.get("error"):
        failures.append({"failure_type": "api_error", "severity": "high", "message": sanitize_text(response.get("error"))})
    if agent_turn_timed_out:
        timeout_stage = sanitize_text((evidence_debug.get("agent_turn_timeout") or {}).get("stage") or "agent_call")
        failures.append({
            "failure_type": "replay_turn_timeout",
            "severity": "medium",
            "message": f"replay turn timed out at {timeout_stage}",
        })
    if response.get("tool_policy_blocked") or response.get("policy_blocked"):
        failures.append({"failure_type": "tool_policy_blocked", "severity": "medium", "message": "tool policy blocked the turn"})
    if (
        isinstance(final_audit, dict)
        and final_audit.get("passed") is False
        and not (response.get("requires_human_review") and not has_answerable_evidence)
    ):
        failures.append({"failure_type": "semantic_mismatch", "severity": "high", "message": "final answer audit did not pass"})
    if (
        response.get("product_identified") is False
        or evidence_debug.get("product_identified") is False
        or str(evidence_debug.get("product_resolution_status") or "") == "not_found"
    ):
        failures.append({"failure_type": "no_product_identified", "severity": "medium", "message": "product identity was not resolved"})
    if response.get("requires_human_review"):
        failures.append({"failure_type": "needs_human_review", "severity": "medium", "message": "agent requested human review"})
    if not reply.strip() and not response.get("skipped_agent_reply") and not agent_turn_timed_out:
        failures.append({"failure_type": "answer_incomplete", "severity": "high", "message": "empty agent reply"})
    unsafe_terms = ("绝对安全", "完全无害", "0甲醛", "零甲醛", "宝宝可以直接用")
    if _contains_unnegated_unsafe_claim(reply, unsafe_terms):
        failures.append({"failure_type": "unsafe_claim", "severity": "high", "message": "reply contains unsafe absolute claim"})
    media_terms = ("我把视频发您", "我把图片发您", "下面发您", "已发您视频", "已发您图片")
    if any(term in reply for term in media_terms) and not response.get("recommended_assets"):
        failures.append({"failure_type": "unsupported_media_claim", "severity": "medium", "message": "reply promises media without attached asset"})
    required = set(str(x) for x in _extract_required_fact_types(response) if x)
    if (
        query_fact_type
        and query_fact_type not in {"logistics", "order_status", "after_sales", "aftersales", "aftersales_policy"}
        and not has_answerable_evidence
        and not agent_turn_timed_out
    ):
        failures.append({"failure_type": "rag_miss", "severity": "medium", "message": "product question has no selected evidence"})
    answered = set(str(x) for x in _json_list(answer_trace.get("evidence_answered_fact_types")) if x)
    if (
        required
        and answered
        and not _has_compatible_fact_type_overlap(required, answered)
        and not (response.get("requires_human_review") and not has_answerable_evidence)
    ):
        failures.append({"failure_type": "evidence_misuse", "severity": "medium", "message": "answered fact types do not overlap required fact types"})
    enriched = []
    for failure in failures:
        failure_type = failure.get("failure_type", "api_error")
        enriched.append({**repair_guidance_for_failure(failure_type), **failure})
    return enriched


def _contains_unnegated_unsafe_claim(reply: str, unsafe_terms: tuple[str, ...]) -> bool:
    negation_markers = (
        "不说",
        "不能说",
        "不会说",
        "不直接承诺",
        "不承诺",
        "不能承诺",
        "不会承诺",
        "不得承诺",
        "不要承诺",
        "不保证",
        "不能保证",
        "不会保证",
        "不敢保证",
        "不建议承诺",
    )
    for term in unsafe_terms:
        start = 0
        while True:
            idx = reply.find(term, start)
            if idx < 0:
                break
            prefix = reply[max(0, idx - 14):idx]
            if not any(marker in prefix for marker in negation_markers):
                return True
            start = idx + len(term)
    return False


def evaluate_replay_turn_result(
    turn_understanding: dict[str, Any] | None,
    response: dict[str, Any],
    failures: list[dict[str, str]],
    exception: Exception | None = None,
) -> tuple[bool, list[dict[str, str]]]:
    """Apply replay-specific scoring rules on top of Agent failures."""
    all_failures = list(failures or [])
    understanding = turn_understanding or {}
    if not understanding:
        all_failures.append({
            "failure_type": "turn_understanding_missing",
            "severity": "high",
            "message": "turn understanding is missing",
        })
    if exception is not None:
        return False, _enrich_failures(all_failures)

    should_score = bool(understanding.get("should_score"))
    if not should_score:
        return False, _enrich_failures(all_failures)

    reply = str(response.get("suggested_reply") or response.get("reply") or "")
    reply_topics = set(detect_reply_topics(reply))
    contract = get_query_fact_type_contract(response, understanding)
    expected_query_fact_type = contract["expected_query_fact_type"]
    actual_query_fact_type = contract["actual_query_fact_type"]
    query_fact_type = contract["effective_query_fact_type"]
    required_fact_types = set(str(item) for item in _extract_required_fact_types(response) if item)
    selected, _ = _extract_evidence(response)
    has_answerable_evidence = _has_direct_answerable_evidence(selected, response)
    actionability = str(understanding.get("turn_actionability") or "")
    forbidden_topics = set(str(item) for item in (understanding.get("forbidden_reply_topics") or []) if item)
    skip_reason = str(understanding.get("skip_reason") or "")

    if skip_reason == "encoding_corruption":
        all_failures.append({
            "failure_type": "encoding_corruption",
            "severity": "high",
            "message": "buyer message appears encoding-corrupted",
        })
    elif skip_reason == "context_insufficient":
        all_failures.append({
            "failure_type": "context_insufficient",
            "severity": "medium",
            "message": "turn requires prior context that is unavailable",
        })

    if not bool(understanding.get("needs_rag")) and selected:
        all_failures.append({
            "failure_type": "unnecessary_rag_call",
            "severity": "medium",
            "message": "selected evidence exists for a turn that should not use RAG",
        })

    if not bool(understanding.get("needs_rag")) and reply_topics & forbidden_topics:
        all_failures.append({
            "failure_type": "wrong_topic_reply",
            "severity": "high",
            "message": "reply expands forbidden product topics for this turn",
        })

    if actionability != "actionable_question" and reply_topics:
        final_audit = response.get("final_answer_audit") or response.get("final_audit") or {}
        expected_topics = final_audit.get("expected_topics") if isinstance(final_audit, dict) else []
        if not expected_topics:
            all_failures.append({
                "failure_type": "wrong_topic_reply",
                "severity": "high",
                "message": "final audit had no expected topics but reply contains product topics",
            })

    if expected_query_fact_type and not actual_query_fact_type and not _has_explicit_service_action(reply, expected_query_fact_type) and not response.get("requires_human_review"):
        all_failures.append({
            "failure_type": "query_fact_type_missing",
            "severity": "high",
            "message": "Agent final trace dropped query_fact_type required by turn understanding",
        })

    if contract["intent_contract_status"] == "mismatch":
        all_failures.append({
            "failure_type": "intent_contract_mismatch",
            "severity": "high",
            "message": f"expected {expected_query_fact_type}, actual {actual_query_fact_type}",
        })

    if (
        actionability == "actionable_question"
        and expected_query_fact_type
        and _is_generic_fallback_reply(reply)
        and not selected
        and not _has_explicit_service_action(reply, expected_query_fact_type)
        and not response.get("requires_human_review")
    ):
        all_failures.append({
            "failure_type": "generic_reply_to_actionable_issue",
            "severity": "high",
            "message": "generic fallback reply was used for an actionable buyer issue",
        })

    if not actual_query_fact_type and reply_topics and not expected_query_fact_type:
        all_failures.append({
            "failure_type": "query_fact_type_missing",
            "severity": "high",
            "message": "query_fact_type is empty while reply contains product fact topics",
        })
        all_failures.append({
            "failure_type": "unrequested_product_fact",
            "severity": "high",
            "message": "reply contains product facts not grounded in the current turn intent",
        })

    if bool(understanding.get("needs_rag")) and not has_answerable_evidence and not response.get("requires_human_review"):
        all_failures.append({
            "failure_type": "rag_miss",
            "severity": "medium",
            "message": "turn needs RAG but no selected evidence or human-review fallback exists",
        })

    if (
        required_fact_types
        and reply_topics
        and query_fact_type
        and not _has_compatible_fact_type_overlap(reply_topics, required_fact_types)
        and not (response.get("requires_human_review") and not has_answerable_evidence)
    ):
        all_failures.append({
            "failure_type": "evidence_misuse",
            "severity": "medium",
            "message": "reply product topics do not overlap required fact types",
        })

    enriched = _enrich_failures(all_failures)
    return not enriched, enriched


def _enrich_failures(failures: list[dict[str, str]]) -> list[dict[str, str]]:
    enriched = []
    seen = set()
    for failure in failures:
        failure_type = failure.get("failure_type", "api_error")
        key = (failure_type, failure.get("message", ""))
        if key in seen:
            continue
        seen.add(key)
        enriched.append({**repair_guidance_for_failure(failure_type), **failure})
    return enriched


class RealConversationReplayService:
    def __init__(self, turn_understanding_service: RealConversationTurnUnderstandingService | None = None):
        self.turn_understanding_service = turn_understanding_service or RealConversationTurnUnderstandingService()

    def _call_agent(self, payload: dict[str, Any]) -> dict[str, Any]:
        from app.main import get_reply_service
        from app.services.analysis_pipeline_service import AnalysisPipelineRequest, AnalysisPipelineService

        response = AnalysisPipelineService().run(
            AnalysisPipelineRequest(
                reply_service=get_reply_service(),
                customer_message=payload.get("message", ""),
                delivery_message=payload.get("message", ""),
                conversation_id=payload.get("conversation_id", "real_conversation_eval"),
                product_name=payload.get("product_name", ""),
                copilot_context=payload.get("copilot_context") or {},
                source="real_conversation_eval",
                scenario="daily_replay",
            )
        )
        return response

    def _call_agent_with_replay_timeout(self, payload: dict[str, Any], timeout_seconds: float) -> dict[str, Any]:
        if timeout_seconds <= 0:
            return self._call_agent(payload)

        result_queue: queue.Queue = queue.Queue(maxsize=1)

        def _target() -> None:
            try:
                result_queue.put(("result", self._call_agent(payload)), block=False)
            except Exception as exc:
                result_queue.put(("error", exc), block=False)

        thread = threading.Thread(target=_target, daemon=True)
        thread.start()
        thread.join(timeout_seconds)
        if thread.is_alive():
            return self._agent_timeout_response(payload, timeout_seconds)
        kind, value = result_queue.get_nowait()
        if kind == "error":
            raise value
        return value or {}

    def _agent_timeout_response(self, payload: dict[str, Any], timeout_seconds: float) -> dict[str, Any]:
        copilot_context = payload.get("copilot_context") or {}
        turn_understanding = copilot_context.get("turn_understanding") or {}
        query_fact_type = str(turn_understanding.get("query_fact_type") or "")
        eval_replay_options = copilot_context.get("eval_replay_options") or {}
        progress = sanitize_obj(copilot_context.get("replay_progress") or {})
        timeout_stage = sanitize_text(progress.get("stage") or "agent_call")
        reason = "agent_turn_timeout_for_replay"
        draft_reply = "亲，这条需要我再核对一下资料和订单情况，避免给您说错，我确认后再给您准确回复。"
        return {
            "suggested_reply": draft_reply,
            "draft_reply": draft_reply,
            "sendable_reply": "",
            "can_send": False,
            "requires_human_review": True,
            "reply_status": "needs_human_review",
            "reason_for_review": reason,
            "block_reasons": [reason],
            "query_fact_type": query_fact_type,
            "evidence_debug": {
                "query_fact_type": query_fact_type,
                "external_tool_control": eval_replay_options,
                "agent_turn_timeout": {
                    "timed_out": True,
                    "timeout_seconds": timeout_seconds,
                    "stage": timeout_stage,
                    "progress": progress,
                    "reason": reason,
                },
                "selected_evidence": [],
            },
            "answer_trace": {
                "query_fact_type": query_fact_type,
                "required_fact_types": [query_fact_type] if query_fact_type else [],
                "agent_turn_timeout": True,
                "replay_turn_timeout": True,
                "timeout_seconds": timeout_seconds,
                "timeout_stage": timeout_stage,
                "replay_progress": progress,
                "reason": reason,
            },
        }

    def replay_cases(self, options: ReplayOptions | None = None) -> dict[str, Any]:
        from app.db import SessionLocal
        from app.models.eval_tables import EvalCase, EvalConversationTurn, EvalFailure, EvalRun, EvalTrace

        options = options or ReplayOptions()
        run_uid = options.run_uid or _new_run_uid()
        case_uid_filter = set(options.case_uids or [])
        turn_uid_filter = set(options.turn_uids or [])
        eval_sidecar_context = sanitize_obj(options.eval_sidecar_context or {})
        eval_sidecar_mode = _normalize_eval_sidecar_mode(options.eval_sidecar_mode, eval_sidecar_context)
        eval_replay_options = sanitize_obj({
            "disable_external_tools": bool(options.disable_external_tools),
            "external_tool_timeout_seconds": float(options.external_tool_timeout_seconds or 0),
            "agent_turn_timeout_seconds": _agent_turn_timeout_seconds(options),
            "progress_log": bool(options.progress_log),
            "enable_pgvector_shadow_trace": bool(options.enable_pgvector_shadow_trace),
            "pgvector_shadow_top_k": max(1, min(int(options.pgvector_shadow_top_k or 5), 20)),
            "eval_sidecar_mode": eval_sidecar_mode,
        })
        db = SessionLocal()
        try:
            query = (
                db.query(EvalCase)
                .filter(EvalCase.source_type == "real_conversation", EvalCase.status == "active")
                .order_by(EvalCase.id.asc())
            )
            if case_uid_filter:
                query = query.filter(EvalCase.case_uid.in_(case_uid_filter))
            if options.limit_cases:
                query = query.limit(options.limit_cases)
            cases = query.all()
            run = EvalRun(run_uid=run_uid, source_type=options.source_type or "real_conversation", status="running")
            run.total_cases = len(cases)
            run.set_metadata({
                "sample_only": options.sample_only,
                **sanitize_obj(options.run_metadata or {}),
                "eval_sidecar_context": eval_sidecar_context,
                "eval_sidecar_mode": eval_sidecar_mode,
                "eval_replay_options": eval_replay_options,
            })
            db.add(run)
            db.commit()

            totals = {
                "passed": 0,
                "failed": 0,
                "requires_review": 0,
                "turns": 0,
                "agent_accuracy_turns": 0,
                "agent_accuracy_passed": 0,
                "agent_accuracy_failed": 0,
                "context_gap": 0,
                "replay_turn_timeout_count": 0,
                "pgvector_shadow_enabled_trace_count": 0,
                "pgvector_shadow_available_count": 0,
                "pgvector_shadow_error_count": 0,
                "pgvector_product_fact_hit_count": 0,
                "pgvector_direct_answerable_count": 0,
                "pgvector_service_action_hit_count": 0,
                "pgvector_media_reference_hit_count": 0,
                "current_sqlite_no_evidence_but_pgvector_direct_count": 0,
                "current_sqlite_safe_handoff_but_pgvector_service_action_count": 0,
                "pgvector_media_reference_without_reply_blocks_count": 0,
            }
            if options.sample_only:
                run.status = "sampled"
                run.total_turns = 0
                db.commit()
                return {"run_uid": run_uid, "status": run.status, "total_cases": len(cases), **totals}

            for case_index, case in enumerate(cases, start=1):
                turns = (
                    db.query(EvalConversationTurn)
                    .filter(EvalConversationTurn.case_uid == case.case_uid)
                    .order_by(EvalConversationTurn.turn_index.asc())
                    .all()
                )
                history: list[dict[str, str]] = []
                for turn in turns:
                    history.append({"speaker": turn.speaker, "text": turn.sanitized_text})
                    if turn.speaker != "buyer":
                        continue
                    if turn_uid_filter and turn.turn_uid not in turn_uid_filter:
                        continue
                    conversation_history = history[:-1]
                    real_context = _real_context_for_turn(case, turn)
                    agent_real_context = build_agent_context_from_real_context(real_context)
                    sidecar_fixture_used = bool(eval_sidecar_context and eval_sidecar_mode == "global")
                    if sidecar_fixture_used:
                        agent_real_context.update(eval_sidecar_context)
                    product_name = turn.product_hint or agent_real_context.get("product_name", "")
                    case_metadata = case.get_metadata() or {}
                    turn_metadata = turn.get_metadata() or {}
                    preliminary_sidecar_context = build_sidecar_context(
                        case_metadata=case_metadata,
                        turn_metadata=turn_metadata,
                        real_context=real_context,
                        agent_context=agent_real_context,
                        buyer_message=turn.sanitized_text,
                        product_hint=product_name,
                    )
                    product_name = preliminary_sidecar_context.get("product_name") or product_name
                    product_candidates = merge_product_candidates(
                        preliminary_sidecar_context.get("product_candidates") or [],
                        product_candidates_from_real_context(real_context),
                    )
                    real_context_summary = summarize_real_context(real_context)
                    real_context_identity = agent_real_context.get("real_context_product_identity") or {}
                    conversation_media_reference = build_conversation_media_reference(agent_real_context)
                    progress = _replay_progress_snapshot(
                        stage="turn_understanding",
                        case_index=case_index,
                        total_cases=len(cases),
                        turn_index=turn.turn_index,
                        total_turns=len(turns),
                        case_uid=case.case_uid,
                        turn_uid=turn.turn_uid,
                        buyer_message=turn.sanitized_text,
                    )
                    if options.progress_log:
                        _record_replay_progress(db, run, progress, progress_log=True)
                    turn_understanding = self.turn_understanding_service.understand(
                        turn.sanitized_text,
                        history=conversation_history,
                        message_type=turn.message_type,
                        product_hint=product_name,
                    )
                    sidecar_context = build_sidecar_context(
                        case_metadata=case_metadata,
                        turn_metadata=turn_metadata,
                        real_context=real_context,
                        agent_context=agent_real_context,
                        turn_understanding=turn_understanding,
                        buyer_message=turn.sanitized_text,
                        product_hint=product_name,
                    )
                    product_name = sidecar_context.get("product_name") or product_name
                    product_candidates = merge_product_candidates(
                        sidecar_context.get("product_candidates") or [],
                        product_candidates,
                    )
                    context_sufficiency = assess_context_sufficiency(
                        turn_understanding=turn_understanding,
                        real_context_summary=real_context_summary,
                        real_context_identity=real_context_identity,
                    ).to_dict()
                    context_sufficiency = apply_sidecar_to_context_sufficiency(context_sufficiency, sidecar_context)
                    sidecar_product_mismatch = _sidecar_product_mismatch_marker(
                        sidecar_context=sidecar_context,
                        real_context_identity=real_context_identity,
                        sidecar_fixture_used=sidecar_fixture_used,
                    )
                    eval_fixture_gap = sidecar_fixture_used and sidecar_product_mismatch == "true"
                    turn_understanding["context_sufficiency"] = context_sufficiency
                    turn_understanding["sidecar_context_quality"] = sidecar_context.get("sidecar_context_quality", "")
                    turn_understanding["sidecar_context_sources"] = sidecar_context.get("sidecar_context_sources", [])
                    turn_understanding["missing_context_fields"] = sidecar_context.get("missing_context_fields", [])
                    turn_understanding["has_sidecar_product_context"] = bool(sidecar_context.get("has_sidecar_product_context"))
                    turn_understanding["has_sidecar_order_context"] = bool(sidecar_context.get("has_sidecar_order_context"))
                    turn_understanding["sidecar_mode"] = eval_sidecar_mode
                    turn_understanding["sidecar_fixture_used"] = sidecar_fixture_used
                    turn_understanding["sidecar_product_mismatch"] = sidecar_product_mismatch
                    turn_understanding["eval_fixture_gap"] = eval_fixture_gap
                    should_score = bool(turn_understanding.get("should_score"))
                    if should_score:
                        totals["turns"] += 1
                    payload = {
                        "message": turn.sanitized_text,
                        "conversation_id": f"real_eval_{case.case_uid}",
                        "product_name": product_name,
                        "product_title": sidecar_context.get("product_title") or product_name,
                        "sku_code": sidecar_context.get("sku_code") or agent_real_context.get("sku_code", ""),
                        "i_id": sidecar_context.get("i_id") or agent_real_context.get("i_id", ""),
                        "product_candidates": product_candidates,
                        "order_id": sidecar_context.get("order_id") or agent_real_context.get("order_id", ""),
                        "platform_order_id": sidecar_context.get("platform_order_id") or "",
                        "tracking_no": agent_real_context.get("tracking_no", ""),
                        "copilot_context": {
                            **agent_real_context,
                            "conversation_history": conversation_history,
                            "eval_case_uid": case.case_uid,
                            "eval_turn_uid": turn.turn_uid,
                            "source_type": "real_conversation",
                            "turn_understanding": turn_understanding,
                            "sidecar_context": sidecar_context,
                            "sidecar_context_quality": sidecar_context.get("sidecar_context_quality", ""),
                            "sidecar_context_sources": sidecar_context.get("sidecar_context_sources", []),
                            "missing_context_fields": sidecar_context.get("missing_context_fields", []),
                            "has_sidecar_product_context": bool(sidecar_context.get("has_sidecar_product_context")),
                            "has_sidecar_order_context": bool(sidecar_context.get("has_sidecar_order_context")),
                            "sidecar_mode": eval_sidecar_mode,
                            "sidecar_fixture_used": sidecar_fixture_used,
                            "sidecar_product_mismatch": sidecar_product_mismatch,
                            "eval_fixture_gap": eval_fixture_gap,
                            "product_candidates": product_candidates,
                            "product_name": product_name,
                            "product_title": sidecar_context.get("product_title") or product_name,
                            "sku_code": sidecar_context.get("sku_code") or agent_real_context.get("sku_code", ""),
                            "i_id": sidecar_context.get("i_id") or agent_real_context.get("i_id", ""),
                            "order_id": sidecar_context.get("order_id") or agent_real_context.get("order_id", ""),
                            "platform_order_id": sidecar_context.get("platform_order_id") or "",
                            "eval_replay_options": eval_replay_options,
                        },
                    }
                    progress = _replay_progress_snapshot(
                        stage="agent_call" if turn_understanding.get("needs_agent_reply") else "scoring",
                        case_index=case_index,
                        total_cases=len(cases),
                        turn_index=turn.turn_index,
                        total_turns=len(turns),
                        case_uid=case.case_uid,
                        turn_uid=turn.turn_uid,
                        buyer_message=turn.sanitized_text,
                    )
                    payload["copilot_context"]["replay_progress"] = progress
                    if options.progress_log or float(eval_replay_options.get("agent_turn_timeout_seconds") or 0) > 0:
                        _record_replay_progress(db, run, progress, progress_log=bool(options.progress_log))
                    started = time.time()
                    exception = None
                    response: dict[str, Any] = {}
                    if turn_understanding.get("needs_agent_reply"):
                        try:
                            response = self._call_agent_with_replay_timeout(
                                payload,
                                float(eval_replay_options.get("agent_turn_timeout_seconds") or 0),
                            ) or {}
                        except Exception as exc:
                            exception = exc
                            response = {"error": str(exc)}
                    else:
                        response = {
                            "suggested_reply": "",
                            "skipped_agent_reply": True,
                            "requires_human_review": False,
                            "query_fact_type": turn_understanding.get("query_fact_type", ""),
                            "answer_trace": {
                                "turn_actionability": turn_understanding.get("turn_actionability"),
                                "reply_strategy": turn_understanding.get("reply_strategy"),
                                "skip_reason": turn_understanding.get("skip_reason", ""),
                            },
                        }
                    latency_ms = int((time.time() - started) * 1000)
                    if options.progress_log or float(eval_replay_options.get("agent_turn_timeout_seconds") or 0) > 0:
                        _record_replay_progress(db, run, {
                            **progress,
                            "stage": "scoring",
                            "elapsed_ms": latency_ms,
                        }, progress_log=bool(options.progress_log))
                    turn_understanding = enrich_turn_understanding_with_contract(response, turn_understanding)
                    intent_contract = {
                        "expected_query_fact_type": turn_understanding.get("expected_query_fact_type", ""),
                        "actual_query_fact_type": turn_understanding.get("actual_query_fact_type", ""),
                        "effective_query_fact_type": turn_understanding.get("effective_query_fact_type", ""),
                        "intent_contract_status": turn_understanding.get("intent_contract_status", ""),
                    }
                    base_failures = classify_turn_failures(response, exception) if should_score else []
                    passed, failures = evaluate_replay_turn_result(turn_understanding, response, base_failures, exception)
                    if should_score and context_sufficiency.get("is_sufficient") is False:
                        failures = _enrich_failures([
                            *failures,
                            {
                                "failure_type": "context_gap",
                                "severity": "medium",
                                "message": context_sufficiency.get("reason") or "source conversation lacks required context",
                            },
                        ])
                        passed = False
                    labels = [f["failure_type"] for f in failures]
                    if "replay_turn_timeout" in labels:
                        totals["replay_turn_timeout_count"] += 1
                    quality_bucket = classify_quality_bucket(
                        passed=passed,
                        requires_human_review=bool(response.get("requires_human_review")),
                        failure_labels=labels,
                        failures=failures,
                        turn_understanding=turn_understanding,
                    ).to_dict()
                    if should_score and response.get("requires_human_review"):
                        totals["requires_review"] += 1
                    if quality_bucket.get("quality_bucket") == "context_gap":
                        totals["context_gap"] += 1
                    if quality_bucket.get("should_count_in_quality_rate") is not False:
                        totals["agent_accuracy_turns"] += 1
                        if labels:
                            totals["agent_accuracy_failed"] += 1
                        else:
                            totals["agent_accuracy_passed"] += 1
                    if not should_score:
                        pass
                    elif labels:
                        totals["failed"] += 1
                    else:
                        totals["passed"] += 1

                    selected, rejected = _extract_evidence(response)
                    pgvector_shadow = {}
                    if bool(eval_replay_options.get("enable_pgvector_shadow_trace")):
                        pgvector_shadow = build_pgvector_shadow_trace(
                            query_text=turn.sanitized_text,
                            query_fact_type=turn_understanding.get("effective_query_fact_type")
                            or turn_understanding.get("query_fact_type")
                            or _extract_query_fact_type(response),
                            sidecar=sidecar_context,
                            top_k=int(eval_replay_options.get("pgvector_shadow_top_k") or 5),
                        )
                        totals["pgvector_shadow_enabled_trace_count"] += 1
                        if pgvector_shadow.get("available"):
                            totals["pgvector_shadow_available_count"] += 1
                        if pgvector_shadow.get("error"):
                            totals["pgvector_shadow_error_count"] += 1
                        product_fact = pgvector_shadow.get("product_fact") or {}
                        service_action = pgvector_shadow.get("service_action") or {}
                        media_reference = pgvector_shadow.get("media_reference") or {}
                        if int(product_fact.get("candidate_count") or 0) > 0:
                            totals["pgvector_product_fact_hit_count"] += 1
                        if int(product_fact.get("direct_answerable_count") or 0) > 0:
                            totals["pgvector_direct_answerable_count"] += 1
                            if not selected:
                                totals["current_sqlite_no_evidence_but_pgvector_direct_count"] += 1
                        if int(service_action.get("hit_count") or 0) > 0:
                            totals["pgvector_service_action_hit_count"] += 1
                            if quality_bucket.get("quality_bucket") == "safe_handoff":
                                totals["current_sqlite_safe_handoff_but_pgvector_service_action_count"] += 1
                        if int(media_reference.get("candidate_count") or 0) > 0:
                            totals["pgvector_media_reference_hit_count"] += 1
                            if not _has_reply_media_delivery(response):
                                totals["pgvector_media_reference_without_reply_blocks_count"] += 1
                    trace = EvalTrace(
                        run_uid=run_uid,
                        case_uid=case.case_uid,
                        turn_uid=turn.turn_uid,
                        turn_index=turn.turn_index,
                        buyer_message=turn.sanitized_text,
                        reference_human_reply=turn.reference_human_reply,
                        agent_reply=sanitize_text(response.get("suggested_reply") or response.get("reply") or ""),
                        query_fact_type=turn_understanding.get("effective_query_fact_type") or _extract_query_fact_type(response),
                        requires_human_review=bool(response.get("requires_human_review")),
                        latency_ms=latency_ms,
                        order_identity_hash=turn.order_hint_hash,
                        passed=passed,
                    )
                    trace.set_turn_understanding(sanitize_obj(turn_understanding))
                    trace.set_required_fact_types(_extract_required_fact_types(response))
                    trace.set_selected_evidence(selected)
                    trace.set_rejected_evidence(rejected)
                    trace.set_answer_trace(sanitize_obj({
                        **(response.get("answer_trace") or {}),
                        **intent_contract,
                        "real_context": real_context_summary,
                        "real_context_product_identity": real_context_identity,
                        "sidecar_context": sidecar_context,
                        "sidecar_context_quality": sidecar_context.get("sidecar_context_quality", ""),
                        "sidecar_context_sources": sidecar_context.get("sidecar_context_sources", []),
                        "missing_context_fields": sidecar_context.get("missing_context_fields", []),
                        "has_sidecar_product_context": bool(sidecar_context.get("has_sidecar_product_context")),
                        "has_sidecar_order_context": bool(sidecar_context.get("has_sidecar_order_context")),
                        "sidecar_mode": eval_sidecar_mode,
                        "sidecar_fixture_used": sidecar_fixture_used,
                        "sidecar_product_mismatch": sidecar_product_mismatch,
                        "eval_fixture_gap": eval_fixture_gap,
                        "conversation_media_reference": conversation_media_reference,
                        "eval_replay_options": eval_replay_options,
                        **({"pgvector_shadow": pgvector_shadow} if pgvector_shadow else {}),
                    }))
                    trace.set_final_audit(sanitize_obj(response.get("final_answer_audit") or response.get("final_audit") or {}))
                    trace.set_semantic_compiler(sanitize_obj(response.get("semantic_compiler") or response.get("semantic_compiler_debug") or {}))
                    product_identity = _extract_product_identity(response)
                    product_identity["real_context"] = real_context_summary
                    product_identity["real_context_product_identity"] = real_context_identity
                    product_identity["sidecar_context"] = sidecar_context
                    trace.set_product_identity(product_identity)
                    trace.set_failure_labels(labels)
                    trace.set_raw_response(sanitize_obj({
                        "request_id": response.get("request_id"),
                        "trace_id": response.get("trace_id"),
                        "evidence_debug": response.get("evidence_debug") or {},
                        "debug_runtime": response.get("debug_runtime") or {},
                        "turn_understanding": turn_understanding,
                        "intent_contract": intent_contract,
                        "quality_bucket": quality_bucket,
                        "real_context": real_context_summary,
                        "real_context_product_identity": real_context_identity,
                        "sidecar_context": sidecar_context,
                        "sidecar_context_quality": sidecar_context.get("sidecar_context_quality", ""),
                        "sidecar_context_sources": sidecar_context.get("sidecar_context_sources", []),
                        "missing_context_fields": sidecar_context.get("missing_context_fields", []),
                        "has_sidecar_product_context": bool(sidecar_context.get("has_sidecar_product_context")),
                        "has_sidecar_order_context": bool(sidecar_context.get("has_sidecar_order_context")),
                        "sidecar_mode": eval_sidecar_mode,
                        "sidecar_fixture_used": sidecar_fixture_used,
                        "sidecar_product_mismatch": sidecar_product_mismatch,
                        "eval_fixture_gap": eval_fixture_gap,
                        "conversation_media_reference": conversation_media_reference,
                        "eval_replay_options": eval_replay_options,
                        **({"pgvector_shadow": pgvector_shadow} if pgvector_shadow else {}),
                    }))
                    db.add(trace)
                    for failure in failures:
                        failure_type = failure.get("failure_type", "api_error")
                        if failure_type not in FAILURE_TYPES:
                            failure_type = "api_error"
                        row = EvalFailure(
                            run_uid=run_uid,
                            case_uid=case.case_uid,
                            turn_uid=turn.turn_uid,
                            failure_type=failure_type,
                            severity=failure.get("severity", "medium"),
                            suggested_fix_area=failure.get("suggested_fix_area", ""),
                            suggested_owner=failure.get("suggested_owner", ""),
                            explanation=failure.get("explanation", ""),
                            message=sanitize_text(failure.get("message", "")),
                        )
                        row.set_metadata({"trace_turn_index": turn.turn_index})
                        db.add(row)
                    db.commit()
                    if options.progress_log or float(eval_replay_options.get("agent_turn_timeout_seconds") or 0) > 0:
                        _record_replay_progress(db, run, {
                            **progress,
                            "stage": "persist_trace",
                            "elapsed_ms": latency_ms,
                            "passed": passed,
                            "failure_labels": labels,
                        }, progress_log=bool(options.progress_log))

            run.status = "completed"
            run.total_turns = totals["turns"]
            run.passed_turns = totals["passed"]
            run.failed_turns = totals["failed"]
            run.requires_review_turns = totals["requires_review"]
            if totals["pgvector_shadow_enabled_trace_count"]:
                current_metadata = run.get_metadata()
                current_metadata["pgvector_shadow_summary"] = {
                    key: totals[key]
                    for key in (
                        "pgvector_shadow_enabled_trace_count",
                        "pgvector_shadow_available_count",
                        "pgvector_shadow_error_count",
                        "pgvector_product_fact_hit_count",
                        "pgvector_direct_answerable_count",
                        "pgvector_service_action_hit_count",
                        "pgvector_media_reference_hit_count",
                        "current_sqlite_no_evidence_but_pgvector_direct_count",
                        "current_sqlite_safe_handoff_but_pgvector_service_action_count",
                        "pgvector_media_reference_without_reply_blocks_count",
                    )
                }
                run.set_metadata(current_metadata)
            db.commit()
            return {"run_uid": run_uid, "status": run.status, **totals, "total_cases": len(cases)}
        except Exception:
            db.rollback()
            run = db.query(EvalRun).filter(EvalRun.run_uid == run_uid).one_or_none()
            if run is not None:
                run.status = "failed"
                db.commit()
            raise
        finally:
            db.close()
