"""
LLM 客户端 - 封装模型调用逻辑，含安全降级
"""

import json
import logging
from typing import Optional

from openai import OpenAI

from app.config import LLM_API_BASE, LLM_API_KEY, LLM_MODEL
from .schemas import validate_llm_output, FallbackReplyOutput

logger = logging.getLogger(__name__)


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
    ):
        self.api_key = api_key or LLM_API_KEY
        self.api_base = api_base or LLM_API_BASE
        self.model = model or LLM_MODEL
        self._client = None

    @property
    def client(self) -> OpenAI:
        if self._client is None:
            self._client = OpenAI(api_key=self.api_key, base_url=self.api_base)
        return self._client

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

            response = self.client.chat.completions.create(**kwargs)
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
        _client = LLMClient()
    return _client
