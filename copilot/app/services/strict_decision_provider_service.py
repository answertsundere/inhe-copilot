"""Independent, fail-closed structured-output transport for model roles."""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass
from typing import Any, Callable, Literal
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from openai import OpenAI

from app import config
from app.services.eval_sanitizer_service import sanitize_text


StrictCapability = Literal["strict_json_schema", "tool_call_schema"]
_SUPPORTED_CAPABILITIES = {"strict_json_schema", "tool_call_schema"}
_DEEPSEEK_UNSUPPORTED_SCHEMA_KEYWORDS = {
    "maxItems",
    "maxLength",
    "minItems",
    "minLength",
}


class StrictDecisionProviderError(RuntimeError):
    """Safe error categories only; configuration values must not escape."""


def qualification_configuration_fingerprint(
    config: "StrictDecisionProviderConfig",
) -> str:
    """Return a non-secret identity for one qualified strict-output role."""
    payload = {
        "role_name": config.role_name,
        "api_base_sha256": hashlib.sha256(
            str(config.api_base or "").strip().encode("utf-8")
        ).hexdigest(),
        "provider_name": str(config.provider_name or "").strip(),
        "model": str(config.model or "").strip(),
        "capability": str(config.capability or "").strip(),
        "timeout_seconds": int(config.timeout_seconds),
        "disable_thinking": bool(config.disable_thinking),
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        )
    ).hexdigest()


def _canonical_provider_origin(api_base: str) -> str:
    """Return a comparison-only origin without retaining path or credentials."""
    raw = str(api_base or "").strip()
    if not raw:
        return ""
    try:
        parsed = urlsplit(raw)
        hostname = parsed.hostname
        port = parsed.port
    except ValueError:
        return ""
    scheme = parsed.scheme.lower()
    if not scheme or not parsed.netloc or not hostname or any(char.isspace() for char in hostname):
        return ""
    hostname = hostname.lower()
    default_port = 443 if scheme == "https" else 80 if scheme == "http" else None
    effective_port = port if port is not None else default_port
    if effective_port is None:
        return f"{scheme}://{hostname}"
    return f"{scheme}://{hostname}:{effective_port}"


def safe_provider_identity(*, provider_name: str, api_base: str, model: str) -> dict[str, Any]:
    """Return a comparable provider identity without exposing endpoint or key."""
    canonical_origin = _canonical_provider_origin(api_base)
    normalized_model = sanitize_text(str(model or "")).strip()
    host_fingerprint = (
        hashlib.sha256(canonical_origin.encode("utf-8")).hexdigest()[:12]
        if canonical_origin else ""
    )
    configured = bool(host_fingerprint and normalized_model)
    return {
        "provider_name": sanitize_text(str(provider_name or "")).strip() or "unconfigured",
        "host_fingerprint": host_fingerprint,
        "model_name": normalized_model or "unconfigured",
        "configured": configured,
        "identity": f"{host_fingerprint}:{normalized_model}" if configured else "",
    }


