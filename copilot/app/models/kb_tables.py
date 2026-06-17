"""
智能客服知识库 - 扩展数据模型
与现有 knowledge_entries 表并存，提供更细粒度的实体管理
"""

import json
from datetime import datetime
from sqlalchemy import (
    Column, Integer, String, Text, Boolean, DateTime, Float, ForeignKey,
    Index,
)
from sqlalchemy.orm import relationship

from app.db import Base


def _json_get(raw, default=None):
    try:
        return json.loads(raw or ("[]" if default is None else "{}"))
    except Exception:
        return default if default is not None else []


def _json_set(value, is_list=True):
    if value is None:
        return "[]" if is_list else "{}"
    return json.dumps(value, ensure_ascii=False)


# ─── 商品知识库 ───
class KBProduct(Base):
    __tablename__ = "kb_product"

    id = Column(Integer, primary_key=True, autoincrement=True)
    i_id = Column(String(64), nullable=False, unique=True, index=True)
    product_name = Column(String(255), nullable=False, index=True)
    brand = Column(String(128), nullable=False, default="")

    category_l1 = Column(String(64), nullable=False, default="", index=True)
    category_l2 = Column(String(64), nullable=False, default="")
    category_l3 = Column(String(64), nullable=False, default="")

    sku_list_json = Column(Text, nullable=False, default="[]")
    specs_json = Column(Text, nullable=False, default="{}")
    logistics_json = Column(Text, nullable=False, default="{}")
    warranty_json = Column(Text, nullable=False, default="{}")

    completeness_score = Column(Float, nullable=False, default=0.0)
    missing_fields_json = Column(Text, nullable=False, default="[]")

    status = Column(String(16), nullable=False, default="draft", index=True)
    version = Column(Integer, nullable=False, default=1)

    created_by = Column(String(64), nullable=False, default="")
    updated_by = Column(String(64), nullable=False, default="")
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    import_batch_id = Column(String(64), nullable=False, default="")

    qa_entries = relationship("KBQA", back_populates="product")

    __table_args__ = (
        Index("idx_product_cat12", "category_l1", "category_l2"),
    )

    def get_sku_list(self):
        return _json_get(self.sku_list_json, [])

    def set_sku_list(self, value):
        self.sku_list_json = _json_set(value, True)

    def get_specs(self):
        return _json_get(self.specs_json, {})

    def set_specs(self, value):
        self.specs_json = _json_set(value, False)

    def get_logistics(self):
        return _json_get(self.logistics_json, {})

    def set_logistics(self, value):
        self.logistics_json = _json_set(value, False)

    def get_warranty(self):
        return _json_get(self.warranty_json, {})

    def set_warranty(self, value):
        self.warranty_json = _json_set(value, False)

    def get_missing_fields(self):
        return _json_get(self.missing_fields_json, [])

    def set_missing_fields(self, value):
        self.missing_fields_json = _json_set(value, True)

    def to_dict(self, detail=False):
        d = {
            "id": self.id,
            "i_id": self.i_id,
            "product_name": self.product_name,
            "brand": self.brand,
            "category_l1": self.category_l1,
            "category_l2": self.category_l2,
            "category_l3": self.category_l3,
            "completeness_score": self.completeness_score,
            "missing_fields": self.get_missing_fields(),
            "specs": self.get_specs(),
            "logistics": self.get_logistics(),
            "warranty": self.get_warranty(),
            "status": self.status,
            "version": self.version,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
        if detail:
            d.update({
                "sku_list": self.get_sku_list(),
                "created_by": self.created_by,
                "updated_by": self.updated_by,
            })
        return d


class KBProductActivityRule(Base):
    __tablename__ = "kb_product_activity_rule"

    id = Column(Integer, primary_key=True, autoincrement=True)
    product_id = Column(Integer, ForeignKey("kb_product.id"), nullable=True, index=True)
    i_id = Column(String(64), nullable=False, default="", index=True)
    sku_code = Column(String(64), nullable=False, default="", index=True)
    product_name = Column(String(255), nullable=False, default="", index=True)

    activity_type = Column(String(32), nullable=False, default="other", index=True)
    title = Column(String(255), nullable=False, default="")
    condition_text = Column(Text, nullable=False, default="")
    customer_visible_benefit = Column(Text, nullable=False, default="")
    customer_reply = Column(Text, nullable=False, default="")

    internal_price_field = Column(String(128), nullable=False, default="")
    internal_price_value = Column(Float, nullable=True)
    internal_only_json = Column(Text, nullable=False, default="{}")

    start_at = Column(DateTime, nullable=True)
    end_at = Column(DateTime, nullable=True)
    status = Column(String(16), nullable=False, default="pending_review", index=True)
    risk_level = Column(String(16), nullable=False, default="low")
    auto_reply_allowed = Column(Boolean, nullable=False, default=False)

    source = Column(String(64), nullable=False, default="dingtalk_activity_sheet")
    source_record_id = Column(String(128), nullable=False, default="", index=True)
    source_sheet_id = Column(String(64), nullable=False, default="")
    content_hash = Column(String(64), nullable=False, default="", index=True)
    raw_fields_json = Column(Text, nullable=False, default="{}")

    last_seen_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        Index("idx_activity_product_status", "product_id", "status"),
        Index("idx_activity_iid_status", "i_id", "status"),
        Index("idx_activity_sku_status", "sku_code", "status"),
        Index("idx_activity_source_record", "source_sheet_id", "source_record_id"),
    )

    def get_internal_only(self):
        return _json_get(self.internal_only_json, {})

    def set_internal_only(self, value):
        self.internal_only_json = _json_set(value, False)

    def get_raw_fields(self):
        return _json_get(self.raw_fields_json, {})

    def set_raw_fields(self, value):
        self.raw_fields_json = _json_set(value, False)

    def customer_context(self):
        return {
            "id": self.id,
            "product_id": self.product_id,
            "i_id": self.i_id,
            "sku_code": self.sku_code,
            "product_name": self.product_name,
            "activity_type": self.activity_type,
            "title": self.title,
            "condition_text": self.condition_text,
            "customer_visible_benefit": self.customer_visible_benefit,
            "customer_reply": self.customer_reply,
            "status": self.status,
            "risk_level": self.risk_level,
            "auto_reply_allowed": self.auto_reply_allowed,
            "start_at": self.start_at.isoformat() if self.start_at else None,
            "end_at": self.end_at.isoformat() if self.end_at else None,
        }

    def to_dict(self, include_internal=False):
        data = self.customer_context()
        data.update({
            "source": self.source,
            "source_record_id": self.source_record_id,
            "source_sheet_id": self.source_sheet_id,
            "content_hash": self.content_hash,
            "last_seen_at": self.last_seen_at.isoformat() if self.last_seen_at else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        })
        if include_internal:
            data.update({
                "internal_price_field": self.internal_price_field,
                "internal_price_value": self.internal_price_value,
                "internal_only": self.get_internal_only(),
                "raw_fields": self.get_raw_fields(),
            })
        return data


