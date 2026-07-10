"""
AnalysisExecutionService — unified entry point for analysis execution.

Handles:
- ID generation
- Trace lifecycle
- ReplyService invocation
- Snapshot persistence
- API response construction
"""

import json
import logging
import time
import uuid
from copy import deepcopy
from collections.abc import Callable

from app.config import (
    APP_VERSION, GRAPH_VERSION, PROMPT_VERSION,
    ROUTING_CONFIG_VERSION, TOOL_REGISTRY_VERSION, LLM_MODEL,
)

logger = logging.getLogger(__name__)


_FINAL_RESPONSE_CONTRACT_FIELDS = (
    "suggested_reply",
    "draft_reply",
    "sendable_reply",
    "can_send",
    "requires_human_review",
    "reply_status",
    "reply_blocks",
    "reply_delivery",
    "recommended_assets",
    "final_answer_audit",
    "final_semantic_fit_audit",
    "trace_response_stage",
    "final_response_pipeline_version",
)


def _gen_request_id() -> str:
    return f"req_{uuid.uuid4().hex[:12]}"


def _gen_message_id() -> str:
    return f"msg_{uuid.uuid4().hex[:12]}"


def execute_analysis(
    reply_service,
    customer_message: str,
    order_id: str = "",
    tracking_no: str = "",
    conversation_id: str = "default",
    product_name: str = "",
    product_candidates: list | None = None,
    copilot_context: dict | None = None,
    image_attachments: list | None = None,
    source: str = "api",
    scenario: str = "",
    final_orchestration: bool = True,
    response_post_processor: Callable[[dict], dict] | None = None,
) -> dict:
    """
    Execute a full analysis with trace lifecycle management.

    Returns a dict with trace_id, message_id, request_id, and the result.
    """
    request_id = _gen_request_id()
    message_id = _gen_message_id()

    # Initialize trace tables (idempotent)
    try:
        from app.tracing.repository import init_trace_tables
        init_trace_tables()
    except Exception as e:
        logger.warning("init_trace_tables failed: %s", e)

    # Start trace
    trace_id = ""
    root_span_id = ""
    try:
        from app.tracing.recorder import start_trace, start_span, end_trace, end_span
        trace_id = start_trace(
            request_id=request_id,
            message_id=message_id,
            conversation_id=conversation_id,
            source=source,
            scenario=scenario,
        )
        root_span_id = start_span(
            name="analysis",
            span_type="api",
            input_summary={
                "customer_message": customer_message[:100],
                "order_id": order_id,
                "source": source,
            },
        )
    except Exception as e:
        logger.warning("Trace start failed: %s", e)

    # Execute analysis
    result = None
    error = None
    try:
        result = reply_service.analyze(
            customer_message,
            order_id=order_id,
            tracking_no=tracking_no,
            conversation_id=conversation_id,
            product_name=product_name,
            product_candidates=product_candidates,
            copilot_context=copilot_context,
            image_attachments=image_attachments,
            request_id=request_id,
            message_id=message_id,
            source=source,
            scenario=scenario,
        )
    except Exception as e:
        error = e
        logger.error("Analysis execution failed: %s", e, exc_info=True)

    # Build response
    response = _build_response(
        result=result,
        error=error,
        request_id=request_id,
        message_id=message_id,
        trace_id=trace_id,
        conversation_id=conversation_id,
        source=source,
        scenario=scenario,
        customer_message=customer_message,
        copilot_context=copilot_context,
        final_orchestration=final_orchestration,
        response_post_processor=response_post_processor,
    )

    # Persist the same response object returned to the caller. The graph result
    # may differ after final orchestration and must not be recorded as delivery.
    if result and trace_id:
        _save_snapshot(
            trace_id=trace_id,
            request_id=request_id,
            message_id=message_id,
            conversation_id=conversation_id,
            source=source,
            scenario=scenario,
            customer_message=customer_message,
            response=response,
        )

    # Save file-based snapshot for feedback/bad-case lookups
    if result:
        _save_file_snapshot(
            request_id=request_id,
            message_id=message_id,
            conversation_id=conversation_id,
            source=source,
            scenario=scenario,
            customer_message=customer_message,
            response=response,
            copilot_context=copilot_context,
        )

    # End trace
    if trace_id:
        _end_trace_safely(
            trace_id=trace_id,
            root_span_id=root_span_id,
            response=response,
            error=error,
        )

    return response