@dataclass(frozen=True)
class StrictDecisionProviderConfig:
    provider_name: str
    api_base: str
    api_key: str
    model: str
    capability: str
    timeout_seconds: int
    qualified: bool
    disable_thinking: bool = False
    qualification_fingerprint: str = ""
    qualification_fingerprint_required: bool = False
    role_name: str = "decision"

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
            disable_thinking=bool(config.COPILOT_DECISION_LLM_DISABLE_THINKING),
        )

    @classmethod
    def from_unified_audit_environment(cls) -> "StrictDecisionProviderConfig":
        return cls(
            provider_name=sanitize_text(
                config.COPILOT_UNIFIED_AUDIT_PROVIDER
            ),
            api_base=sanitize_text(
                config.COPILOT_UNIFIED_AUDIT_API_BASE
            ),
            api_key=config.COPILOT_UNIFIED_AUDIT_API_KEY,
            model=sanitize_text(config.COPILOT_UNIFIED_AUDIT_MODEL),
            capability=sanitize_text(
                config.COPILOT_UNIFIED_AUDIT_CAPABILITY
            ).lower(),
            timeout_seconds=_bounded_timeout(
                str(config.COPILOT_UNIFIED_AUDIT_TIMEOUT_SECONDS)
            ),
            qualified=bool(config.COPILOT_UNIFIED_AUDIT_QUALIFIED),
            disable_thinking=bool(
                config.COPILOT_UNIFIED_AUDIT_DISABLE_THINKING
            ),
            qualification_fingerprint=str(
                config.COPILOT_UNIFIED_AUDIT_QUALIFICATION_FINGERPRINT
                or ""
            ).strip(),
            qualification_fingerprint_required=True,
            role_name="unified_audit",
        )

    @classmethod
    def from_turn_understanding_environment(cls) -> "StrictDecisionProviderConfig":
        """Load the explicitly configured formal Turn Understanding role only."""

        return cls(
            provider_name=sanitize_text(
                config.COPILOT_TURN_UNDERSTANDING_STRICT_PROVIDER
            ),
            api_base=sanitize_text(
                config.COPILOT_TURN_UNDERSTANDING_STRICT_API_BASE
            ),
            api_key=config.COPILOT_TURN_UNDERSTANDING_STRICT_API_KEY,
            model=sanitize_text(
                config.COPILOT_TURN_UNDERSTANDING_STRICT_MODEL
            ),
            capability=sanitize_text(
                config.COPILOT_TURN_UNDERSTANDING_STRICT_CAPABILITY
            ).lower(),
            timeout_seconds=_bounded_timeout(
                str(config.COPILOT_TURN_UNDERSTANDING_STRICT_TIMEOUT_SECONDS)
            ),
            qualified=bool(config.COPILOT_TURN_UNDERSTANDING_STRICT_QUALIFIED),
            disable_thinking=bool(
                config.COPILOT_TURN_UNDERSTANDING_STRICT_DISABLE_THINKING
            ),
            qualification_fingerprint=str(
                config.COPILOT_TURN_UNDERSTANDING_STRICT_QUALIFICATION_FINGERPRINT
                or ""
            ).strip(),
            qualification_fingerprint_required=True,
            role_name="turn_understanding",
        )

    def capability_status(self) -> str:
        if not all((self.provider_name, self.api_base, self.api_key, self.model)):
            return "provider_not_configured"
        if self.capability not in _SUPPORTED_CAPABILITIES:
            return "strict_capability_not_supported"
        return "configured"

    def safe_metadata(self) -> dict[str, Any]:
        identity = safe_provider_identity(
            provider_name=self.provider_name,
            api_base=self.api_base,
            model=self.model,
        )
        return {
            **identity,
            "capability": self.capability,
            "configured": self.capability_status() == "configured",
            "qualified": self.qualified,
            "qualification_status": self.qualification_status(),
            "disable_thinking": self.disable_thinking,
        }

    def qualification_status(self) -> str:
        if self.capability_status() != "configured":
            return self.capability_status()
        if not self.qualified:
            return "provider_not_qualified"
        if not self.qualification_fingerprint_required:
            return "qualified"
        if not self.qualification_fingerprint:
            return "qualification_fingerprint_missing"
        if self.qualification_fingerprint != qualification_configuration_fingerprint(
            self
        ):
            return "provider_configuration_changed"
        return "qualified"


def _bounded_timeout(value: str) -> int:
    try:
        return max(1, min(int(value), 120))
    except (TypeError, ValueError):
        return 20


