"""LLM client wrapper with safe fallback, model routing, and ledger logging."""

from __future__ import annotations

import json
import logging
import time
from typing import Optional

from openai import OpenAI

from app.config import LLM_API_BASE, LLM_API_KEY, LLM_MODEL
from app.services.model_call_ledger_service import record_model_call
from app.services.model_router_service import resolve_model, resolve_model_api_key
from .schemas import FallbackReplyOutput, validate_llm_output

logger = logging.getLogger(__name__)


_FALLBACK_REPLIES = {
    "high": "这个问题需要人工进一步核实，我会先帮您记录并转人工处理。",
    "medium": "这个情况我先帮您记录下来，需要核实后再回复您。",
    "low": "我这边先收到您的问题了，当前生成结果不够稳定，需要继续核对后再回复。",
}


class LLMClient:
    """OpenAI-compatible LLM client.

    Existing callers may keep using ``client`` or ``chat``. New model-aware
    callers should use ``chat_completion(..., model_alias=...)`` so routing and
    ledger metadata are recorded consistently.
    """

    def __init__(
        self,
        api_key: str = "",
        api_base: str = "",
        model: str = "",
        model_alias: str = "strong_model",
    ):
        self.model_alias = model_alias or "strong_model"
        resolved = resolve_model(self.model_alias)
        self.provider = str(resolved.get("provider") or "openai_compatible")
        self.api_key = api_key or resolve_model_api_key(self.model_alias) or LLM_API_KEY
        self.api_base = api_base or str(resolved.get("api_base") or LLM_API_BASE)
        self.model = model or str(resolved.get("model") or LLM_MODEL)
        self.timeout_seconds = int(resolved.get("timeout_seconds") or 30)
        self.max_retries = int(resolved.get("max_retries") or 1)
        self.last_model_call_trace: dict = {}
        self._client = None

    @property
    def client(self) -> OpenAI:
        if self._client is None:
            self._client = OpenAI(api_key=self.api_key, base_url=self.api_base)
        return self._client

    def is_configured(self, model_alias: str = "") -> bool:
        return bool(resolve_model(model_alias or self.model_alias).get("enabled"))

    def chat_completion(
        self,
        *,
        messages: list[dict],
        model_alias: str = "strong_model",
        node_name: str = "unknown",
        trace_id: str = "",
        conversation_id: str = "",
        request_id: str = "",
        temperature: float = 0.3,
        max_tokens: int = 300,
        response_format: dict | None = None,
        **kwargs,
    ):
        alias = model_alias or self.model_alias or "strong_model"
        resolved = resolve_model(alias)
        api_key = resolve_model_api_key(alias)
        api_base = str(resolved.get("api_base") or self.api_base or "")
        model = str(resolved.get("model") or self.model or "")
        provider = str(resolved.get("provider") or self.provider or "")
        fallback_available = bool(resolved.get("fallback_aliases"))
        started = time.monotonic()

        if not api_key:
            latency_ms = int((time.monotonic() - started) * 1000)
            ledger = record_model_call(
                trace_id=trace_id,
                conversation_id=conversation_id,
                request_id=request_id,
                node_name=node_name,
                alias=alias,
                provider=provider,
                model=model,
                api_base=api_base,
                latency_ms=latency_ms,
                status="error",
                error_type="UNCONFIGURED",
                error_message=f"missing {resolved.get('api_key_env') or 'api key'}",
                metadata={"fallback_available": fallback_available},
            )
            self.last_model_call_trace = _call_trace(resolved, ledger, latency_ms, fallback_available)
            raise RuntimeError(f"Model alias {alias} is not configured")

        try:
            request = {
                "model": model,
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
                **kwargs,
            }
            if response_format is not None:
                request["response_format"] = response_format
            call_client = OpenAI(
                api_key=api_key,
                base_url=api_base,
                max_retries=int(resolved.get("max_retries") or self.max_retries),
                timeout=int(resolved.get("timeout_seconds") or self.timeout_seconds),
            )
            response = call_client.chat.completions.create(**request)
            latency_ms = int((time.monotonic() - started) * 1000)
            usage = _usage_dict(getattr(response, "usage", None))
            ledger = record_model_call(
                trace_id=trace_id,
                conversation_id=conversation_id,
                request_id=request_id,
                node_name=node_name,
                alias=alias,
                provider=provider,
                model=model,
                api_base=api_base,
                prompt_tokens=usage["prompt_tokens"],
                completion_tokens=usage["completion_tokens"],
                total_tokens=usage["total_tokens"],
                latency_ms=latency_ms,
                status="success",
                metadata={
                    "fallback_available": fallback_available,
                    "usage_missing": not bool(getattr(response, "usage", None)),
                },
            )
            self.last_model_call_trace = _call_trace(resolved, ledger, latency_ms, fallback_available, usage)
            return response
        except Exception as exc:
            latency_ms = int((time.monotonic() - started) * 1000)
            ledger = record_model_call(
                trace_id=trace_id,
                conversation_id=conversation_id,
                request_id=request_id,
                node_name=node_name,
                alias=alias,
                provider=provider,
                model=model,
                api_base=api_base,
                latency_ms=latency_ms,
                status="error",
                error_type=type(exc).__name__,
                error_message=str(exc),
                metadata={"fallback_available": fallback_available},
            )
            self.last_model_call_trace = _call_trace(resolved, ledger, latency_ms, fallback_available)
            raise

    def chat(
        self,
        system_prompt: str,
        user_message: str,
        temperature: float = 0.3,
        max_tokens: int = 300,
        model_alias: str = "strong_model",
        node_name: str = "llm_client_chat",
        trace_id: str = "",
        conversation_id: str = "",
        request_id: str = "",
    ) -> dict:
        if not self.is_configured(model_alias):
            return _make_fallback(
                risk_level="low",
                error_type="UNCONFIGURED",
                detail=f"missing {model_alias} config",
            )

        try:
            response = self.chat_completion(
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_message},
                ],
                model_alias=model_alias,
                node_name=node_name,
                trace_id=trace_id,
                conversation_id=conversation_id,
                request_id=request_id,
                temperature=temperature,
                max_tokens=max_tokens,
                response_format={"type": "json_object"},
            )
            raw = response.choices[0].message.content.strip()
            parsed = self._parse_json(raw)
            is_valid, errors = validate_llm_output(parsed)
            if not is_valid:
                logger.warning("LLM schema validation failed: %s", errors)
                return _make_fallback(
                    risk_level=parsed.get("risk_level", "low"),
                    error_type="SCHEMA_VALIDATION_ERROR",
                    detail="; ".join(errors),
                    partial_intent=parsed.get("intent", ""),
                )
            return parsed
        except json.JSONDecodeError:
            logger.error("LLM JSON parse failed")
            return _make_fallback(
                risk_level="low",
                error_type="JSON_PARSE_ERROR",
                detail="LLM output is not valid JSON",
            )
        except Exception as exc:
            logger.error("LLM call failed: %s", exc)
            return _make_fallback(
                risk_level="low",
                error_type="LLM_CALL_ERROR",
                detail=str(exc),
            )

    def _parse_json(self, raw: str) -> dict:
        text = raw.strip()
        if text.startswith("```"):
            start = text.find("```")
            end = text.rfind("```")
            if end > start:
                inner = text[start + 3:end]
                if inner.startswith("json"):
                    inner = inner[4:]
                text = inner.strip()
        brace_start = text.find("{")
        brace_end = text.rfind("}")
        if brace_start != -1 and brace_end > brace_start:
            text = text[brace_start:brace_end + 1]
        return json.loads(text)