def _build_response(
    result,
    error,
    request_id: str,
    message_id: str,
    trace_id: str,
    conversation_id: str,
    source: str,
    scenario: str,
    customer_message: str,
    copilot_context: dict | None,
    final_orchestration: bool = True,
    response_post_processor: Callable[[dict], dict] | None = None,
) -> dict:
    """Build the API response dict."""
    if error:
        return {
            "error": str(error),
            "request_id": request_id,
            "message_id": message_id,
            "trace_id": trace_id,
            "conversation_id": conversation_id,
            "trace_response_stage": "error",
            "final_response_pipeline_version": "",
        }

    response = result.to_dict()
    response["request_id"] = request_id
    response["message_id"] = message_id
    response["trace_id"] = trace_id
    response["conversation_id"] = conversation_id

    orchestration_applied = False
    if final_orchestration:
        try:
            from app.services.final_response_orchestrator import orchestrate_final_response

            response = orchestrate_final_response(
                response,
                customer_message=customer_message,
                copilot_context=copilot_context,
            )
            orchestration_applied = True
        except Exception as e:
            logger.warning("final_response_orchestration failed: %s", e)

    post_processor_applied = False
    post_processor_finalized = False
    if response_post_processor is not None:
        try:
            processed = response_post_processor(response)
            if not isinstance(processed, dict):
                raise TypeError("response_post_processor must return a dict")
            response = processed
            post_processor_applied = True
            post_processor_finalized = bool(
                (response.get("analysis_pipeline") or {}).get(
                    "final_orchestration_completed"
                )
            )
        except Exception as exc:
            logger.warning("analysis response post-processing failed: %s", exc, exc_info=True)
            response.setdefault("evidence_debug", {})["analysis_pipeline_post_processor_error"] = {
                "type": type(exc).__name__,
                "message": str(exc),
            }

    if response_post_processor is not None:
        response["trace_response_stage"] = "final" if post_processor_finalized else "pre_final"
        response["final_response_pipeline_version"] = str(
            (response.get("final_response_pipeline") or {}).get("version") or ""
        ) if post_processor_finalized else ""
    elif orchestration_applied:
        response["trace_response_stage"] = "final"
        response["final_response_pipeline_version"] = str(
            (response.get("final_response_pipeline") or {}).get("version") or ""
        )
    elif final_orchestration:
        response["trace_response_stage"] = "pre_final"
        response["final_response_pipeline_version"] = ""
    else:
        response["trace_response_stage"] = "graph_result"
        response["final_response_pipeline_version"] = ""

    # Build trace summary from execution_debug if present
    ed = response.get("execution_debug", {})
    if ed:
        response["trace_summary"] = {
            "intent": ed.get("routing", {}).get("final_intent", ""),
            "risk": ed.get("routing", {}).get("risk_level", ""),
            "duration_ms": ed.get("timing", {}).get("total_ms", 0),
            "rag_retrieved": ed.get("rag", {}).get("metrics", {}).get("retrieved_count", 0),
            "rag_used": ed.get("rag", {}).get("metrics", {}).get("used_count", 0),
            "tool_calls": len(ed.get("tool_calls", [])),
            "fallback_used": ed.get("outcome", {}).get("fallback_used", False),
            "source": "trace_v2" if trace_id else "legacy_builder",
        }

    return response


def _final_response_contract(response: dict) -> dict:
    """Return the auditable final delivery fields without graph-only state."""
    return {
        field: deepcopy(response.get(field))
        for field in _FINAL_RESPONSE_CONTRACT_FIELDS
    }


def _snapshot_execution_debug(response: dict, contract: dict) -> dict:
    execution_debug = deepcopy(response.get("execution_debug") or {})
    execution_debug["trace_response_stage"] = response.get("trace_response_stage", "")
    execution_debug["final_response_pipeline_version"] = response.get(
        "final_response_pipeline_version", ""
    )
    execution_debug["final_response_contract"] = contract
    return execution_debug


