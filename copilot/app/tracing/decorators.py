"""
Trace decorators — @trace_node, @trace_tool, @trace_llm, @trace_rag, @trace_guard

Wrap functions to automatically record span lifecycle. Failures are caught
and never block the business function.
"""

from __future__ import annotations

import functools
import logging
import time
from typing import Callable

from app.tracing import context as ctx
from app.tracing.recorder import start_span, end_span
from app.tracing.sanitizer import sanitize_dict

logger = logging.getLogger(__name__)


def trace_node(name: str, span_type: str = "graph_node"):
    """Decorator for LangGraph node functions."""
    def decorator(fn: Callable) -> Callable:
        @functools.wraps(fn)
        def wrapper(state: dict, *args, **kwargs):
            span_id = ""
            try:
                span_id = start_span(name, span_type, input_summary=_extract_input(state, fn))
            except Exception:
                pass

            t0 = time.monotonic()
            try:
                result = fn(state, *args, **kwargs)
                _safe_end(span_id, "success", _extract_output(result, state))
                return result
            except Exception as e:
                _safe_end(span_id, "error", error={"type": type(e).__name__, "code": "exception", "message": str(e)[:200], "retryable": False})
                raise
        return wrapper
    return decorator


def trace_tool(tool_name: str):
    """Decorator for tool handler functions."""
    def decorator(fn: Callable) -> Callable:
        @functools.wraps(fn)
        def wrapper(inputs: dict, state: dict, *args, **kwargs):
            span_id = ""
            try:
                span_id = start_span(tool_name, "tool", input_summary=sanitize_dict(inputs, 200))
            except Exception:
                pass

            t0 = time.monotonic()
            try:
                result = fn(inputs, state, *args, **kwargs)
                _safe_end(span_id, "success", output_summary=sanitize_dict(result or {}, 200))
                return result
            except Exception as e:
                _safe_end(span_id, "error", error={"type": type(e).__name__, "code": "tool_error", "message": str(e)[:200]})
                raise
        return wrapper
    return decorator


def trace_llm(purpose: str):
    """Decorator for LLM call functions."""
    def decorator(fn: Callable) -> Callable:
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            span_id = ""
            attrs = {"purpose": purpose}
            try:
                span_id = start_span(f"llm_{purpose}", "llm", attributes=attrs)
            except Exception:
                pass

            try:
                result = fn(*args, **kwargs)
                # Extract usage if available
                output = {}
                if isinstance(result, dict):
                    if "usage" in result:
                        output["token_usage"] = result["usage"]
                    if "model" in result:
                        output["model"] = result["model"]
                _safe_end(span_id, "success", output_summary=sanitize_dict(output, 200))
                return result
            except Exception as e:
                _safe_end(span_id, "error", error={"type": type(e).__name__, "code": "llm_error", "message": str(e)[:200]})
                raise
        return wrapper
    return decorator


def trace_rag(name: str):
    """Decorator for RAG functions."""
    def decorator(fn: Callable) -> Callable:
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            span_id = ""
            try:
                span_id = start_span(name, "rag")
            except Exception:
                pass

            try:
                result = fn(*args, **kwargs)
                output = {}
                if isinstance(result, list):
                    output["result_count"] = len(result)
                elif isinstance(result, dict):
                    output["result_count"] = len(result.get("chunks", result.get("results", [])))
                _safe_end(span_id, "success", output_summary=sanitize_dict(output, 300))
                return result
            except Exception as e:
                _safe_end(span_id, "error", error={"type": type(e).__name__, "code": "rag_error", "message": str(e)[:200]})
                raise
        return wrapper
    return decorator


def trace_guard(guard_name: str):
    """Decorator for guard functions."""
    def decorator(fn: Callable) -> Callable:
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            span_id = ""
            try:
                span_id = start_span(guard_name, "guard")
            except Exception:
                pass

            try:
                result = fn(*args, **kwargs)
                _safe_end(span_id, "success")
                return result
            except Exception as e:
                _safe_end(span_id, "error", error={"type": type(e).__name__, "code": "guard_error", "message": str(e)[:200]})
                raise
        return wrapper
    return decorator


# ========== Helpers ==========

def _extract_input(state: dict, fn: Callable) -> dict:
    """Extract a small input summary from graph state."""
    return {
        "intent": state.get("intent", ""),
        "customer_message": (state.get("customer_message") or "")[:100],
        "risk_level": state.get("risk_level", ""),
    }


def _extract_output(result, state: dict) -> dict:
    """Extract output summary from graph node result."""
    if isinstance(result, dict):
        return {
            "status": result.get("status", "success"),
            "intent": result.get("intent", ""),
        }
    return {}


def _safe_end(span_id: str, status: str, output_summary: dict = None, error: dict = None):
    """End span, catching any failures."""
    if not span_id:
        return
    try:
        end_span(span_id, status, output_summary=output_summary, error=error)
    except Exception as e:
        logger.warning("_safe_end failed: %s", e)