class KBGenericServiceRule(Base):
    """通用服务规则 / 金牌话术库。

    只作为商品事实不足时的服务表达和安全边界补充，不能覆盖明确商品事实。
    """
    __tablename__ = "kb_generic_service_rule"

    id = Column(Integer, primary_key=True, autoincrement=True)
    rule_key = Column(String(128), nullable=False, unique=True, index=True)
    title = Column(String(255), nullable=False, default="")
    intent = Column(String(64), nullable=False, default="general", index=True)
    fact_type = Column(String(64), nullable=False, default="", index=True)
    scenario = Column(String(64), nullable=False, default="", index=True)
    query_keywords_json = Column(Text, nullable=False, default="[]")
    content = Column(Text, nullable=False, default="")
    reply_template = Column(Text, nullable=False, default="")
    forbidden_claims_json = Column(Text, nullable=False, default="[]")
    allowed_when_product_fact_missing = Column(Boolean, nullable=False, default=True)
    required_guardrails_json = Column(Text, nullable=False, default="[]")
    priority = Column(Integer, nullable=False, default=100)
    version = Column(String(32), nullable=False, default="v1")
    status = Column(String(16), nullable=False, default="active", index=True)
    risk_level = Column(String(16), nullable=False, default="low")
    auto_reply_allowed = Column(Boolean, nullable=False, default=True)
    source_confidence = Column(Float, nullable=False, default=0.75)
    source = Column(String(64), nullable=False, default="seed_generic_service_rules")
    content_hash = Column(String(64), nullable=False, default="", index=True)
    created_by = Column(String(64), nullable=False, default="")
    updated_by = Column(String(64), nullable=False, default="")
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        Index("idx_generic_rule_intent_fact", "intent", "fact_type", "status"),
    )

    def get_query_keywords(self):
        return _json_get(self.query_keywords_json, [])

    def set_query_keywords(self, value):
        self.query_keywords_json = _json_set(value, True)

    def get_forbidden_claims(self):
        return _json_get(self.forbidden_claims_json, [])

    def set_forbidden_claims(self, value):
        self.forbidden_claims_json = _json_set(value, True)

    def get_required_guardrails(self):
        return _json_get(self.required_guardrails_json, [])

    def set_required_guardrails(self, value):
        self.required_guardrails_json = _json_set(value, True)

    def to_dict(self):
        return {
            "id": self.id,
            "rule_key": self.rule_key,
            "title": self.title,
            "intent": self.intent,
            "fact_type": self.fact_type,
            "scenario": self.scenario,
            "query_keywords": self.get_query_keywords(),
            "content": self.content,
            "reply_template": self.reply_template,
            "forbidden_claims": self.get_forbidden_claims(),
            "allowed_when_product_fact_missing": self.allowed_when_product_fact_missing,
            "required_guardrails": self.get_required_guardrails(),
            "priority": self.priority,
            "version": self.version,
            "status": self.status,
            "risk_level": self.risk_level,
            "auto_reply_allowed": self.auto_reply_allowed,
            "source_confidence": self.source_confidence,
            "source": self.source,
            "content_hash": self.content_hash,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


# ─── 问答知识库 ───
class KBQA(Base):
    __tablename__ = "kb_qa"

    id = Column(Integer, primary_key=True, autoincrement=True)

    question = Column(String(500), nullable=False, index=True)
    answer = Column(Text, nullable=False)
    intent = Column(String(64), nullable=False, default="general", index=True)
    sub_intent = Column(String(64), nullable=False, default="")

    category_l1 = Column(String(64), nullable=False, default="", index=True)
    category_l2 = Column(String(64), nullable=False, default="")
    category_l3 = Column(String(64), nullable=False, default="")

    product_id = Column(Integer, ForeignKey("kb_product.id"), nullable=True, index=True)
    sku_codes_json = Column(Text, nullable=False, default="[]")

    risk_level = Column(String(16), nullable=False, default="low", index=True)
    auto_reply = Column(Boolean, nullable=False, default=True)
    human_review = Column(Boolean, nullable=False, default=False)

    keywords_json = Column(Text, nullable=False, default="[]")
    source_type = Column(String(32), nullable=False, default="faq", index=True)

    # QA-SOP linking and classification
    scenario_category = Column(String(64), nullable=False, default="", index=True)
    issue_type = Column(String(64), nullable=False, default="", index=True)
    sop_id = Column(Integer, nullable=True, index=True)

    status = Column(String(16), nullable=False, default="draft", index=True)
    version = Column(Integer, nullable=False, default=1)

    created_by = Column(String(64), nullable=False, default="")
    updated_by = Column(String(64), nullable=False, default="")
    reviewed_by = Column(String(64), nullable=False, default="")
    published_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    import_batch_id = Column(String(64), nullable=False, default="")
    content_hash = Column(String(64), nullable=False, default="", index=True)

    product = relationship("KBProduct", back_populates="qa_entries")
    variants = relationship("KBQuestionVariant", back_populates="qa_entry", cascade="all, delete-orphan")

    __table_args__ = (
        Index("idx_qa_intent_status", "intent", "status"),
        Index("idx_qa_source_status", "source_type", "status"),
        Index("idx_qa_risk_status", "risk_level", "status"),
    )

    def get_sku_codes(self):
        return _json_get(self.sku_codes_json, [])

    def set_sku_codes(self, value):
        self.sku_codes_json = _json_set(value, True)

    def get_keywords(self):
        return _json_get(self.keywords_json, [])

    def set_keywords(self, value):
        self.keywords_json = _json_set(value, True)

    def to_dict(self, include_variants=False):
        d = {
            "id": self.id,
            "question": self.question,
            "answer": self.answer,
            "intent": self.intent,
            "sub_intent": self.sub_intent,
            "category_l1": self.category_l1,
            "category_l2": self.category_l2,
            "category_l3": self.category_l3,
            "product_id": self.product_id,
            "sku_codes": self.get_sku_codes(),
            "risk_level": self.risk_level,
            "auto_reply": self.auto_reply,
            "human_review": self.human_review,
            "scenario_category": self.scenario_category,
            "issue_type": self.issue_type,
            "sop_id": self.sop_id,
            "keywords": self.get_keywords(),
            "source_type": self.source_type,
            "status": self.status,
            "version": self.version,
            "created_by": self.created_by,
            "updated_by": self.updated_by,
            "reviewed_by": self.reviewed_by,
            "published_at": self.published_at.isoformat() if self.published_at else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
        if include_variants:
            d["variants"] = [v.to_dict() for v in (self.variants or [])]
        return d


# ─── 口语化问法变体 ───
class KBQuestionVariant(Base):
    __tablename__ = "kb_question_variant"

    id = Column(Integer, primary_key=True, autoincrement=True)
    qa_id = Column(Integer, ForeignKey("kb_qa.id"), nullable=False, index=True)
    variant_text = Column(String(500), nullable=False)
    source = Column(String(32), nullable=False, default="manual")
    created_by = Column(String(64), nullable=False, default="")
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    qa_entry = relationship("KBQA", back_populates="variants")

    def to_dict(self):
        return {
            "id": self.id,
            "qa_id": self.qa_id,
            "variant_text": self.variant_text,
            "source": self.source,
            "created_by": self.created_by,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


# ─── 高风险 SOP ───
class KBSOP(Base):
    __tablename__ = "kb_sop"

    id = Column(Integer, primary_key=True, autoincrement=True)

    scenario = Column(String(255), nullable=False, index=True)
    scenario_code = Column(String(64), nullable=False, default="", index=True)
    risk_level = Column(String(16), nullable=False, default="high", index=True)

    keywords_json = Column(Text, nullable=False, default="[]")
    steps_json = Column(Text, nullable=False, default="[]")

    escalation_condition = Column(Text, nullable=False, default="")
    escalation_target = Column(String(128), nullable=False, default="")

    forbidden_actions_json = Column(Text, nullable=False, default="[]")
    response_template = Column(Text, nullable=False, default="")
    agent_action = Column(String(32), nullable=False, default="auto_reply")

    category_l1 = Column(String(64), nullable=False, default="", index=True)

    status = Column(String(16), nullable=False, default="draft", index=True)
    version = Column(Integer, nullable=False, default=1)

    owner = Column(String(64), nullable=False, default="")
    created_by = Column(String(64), nullable=False, default="")
    updated_by = Column(String(64), nullable=False, default="")
    reviewed_by = Column(String(64), nullable=False, default="")
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        Index("idx_sop_risk_status", "risk_level", "status"),
    )

    def get_keywords(self):
        return _json_get(self.keywords_json, [])

    def set_keywords(self, value):
        self.keywords_json = _json_set(value, True)

    def get_steps(self):
        return _json_get(self.steps_json, [])

    def set_steps(self, value):
        self.steps_json = _json_set(value, True)

    def get_forbidden_actions(self):
        return _json_get(self.forbidden_actions_json, [])

    def set_forbidden_actions(self, value):
        self.forbidden_actions_json = _json_set(value, True)

    def to_dict(self):
        return {
            "id": self.id,
            "scenario": self.scenario,
            "scenario_code": self.scenario_code,
            "risk_level": self.risk_level,
            "keywords": self.get_keywords(),
            "steps": self.get_steps(),
            "escalation_condition": self.escalation_condition,
            "escalation_target": self.escalation_target,
            "forbidden_actions": self.get_forbidden_actions(),
            "response_template": self.response_template,
            "agent_action": self.agent_action,
            "category_l1": self.category_l1,
            "status": self.status,
            "version": self.version,
            "owner": self.owner,
            "created_by": self.created_by,
            "updated_by": self.updated_by,
            "reviewed_by": self.reviewed_by,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


# ─── 真实客服案例 ───
class KBCase(Base):
    __tablename__ = "kb_case"

    id = Column(Integer, primary_key=True, autoincrement=True)

    case_code = Column(String(64), nullable=False, default="", index=True)
    scenario = Column(String(255), nullable=False, default="")

    customer_dialogue = Column(Text, nullable=False, default="")
    correct_reply = Column(Text, nullable=False, default="")
    wrong_reply = Column(Text, nullable=False, default="")

    reply_quality_score = Column(Integer, nullable=True)
    empathy_score = Column(Integer, nullable=True)
    accuracy_score = Column(Integer, nullable=True)
    wrong_reply_score = Column(Integer, nullable=True)

    wrong_reason = Column(Text, nullable=False, default="")
    supervisor_comment = Column(Text, nullable=False, default="")
    final_result = Column(String(255), nullable=False, default="")
    tags_json = Column(Text, nullable=False, default="[]")

    category_l1 = Column(String(64), nullable=False, default="")
    risk_level = Column(String(16), nullable=False, default="low")

    qa_id = Column(Integer, ForeignKey("kb_qa.id"), nullable=True)

    status = Column(String(16), nullable=False, default="draft", index=True)
    created_by = Column(String(64), nullable=False, default="")
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    def get_tags(self):
        return _json_get(self.tags_json, [])

    def set_tags(self, value):
        self.tags_json = _json_set(value, True)

    def to_dict(self):
        return {
            "id": self.id,
            "case_code": self.case_code,
            "scenario": self.scenario,
            "customer_dialogue": self.customer_dialogue,
            "correct_reply": self.correct_reply,
            "wrong_reply": self.wrong_reply,
            "reply_quality_score": self.reply_quality_score,
            "empathy_score": self.empathy_score,
            "accuracy_score": self.accuracy_score,
            "wrong_reply_score": self.wrong_reply_score,
            "wrong_reason": self.wrong_reason,
            "supervisor_comment": self.supervisor_comment,
            "final_result": self.final_result,
            "tags": self.get_tags(),
            "category_l1": self.category_l1,
            "risk_level": self.risk_level,
            "qa_id": self.qa_id,
            "status": self.status,
            "created_by": self.created_by,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


# ─── Agent 流程轨迹 ───
class KBAgentTrace(Base):
    __tablename__ = "kb_agent_trace"

    id = Column(Integer, primary_key=True, autoincrement=True)

    conversation_id = Column(String(64), nullable=False, index=True)
    message_id = Column(String(64), nullable=False, default="")
    customer_message = Column(Text, nullable=False, default="")

    detected_intent = Column(String(64), nullable=False, default="")
    confidence = Column(Float, nullable=False, default=0.0)
    slots_json = Column(Text, nullable=False, default="{}")

    tool_calls_json = Column(Text, nullable=False, default="[]")
    decision_nodes_json = Column(Text, nullable=False, default="[]")

    guard_passed = Column(Boolean, nullable=False, default=True)
    guard_warnings_json = Column(Text, nullable=False, default="[]")

    used_knowledge_ids_json = Column(Text, nullable=False, default="[]")

    response_strategy = Column(String(64), nullable=False, default="")
    final_reply_preview = Column(Text, nullable=False, default="")

    total_duration_ms = Column(Integer, nullable=False, default=0)
    risk_level = Column(String(16), nullable=False, default="low")

    created_at = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)

    __table_args__ = (
        Index("idx_trace_conv_time", "conversation_id", "created_at"),
        Index("idx_trace_intent", "detected_intent"),
    )

    def get_slots(self):
        return _json_get(self.slots_json, {})

    def set_slots(self, value):
        self.slots_json = _json_set(value, False)

    def get_tool_calls(self):
        return _json_get(self.tool_calls_json, [])

    def set_tool_calls(self, value):
        self.tool_calls_json = _json_set(value, True)

    def get_decision_nodes(self):
        return _json_get(self.decision_nodes_json, [])

    def set_decision_nodes(self, value):
        self.decision_nodes_json = _json_set(value, True)

    def get_guard_warnings(self):
        return _json_get(self.guard_warnings_json, [])

    def set_guard_warnings(self, value):
        self.guard_warnings_json = _json_set(value, True)

    def get_used_knowledge_ids(self):
        return _json_get(self.used_knowledge_ids_json, [])

    def set_used_knowledge_ids(self, value):
        self.used_knowledge_ids_json = _json_set(value, True)

    def to_dict(self):
        return {
            "id": self.id,
            "conversation_id": self.conversation_id,
            "message_id": self.message_id,
            "customer_message": self.customer_message,
            "detected_intent": self.detected_intent,
            "confidence": self.confidence,
            "slots": self.get_slots(),
            "tool_calls": self.get_tool_calls(),
            "decision_nodes": self.get_decision_nodes(),
            "guard_passed": self.guard_passed,
            "guard_warnings": self.get_guard_warnings(),
            "used_knowledge_ids": self.get_used_knowledge_ids(),
            "response_strategy": self.response_strategy,
            "final_reply_preview": self.final_reply_preview,
            "total_duration_ms": self.total_duration_ms,
            "risk_level": self.risk_level,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


# ─── 反馈学习数据 ───
class KBFeedback(Base):
    __tablename__ = "kb_feedback"

    id = Column(Integer, primary_key=True, autoincrement=True)

    conversation_id = Column(String(64), nullable=False, index=True)
    ai_suggestion = Column(Text, nullable=False, default="")
    csr_action = Column(String(32), nullable=False, default="")
    csr_final_reply = Column(Text, nullable=False, default="")

    supervisor_score = Column(Integer, nullable=True)
    customer_result = Column(String(64), nullable=False, default="")
    reward_score = Column(Float, nullable=True)

    used_knowledge_ids_json = Column(Text, nullable=False, default="[]")
    qa_id = Column(Integer, ForeignKey("kb_qa.id"), nullable=True)

    customer_message = Column(Text, nullable=False, default="")
    risk_level = Column(String(16), nullable=False, default="low")
    source = Column(String(32), nullable=False, default="copilot")

    created_by = Column(String(64), nullable=False, default="")
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)

    __table_args__ = (
        Index("idx_feedback_action_time", "csr_action", "created_at"),
    )

    def get_used_knowledge_ids(self):
        return _json_get(self.used_knowledge_ids_json, [])

    def set_used_knowledge_ids(self, value):
        self.used_knowledge_ids_json = _json_set(value, True)

    def to_dict(self):
        return {
            "id": self.id,
            "conversation_id": self.conversation_id,
            "ai_suggestion": self.ai_suggestion,
            "csr_action": self.csr_action,
            "csr_final_reply": self.csr_final_reply,
            "supervisor_score": self.supervisor_score,
            "customer_result": self.customer_result,
            "reward_score": self.reward_score,
            "used_knowledge_ids": self.get_used_knowledge_ids(),
            "qa_id": self.qa_id,
            "customer_message": self.customer_message,
            "risk_level": self.risk_level,
            "source": self.source,
            "created_by": self.created_by,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


# ─── 审核任务 ───
class KBReviewTask(Base):
    __tablename__ = "kb_review_task"

    id = Column(Integer, primary_key=True, autoincrement=True)

    target_type = Column(String(32), nullable=False, index=True)
    target_id = Column(Integer, nullable=False, index=True)

    before_snapshot_json = Column(Text, nullable=False, default="{}")
    after_snapshot_json = Column(Text, nullable=False, default="{}")

    change_type = Column(String(32), nullable=False, default="update")
    change_summary = Column(String(500), nullable=False, default="")
    changed_fields_json = Column(Text, nullable=False, default="[]")

    status = Column(String(16), nullable=False, default="pending", index=True)
    priority = Column(String(16), nullable=False, default="normal")
    risk_level = Column(String(16), nullable=False, default="low")

    requested_by = Column(String(64), nullable=False, default="")
    reviewer = Column(String(64), nullable=False, default="")
    reviewed_at = Column(DateTime, nullable=True)
    review_opinion = Column(Text, nullable=False, default="")

    created_at = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)

    __table_args__ = (
        Index("idx_review_target", "target_type", "target_id"),
        Index("idx_review_status_pri", "status", "priority"),
    )

    def get_before_snapshot(self):
        return _json_get(self.before_snapshot_json, {})

    def set_before_snapshot(self, value):
        self.before_snapshot_json = _json_set(value, False)

    def get_after_snapshot(self):
        return _json_get(self.after_snapshot_json, {})

    def set_after_snapshot(self, value):
        self.after_snapshot_json = _json_set(value, False)

    def get_changed_fields(self):
        return _json_get(self.changed_fields_json, [])

    def set_changed_fields(self, value):
        self.changed_fields_json = _json_set(value, True)

    def to_dict(self):
        return {
            "id": self.id,
            "target_type": self.target_type,
            "target_id": self.target_id,
            "before_snapshot": self.get_before_snapshot(),
            "after_snapshot": self.get_after_snapshot(),
            "change_type": self.change_type,
            "change_summary": self.change_summary,
            "changed_fields": self.get_changed_fields(),
            "status": self.status,
            "priority": self.priority,
            "risk_level": self.risk_level,
            "requested_by": self.requested_by,
            "reviewer": self.reviewer,
            "reviewed_at": self.reviewed_at.isoformat() if self.reviewed_at else None,
            "review_opinion": self.review_opinion,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


# ─── 变更日志 ───
class KBChangeLog(Base):
    __tablename__ = "kb_change_log"

    id = Column(Integer, primary_key=True, autoincrement=True)

    target_type = Column(String(32), nullable=False, index=True)
    target_id = Column(Integer, nullable=False, index=True)
    target_title = Column(String(255), nullable=False, default="")

    action = Column(String(32), nullable=False)
    before_status = Column(String(16), nullable=False, default="")
    after_status = Column(String(16), nullable=False, default="")

    snapshot_json = Column(Text, nullable=False, default="{}")
    changed_fields_json = Column(Text, nullable=False, default="[]")
    change_reason = Column(String(500), nullable=False, default="")

    performed_by = Column(String(64), nullable=False, default="")
    review_task_id = Column(Integer, ForeignKey("kb_review_task.id"), nullable=True)

    created_at = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)

    __table_args__ = (
        Index("idx_changelog_target_time", "target_type", "target_id", "created_at"),
    )

    def get_snapshot(self):
        return _json_get(self.snapshot_json, {})

    def set_snapshot(self, value):
        self.snapshot_json = _json_set(value, False)

    def get_changed_fields(self):
        return _json_get(self.changed_fields_json, [])

    def set_changed_fields(self, value):
        self.changed_fields_json = _json_set(value, True)

    def to_dict(self):
        return {
            "id": self.id,
            "target_type": self.target_type,
            "target_id": self.target_id,
            "target_title": self.target_title,
            "action": self.action,
            "before_status": self.before_status,
            "after_status": self.after_status,
            "snapshot": self.get_snapshot(),
            "changed_fields": self.get_changed_fields(),
            "change_reason": self.change_reason,
            "performed_by": self.performed_by,
            "review_task_id": self.review_task_id,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


# ─── 图片/视频素材库 ───
class KBMediaAsset(Base):
    """商品图片/视频素材（安装视频、安装图、SKU图、配件图等）。

    设计要点：
    - 只有 status='approved' 且 usable_for_agent=1 的素材才允许 Agent 推荐。
    - content_hash 基于「稳定 URL 路径 + i_id + sku_code + asset_type」生成，
      去掉签名 query 参数（Expires/Signature），避免重签导致重复入库。
    - source_raw_json 保留导入时的原始 JSON 供溯源。
    """
    __tablename__ = "kb_media_asset"

    id = Column(Integer, primary_key=True, autoincrement=True)
    product_id = Column(Integer, nullable=True)
    i_id = Column(String(64), nullable=False, default="")
    sku_code = Column(String(64), nullable=False, default="")
    product_name = Column(String(255), nullable=False, default="")

    asset_type = Column(String(32), nullable=False, default="other")
    asset_title = Column(String(255), nullable=False, default="")
    asset_url = Column(Text, nullable=False, default="")

    source = Column(String(32), nullable=False, default="dingtalk")
    source_doc_id = Column(String(128), nullable=False, default="")
    source_raw_json = Column(Text, nullable=False, default="{}")

    match_confidence = Column(Float, nullable=False, default=0.5)
    match_reason = Column(String(255), nullable=False, default="")

    status = Column(String(16), nullable=False, default="pending_review")
    audit_status = Column(String(16), nullable=False, default="unreviewed")
    usable_for_agent = Column(Integer, nullable=False, default=0)

    scene_tags_json = Column(Text, nullable=False, default="[]")

    created_by = Column(String(64), nullable=False, default="")
    updated_by = Column(String(64), nullable=False, default="")
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    last_seen_at = Column(DateTime, nullable=True)
    content_hash = Column(String(64), nullable=False, default="")

    # 链接保鲜 / 每日刷新
    url_expires_at = Column(DateTime, nullable=True)
    refresh_status = Column(String(16), nullable=False, default="ok")  # ok / needs_refresh / error
    source_updated_at = Column(DateTime, nullable=True)
    reviewed_by = Column(String(64), nullable=False, default="")

    __table_args__ = (
        Index("idx_media_i_id", "i_id"),
        Index("idx_media_sku_code", "sku_code"),
        Index("idx_media_asset_type", "asset_type"),
        Index("idx_media_status", "status"),
        Index("idx_media_hash", "content_hash"),
        Index("idx_media_usable", "usable_for_agent"),
        Index("idx_media_refresh_status", "refresh_status"),
        Index("idx_media_url_expires_at", "url_expires_at"),
    )

    def get_scene_tags(self):
        return _json_get(self.scene_tags_json, [])

    def set_scene_tags(self, value):
        self.scene_tags_json = _json_set(value, True)

    def get_source_raw(self):
        return _json_get(self.source_raw_json, {})

    def set_source_raw(self, value):
        self.source_raw_json = _json_set(value, False)

    def to_dict(self):
        return {
            "id": self.id,
            "asset_id": self.id,
            "product_id": self.product_id,
            "i_id": self.i_id,
            "sku_code": self.sku_code,
            "product_name": self.product_name,
            "asset_type": self.asset_type,
            "asset_title": self.asset_title,
            "asset_url": self.asset_url,
            "source": self.source,
            "source_doc_id": self.source_doc_id,
            "source_raw": self.get_source_raw(),
            "match_confidence": self.match_confidence,
            "match_reason": self.match_reason,
            "status": self.status,
            "audit_status": self.audit_status,
            "usable_for_agent": bool(self.usable_for_agent),
            "scene_tags": self.get_scene_tags(),
            "created_by": self.created_by,
            "updated_by": self.updated_by,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "last_seen_at": self.last_seen_at.isoformat() if self.last_seen_at else None,
            "source_updated_at": self.source_updated_at.isoformat() if self.source_updated_at else None,
            "url_expires_at": self.url_expires_at.isoformat() if self.url_expires_at else None,
            "refresh_status": self.refresh_status,
            "reviewed_by": self.reviewed_by,
            "content_hash": self.content_hash,
        }


# ─── 客服训练样本收集（用于训练客服系统） ───
class KBTrainingSample(Base):
    __tablename__ = "kb_training_sample"

    id = Column(Integer, primary_key=True, autoincrement=True)

    # 基础信息
    collected_at = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)
    csr_name = Column(String(64), nullable=False, default="")
    shop_platform = Column(String(64), nullable=False, default="")

    # 对话内容（支持富文本 HTML，图文混排）
    customer_quote = Column(Text, nullable=False, default="")
    full_context = Column(Text, nullable=False, default="")

    # 商品/订单信息
    product_title = Column(String(255), nullable=False, default="")
    sku = Column(String(64), nullable=False, default="")
    order_no = Column(String(64), nullable=False, default="")

    # 问题分类与难点
    question_type = Column(String(64), nullable=False, default="")
    difficulty_reason = Column(String(64), nullable=False, default="")

    # 回复内容（支持富文本 HTML）
    csr_actual_reply = Column(Text, nullable=False, default="")
    correct_answer = Column(Text, nullable=False, default="")

    # 知识库补充
    need_knowledge_base = Column(Boolean, nullable=False, default=False)
    target_knowledge_base = Column(String(64), nullable=False, default="")

    # 多媒体
    need_media = Column(Boolean, nullable=False, default=False)
    media_links_json = Column(Text, nullable=False, default="[]")

    # 风险与自动回复
    risk_level = Column(String(16), nullable=False, default="low")
    auto_reply_type = Column(String(32), nullable=False, default="需人工确认")

    # 审核与负责人
    review_status = Column(String(16), nullable=False, default="待处理", index=True)
    owner = Column(String(64), nullable=False, default="")

    # 备注
    notes = Column(Text, nullable=False, default="")

    created_by = Column(String(64), nullable=False, default="")
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    attachments = relationship(
        "KBTrainingSampleAttachment",
        back_populates="sample",
        cascade="all, delete-orphan",
        order_by="KBTrainingSampleAttachment.created_at",
    )

    def get_media_links(self):
        return _json_get(self.media_links_json, [])

    def set_media_links(self, value):
        self.media_links_json = _json_set(value, True)

    def to_dict(self):
        return {
            "id": self.id,
            "collected_at": self.collected_at.isoformat() if self.collected_at else None,
            "csr_name": self.csr_name,
            "shop_platform": self.shop_platform,
            "customer_quote": self.customer_quote,
            "full_context": self.full_context,
            "product_title": self.product_title,
            "sku": self.sku,
            "order_no": self.order_no,
            "question_type": self.question_type,
            "difficulty_reason": self.difficulty_reason,
            "csr_actual_reply": self.csr_actual_reply,
            "correct_answer": self.correct_answer,
            "need_knowledge_base": bool(self.need_knowledge_base),
            "target_knowledge_base": self.target_knowledge_base,
            "need_media": bool(self.need_media),
            "media_links": self.get_media_links(),
            "risk_level": self.risk_level,
            "auto_reply_type": self.auto_reply_type,
            "review_status": self.review_status,
            "owner": self.owner,
            "notes": self.notes,
            "created_by": self.created_by,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "attachments": [att.to_dict() for att in self.attachments],
        }


class KBTrainingSampleAttachment(Base):
    __tablename__ = "kb_training_sample_attachment"

    id = Column(Integer, primary_key=True, autoincrement=True)
    sample_id = Column(Integer, ForeignKey("kb_training_sample.id"), nullable=False, index=True)

    # 该附件用于哪个富文本字段（customer_quote / full_context / csr_actual_reply / correct_answer）
    field_name = Column(String(64), nullable=False, default="")
    original_filename = Column(String(255), nullable=False, default="")
    stored_filename = Column(String(255), nullable=False, default="")
    file_path = Column(Text, nullable=False, default="")
    file_size = Column(Integer, nullable=False, default=0)
    mime_type = Column(String(64), nullable=False, default="")

    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    sample = relationship("KBTrainingSample", back_populates="attachments")

    def to_dict(self):
        return {
            "id": self.id,
            "sample_id": self.sample_id,
            "field_name": self.field_name,
            "original_filename": self.original_filename,
            "stored_filename": self.stored_filename,
            "file_size": self.file_size,
            "mime_type": self.mime_type,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