def _save_snapshot(
    trace_id: str,
    request_id: str,
    message_id: str,
    conversation_id: str,
    source: str,
    scenario: str,
    customer_message: str,
    response: dict,
) -> None:
    """Save analysis snapshot to SQLite."""
    try:
        from app.tracing.recorder import save_analysis_snapshot

        data = response if isinstance(response, dict) else {}
        contract = _final_response_contract(data)
        save_analysis_snapshot(
            trace_id=trace_id,
            request_id=request_id,
            message_id=message_id,
            conversation_id=conversation_id,
            source=source,
            scenario=scenario,
            customer_message=customer_message,
            suggested_reply=data.get("suggested_reply", ""),
            intent=data.get("intent", ""),
            risk_level=data.get("risk_level", "low"),
            need_human_review=data.get("requires_human_review", False),
            execution_debug=_snapshot_execution_debug(data, contract),
            evidence_debug=data.get("evidence_debug", {}),
            trace_steps=data.get("trace_steps", []),
            used_knowledge_entry_ids=data.get("context_used", {}).get("used_knowledge_entry_ids", []),
            used_fact_tools=data.get("used_fact_tool", ""),
            copilot_context=data.get("copilot_context", {}),
        )
    except Exception as e:
        logger.warning("save_snapshot failed: %s", e)


def _save_file_snapshot(
    request_id: str,
    message_id: str,
    conversation_id: str,
    source: str,
    scenario: str,
    customer_message: str,
    response: dict,
    copilot_context: dict | None,
) -> None:
    """Save file-based snapshot for feedback/bad-case lookups."""
    try:
        from app.services.analysis_snapshot import save_snapshot

        data = response if isinstance(response, dict) else {}
        contract = _final_response_contract(data)
        save_snapshot(
            request_id=request_id,
            message_id=message_id,
            conversation_id=conversation_id,
            source=source,
            scenario=scenario,
            customer_message=customer_message,
            suggested_reply=data.get("suggested_reply", ""),
            intent=data.get("intent", ""),
            risk_level=data.get("risk_level", "low"),
            need_human_review=data.get("requires_human_review", False),
            execution_debug=_snapshot_execution_debug(data, contract),
            evidence_debug=data.get("evidence_debug", {}),
            trace_steps=data.get("trace_steps", []),
            used_knowledge_entry_ids=data.get("evidence_debug", {}).get("used_knowledge_entry_ids", []),
            used_fact_tools=data.get("used_fact_tool", ""),
            copilot_context=data.get("copilot_context") or copilot_context or {},
            final_response_contract=contract,
        )
    except Exception as e:
        logger.warning("file snapshot save failed: %s", e)


def _end_trace_safely(
    trace_id: str,
    root_span_id: str,
    response: dict,
    error,
) -> None:
    """End trace and root span, catching any failures."""
    try:
        from app.tracing.recorder import end_trace, end_span

        if root_span_id:
            status = "error" if error else "success"
            end_span(root_span_id, status=status)

        outcome = {
            "trace_response_stage": str(response.get("trace_response_stage") or "error"),
            "final_response_pipeline_version": str(
                response.get("final_response_pipeline_version") or ""
            ),
        }
        if response and not error:
            data = response
            outcome = {
                **outcome,
                "intent": data.get("intent", ""),
                "risk_level": data.get("risk_level", "low"),
                "answer_mode": data.get("execution_debug", {}).get("generation", {}).get("answer_mode", ""),
                "need_human_review": data.get("requires_human_review", False),
                "reply_generated": bool(data.get("suggested_reply", "")),
                "fallback_used": data.get("execution_debug", {}).get("outcome", {}).get("fallback_used", False),
                "final_response_contract": _final_response_contract(data),
            }

        end_trace(
            trace_id,
            outcome=outcome,
            status="error" if error else "success",
        )
    except Exception as e:
        logger.warning("end_trace failed: %s", e)
