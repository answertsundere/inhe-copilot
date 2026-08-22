"""
LLM 客户端 - 封装模型调用逻辑，含安全降级
"""

import json
import logging
import hashlib
from typing import Optional
from urllib.parse import urlparse

from openai import OpenAI

from app import config
from app.config import LLM_API_BASE, LLM_API_KEY, LLM_MODEL
from .schemas import validate_llm_output, FallbackReplyOutput

logger = logging.getLogger(__name__)


class ComposerRoleConfigurationError(RuntimeError):
    """Raised when an explicit Composer role override is incomplete or unqualified."""


COMPOSER_ROLE_QUALIFICATION_CONTRACT = "composer-role-qualification/v1"


# 降级回复模板（不依赖 LLM 输出）
_FALLBACK_REPLIES = {
    "high": "非常理解您的心情，这个问题我们会高度重视。由于情况比较特殊，我需要将您的问题转交主管进一步核实处理，请您稍等，我们会尽快给您答复。",
    "medium": "感谢您的反馈，我已经记录了您的问题，会尽快帮您核实情况。涉及具体处理方案需要确认后再回复您，请您耐心等待。",
    "low": "亲，我这边先收到您的问题了。系统刚才没有生成到足够稳定的建议，我会按当前会话里的商品、订单或售后信息继续核对；如果需要补充资料，我会只问和当前问题相关的一项信息。",
}


