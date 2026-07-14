"""Independent, fail-closed structured-output transport for decision shadow."""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass
from typing import Any, Callable, Literal

from openai import OpenAI

from app import config
from app.services.eval_sanitizer_service import sanitize_text


StrictCapability = Literal["strict_json_schema", "tool_call_schema"]
_SUPPORTED_CAPABILITIES = {"strict_json_schema", "tool_call_schema"}


class StrictDecisionProviderError(RuntimeError):
    """Safe error categories only; configuration values must not escape."""


@dataclass(frozen=True)
class StrictDecisionProviderConfig:
    provider_name: str
    api_base: str
    api_key: str
    model: str
    capability: str
    timeout_seconds: int
    qualified: bool

    @classmethod
    def from_environment(cls) -> "StrictDecisionProviderConfig":
        return cls(
            provider_name=sanitize_text(config.COPILOT_DECISION_LLM_PROVIDER),
            api_base=sanitize_text(config.COPILOT_DECISION_LLM_API_BASE),
            api_key=config.COPILOT_DECISION_LLM_API_KEY,
            model=sanitize_text(config.COPILOT_DECISION_LLM_MODEL),
            capability=sanitize_text(config.COPILOT_DECISION_LLM_CAPABILITY).lower(),
            timeout_seconds=_bounded_timeout(str(config.COPILOT_DECISION_LLM_TIMEOUT_SECONDS)),
            qualified=bool(config.COPILOT_DECISION_LLM_QUALIFIED),
        )

    def capability_status(self) -> str:
        if not all((self.provider_name, self.api_base, self.api_key, self.model)):
            return "provider_not_configured"
        if self.capability not in _SUPPORTED_CAPABILITIES:
            return "strict_capability_not_supported"
        return "configured"

    def safe_metadata(self) -> dict[str, Any]:
        host_fingerprint = ""
        if self.api_base:
            host_fingerprint = hashlib.sha256(self.api_base.encode("utf-8")).hexdigest()[:12]
        return {
            "provider_name": self.provider_name or "unconfigured",
            "model_name": self.model or "unconfigured",
            "capability": self.capability,
            "configured": self.capability_status() == "configured",
            "qualified": self.qualified,
            "host_fingerprint": host_fingerprint,
        }


def _bounded_timeout(value: str) -> int:
    try:
        return max(1, min(int(value), 120))
    except (TypeError, ValueError):
        return 20


def _safe_error_category(exc: Exception) -> str:
    name = type(exc).__name__.lower()
    detail = sanitize_text(str(exc)).lower()
    if "timeout" in name or "timeout" in detail:
        return "timeout"
    if "rate" in name or "429" in detail or "rate limit" in detail:
        return "rate_limited"
    if "badrequest" in name or "response_format" in detail or "json_schema" in detail:
        return "strict_schema_rejected"
    if "authentication" in name or "auth" in detail or "401" in detail or "403" in detail:
        return "authentication_failed"
    return "provider_request_failed"


class StrictDecisionProviderService:
    """Issue exactly one strict structured request; never parse free-form JSON."""

    def __init__(
        self,
        config: StrictDecisionProviderConfig | None = None,
        client_factory: Callable[..., Any] = OpenAI,
    ):
        self.config = config or StrictDecisionProviderConfig.from_environment()
        self._client_factory = client_factory
        self._client: Any | None = None

    def metadata(self) -> dict[str, Any]:
        return self.config.safe_metadata()

    def ready_for_shadow(self) -> bool:
        return self.config.capability_status() == "configured" and self.config.qualified

    def _require_ready(self, *, allow_unqualified: bool) -> None:
        status = self.config.capability_status()
        if status != "configured":
            raise StrictDecisionProviderError(status)
        if not allow_unqualified and not self.config.qualified:
            raise StrictDecisionProviderError("provider_not_qualified")

    @property
    def client(self) -> Any:
        if self._client is None:
            self._client = self._client_factory(
                api_key=self.config.api_key,
                base_url=self.config.api_base,
                timeout=self.config.timeout_seconds,
            )
        return self._client

    def request(
        self,
        *,
        name: str,
        schema: dict[str, Any],
        system_prompt: str,
        payload: dict[str, Any],
        max_tokens: int,
        allow_unqualified: bool = False,
    ) -> dict[str, Any]:
        self._require_ready(allow_unqualified=allow_unqualified)
        started = time.perf_counter()
        try:
            if self.config.capability == "strict_json_schema":
                result = self.client.chat.completions.create(
                    model=self.config.model,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
                    ],
                    temperature=0,
                    max_tokens=max_tokens,
                    response_format={
                        "type": "json_schema",
                        "json_schema": {"name": name, "strict": True, "schema": schema},
                    },
                )
                choice = result.choices[0]
                if sanitize_text(getattr(choice, "finish_reason", "")) == "length":
                    raise StrictDecisionProviderError("structured_output_truncated")
                raw = sanitize_text(choice.message.content)
            else:
                result = self.client.chat.completions.create(
                    model=self.config.model,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
                    ],
                    temperature=0,
                    max_tokens=max_tokens,
                    tools=[{
                        "type": "function",
                        "function": {"name": name, "strict": True, "parameters": schema},
                    }],
                    tool_choice={"type": "function", "function": {"name": name}},
                )
                choice = result.choices[0]
                if sanitize_text(getattr(choice, "finish_reason", "")) == "length":
                    raise StrictDecisionProviderError("structured_output_truncated")
                tool_calls = choice.message.tool_calls or []
                if len(tool_calls) != 1 or tool_calls[0].function.name != name:
                    raise StrictDecisionProviderError("strict_tool_call_missing")
                raw = sanitize_text(tool_calls[0].function.arguments)
            if not raw:
                raise StrictDecisionProviderError("empty_structured_output")
            parsed = json.loads(raw)
            if not isinstance(parsed, dict):
                raise StrictDecisionProviderError("structured_output_not_object")
            return parsed
        except StrictDecisionProviderError:
            raise
        except json.JSONDecodeError as exc:
            raise StrictDecisionProviderError("structured_output_not_json") from exc
        except Exception as exc:
            raise StrictDecisionProviderError(_safe_error_category(exc)) from exc
        finally:
            # Request duration is intentionally not attached to an exception or log.
            self._last_latency_ms = round((time.perf_counter() - started) * 1000, 2)

    @property
    def last_latency_ms(self) -> float | None:
        return getattr(self, "_last_latency_ms", None)