def _provider_family(config: StrictDecisionProviderConfig) -> str:
    provider_name = str(config.provider_name or "").strip().lower()
    try:
        hostname = (urlsplit(config.api_base).hostname or "").lower()
    except ValueError:
        hostname = ""
    if (
        "minimax" in provider_name
        or hostname == "api.minimaxi.com"
        or hostname.endswith(".minimaxi.com")
        or hostname == "api.minimax.io"
        or hostname.endswith(".minimax.io")
    ):
        return "minimax"
    if provider_name in {"ollama", "ollama_native"}:
        return "ollama_native"
    if (
        provider_name == "deepseek"
        or hostname == "api.deepseek.com"
        or hostname.endswith(".deepseek.com")
    ):
        return "deepseek"
    return "generic"


def _provider_schema(
    schema: dict[str, Any],
    *,
    config: StrictDecisionProviderConfig,
) -> dict[str, Any]:
    """Project only documented transport incompatibilities from a strict schema.

    Local validation retains the original schema. DeepSeek beta strict tool
    calling rejects array length keywords and requires every object property to
    be present in ``required``. The projection is request-local and never
    changes the source schema held by the caller.
    """

    if (
        _provider_family(config) != "deepseek"
        or config.capability != "tool_call_schema"
    ):
        return schema

    def project(value: Any) -> Any:
        if isinstance(value, list):
            return [project(item) for item in value]
        if not isinstance(value, dict):
            return value

        projected = {
            key: project(item)
            for key, item in value.items()
            if key not in _DEEPSEEK_UNSUPPORTED_SCHEMA_KEYWORDS
        }
        properties = projected.get("properties")
        if projected.get("type") == "object" and isinstance(properties, dict):
            projected["required"] = sorted(properties)
            projected["additionalProperties"] = False
        return projected

    projected = project(schema)
    return projected if isinstance(projected, dict) else {}


def _provider_messages(
    *,
    system_prompt: str,
    payload: dict[str, Any],
) -> list[dict[str, str]]:
    """Build the existing field-aware privacy projection at the transport edge."""

    from app.services.canonical_conversation_turn_service import (
        project_provider_message_text,
        project_value_for_external_model,
    )

    return [
        {
            "role": "system",
            "content": project_provider_message_text(system_prompt),
        },
        {
            "role": "user",
            "content": json.dumps(
                project_value_for_external_model(payload),
                ensure_ascii=False,
            ),
        },
    ]


