"""
DebugProjector — project execution_debug from Trace V2 data.

When trace data is complete, project debug from spans.
Otherwise, fall back to legacy execution_debug_builder.
"""

import json
import logging

from app.config import (
    GRAPH_VERSION, PROMPT_VERSION, ROUTING_CONFIG_VERSION,
    TOOL_REGISTRY_VERSION, APP_VERSION, LLM_MODEL, LLM_API_BASE,
)

logger = logging.getLogger(__name__)


def project_execution_debug(
    trace_run: dict,
    spans: list,
    snapshot: dict | None = None,
    legacy_debug: dict | None = None,
) -> dict:
    """
    Project execution_debug from trace data.

    Returns dict with source field indicating projection origin.
    Falls back to legacy_debug if trace data is insufficient.
    """
    has_trace = bool(trace_run and trace_run.get("trace_id"))
    has_spans = bool(spans)

    if not has_trace or not has_spans:
        if legacy_debug:
            legacy_debug["projection_source"] = "legacy_builder"
            return legacy_debug
        return {"projection_source": "partial", "error": "no trace data"}

    try:
        debug = _project_from_trace(trace_run, spans, snapshot)
        debug["projection_source"] = "trace_v2"
        return debug
    except Exception as e:
        logger.warning("DebugProjector failed, falling back: %s", e)
        if legacy_debug:
            legacy_debug["projection_source"] = "legacy_builder"
            return legacy_debug
        return {"projection_source": "partial", "error": str(e)}


def _project_from_trace(trace_run: dict, spans: list, snapshot: dict | None) -> dict:
    """Project debug sections from trace spans."""
    span_map = {s["span_id"]: s for s in spans if s.get("span_id")}
    root_span = None
    for s in spans:
        if not s.get("parent_span_id"):
            root_span = s
            break

    outcome = trace_run.get("outcome", {}) or {}
    snapshot = snapshot or {}

    return {
        "request": _project_request(trace_run, snapshot),
        "versions": _project_versions(),
        "routing": _project_routing(spans, outcome),
        "tool_calls": _project_tool_calls(spans),
        "rag": _project_rag(spans),
        "citations": [],
        "generation": _project_generation(spans, outcome),
        "guards": _project_guards(spans),
        "timing": _project_timing(trace_run, spans),
        "outcome": _project_outcome(outcome),
    }


def _project_request(trace_run: dict, snapshot: dict) -> dict:
    return {
        "request_id": trace_run.get("request_id", ""),
        "message_id": trace_run.get("message_id", ""),
        "conversation_id": trace_run.get("conversation_id", ""),
        "source": trace_run.get("source", ""),
        "scenario": trace_run.get("scenario", ""),
        "customer_message": (snapshot.get("customer_message") or "")[:100],
    }


def _project_versions() -> dict:
    provider = ""
    if "dashscope" in LLM_API_BASE:
        provider = "alibaba_qwen"
    elif "openai" in LLM_API_BASE:
        provider = "openai"

    return {
        "graph_version": GRAPH_VERSION,
        "prompt_version": PROMPT_VERSION,
        "routing_config_version": ROUTING_CONFIG_VERSION,
        "tool_registry_version": TOOL_REGISTRY_VERSION,
        "app_version": APP_VERSION,
        "model_provider": provider,
        "model_name": LLM_MODEL,
    }


def _project_routing(spans: list, outcome: dict) -> dict:
    intent_spans = [s for s in spans if "intent" in s.get("name", "")]
    return {
        "final_intent": outcome.get("intent", ""),
        "risk_level": outcome.get("risk_level", "low"),
        "need_human_review": outcome.get("need_human_review", False),
        "answer_mode": outcome.get("answer_mode", ""),
    }


def _project_tool_calls(spans: list) -> list:
    tool_spans = [s for s in spans if s.get("span_type") == "tool"]
    calls = []
    for s in tool_spans:
        inp = s.get("input_summary", {})
        out = s.get("output_summary", {})
        if isinstance(inp, str):
            try: inp = json.loads(inp)
            except: inp = {}
        if isinstance(out, str):
            try: out = json.loads(out)
            except: out = {}
        calls.append({
            "span_id": s.get("span_id", ""),
            "tool_name": s.get("name", ""),
            "status": s.get("status", ""),
            "duration_ms": s.get("duration_ms"),
            "input_summary": inp,
            "output_summary": out,
            "error": s.get("error"),
        })
    return calls


def _project_rag(spans: list) -> dict:
    rag_spans = [s for s in spans if s.get("span_type") == "rag"]
    metrics = {"retrieved_count": 0, "used_count": 0}
    for s in rag_spans:
        out = s.get("output_summary", {})
        if isinstance(out, str):
            try: out = json.loads(out)
            except: out = {}
        metrics["retrieved_count"] += out.get("result_count", 0)
    return {"metrics": metrics}


def _project_generation(spans: list, outcome: dict) -> dict:
    llm_spans = [s for s in spans if s.get("span_type") == "llm"]
    model = ""
    tokens = None
    for s in llm_spans:
        out = s.get("output_summary", {})
        if isinstance(out, str):
            try: out = json.loads(out)
            except: out = {}
        if out.get("model"):
            model = out["model"]
        if out.get("token_usage"):
            tokens = out["token_usage"]

    return {
        "llm_used": bool(llm_spans),
        "model_name": model or LLM_MODEL,
        "prompt_version": PROMPT_VERSION,
        "fallback_used": outcome.get("fallback_used", False),
        "reply_generated": outcome.get("reply_generated", False),
    }


def _project_guards(spans: list) -> list:
    guard_spans = [s for s in spans if s.get("span_type") == "guard"]
    guards = []
    for s in guard_spans:
        guards.append({
            "guard_name": s.get("name", ""),
            "status": s.get("status", ""),
            "duration_ms": s.get("duration_ms"),
        })
    return guards


def _project_timing(trace_run: dict, spans: list) -> dict:
    total = trace_run.get("duration_ms") or 0
    node_durations = {}
    for s in spans:
        name = s.get("name", "")
        dur = s.get("duration_ms") or 0
        if name and dur:
            node_durations[name] = node_durations.get(name, 0) + dur

    return {
        "total_ms": total,
        "node_durations": node_durations,
    }


def _project_outcome(outcome: dict) -> dict:
    return {
        "reply_generated": outcome.get("reply_generated", False),
        "need_human_review": outcome.get("need_human_review", False),
        "fallback_used": outcome.get("fallback_used", False),
        "intent": outcome.get("intent", ""),
        "risk_level": outcome.get("risk_level", "low"),
    }
