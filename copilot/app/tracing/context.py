"""
TraceContext — request-scoped trace context using contextvars.
"""

from __future__ import annotations

import contextvars
from typing import Optional

# Context vars — each request gets its own values
current_trace_id: contextvars.ContextVar[str] = contextvars.ContextVar("trace_id", default="")
current_request_id: contextvars.ContextVar[str] = contextvars.ContextVar("request_id", default="")
current_message_id: contextvars.ContextVar[str] = contextvars.ContextVar("message_id", default="")
current_conversation_id: contextvars.ContextVar[str] = contextvars.ContextVar("conversation_id", default="")
current_span_id: contextvars.ContextVar[str] = contextvars.ContextVar("current_span_id", default="")
current_source: contextvars.ContextVar[str] = contextvars.ContextVar("source", default="")
current_scenario: contextvars.ContextVar[str] = contextvars.ContextVar("scenario", default="")


class TraceContext:
    """Read-only access to current trace context."""

    @staticmethod
    def trace_id() -> str:
        return current_trace_id.get("")

    @staticmethod
    def request_id() -> str:
        return current_request_id.get("")

    @staticmethod
    def message_id() -> str:
        return current_message_id.get("")

    @staticmethod
    def conversation_id() -> str:
        return current_conversation_id.get("")

    @staticmethod
    def current_span_id() -> str:
        return current_span_id.get("")

    @staticmethod
    def source() -> str:
        return current_source.get("")

    @staticmethod
    def scenario() -> str:
        return current_scenario.get("")

    @staticmethod
    def is_active() -> bool:
        return bool(current_trace_id.get(""))


def set_trace_context(
    trace_id: str,
    request_id: str = "",
    message_id: str = "",
    conversation_id: str = "",
    source: str = "",
    scenario: str = "",
) -> None:
    """Set all context vars for the current request."""
    current_trace_id.set(trace_id)
    current_request_id.set(request_id)
    current_message_id.set(message_id)
    current_conversation_id.set(conversation_id)
    current_source.set(source)
    current_scenario.set(scenario)


def set_current_span(span_id: str) -> None:
    current_span_id.set(span_id)
