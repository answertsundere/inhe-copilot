"""
LLM 输出 Schema - Pydantic 模型定义 + 校验
"""

from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field, field_validator


# ============ 枚举 ============


class RiskLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


# ============ 子模型 ============


class ActionProposal(BaseModel):
    """建议动作"""
    action_type: str = Field(default="无", description="建议动作，如：无、查订单、催仓、创建售后工单、转主管")
    reason: str = Field(default="", description="建议原因")


# ============ 主模型 ============


class LLMReplyOutput(BaseModel):
    """LLM 结构化输出 - 完整 schema"""

    intent: str = Field(description="客户意图，如：催发货、查物流、退货退款、商品咨询、投诉等")
    risk_level: RiskLevel = Field(description="风险等级")
    customer_emotion: str = Field(default="未知", description="客户情绪，如：平静、焦急、不满、愤怒")
    need_lookup: list[str] = Field(default_factory=list, description="需要查询的数据类型")
    suggested_reply: str = Field(description="建议回复内容")
    reply_style: str = Field(default="简洁专业", description="回复风格")
    policy_warnings: list[str] = Field(default_factory=list, description="规则提醒")
    action_proposal: ActionProposal = Field(default_factory=ActionProposal, description="建议动作")
    requires_human_review: bool = Field(default=False, description="是否需要人工复核")

    @field_validator("suggested_reply")
    @classmethod
    def reply_must_not_be_empty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("suggested_reply 不能为空")
        return v


# ============ 降级模型 (LLM 不可用或出错时) ============


class FallbackReplyOutput(BaseModel):
    """降级输出 - LLM 不可用或出错时"""
    intent: str = "系统提示"
    risk_level: RiskLevel = RiskLevel.LOW
    customer_emotion: str = "未知"
    suggested_reply: str = "系统暂时无法生成建议，请人工处理。"
    requires_human_review: bool = False
    error: str = ""


# ============ 校验函数 ============


def validate_llm_output(data: dict) -> tuple[bool, list[str]]:
    """
    用 Pydantic 校验 LLM 输出。
    返回 (is_valid, errors)
    """
    try:
        LLMReplyOutput.model_validate(data)
        return True, []
    except Exception as e:
        # 收集所有校验错误
        errors = []
        if hasattr(e, "errors"):
            for err in e.errors():
                loc = ".".join(str(x) for x in err.get("loc", []))
                msg = err.get("msg", str(err))
                errors.append(f"{loc}: {msg}")
        else:
            errors.append(str(e))
        return False, errors


def parse_llm_output(data: dict) -> LLMReplyOutput:
    """
    解析并校验 LLM 输出为 Pydantic 模型。
    校验失败时返回降级结果。
    """
    try:
        return LLMReplyOutput.model_validate(data)
    except Exception:
        # 尝试部分填充
        return LLMReplyOutput(
            intent=data.get("intent", "解析失败"),
            risk_level=_safe_risk_level(data.get("risk_level", "low")),
            customer_emotion=data.get("customer_emotion", "未知"),
            suggested_reply=data.get("suggested_reply") or "AI 输出格式异常，请人工处理",
            reply_style=data.get("reply_style", "简洁专业"),
            policy_warnings=data.get("policy_warnings", []),
            action_proposal=ActionProposal(
                action_type=data.get("action_proposal", {}).get("action_type", "无"),
                reason=data.get("action_proposal", {}).get("reason", ""),
            ) if isinstance(data.get("action_proposal"), dict) else ActionProposal(),
            requires_human_review=data.get("requires_human_review", False),
        )


def _safe_risk_level(value) -> RiskLevel:
    """安全转换 risk_level"""
    if isinstance(value, RiskLevel):
        return value
    try:
        return RiskLevel(value)
    except (ValueError, KeyError):
        return RiskLevel.LOW