def _ollama_native_request(
    *,
    api_base: str,
    payload: dict[str, Any],
    timeout_seconds: int,
) -> dict[str, Any]:
    parsed = urlsplit(str(api_base or "").strip())
    if not parsed.scheme or not parsed.netloc:
        raise StrictDecisionProviderError("provider_not_configured")
    if (parsed.hostname or "").lower() not in {
        "127.0.0.1",
        "localhost",
        "::1",
    }:
        raise StrictDecisionProviderError("provider_origin_not_allowed")
    request = Request(
        f"{parsed.scheme}://{parsed.netloc}/api/chat",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urlopen(request, timeout=timeout_seconds) as response:
        result = json.loads(response.read().decode("utf-8"))
    if not isinstance(result, dict):
        raise StrictDecisionProviderError("structured_output_not_object")
    return result


def _provider_request_options(
    config: StrictDecisionProviderConfig,
    *,
    max_tokens: int,
) -> tuple[float, int, dict[str, Any]]:
    provider_family = _provider_family(config)
    if provider_family == "minimax":
        extra_body: dict[str, Any] = {"reasoning_split": True}
        if config.disable_thinking:
            extra_body["thinking"] = {"type": "disabled"}
        return 0.1, max(max_tokens, 1600), {"extra_body": extra_body}
    if provider_family == "ollama_native":
        return 0, max(max_tokens, 1600), {}
    if provider_family == "deepseek" and config.disable_thinking:
        return 0, max_tokens, {"extra_body": {"thinking": {"type": "disabled"}}}
    if config.disable_thinking:
        return 0, max_tokens, {
            "extra_body": {
                "chat_template_kwargs": {"enable_thinking": False}
            }
        }
    return 0, max_tokens, {}


def _http_status_code(exc: Exception) -> int | None:
    """Read an HTTP status without retaining provider response content."""

    candidates = (
        getattr(exc, "status_code", None),
        getattr(getattr(exc, "response", None), "status_code", None),
    )
    for value in candidates:
        try:
            status = int(value)
        except (TypeError, ValueError):
            continue
        if 100 <= status <= 599:
            return status
    return None


def _safe_error_category(exc: Exception) -> str:
    status = _http_status_code(exc)
    if status in {401, 403}:
        return "authentication_failed"
    if status == 402:
        return "provider_quota_exhausted"
    if status == 429:
        return "rate_limited"
    if status is not None and 400 <= status < 500:
        return "strict_request_rejected"
    if status is not None and status >= 500:
        return "provider_server_error"
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
        native_request: Callable[..., dict[str, Any]] = _ollama_native_request,
    ):
        self.config = config or StrictDecisionProviderConfig.from_environment()
        self._client_factory = client_factory
        self._native_request = native_request
        self._client: Any | None = None

    def metadata(self) -> dict[str, Any]:
        return self.config.safe_metadata()

    def ready_for_shadow(self) -> bool:
        return self.config.qualification_status() == "qualified"

    def qualification_fingerprint(self) -> str:
        return qualification_configuration_fingerprint(self.config)

    def _require_ready(self, *, allow_unqualified: bool) -> None:
        status = self.config.capability_status()
        if status != "configured":
            raise StrictDecisionProviderError(status)
        if not allow_unqualified:
            qualification_status = self.config.qualification_status()
            if qualification_status != "qualified":
                raise StrictDecisionProviderError(qualification_status)

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
        provider_schema = _provider_schema(schema, config=self.config)
        provider_messages = _provider_messages(
            system_prompt=system_prompt,
            payload=payload,
        )
        temperature, output_tokens, provider_options = (
            _provider_request_options(
                self.config,
                max_tokens=max_tokens,
            )
        )
        try:
            if _provider_family(self.config) == "ollama_native":
                if self.config.capability != "strict_json_schema":
                    raise StrictDecisionProviderError(
                        "strict_capability_not_supported"
                    )
                result = self._native_request(
                    api_base=self.config.api_base,
                    payload={
                        "model": self.config.model,
                        "messages": provider_messages,
                        "stream": False,
                        "format": provider_schema,
                        "think": not self.config.disable_thinking,
                        "options": {
                            "temperature": temperature,
                            "num_predict": output_tokens,
                        },
                    },
                    timeout_seconds=self.config.timeout_seconds,
                )
                if sanitize_text(result.get("done_reason")) == "length":
                    raise StrictDecisionProviderError(
                        "structured_output_truncated"
                    )
                message = result.get("message")
                if not isinstance(message, dict):
                    raise StrictDecisionProviderError(
                        "empty_structured_output"
                    )
                raw = sanitize_text(message.get("content"))
            elif self.config.capability == "strict_json_schema":
                result = self.client.chat.completions.create(
                    model=self.config.model,
                    messages=provider_messages,
                    temperature=temperature,
                    max_tokens=output_tokens,
                    response_format={
                        "type": "json_schema",
                        "json_schema": {"name": name, "strict": True, "schema": provider_schema},
                    },
                    **provider_options,
                )
                choice = result.choices[0]
                if sanitize_text(getattr(choice, "finish_reason", "")) == "length":
                    raise StrictDecisionProviderError("structured_output_truncated")
                raw = sanitize_text(choice.message.content)
            else:
                result = self.client.chat.completions.create(
                    model=self.config.model,
                    messages=provider_messages,
                    temperature=temperature,
                    max_tokens=output_tokens,
                    tools=[{
                        "type": "function",
                        "function": {"name": name, "strict": True, "parameters": provider_schema},
                    }],
                    tool_choice={"type": "function", "function": {"name": name}},
                    **provider_options,
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
