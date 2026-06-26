"""Turn-by-turn replay for sanitized real conversation eval cases."""

import time
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
from app.services.real_context_product_identity_service import build_conversation_media_reference


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
    "wrong_topic_reply",
    "unrequested_product_fact",
    "query_fact_type_missing",
    "unnecessary_rag_call",
    "encoding_corruption",
    "intent_contract_mismatch",
    "generic_reply_to_actionable_issue",
    "accessory_usage_missed",
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
}

FACT_TYPE_COMPATIBILITY_GROUPS = {
    "aftersales": {"aftersales", "aftersales_policy", "after_sales"},
    "installation": {"installation", "accessory_usage"},
    "logistics": {"logistics", "order_status", "delivery_not_received"},
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


def _new_run_uid() -> str:
    return f"real_run_{uuid.uuid4().hex[:12]}"


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
        or []
    )
    rejected = (
        evidence_debug.get("rejected_evidence")
        or evidence_debug.get("evidence_rejected")
        or response.get("rejected_evidence")
        or []
    )
    return _json_list(sanitize_obj(selected)), _json_list(sanitize_obj(rejected))


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
    answer_trace = response.get("answer_trace") or {}
    final_audit = response.get("final_answer_audit") or response.get("final_audit") or {}
    evidence_debug = response.get("evidence_debug") or {}
    if response.get("error"):
        failures.append({"failure_type": "api_error", "severity": "high", "message": sanitize_text(response.get("error"))})
    if response.get("tool_policy_blocked") or response.get("policy_blocked"):
        failures.append({"failure_type": "tool_policy_blocked", "severity": "medium", "message": "tool policy blocked the turn"})
    if isinstance(final_audit, dict) and final_audit.get("passed") is False:
        failures.append({"failure_type": "semantic_mismatch", "severity": "high", "message": "final answer audit did not pass"})
    if (
        response.get("product_identified") is False
        or evidence_debug.get("product_identified") is False
        or str(evidence_debug.get("product_resolution_status") or "") == "not_found"
    ):
        failures.append({"failure_type": "no_product_identified", "severity": "medium", "message": "product identity was not resolved"})
    if response.get("requires_human_review"):
        failures.append({"failure_type": "needs_human_review", "severity": "medium", "message": "agent requested human review"})
    if not reply.strip():
        failures.append({"failure_type": "answer_incomplete", "severity": "high", "message": "empty agent reply"})
    unsafe_terms = ("绝对安全", "完全无害", "0甲醛", "零甲醛", "宝宝可以直接用")
    if any(term in reply for term in unsafe_terms):
        failures.append({"failure_type": "unsafe_claim", "severity": "high", "message": "reply contains unsafe absolute claim"})
    media_terms = ("我把视频发您", "我把图片发您", "下面发您", "已发您视频", "已发您图片")
    if any(term in reply for term in media_terms) and not response.get("recommended_assets"):
        failures.append({"failure_type": "unsupported_media_claim", "severity": "medium", "message": "reply promises media without attached asset"})
    required = set(str(x) for x in _extract_required_fact_types(response) if x)
    if query_fact_type and query_fact_type not in {"logistics", "order_status", "after_sales", "aftersales", "aftersales_policy"} and not selected:
        failures.append({"failure_type": "rag_miss", "severity": "medium", "message": "product question has no selected evidence"})
    answered = set(str(x) for x in _json_list(answer_trace.get("evidence_answered_fact_types")) if x)
    if required and answered and not _has_compatible_fact_type_overlap(required, answered):
        failures.append({"failure_type": "evidence_misuse", "severity": "medium", "message": "answered fact types do not overlap required fact types"})
    enriched = []
    for failure in failures:
        failure_type = failure.get("failure_type", "api_error")
        enriched.append({**repair_guidance_for_failure(failure_type), **failure})
    return enriched


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

    if bool(understanding.get("needs_rag")) and not selected and not response.get("requires_human_review"):
        all_failures.append({
            "failure_type": "rag_miss",
            "severity": "medium",
            "message": "turn needs RAG but no selected evidence or human-review fallback exists",
        })

    if required_fact_types and reply_topics and query_fact_type and not _has_compatible_fact_type_overlap(reply_topics, required_fact_types):
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
        from app.services.analysis_execution_service import execute_analysis

        response = execute_analysis(
            reply_service=get_reply_service(),
            customer_message=payload.get("message", ""),
            conversation_id=payload.get("conversation_id", "real_conversation_eval"),
            product_name=payload.get("product_name", ""),
            copilot_context=payload.get("copilot_context") or {},
            source="real_conversation_eval",
            scenario="daily_replay",
            final_orchestration=True,
        )
        return response

    def replay_cases(self, options: ReplayOptions | None = None) -> dict[str, Any]:
        from app.db import SessionLocal
        from app.models.eval_tables import EvalCase, EvalConversationTurn, EvalFailure, EvalRun, EvalTrace

        options = options or ReplayOptions()
        run_uid = options.run_uid or _new_run_uid()
        case_uid_filter = set(options.case_uids or [])
        turn_uid_filter = set(options.turn_uids or [])
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
            })
            db.add(run)
            db.commit()

            totals = {"passed": 0, "failed": 0, "requires_review": 0, "turns": 0}
            if options.sample_only:
                run.status = "sampled"
                run.total_turns = 0
                db.commit()
                return {"run_uid": run_uid, "status": run.status, "total_cases": len(cases), **totals}

            for case in cases:
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
                    product_name = turn.product_hint or agent_real_context.get("product_name", "")
                    product_candidates = product_candidates_from_real_context(real_context)
                    real_context_summary = summarize_real_context(real_context)
                    real_context_identity = agent_real_context.get("real_context_product_identity") or {}
                    conversation_media_reference = build_conversation_media_reference(agent_real_context)
                    turn_understanding = self.turn_understanding_service.understand(
                        turn.sanitized_text,
                        history=conversation_history,
                        message_type=turn.message_type,
                        product_hint=product_name,
                    )
                    should_score = bool(turn_understanding.get("should_score"))
                    if should_score:
                        totals["turns"] += 1
                    payload = {
                        "message": turn.sanitized_text,
                        "conversation_id": f"real_eval_{case.case_uid}",
                        "product_name": product_name,
                        "product_candidates": product_candidates,
                        "order_id": agent_real_context.get("order_id", ""),
                        "tracking_no": agent_real_context.get("tracking_no", ""),
                        "copilot_context": {
                            "conversation_history": conversation_history,
                            "eval_case_uid": case.case_uid,
                            "eval_turn_uid": turn.turn_uid,
                            "source_type": "real_conversation",
                            "turn_understanding": turn_understanding,
                            **agent_real_context,
                        },
                    }
                    started = time.time()
                    exception = None
                    response: dict[str, Any] = {}
                    if turn_understanding.get("needs_agent_reply"):
                        try:
                            response = self._call_agent(payload) or {}
                        except Exception as exc:
                            exception = exc
                            response = {"error": str(exc)}
                    else:
                        response = {
                            "suggested_reply": "",
                            "requires_human_review": False,
                            "query_fact_type": turn_understanding.get("query_fact_type", ""),
                            "answer_trace": {
                                "turn_actionability": turn_understanding.get("turn_actionability"),
                                "reply_strategy": turn_understanding.get("reply_strategy"),
                                "skip_reason": turn_understanding.get("skip_reason", ""),
                            },
                        }
                    latency_ms = int((time.time() - started) * 1000)
                    turn_understanding = enrich_turn_understanding_with_contract(response, turn_understanding)
                    intent_contract = {
                        "expected_query_fact_type": turn_understanding.get("expected_query_fact_type", ""),
                        "actual_query_fact_type": turn_understanding.get("actual_query_fact_type", ""),
                        "effective_query_fact_type": turn_understanding.get("effective_query_fact_type", ""),
                        "intent_contract_status": turn_understanding.get("intent_contract_status", ""),
                    }
                    base_failures = classify_turn_failures(response, exception) if should_score else []
                    passed, failures = evaluate_replay_turn_result(turn_understanding, response, base_failures, exception)
                    labels = [f["failure_type"] for f in failures]
                    quality_bucket = classify_quality_bucket(
                        passed=passed,
                        requires_human_review=bool(response.get("requires_human_review")),
                        failure_labels=labels,
                        failures=failures,
                        turn_understanding=turn_understanding,
                    ).to_dict()
                    if should_score and response.get("requires_human_review"):
                        totals["requires_review"] += 1
                    if not should_score:
                        pass
                    elif labels:
                        totals["failed"] += 1
                    else:
                        totals["passed"] += 1

                    selected, rejected = _extract_evidence(response)
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
                        "conversation_media_reference": conversation_media_reference,
                    }))
                    trace.set_final_audit(sanitize_obj(response.get("final_answer_audit") or response.get("final_audit") or {}))
                    trace.set_semantic_compiler(sanitize_obj(response.get("semantic_compiler") or response.get("semantic_compiler_debug") or {}))
                    product_identity = _extract_product_identity(response)
                    product_identity["real_context"] = real_context_summary
                    product_identity["real_context_product_identity"] = real_context_identity
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
                        "conversation_media_reference": conversation_media_reference,
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

            run.status = "completed"
            run.total_turns = totals["turns"]
            run.passed_turns = totals["passed"]
            run.failed_turns = totals["failed"]
            run.requires_review_turns = totals["requires_review"]
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
