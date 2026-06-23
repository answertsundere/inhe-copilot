"""Turn-by-turn replay for sanitized real conversation eval cases."""

import time
import uuid
from dataclasses import dataclass
from typing import Any

from app.services.eval_sanitizer_service import sanitize_obj, sanitize_text


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
}


@dataclass
class ReplayOptions:
    limit_cases: int | None = None
    run_uid: str | None = None
    sample_only: bool = False


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
    if query_fact_type and query_fact_type not in {"logistics", "order_status", "after_sales"} and not selected:
        failures.append({"failure_type": "rag_miss", "severity": "medium", "message": "product question has no selected evidence"})
    answered = set(str(x) for x in _json_list(answer_trace.get("evidence_answered_fact_types")) if x)
    if required and answered and not (required & answered):
        failures.append({"failure_type": "evidence_misuse", "severity": "medium", "message": "answered fact types do not overlap required fact types"})
    return failures


class RealConversationReplayService:
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
        db = SessionLocal()
        try:
            query = (
                db.query(EvalCase)
                .filter(EvalCase.source_type == "real_conversation", EvalCase.status == "active")
                .order_by(EvalCase.id.asc())
            )
            if options.limit_cases:
                query = query.limit(options.limit_cases)
            cases = query.all()
            run = EvalRun(run_uid=run_uid, source_type="real_conversation", status="running")
            run.total_cases = len(cases)
            run.set_metadata({"sample_only": options.sample_only})
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
                    totals["turns"] += 1
                    payload = {
                        "message": turn.sanitized_text,
                        "conversation_id": f"real_eval_{case.case_uid}",
                        "product_name": turn.product_hint,
                        "copilot_context": {
                            "conversation_history": history[:-1],
                            "eval_case_uid": case.case_uid,
                            "eval_turn_uid": turn.turn_uid,
                            "source_type": "real_conversation",
                        },
                    }
                    started = time.time()
                    exception = None
                    response: dict[str, Any] = {}
                    try:
                        response = self._call_agent(payload) or {}
                    except Exception as exc:
                        exception = exc
                        response = {"error": str(exc)}
                    latency_ms = int((time.time() - started) * 1000)
                    failures = classify_turn_failures(response, exception)
                    labels = [f["failure_type"] for f in failures]
                    if response.get("requires_human_review"):
                        totals["requires_review"] += 1
                    if labels:
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
                        query_fact_type=_extract_query_fact_type(response),
                        requires_human_review=bool(response.get("requires_human_review")),
                        latency_ms=latency_ms,
                        order_identity_hash=turn.order_hint_hash,
                        passed=not labels,
                    )
                    trace.set_required_fact_types(_extract_required_fact_types(response))
                    trace.set_selected_evidence(selected)
                    trace.set_rejected_evidence(rejected)
                    trace.set_answer_trace(sanitize_obj(response.get("answer_trace") or {}))
                    trace.set_final_audit(sanitize_obj(response.get("final_answer_audit") or response.get("final_audit") or {}))
                    trace.set_semantic_compiler(sanitize_obj(response.get("semantic_compiler") or response.get("semantic_compiler_debug") or {}))
                    trace.set_product_identity(_extract_product_identity(response))
                    trace.set_failure_labels(labels)
                    trace.set_raw_response(sanitize_obj({
                        "request_id": response.get("request_id"),
                        "trace_id": response.get("trace_id"),
                        "evidence_debug": response.get("evidence_debug") or {},
                        "debug_runtime": response.get("debug_runtime") or {},
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
