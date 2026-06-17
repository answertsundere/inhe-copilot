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

from app.config import (
    APP_VERSION, GRAPH_VERSION, PROMPT_VERSION,
    ROUTING_CONFIG_VERSION, TOOL_REGISTRY_VERSION, LLM_MODEL,
)

logger = logging.getLogger(__name__)


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
    )

    # Save tracing snapshot
    if result and trace_id:
        _save_snapshot(
            trace_id=trace_id,
            request_id=request_id,
            message_id=message_id,
            conversation_id=conversation_id,
            source=source,
            scenario=scenario,
            customer_message=customer_message,
            result=result,
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
            result=result,
            copilot_context=copilot_context,
        )

    # End trace
    if trace_id:
        _end_trace_safely(
            trace_id=trace_id,
            root_span_id=root_span_id,
            result=result,
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
) -> dict:
    """Build the API response dict."""
    if error:
        return {
            "error": str(error),
            "request_id": request_id,
            "message_id": message_id,
            "trace_id": trace_id,
            "conversation_id": conversation_id,
        }

    response = result.to_dict()
    response["request_id"] = request_id
    response["message_id"] = message_id
    response["trace_id"] = trace_id
    response["conversation_id"] = conversation_id

    if final_orchestration:
        try:
            from app.services.final_response_orchestrator import orchestrate_final_response

            response = orchestrate_final_response(
                response,
                customer_message=customer_message,
                copilot_context=copilot_context,
            )
        except Exception as e:
            logger.warning("final_response_orchestration failed: %s", e)

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


def _save_snapshot(
    trace_id: str,
    request_id: str,
    message_id: str,
    conversation_id: str,
    source: str,
    scenario: str,
    customer_message: str,
    result,
) -> None:
    """Save analysis snapshot to SQLite."""
    try:
        from app.tracing.recorder import save_analysis_snapshot

        data = result.to_dict() if hasattr(result, "to_dict") else {}
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
            execution_debug=data.get("execution_debug", {}),
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
    result,
    copilot_context: dict | None,
) -> None:
    """Save file-based snapshot for feedback/bad-case lookups."""
    try:
        from app.services.analysis_snapshot import save_snapshot

        data = result.to_dict() if hasattr(result, "to_dict") else {}
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
            execution_debug=data.get("execution_debug", {}),
            evidence_debug=data.get("evidence_debug", {}),
            trace_steps=data.get("trace_steps", []),
            used_knowledge_entry_ids=data.get("evidence_debug", {}).get("used_knowledge_entry_ids", []),
            used_fact_tools=data.get("used_fact_tool", ""),
            copilot_context=copilot_context or {},
        )
    except Exception as e:
        logger.warning("file snapshot save failed: %s", e)


def _end_trace_safely(
    trace_id: str,
    root_span_id: str,
    result,
    error,
) -> None:
    """End trace and root span, catching any failures."""
    try:
        from app.tracing.recorder import end_trace, end_span

        if root_span_id:
            status = "error" if error else "success"
            end_span(root_span_id, status=status)

        outcome = {}
        if result:
            data = result.to_dict() if hasattr(result, "to_dict") else {}
            outcome = {
                "intent": data.get("intent", ""),
                "risk_level": data.get("risk_level", "low"),
                "answer_mode": data.get("execution_debug", {}).get("generation", {}).get("answer_mode", ""),
                "need_human_review": data.get("requires_human_review", False),
                "reply_generated": bool(data.get("suggested_reply", "")),
                "fallback_used": data.get("execution_debug", {}).get("outcome", {}).get("fallback_used", False),
            }

        end_trace(
            trace_id,
            outcome=outcome,
            status="error" if error else "success",
        )
    except Exception as e:
        logger.warning("end_trace failed: %s", e)