class LLMClient:
    """LLM 调用客户端"""

    def __init__(
        self,
        api_key: str = "",
        api_base: str = "",
        model: str = "",
        timeout_seconds: int | None = None,
        transport_thinking: str = "",
        minimum_output_tokens: int = 0,
    ):
        self.api_key = api_key or LLM_API_KEY
        self.api_base = api_base or LLM_API_BASE
        self.model = model or LLM_MODEL
        self.timeout_seconds = timeout_seconds
        self.transport_thinking = str(transport_thinking or "").strip().lower()
        self.minimum_output_tokens = max(0, int(minimum_output_tokens or 0))
        self._client = None

    @property
    def client(self) -> OpenAI:
        if self._client is None:
            kwargs = {
                "api_key": self.api_key,
                "base_url": self.api_base,
            }
            if self.timeout_seconds is not None:
                kwargs["timeout"] = self.timeout_seconds
            self._client = OpenAI(**kwargs)
        return self._client

    @property
    def provider_name(self) -> str:
        """Infer the transport provider without exposing credentials."""
        hostname = (urlparse(self.api_base).hostname or "").lower()
        if hostname == "api.minimaxi.com" or hostname.endswith(".minimaxi.com"):
            return "minimax"
        if hostname == "api.minimax.io" or hostname.endswith(".minimax.io"):
            return "minimax"
        if hostname == "api.deepseek.com" or hostname.endswith(".deepseek.com"):
            return "deepseek"
        if hostname:
            return hostname.split(".")[0]
        return "unknown"

    def create_chat_completion(self, **kwargs):
        """Create a completion with provider-specific transport compatibility.

        MiniMax M2 reasoning models need enough output budget to finish their
        reasoning before emitting the customer-facing content. Separating the
        reasoning keeps existing JSON and plain-text consumers unchanged.
        """
        request = dict(kwargs)
        single_attempt_no_repair = bool(
            request.pop("_single_attempt_no_repair", False)
        )
        request["messages"] = self._privacy_project_messages(request.get("messages"))
        if self.minimum_output_tokens:
            request["max_tokens"] = max(
                int(request.get("max_tokens") or 0),
                self.minimum_output_tokens,
            )
        if self.provider_name == "minimax":
            temperature = float(request.get("temperature", 0.3) or 0)
            request["temperature"] = max(temperature, 0.1)
            model = str(request.get("model") or self.model or "")
            is_m3 = model.lower().startswith("minimax-m3")
            minimum_output_tokens = 800 if is_m3 else 1200
            request["max_tokens"] = max(
                int(request.get("max_tokens") or 0),
                minimum_output_tokens,
            )
            extra_body = dict(request.get("extra_body") or {})
            extra_body.setdefault("reasoning_split", True)
            if is_m3 or self.transport_thinking == "disabled":
                extra_body.setdefault("thinking", {"type": "disabled"})
            request["extra_body"] = extra_body
        elif self.provider_name == "deepseek":
            # DeepSeek V4 enables hidden reasoning by default. Composer emits a
            # bounded JSON contract, so reserve its output budget for that contract.
            extra_body = dict(request.get("extra_body") or {})
            extra_body.setdefault("thinking", {"type": "disabled"})
            request["extra_body"] = extra_body
        elif self.transport_thinking == "disabled":
            # Qwen/vLLM and other compatible local servers use chat-template
            # kwargs rather than DeepSeek's transport-specific thinking field.
            extra_body = dict(request.get("extra_body") or {})
            extra_body.setdefault(
                "chat_template_kwargs", {"enable_thinking": False}
            )
            request["extra_body"] = extra_body

        if single_attempt_no_repair:
            return self.client.chat.completions.create(**request)

        response_format = request.get("response_format") or {}
        max_attempts = 2 if (
            self.provider_name == "minimax"
            and response_format.get("type") == "json_object"
        ) else 1
        for attempt in range(max_attempts):
            response = self.client.chat.completions.create(**request)
            if self.provider_name != "minimax":
                return response

            choice = response.choices[0] if response.choices else None
            finish_reason = str(getattr(choice, "finish_reason", "") or "")
            content = str(getattr(getattr(choice, "message", None), "content", "") or "")
            if finish_reason == "length":
                raise RuntimeError("minimax_response_truncated")
            if not content.strip():
                raise RuntimeError("minimax_empty_response")
            if response_format.get("type") != "json_object":
                return response

            normalized = self._complete_json_object(content)
            if normalized is not None:
                choice.message.content = json.dumps(normalized, ensure_ascii=False)
                return response
            if attempt + 1 == max_attempts:
                raise RuntimeError("minimax_invalid_json_object")

        raise RuntimeError("minimax_completion_unavailable")

    @staticmethod
    def _privacy_project_messages(messages):
        """Apply the field-aware provider-boundary privacy projection.

        Most structured context arrives as a JSON string inside a user message.
        Parsing that shape before projection preserves product titles and
        admitted facts while pseudonymising private and product identifiers.
        Plain system prompts remain text and use the precise text projection.
        """
        from app.services.canonical_conversation_turn_service import (
            project_provider_message_text,
            project_value_for_external_model,
        )

        def project_text(value):
            text = str(value or "")
            stripped = text.strip()
            if stripped.startswith(("{", "[")):
                try:
                    parsed = json.loads(stripped)
                except json.JSONDecodeError:
                    pass
                else:
                    return json.dumps(project_value_for_external_model(parsed), ensure_ascii=False)
            return project_provider_message_text(text)

        if not isinstance(messages, list):
            return messages
        projected = []
        for message in messages:
            if not isinstance(message, dict):
                projected.append(message)
                continue
            current = dict(message)
            content = current.get("content")
            if isinstance(content, str):
                current["content"] = project_text(content)
            elif isinstance(content, list):
                parts = []
                for part in content:
                    if not isinstance(part, dict):
                        parts.append(part)
                        continue
                    projected_part = dict(part)
                    if projected_part.get("type") == "text" and isinstance(projected_part.get("text"), str):
                        projected_part["text"] = project_text(projected_part["text"])
                    parts.append(projected_part)
                current["content"] = parts
            projected.append(current)
        return projected

    @staticmethod
    def _complete_json_object(content: str) -> Optional[dict]:
        """Return a complete JSON object without repairing incomplete output."""
        text = str(content or "").strip()
        candidates = [text]
        if text.startswith("```") and text.endswith("```"):
            inner = text[3:-3].strip()
            if inner.lower().startswith("json"):
                inner = inner[4:].strip()
            candidates.append(inner)
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            candidates.append(text[start : end + 1])
        for candidate in candidates:
            try:
                parsed = json.loads(candidate)
            except (TypeError, json.JSONDecodeError):
                continue
            if isinstance(parsed, dict):
                return parsed
        return None

    def chat(
        self,
        system_prompt: str,
        user_message: str,
        temperature: float = 0.3,
        max_tokens: int = 300,  # 客服回复简短，300足够
    ) -> dict:
        """
        调用 LLM，返回字典。
        - 成功: 返回 LLM 解析后的 dict
        - 失败: 返回安全降级 dict，error 字段标明原因
        """
        if not self.api_key:
            return _make_fallback(
                risk_level="low",
                error_type="UNCONFIGURED",
                detail="缺少 COPILOT_LLM_API_KEY",
            )

        raw = ""
        try:
            kwargs = dict(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_message},
                ],
                temperature=temperature,
                max_tokens=max_tokens,
            )
            # 通义千问支持 json_object 模式
            kwargs["response_format"] = {"type": "json_object"}

            response = self.create_chat_completion(**kwargs)
            raw = response.choices[0].message.content.strip()

            # 解析 JSON
            parsed = self._parse_json(raw)

            # Pydantic schema 校验
            is_valid, errors = validate_llm_output(parsed)
            if not is_valid:
                logger.warning("LLM schema 校验失败: %s", errors)
                # 不直接用不合格结果，进入安全降级
                return _make_fallback(
                    risk_level=parsed.get("risk_level", "low"),
                    error_type="SCHEMA_VALIDATION_ERROR",
                    detail="; ".join(errors),
                    partial_intent=parsed.get("intent", ""),
                )

            return parsed

        except json.JSONDecodeError:
            logger.error("LLM JSON 解析失败")
            return _make_fallback(
                risk_level="low",
                error_type="JSON_PARSE_ERROR",
                detail="LLM 输出不是有效 JSON",
            )
        except Exception as e:
            logger.error("LLM 调用失败: %s", e)
            return _make_fallback(
                risk_level="low",
                error_type="LLM_CALL_ERROR",
                detail=str(e),
            )

    def _parse_json(self, raw: str) -> dict:
        """解析 LLM 返回的 JSON，处理各种边界情况"""
        text = raw.strip()

        # 去掉 markdown 代码块标记
        if text.startswith("```"):
            # 取第一个 ``` 和最后一个 ``` 之间的内容
            start = text.find("```")
            end = text.rfind("```")
            if end > start:
                inner = text[start + 3 : end]
                # 去掉开头的 json 标记
                if inner.startswith("json"):
                    inner = inner[4:]
                text = inner.strip()

        # 尝试提取第一个 { ... } 块
        brace_start = text.find("{")
        brace_end = text.rfind("}")
        if brace_start != -1 and brace_end > brace_start:
            text = text[brace_start : brace_end + 1]

        return json.loads(text)


