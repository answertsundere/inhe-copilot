"""
TraceRecorder — manages trace and span lifecycle.

Thread-safe. Failures are caught and logged, never blocking business logic.
"""

from __future__ import annotations

import logging
import time
from typing import Optional

from app.tracing import context as ctx
from app.tracing.models import gen_trace_id, gen_span_id, gen_snapshot_id, utcnow
from app.tracing import repository

logger = logging.getLogger(__name__)

_span_counter = 0


class SpanGuard:
    """Context manager that auto-ends a span on exit (even on exception)."""

    def __init__(self, span_id: str, trace_id: str, name: str):
        self.span_id = span_id
        self.trace_id = trace_id
        self.name = name
        self._start_mono = time.monotonic()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        elapsed_ms = int((time.monotonic() - self._start_mono) * 1000)
        status = "error" if exc_type else "success"
        error_json = None
        if exc_type:
            error_json = {
                "type": exc_type.__name__ if exc_type else "",
                "code": "exception",
                "message": str(exc_val)[:200] if exc_val else "",
                "retryable": False,
            }
        try:
            repository.save_span({
                "span_id": self.span_id,
                "trace_id": self.trace_id,
                "status": status,
                "ended_at": utcnow(),
                "duration_ms": elapsed_ms,
                "error_json": error_json,
            })
        except Exception as e:
            logger.warning("SpanGuard end_span failed: %s", e)
        return False  # Don't suppress exceptions


def start_trace(
    request_id: str,
    message_id: str,
    conversation_id: str,
    source: str = "",
    scenario: str = "",
) -> str:
    """Start a new trace. Returns trace_id."""
    trace_id = gen_trace_id()
    try:
        repository.save_trace_run({
            "trace_id": trace_id,
            "request_id": request_id,
            "message_id": message_id,
            "conversation_id": conversation_id,
            "source": source,
            "scenario": scenario,
            "status": "running",
            "started_at": utcnow(),
        })
    except Exception as e:
        logger.warning("start_trace failed: %s", e)

    ctx.set_trace_context(
        trace_id=trace_id,
        request_id=request_id,
        message_id=message_id,
        conversation_id=conversation_id,
        source=source,
        scenario=scenario,
    )
    return trace_id


def end_trace(trace_id: str, outcome: dict = None, status: str = "success") -> None:
    """End a trace with outcome."""
    try:
        updates = {
            "trace_id": trace_id,
            "status": status,
            "ended_at": utcnow(),
        }
        if outcome:
            from app.tracing.models import TraceRun
            updates["outcome_json"] = repository.json.dumps(outcome) if hasattr(repository, 'json') else __import__('json').dumps(outcome, ensure_ascii=False)
        # Compute duration from started_at
        run = repository.get_trace_run(trace_id)
        if run and run.get("started_at"):
            try:
                from datetime import datetime, timezone
                started = datetime.fromisoformat(run["started_at"])
                ended = datetime.now(timezone.utc)
                updates["duration_ms"] = int((ended - started).total_seconds() * 1000)
            except Exception:
                pass
        repository.save_trace_run(updates)
    except Exception as e:
        logger.warning("end_trace failed: %s", e)


def start_span(
    name: str,
    span_type: str,
    parent_span_id: str = "",
    input_summary: dict = None,
    attributes: dict = None,
) -> str:
    """Start a span. Returns span_id. Sets current_span_id in context."""
    global _span_counter
    _span_counter += 1
    span_id = gen_span_id()
    trace_id = ctx.TraceContext.trace_id()
    if not parent_span_id:
        parent_span_id = ctx.TraceContext.current_span_id()

    try:
        import json as _json
        repository.save_span({
            "span_id": span_id,
            "trace_id": trace_id,
            "parent_span_id": parent_span_id,
            "span_type": span_type,
            "name": name,
            "status": "running",
            "started_at": utcnow(),
            "sequence_no": _span_counter,
            "input_summary_json": _json.dumps(input_summary or {}, ensure_ascii=False),
            "attributes_json": _json.dumps(attributes or {}, ensure_ascii=False),
        })
    except Exception as e:
        logger.warning("start_span failed: %s", e)

    ctx.set_current_span(span_id)
    return span_id


def end_span(span_id: str, status: str = "success", output_summary: dict = None,
            error: dict = None, decision: dict = None, evidence_ids: list = None) -> None:
    """End a span with results."""
    import json as _json
    updates = {
        "span_id": span_id,
        "trace_id": ctx.TraceContext.trace_id(),
        "status": status,
        "ended_at": utcnow(),
    }
    # Compute duration
    try:
        from app.tracing.repository import get_session
        from app.tracing.models import TraceSpan
        session = get_session()
        existing = session.query(TraceSpan).filter_by(span_id=span_id).first()
        if existing and existing.started_at:
            from datetime import datetime, timezone
            started = datetime.fromisoformat(existing.started_at)
            ended = datetime.now(timezone.utc)
            updates["duration_ms"] = int((ended - started).total_seconds() * 1000)
        session.close()
    except Exception:
        pass

    if output_summary:
        updates["output_summary_json"] = _json.dumps(output_summary, ensure_ascii=False)
    if error:
        updates["error_json"] = _json.dumps(error, ensure_ascii=False)
    if decision:
        updates["decision_json"] = _json.dumps(decision, ensure_ascii=False)
    if evidence_ids:
        updates["evidence_ids_json"] = _json.dumps(evidence_ids, ensure_ascii=False)

    try:
        repository.save_span(updates)
    except Exception as e:
        logger.warning("end_span failed: %s", e)


def save_analysis_snapshot(
    trace_id: str,
    request_id: str,
    message_id: str,
    conversation_id: str,
    source: str,
    scenario: str,
    customer_message: str,
    suggested_reply: str,
    intent: str,
    risk_level: str,
    need_human_review: bool,
    execution_debug: dict,
    evidence_debug: dict,
    trace_steps: list,
    used_knowledge_entry_ids: list,
    used_fact_tools: str,
    copilot_context: dict = None,
) -> None:
    """Save analysis snapshot to SQLite."""
    import json as _json
    try:
        repository.save_snapshot({
            "snapshot_id": gen_snapshot_id(),
            "trace_id": trace_id,
            "request_id": request_id,
            "message_id": message_id,
            "conversation_id": conversation_id,
            "source": source,
            "scenario": scenario,
            "customer_message": customer_message,
            "suggested_reply": suggested_reply,
            "intent": intent,
            "risk_level": risk_level,
            "need_human_review": 1 if need_human_review else 0,
            "execution_debug_json": _json.dumps(execution_debug or {}, ensure_ascii=False),
            "evidence_debug_json": _json.dumps(evidence_debug or {}, ensure_ascii=False),
            "trace_steps_json": _json.dumps(trace_steps or [], ensure_ascii=False),
            "used_knowledge_entry_ids_json": _json.dumps(used_knowledge_entry_ids or [], ensure_ascii=False),
            "used_fact_tools_json": used_fact_tools or "",
            "copilot_context_json": _json.dumps(copilot_context or {}, ensure_ascii=False),
        })
    except Exception as e:
        logger.warning("save_analysis_snapshot failed: %s", e)
