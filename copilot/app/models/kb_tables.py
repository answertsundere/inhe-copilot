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