def _make_fallback(
    risk_level: str = "low",
    error_type: str = "",
    detail: str = "",
    partial_intent: str = "",
) -> dict:
    """
    生成安全降级回复。
    - suggested_reply 根据风险等级给出不同的安全话术
    - error 标明具体错误类型
    - requires_human_review 高风险时强制 True
    """
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


# 全局单例
_client: Optional[LLMClient] = None


def get_llm_client() -> LLMClient:
    global _client
    if _client is None:
        _client = LLMClient(
            transport_thinking=config.COPILOT_LLM_TRANSPORT_THINKING,
            minimum_output_tokens=config.COPILOT_LLM_MIN_OUTPUT_TOKENS,
        )
    return _client


def composer_role_configuration_fingerprint(
    *,
    api_base: str,
    model: str,
    timeout_seconds: int,
    transport_thinking: str = "",
    minimum_output_tokens: int = 0,
) -> str:
    """Bind a Composer qualification to its non-secret transport settings."""
    payload = {
        "contract": COMPOSER_ROLE_QUALIFICATION_CONTRACT,
        "api_base_sha256": hashlib.sha256(
            str(api_base or "").strip().encode("utf-8")
        ).hexdigest(),
        "model": str(model or "").strip(),
        "timeout_seconds": int(timeout_seconds),
    }
    normalized_thinking = str(transport_thinking or "").strip().lower()
    normalized_minimum_output = max(0, int(minimum_output_tokens or 0))
    if normalized_thinking or normalized_minimum_output:
        payload["transport_capabilities"] = {
            "thinking": normalized_thinking,
            "minimum_output_tokens": normalized_minimum_output,
        }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        )
    ).hexdigest()


def get_composer_llm_client(
    *,
    allow_unqualified: bool = False,
) -> LLMClient:
    """Return the qualified Composer override or the unchanged formal client."""
    values = {
        "api_key": str(config.COPILOT_COMPOSER_LLM_API_KEY or "").strip(),
        "api_base": str(config.COPILOT_COMPOSER_LLM_API_BASE or "").strip(),
        "model": str(config.COPILOT_COMPOSER_LLM_MODEL or "").strip(),
    }
    override_requested = any(values.values())
    if not override_requested:
        return get_llm_client()
    if not all(values.values()):
        raise ComposerRoleConfigurationError(
            "composer_role_provider_incomplete"
        )
    if (
        not config.COPILOT_COMPOSER_LLM_QUALIFIED
        and not allow_unqualified
    ):
        raise ComposerRoleConfigurationError(
            "composer_role_provider_not_qualified"
        )
    timeout_seconds = max(
        1,
        min(int(config.COPILOT_COMPOSER_LLM_TIMEOUT_SECONDS), 120),
    )
    transport_thinking = str(
        config.COPILOT_COMPOSER_LLM_TRANSPORT_THINKING or ""
    ).strip().lower()
    if transport_thinking not in {"", "disabled"}:
        raise ComposerRoleConfigurationError(
            "composer_role_transport_thinking_invalid"
        )
    minimum_output_tokens = max(
        0,
        min(int(config.COPILOT_COMPOSER_LLM_MIN_OUTPUT_TOKENS), 4096),
    )
    if not allow_unqualified:
        expected_fingerprint = str(
            config.COPILOT_COMPOSER_LLM_QUALIFICATION_FINGERPRINT or ""
        ).strip()
        if not expected_fingerprint:
            raise ComposerRoleConfigurationError(
                "composer_role_qualification_fingerprint_missing"
            )
        actual_fingerprint = composer_role_configuration_fingerprint(
            api_base=values["api_base"],
            model=values["model"],
            timeout_seconds=timeout_seconds,
            transport_thinking=transport_thinking,
            minimum_output_tokens=minimum_output_tokens,
        )
        if actual_fingerprint != expected_fingerprint:
            raise ComposerRoleConfigurationError(
                "composer_role_configuration_changed"
            )
    return LLMClient(
        api_key=values["api_key"],
        api_base=values["api_base"],
        model=values["model"],
        timeout_seconds=timeout_seconds,
        transport_thinking=transport_thinking,
        minimum_output_tokens=minimum_output_tokens,
    )
