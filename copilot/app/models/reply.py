"""
回复建议数据模型 - 基于 Pydantic

这个模块是对外暴露的数据结构，用于 API 响应和内部传递。
LLM 原始输出的 schema 定义在 app/llm/schemas.py。
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field

from app.llm.schemas import (
    LLMReplyOutput,
    ActionProposal as LLMActionProposal,
    RiskLevel,
    _safe_risk_level,
)


class ActionProposal(BaseModel):
    """建议动作"""
    action_type: str = "无"
    reason: str = ""


class ReplySuggestion(BaseModel):
    """AI 回复建议 - 对外暴露的完整结构"""
    intent: str = ""
    risk_level: str = "low"
    customer_emotion: str = ""
    need_lookup: list[str] = Field(default_factory=list)
    suggested_reply: str = ""
    reply_style: str = ""
    policy_warnings: list[str] = Field(default_factory=list)
    action_proposal: ActionProposal = Field(default_factory=ActionProposal)
    requires_human_review: bool = False
    reason_for_review: str = ""
    reply_tone: str = ""
    evidence_used: str = ""
    tools_to_call: list[str] = Field(default_factory=list)
    error: str = ""
    guard_warnings: list[str] = Field(default_factory=list)
    review_id: str = ""
    context_used: dict = Field(default_factory=dict)
    skill_route: dict = Field(default_factory=dict)
    matched_sops: list = Field(default_factory=list)
    matched_templates: list = Field(default_factory=list)
    data_quality_warnings: list[str] = Field(default_factory=list)
    trace_steps: list[dict] = Field(default_factory=list)
    evidence_debug: dict = Field(default_factory=dict)
    execution_debug: dict = Field(default_factory=dict)
    needs_clarification: bool = False
    # 路由溯源字段
    used_fact_tool: str = ""
    used_endpoint: str = ""
    identifier_type: str = ""
    # 运行时调试契约字段（前端 evidence_debug / execution_debug 依赖）
    answer_mode: str = ""
    generation_mode: str = ""
    llm_used: bool = False
    used_knowledge_entry_ids: list = Field(default_factory=list)
    used_knowledge_titles: list = Field(default_factory=list)
    used_fact_tools: list = Field(default_factory=list)
    product_context_validation: dict = Field(default_factory=dict)
    generic_service_rule_used: dict = Field(default_factory=dict)
    query_fact_type: str = ""
    query_fact_type_label: str = ""
    secondary_fact_types: list[str] = Field(default_factory=list)
    required_fact_types: list[str] = Field(default_factory=list)
    query_understanding: dict = Field(default_factory=dict)
    product_context_pack_stats: dict = Field(default_factory=dict)

    def to_dict(self) -> dict:
        """转为字典（API 响应用）"""
        d = self.model_dump(exclude_none=True)
        if not self.guard_warnings:
            d.pop("guard_warnings", None)
        if not self.error:
            d.pop("error", None)
        if not self.review_id:
            d.pop("review_id", None)
        if not self.context_used:
            d.pop("context_used", None)
        if not self.skill_route:
            d.pop("skill_route", None)
        if not self.matched_sops:
            d.pop("matched_sops", None)
        if not self.matched_templates:
            d.pop("matched_templates", None)
        if not self.data_quality_warnings:
            d.pop("data_quality_warnings", None)
        if not self.trace_steps:
            d.pop("trace_steps", None)
        if not self.evidence_debug:
            d.pop("evidence_debug", None)
        if not self.execution_debug:
            d.pop("execution_debug", None)
        if not self.needs_clarification:
            d.pop("needs_clarification", None)
        if not self.used_fact_tool:
            d.pop("used_fact_tool", None)
        if not self.used_endpoint:
            d.pop("used_endpoint", None)
        if not self.identifier_type:
            d.pop("identifier_type", None)
        if not self.answer_mode:
            d.pop("answer_mode", None)
        if not self.generation_mode:
            d.pop("generation_mode", None)
        if not self.llm_used:
            d.pop("llm_used", None)
        if not self.used_knowledge_entry_ids:
            d.pop("used_knowledge_entry_ids", None)
        if not self.used_knowledge_titles:
            d.pop("used_knowledge_titles", None)
        if not self.used_fact_tools:
            d.pop("used_fact_tools", None)
        if not self.product_context_validation:
            d.pop("product_context_validation", None)
        if not self.generic_service_rule_used:
            d.pop("generic_service_rule_used", None)
        if not self.query_fact_type:
            d.pop("query_fact_type", None)
        if not self.query_fact_type_label:
            d.pop("query_fact_type_label", None)
        if not self.secondary_fact_types:
            d.pop("secondary_fact_types", None)
        if not self.required_fact_types:
            d.pop("required_fact_types", None)
        if not self.query_understanding:
            d.pop("query_understanding", None)
        if not self.product_context_pack_stats:
            d.pop("product_context_pack_stats", None)
        return d

    @classmethod
    def from_llm_output(cls, llm_output: LLMReplyOutput, **overrides) -> "ReplySuggestion":
        """从 LLM Pydantic 输出创建"""
        data = llm_output.model_dump()
        data.update(overrides)
        # 转换 action_proposal 类型
        ap = data.get("action_proposal", {})
        data["action_proposal"] = ActionProposal(
            action_type=ap.get("action_type", "无") if isinstance(ap, dict) else getattr(ap, "action_type", "无"),
            reason=ap.get("reason", "") if isinstance(ap, dict) else getattr(ap, "reason", ""),
        )
        # risk_level 转字符串 (.value 取枚举值)
        rl = data.get("risk_level", "low")
        data["risk_level"] = rl.value if isinstance(rl, RiskLevel) else str(rl)
        return cls(**data)

    @classmethod
    def from_dict(cls, data: dict) -> "ReplySuggestion":
        """从字典创建（兼容旧调用）"""
        action_data = data.get("action_proposal", {})
        if isinstance(action_data, dict):
            action = ActionProposal(
                action_type=action_data.get("action_type", "无"),
                reason=action_data.get("reason", ""),
            )
        elif isinstance(action_data, ActionProposal):
            action = action_data
        else:
            action = ActionProposal()

        return cls(
            intent=data.get("intent", ""),
            risk_level=str(data.get("risk_level", "low")),
            customer_emotion=data.get("customer_emotion", ""),
            need_lookup=data.get("need_lookup", []),
            suggested_reply=data.get("suggested_reply", ""),
            reply_style=data.get("reply_style", ""),
            policy_warnings=data.get("policy_warnings", []),
            action_proposal=action,
            requires_human_review=data.get("requires_human_review", False),
            reason_for_review=data.get("reason_for_review", data.get("review_reason", "")),
            reply_tone=data.get("reply_tone", ""),
            evidence_used=data.get("evidence_used", ""),
            tools_to_call=data.get("tools_to_call", []),
            error=data.get("error", ""),
            guard_warnings=data.get("guard_warnings", []),
            review_id=data.get("review_id", ""),
            context_used=data.get("context_used", {}),
            skill_route=data.get("skill_route", {}),
            matched_sops=data.get("matched_sops", []),
            matched_templates=data.get("matched_templates", []),
            data_quality_warnings=data.get("data_quality_warnings", []),
            trace_steps=data.get("trace_steps", []),
            evidence_debug=data.get("evidence_debug", {}),
            execution_debug=data.get("execution_debug", {}),
            needs_clarification=data.get("needs_clarification", False),
            used_fact_tool=data.get("used_fact_tool", ""),
            used_endpoint=data.get("used_endpoint", ""),
            identifier_type=data.get("identifier_type", ""),
            answer_mode=data.get("answer_mode", ""),
            generation_mode=data.get("generation_mode", ""),
            llm_used=data.get("llm_used", False),
            used_knowledge_entry_ids=data.get("used_knowledge_entry_ids", []),
            used_knowledge_titles=data.get("used_knowledge_titles", []),
            used_fact_tools=data.get("used_fact_tools", data.get("fact_tools", [])),
            product_context_validation=data.get("product_context_validation", {}),
            generic_service_rule_used=data.get("generic_service_rule_used", {}),
            query_fact_type=data.get("query_fact_type", ""),
            query_fact_type_label=data.get("query_fact_type_label", ""),
            secondary_fact_types=data.get("secondary_fact_types", []),
            required_fact_types=data.get("required_fact_types", []),
            query_understanding=data.get("query_understanding", {}),
            product_context_pack_stats=data.get("product_context_pack_stats", {}),
        )


class FeedbackRecord(BaseModel):
    """反馈记录"""
    customer_message: str = ""
    order_id: str = ""
    suggested_reply: str = ""
    final_reply: str = ""
    action: str = ""              # accepted / edited / rejected / escalated
    risk_level: str = ""
    created_at: str = ""