def _make_fallback(
    risk_level: str = "low",
    error_type: str = "",
    detail: str = "",
    partial_intent: str = "",
) -> dict:
    reply = _FALLBACK_REPLIES.get(risk_level, _FALLBACK_REPLIES["low"])
    if partial_intent:
        reply = f"[系统提示: 识别到意图'{partial_intent}'] {reply}"

    return {
        "intent": partial_intent or "系统提示",
        "risk_level": risk_level,
        "customer_emotion": "未知",
        "need_lookup": [],
        "suggested_reply": reply,
        "reply_style": "简洁专业",
        "policy_warnings": ["AI 回复生成异常，请人工确认"],
        "action_proposal": {"action_type": "人工处理", "reason": f"系统异常: {error_type}"},
        "requires_human_review": risk_level == "high",
        "error": f"{error_type}: {detail}" if detail else error_type,
    }


def _usage_dict(usage) -> dict:
    if not usage:
        return {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    prompt = int(getattr(usage, "prompt_tokens", 0) or 0)
    completion = int(getattr(usage, "completion_tokens", 0) or 0)
    total = int(getattr(usage, "total_tokens", prompt + completion) or 0)
    return {
        "prompt_tokens": prompt,
        "completion_tokens": completion,
        "total_tokens": total,
    }


def _call_trace(
    resolved: dict,
    ledger: dict,
    latency_ms: int,
    fallback_available: bool,
    usage: dict | None = None,
) -> dict:
    usage = usage or {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    return {
        "model_alias": resolved.get("alias", ""),
        "provider": resolved.get("provider", ""),
        "model_name": resolved.get("model", ""),
        "token_usage": usage,
        "estimated_cost": ledger.get("estimated_cost", 0.0),
        "currency": ledger.get("currency", "USD"),
        "cost_unknown": bool(ledger.get("cost_unknown")),
        "latency_ms": latency_ms,
        "fallback_available": fallback_available,
        "ledger_recorded": bool(ledger.get("ledger_recorded")),
    }


_client: Optional[LLMClient] = None


def get_llm_client() -> LLMClient:
    global _client
    if _client is None:
        _client = LLMClient()
    return _client
