"""Evaluation replay tables for real conversation QA."""

import json
from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, Index, Integer, String, Text

from app.db import Base


def _json_load(raw, default):
    try:
        if not raw:
            return default
        value = json.loads(raw)
        return value if value is not None else default
    except Exception:
        return default


def _json_dump(value, default):
    if value is None:
        value = default
    return json.dumps(value, ensure_ascii=False)


def _mask_identifier(value):
    text = str(value or "")
    if len(text) <= 4:
        return text
    return f"{text[:2]}***{text[-2:]}"


class EvalCase(Base):
    __tablename__ = "eval_cases"

    id = Column(Integer, primary_key=True, autoincrement=True)
    case_uid = Column(String(64), nullable=False, unique=True, index=True)
    source_type = Column(String(32), nullable=False, default="manual", index=True)
    source_ref = Column(String(512), nullable=False, default="")
    title = Column(String(255), nullable=False, default="")
    message = Column(Text, nullable=False, default="")
    expected_json = Column(Text, nullable=False, default="{}")
    metadata_json = Column(Text, nullable=False, default="{}")
    status = Column(String(32), nullable=False, default="active", index=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    def get_expected(self):
        return _json_load(self.expected_json, {})

    def set_expected(self, value):
        self.expected_json = _json_dump(value, {})

    def get_metadata(self):
        return _json_load(self.metadata_json, {})

    def set_metadata(self, value):
        self.metadata_json = _json_dump(value, {})

    def to_dict(self):
        return {
            "id": self.id,
            "case_uid": self.case_uid,
            "source_type": self.source_type,
            "source_ref": self.source_ref,
            "title": self.title,
            "message": self.message,
            "expected": self.get_expected(),
            "metadata": self.get_metadata(),
            "status": self.status,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class EvalConversationTurn(Base):
    __tablename__ = "eval_conversation_turns"

    id = Column(Integer, primary_key=True, autoincrement=True)
    case_uid = Column(String(64), nullable=False, index=True)
    conversation_uid = Column(String(64), nullable=False, index=True)
    turn_uid = Column(String(64), nullable=False, unique=True, index=True)
    turn_index = Column(Integer, nullable=False, default=0)
    speaker = Column(String(32), nullable=False, default="")
    message_type = Column(String(32), nullable=False, default="text")
    sanitized_text = Column(Text, nullable=False, default="")
    product_hint = Column(String(255), nullable=False, default="")
    order_hint_hash = Column(String(64), nullable=False, default="")
    timestamp = Column(String(64), nullable=False, default="")
    reference_human_reply = Column(Text, nullable=False, default="")
    metadata_json = Column(Text, nullable=False, default="{}")
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    __table_args__ = (
        Index("idx_eval_turn_case_order", "case_uid", "turn_index"),
    )

    def get_metadata(self):
        return _json_load(self.metadata_json, {})

    def set_metadata(self, value):
        self.metadata_json = _json_dump(value, {})

    def to_dict(self):
        return {
            "id": self.id,
            "case_uid": self.case_uid,
            "conversation_uid": self.conversation_uid,
            "turn_uid": self.turn_uid,
            "turn_index": self.turn_index,
            "speaker": self.speaker,
            "message_type": self.message_type,
            "sanitized_text": self.sanitized_text,
            "product_hint": self.product_hint,
            "order_hint_hash": self.order_hint_hash,
            "timestamp": self.timestamp,
            "reference_human_reply": self.reference_human_reply,
            "metadata": self.get_metadata(),
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class EvalRun(Base):
    __tablename__ = "eval_runs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    run_uid = Column(String(64), nullable=False, unique=True, index=True)
    source_type = Column(String(32), nullable=False, default="manual", index=True)
    status = Column(String(32), nullable=False, default="created", index=True)
    total_cases = Column(Integer, nullable=False, default=0)
    total_turns = Column(Integer, nullable=False, default=0)
    passed_turns = Column(Integer, nullable=False, default=0)
    failed_turns = Column(Integer, nullable=False, default=0)
    requires_review_turns = Column(Integer, nullable=False, default=0)
    metadata_json = Column(Text, nullable=False, default="{}")
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    def get_metadata(self):
        return _json_load(self.metadata_json, {})

    def set_metadata(self, value):
        self.metadata_json = _json_dump(value, {})

    def to_dict(self):
        return {
            "id": self.id,
            "run_uid": self.run_uid,
            "source_type": self.source_type,
            "status": self.status,
            "total_cases": self.total_cases,
            "total_turns": self.total_turns,
            "passed_turns": self.passed_turns,
            "failed_turns": self.failed_turns,
            "requires_review_turns": self.requires_review_turns,
            "metadata": self.get_metadata(),
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class EvalTrace(Base):
    __tablename__ = "eval_traces"

    id = Column(Integer, primary_key=True, autoincrement=True)
    run_uid = Column(String(64), nullable=False, index=True)
    case_uid = Column(String(64), nullable=False, index=True)
    turn_uid = Column(String(64), nullable=False, index=True)
    turn_index = Column(Integer, nullable=False, default=0)
    buyer_message = Column(Text, nullable=False, default="")
    reference_human_reply = Column(Text, nullable=False, default="")
    agent_reply = Column(Text, nullable=False, default="")
    query_fact_type = Column(String(64), nullable=False, default="")
    required_fact_types_json = Column(Text, nullable=False, default="[]")
    selected_evidence_json = Column(Text, nullable=False, default="[]")
    rejected_evidence_json = Column(Text, nullable=False, default="[]")
    turn_understanding_json = Column(Text, nullable=False, default="{}")
    answer_trace_json = Column(Text, nullable=False, default="{}")
    final_audit_json = Column(Text, nullable=False, default="{}")
    semantic_compiler_json = Column(Text, nullable=False, default="{}")
    requires_human_review = Column(Boolean, nullable=False, default=False)
    latency_ms = Column(Integer, nullable=False, default=0)
    product_identity_json = Column(Text, nullable=False, default="{}")
    order_identity_hash = Column(String(64), nullable=False, default="")
    passed = Column(Boolean, nullable=False, default=True)
    failure_labels_json = Column(Text, nullable=False, default="[]")
    raw_response_json = Column(Text, nullable=False, default="{}")
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    __table_args__ = (
        Index("idx_eval_trace_run_turn", "run_uid", "turn_index"),
    )

    def get_required_fact_types(self):
        return _json_load(self.required_fact_types_json, [])

    def set_required_fact_types(self, value):
        self.required_fact_types_json = _json_dump(value, [])

    def get_selected_evidence(self):
        return _json_load(self.selected_evidence_json, [])

    def set_selected_evidence(self, value):
        self.selected_evidence_json = _json_dump(value, [])

    def get_rejected_evidence(self):
        return _json_load(self.rejected_evidence_json, [])

    def set_rejected_evidence(self, value):
        self.rejected_evidence_json = _json_dump(value, [])

    def get_turn_understanding(self):
        return _json_load(self.turn_understanding_json, {})

    def set_turn_understanding(self, value):
        self.turn_understanding_json = _json_dump(value, {})

    def get_answer_trace(self):
        return _json_load(self.answer_trace_json, {})

    def set_answer_trace(self, value):
        self.answer_trace_json = _json_dump(value, {})

    def get_final_audit(self):
        return _json_load(self.final_audit_json, {})

    def set_final_audit(self, value):
        self.final_audit_json = _json_dump(value, {})

    def get_semantic_compiler(self):
        return _json_load(self.semantic_compiler_json, {})

    def set_semantic_compiler(self, value):
        self.semantic_compiler_json = _json_dump(value, {})

    def get_product_identity(self):
        return _json_load(self.product_identity_json, {})

    def set_product_identity(self, value):
        self.product_identity_json = _json_dump(value, {})

    def get_failure_labels(self):
        return _json_load(self.failure_labels_json, [])

    def set_failure_labels(self, value):
        self.failure_labels_json = _json_dump(value, [])

    def get_raw_response(self):
        return _json_load(self.raw_response_json, {})

    def set_raw_response(self, value):
        self.raw_response_json = _json_dump(value, {})

    def get_quality_bucket(self):
        raw = self.get_raw_response()
        if isinstance(raw, dict):
            value = raw.get("quality_bucket")
            if isinstance(value, dict):
                return value
        return {}

    def to_dict(self):
        quality_bucket = self.get_quality_bucket()
        return {
            "id": self.id,
            "run_uid": self.run_uid,
            "case_uid": self.case_uid,
            "turn_uid": self.turn_uid,
            "turn_index": self.turn_index,
            "buyer_message": self.buyer_message,
            "reference_human_reply": self.reference_human_reply,
            "agent_reply": self.agent_reply,
            "query_fact_type": self.query_fact_type,
            "required_fact_types": self.get_required_fact_types(),
            "selected_evidence": self.get_selected_evidence(),
            "rejected_evidence": self.get_rejected_evidence(),
            "turn_understanding": self.get_turn_understanding(),
            "answer_trace": self.get_answer_trace(),
            "final_audit": self.get_final_audit(),
            "semantic_compiler": self.get_semantic_compiler(),
            "requires_human_review": self.requires_human_review,
            "latency_ms": self.latency_ms,
            "product_identity": self.get_product_identity(),
            "order_identity_hash": self.order_identity_hash,
            "passed": self.passed,
            "failure_labels": self.get_failure_labels(),
            **quality_bucket,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class EvalFailure(Base):
    __tablename__ = "eval_failures"

    id = Column(Integer, primary_key=True, autoincrement=True)
    run_uid = Column(String(64), nullable=False, index=True)
    case_uid = Column(String(64), nullable=False, index=True)
    turn_uid = Column(String(64), nullable=False, index=True)
    failure_type = Column(String(64), nullable=False, index=True)
    severity = Column(String(16), nullable=False, default="medium")
    suggested_fix_area = Column(String(64), nullable=False, default="")
    suggested_owner = Column(String(64), nullable=False, default="")
    explanation = Column(Text, nullable=False, default="")
    message = Column(Text, nullable=False, default="")
    metadata_json = Column(Text, nullable=False, default="{}")
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    def get_metadata(self):
        return _json_load(self.metadata_json, {})

    def set_metadata(self, value):
        self.metadata_json = _json_dump(value, {})

    def to_dict(self):
        return {
            "id": self.id,
            "run_uid": self.run_uid,
            "case_uid": self.case_uid,
            "turn_uid": self.turn_uid,
            "failure_type": self.failure_type,
            "severity": self.severity,
            "suggested_fix_area": self.suggested_fix_area,
            "suggested_owner": self.suggested_owner,
            "explanation": self.explanation,
            "message": self.message,
            "metadata": self.get_metadata(),
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class EvalReview(Base):
    __tablename__ = "eval_reviews"

    id = Column(Integer, primary_key=True, autoincrement=True)
    run_uid = Column(String(64), nullable=False, index=True)
    case_uid = Column(String(64), nullable=False, index=True)
    turn_uid = Column(String(64), nullable=False, index=True)
    decision = Column(String(32), nullable=False, default="")
    reason = Column(Text, nullable=False, default="")
    suggested_fix_area = Column(String(64), nullable=False, default="")
    reviewer = Column(String(64), nullable=False, default="")
    metadata_json = Column(Text, nullable=False, default="{}")
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    def get_metadata(self):
        return _json_load(self.metadata_json, {})

    def set_metadata(self, value):
        self.metadata_json = _json_dump(value, {})

    def to_dict(self):
        return {
            "id": self.id,
            "run_uid": self.run_uid,
            "case_uid": self.case_uid,
            "turn_uid": self.turn_uid,
            "decision": self.decision,
            "reason": self.reason,
            "suggested_fix_area": self.suggested_fix_area,
            "reviewer": self.reviewer,
            "metadata": self.get_metadata(),
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class EvalRepairTask(Base):
    __tablename__ = "eval_repair_tasks"

    id = Column(Integer, primary_key=True, autoincrement=True)
    task_uid = Column(String(64), nullable=False, default="", index=True)
    run_uid = Column(String(64), nullable=False, index=True)
    case_uid = Column(String(64), nullable=False, index=True)
    turn_uid = Column(String(64), nullable=False, index=True)
    task_type = Column(String(64), nullable=False, default="manual_review", index=True)
    failure_type = Column(String(64), nullable=False, default="", index=True)
    suggested_fix_area = Column(String(64), nullable=False, default="", index=True)
    suggested_owner = Column(String(64), nullable=False, default="", index=True)
    title = Column(String(255), nullable=False, default="")
    description = Column(Text, nullable=False, default="")
    sample_count = Column(Integer, nullable=False, default=0)
    related_case_uids_json = Column(Text, nullable=False, default="[]")
    related_turn_uids_json = Column(Text, nullable=False, default="[]")
    status = Column(String(32), nullable=False, default="open", index=True)
    priority = Column(String(16), nullable=False, default="medium", index=True)
    created_by = Column(String(64), nullable=False, default="")
    assigned_to = Column(String(64), nullable=False, default="")
    resolution_note = Column(Text, nullable=False, default="")
    last_verified_at = Column(DateTime, nullable=True)
    verification_status = Column(String(32), nullable=False, default="not_verified", index=True)
    verification_run_uid = Column(String(64), nullable=False, default="", index=True)
    verification_summary_json = Column(Text, nullable=False, default="{}")
    verified_by = Column(String(64), nullable=False, default="")
    note = Column(Text, nullable=False, default="")
    metadata_json = Column(Text, nullable=False, default="{}")
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    def get_related_case_uids(self):
        return _json_load(self.related_case_uids_json, [])

    def set_related_case_uids(self, value):
        self.related_case_uids_json = _json_dump(value, [])

    def get_related_turn_uids(self):
        return _json_load(self.related_turn_uids_json, [])

    def set_related_turn_uids(self, value):
        self.related_turn_uids_json = _json_dump(value, [])

    def get_verification_summary(self):
        return _json_load(self.verification_summary_json, {})

    def set_verification_summary(self, value):
        self.verification_summary_json = _json_dump(value, {})

    def get_metadata(self):
        return _json_load(self.metadata_json, {})

    def set_metadata(self, value):
        self.metadata_json = _json_dump(value, {})

    def to_dict(self):
        return {
            "id": self.id,
            "task_uid": self.task_uid,
            "run_uid": self.run_uid,
            "case_uid": self.case_uid,
            "turn_uid": self.turn_uid,
            "task_type": self.task_type,
            "failure_type": self.failure_type,
            "suggested_fix_area": self.suggested_fix_area,
            "suggested_owner": self.suggested_owner,
            "title": self.title,
            "description": self.description,
            "sample_count": self.sample_count,
            "related_case_uids": self.get_related_case_uids(),
            "related_turn_uids": self.get_related_turn_uids(),
            "status": self.status,
            "priority": self.priority,
            "created_by": self.created_by,
            "assigned_to": self.assigned_to,
            "resolution_note": self.resolution_note,
            "last_verified_at": self.last_verified_at.isoformat() if self.last_verified_at else None,
            "verification_status": self.verification_status,
            "verification_run_uid": self.verification_run_uid,
            "verification_summary": self.get_verification_summary(),
            "verified_by": self.verified_by,
            "note": self.note,
            "metadata": self.get_metadata(),
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class KnowledgeGapTask(Base):
    __tablename__ = "knowledge_gap_tasks"

    id = Column(Integer, primary_key=True, autoincrement=True)
    task_uid = Column(String(64), nullable=False, unique=True, index=True)
    gap_type = Column(String(64), nullable=False, default="", index=True)
    product_title = Column(String(255), nullable=False, default="")
    item_id = Column(String(64), nullable=False, default="", index=True)
    sku_code = Column(String(64), nullable=False, default="", index=True)
    query_fact_type = Column(String(64), nullable=False, default="", index=True)
    failure_type = Column(String(64), nullable=False, default="", index=True)
    suggested_fix_area = Column(String(64), nullable=False, default="", index=True)
    suggested_owner = Column(String(64), nullable=False, default="", index=True)
    missing_evidence_type = Column(String(64), nullable=False, default="")
    media_needed_type = Column(String(64), nullable=False, default="")
    risk_level = Column(String(16), nullable=False, default="medium", index=True)
    sample_count = Column(Integer, nullable=False, default=0)
    priority = Column(String(16), nullable=False, default="medium", index=True)
    status = Column(String(32), nullable=False, default="open", index=True)
    summary = Column(Text, nullable=False, default="")
    related_case_uids_json = Column(Text, nullable=False, default="[]")
    related_turn_uids_json = Column(Text, nullable=False, default="[]")
    latest_buyer_questions_json = Column(Text, nullable=False, default="[]")
    latest_agent_replies_json = Column(Text, nullable=False, default="[]")
    latest_original_cs_replies_json = Column(Text, nullable=False, default="[]")
    metadata_json = Column(Text, nullable=False, default="{}")
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    def get_related_case_uids(self):
        return _json_load(self.related_case_uids_json, [])

    def set_related_case_uids(self, value):
        self.related_case_uids_json = _json_dump(value, [])

    def get_related_turn_uids(self):
        return _json_load(self.related_turn_uids_json, [])

    def set_related_turn_uids(self, value):
        self.related_turn_uids_json = _json_dump(value, [])

    def get_latest_buyer_questions(self):
        return _json_load(self.latest_buyer_questions_json, [])

    def set_latest_buyer_questions(self, value):
        self.latest_buyer_questions_json = _json_dump(value, [])

    def get_latest_agent_replies(self):
        return _json_load(self.latest_agent_replies_json, [])

    def set_latest_agent_replies(self, value):
        self.latest_agent_replies_json = _json_dump(value, [])

    def get_latest_original_cs_replies(self):
        return _json_load(self.latest_original_cs_replies_json, [])

    def set_latest_original_cs_replies(self, value):
        self.latest_original_cs_replies_json = _json_dump(value, [])

    def get_metadata(self):
        return _json_load(self.metadata_json, {})

    def set_metadata(self, value):
        self.metadata_json = _json_dump(value, {})

    def to_dict(self):
        metadata = self.get_metadata()
        return {
            "id": self.id,
            "task_uid": self.task_uid,
            "gap_type": self.gap_type,
            "gap_category": metadata.get("gap_category") or self.gap_type,
            "product_title": self.product_title,
            "product_title_preview": (self.product_title or "")[:80],
            "item_id": self.item_id,
            "item_id_masked": _mask_identifier(self.item_id),
            "sku_code": self.sku_code,
            "query_fact_type": self.query_fact_type,
            "failure_type": self.failure_type,
            "suggested_fix_area": self.suggested_fix_area,
            "suggested_owner": self.suggested_owner,
            "missing_evidence_type": self.missing_evidence_type,
            "required_evidence_type": metadata.get("required_evidence_type") or self.missing_evidence_type,
            "target_system": metadata.get("target_system") or "",
            "recommended_action": metadata.get("recommended_action") or "",
            "review_decision": metadata.get("review_decision") or "",
            "reviewer": metadata.get("reviewer") or "",
            "review_note": metadata.get("review_note") or "",
            "assigned_to": metadata.get("assigned_to") or "",
            "assigned_team": metadata.get("assigned_team") or "",
            "due_date": metadata.get("due_date") or "",
            "reviewed_at": metadata.get("reviewed_at") or "",
            "triage_reason": metadata.get("triage_reason") or "",
            "next_action": metadata.get("next_action") or "",
            "status_history": metadata.get("status_history") if isinstance(metadata.get("status_history"), list) else [],
            "verification_status": metadata.get("verification_status") or "not_verified",
            "verification_run_uid": metadata.get("verification_run_uid") or "",
            "last_verified_at": metadata.get("last_verified_at") or "",
            "verified_by": metadata.get("verified_by") or "",
            "verification_summary": metadata.get("verification_summary") or {},
            "verification_history": metadata.get("verification_history") if isinstance(metadata.get("verification_history"), list) else [],
            "missing_fields": metadata.get("missing_fields") or [],
            "current_context_summary": metadata.get("current_context_summary") or {},
            "media_needed_type": self.media_needed_type,
            "risk_level": self.risk_level,
            "sample_count": self.sample_count,
            "priority": self.priority,
            "status": self.status,
            "summary": self.summary,
            "related_case_uids": self.get_related_case_uids(),
            "related_turn_uids": self.get_related_turn_uids(),
            "latest_buyer_questions": self.get_latest_buyer_questions(),
            "latest_agent_replies": self.get_latest_agent_replies(),
            "latest_original_cs_replies": self.get_latest_original_cs_replies(),
            "metadata": metadata,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class KnowledgeGapTaskSample(Base):
    __tablename__ = "knowledge_gap_task_samples"

    id = Column(Integer, primary_key=True, autoincrement=True)
    task_uid = Column(String(64), nullable=False, index=True)
    run_uid = Column(String(64), nullable=False, index=True)
    case_uid = Column(String(64), nullable=False, index=True)
    turn_uid = Column(String(64), nullable=False, index=True)
    buyer_message = Column(Text, nullable=False, default="")
    agent_reply = Column(Text, nullable=False, default="")
    reference_human_reply = Column(Text, nullable=False, default="")
    failure_type = Column(String(64), nullable=False, default="")
    query_fact_type = Column(String(64), nullable=False, default="")
    trace_summary_json = Column(Text, nullable=False, default="{}")
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    __table_args__ = (
        Index("idx_knowledge_gap_sample_task_turn", "task_uid", "turn_uid"),
    )

    def get_trace_summary(self):
        return _json_load(self.trace_summary_json, {})

    def set_trace_summary(self, value):
        self.trace_summary_json = _json_dump(value, {})

    def to_dict(self):
        return {
            "id": self.id,
            "task_uid": self.task_uid,
            "run_uid": self.run_uid,
            "case_uid": self.case_uid,
            "turn_uid": self.turn_uid,
            "buyer_message": self.buyer_message,
            "agent_reply": self.agent_reply,
            "reference_human_reply": self.reference_human_reply,
            "failure_type": self.failure_type,
            "query_fact_type": self.query_fact_type,
            "trace_summary": self.get_trace_summary(),
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class KnowledgeGapDraft(Base):
    __tablename__ = "knowledge_gap_drafts"

    id = Column(Integer, primary_key=True, autoincrement=True)
    draft_uid = Column(String(64), nullable=False, unique=True, index=True)
    task_uid = Column(String(64), nullable=False, index=True)
    draft_type = Column(String(64), nullable=False, default="", index=True)
    draft_content_json = Column(Text, nullable=False, default="{}")
    generated_by = Column(String(32), nullable=False, default="ai")
    review_status = Column(String(32), nullable=False, default="pending_review", index=True)
    reviewer = Column(String(64), nullable=False, default="")
    reviewed_at = Column(DateTime, nullable=True)
    rejection_reason = Column(Text, nullable=False, default="")
    publish_target = Column(String(64), nullable=False, default="staging")
    published_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    def get_draft_content(self):
        return _json_load(self.draft_content_json, {})

    def set_draft_content(self, value):
        self.draft_content_json = _json_dump(value, {})

    def to_dict(self):
        return {
            "id": self.id,
            "draft_uid": self.draft_uid,
            "task_uid": self.task_uid,
            "draft_type": self.draft_type,
            "draft_content": self.get_draft_content(),
            "generated_by": self.generated_by,
            "review_status": self.review_status,
            "reviewer": self.reviewer,
            "reviewed_at": self.reviewed_at.isoformat() if self.reviewed_at else None,
            "rejection_reason": self.rejection_reason,
            "publish_target": self.publish_target,
            "published_at": self.published_at.isoformat() if self.published_at else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class KnowledgeGapPublishQueue(Base):
    __tablename__ = "knowledge_gap_publish_queue"

    id = Column(Integer, primary_key=True, autoincrement=True)
    queue_uid = Column(String(64), nullable=False, unique=True, index=True)
    task_uid = Column(String(64), nullable=False, index=True)
    draft_uid = Column(String(64), nullable=False, index=True)
    source_run_uid = Column(String(64), nullable=False, default="", index=True)
    publish_target = Column(String(64), nullable=False, default="", index=True)
    payload_fingerprint = Column(String(64), nullable=False, default="", index=True)
    payload_json = Column(Text, nullable=False, default="{}")
    readiness_snapshot_json = Column(Text, nullable=False, default="{}")
    reviewer = Column(String(64), nullable=False, default="", index=True)
    review_note = Column(Text, nullable=False, default="")
    risk_level = Column(String(16), nullable=False, default="medium", index=True)
    status = Column(String(32), nullable=False, default="queued", index=True)
    export_status = Column(String(32), nullable=False, default="not_exported", index=True)
    exported_at = Column(DateTime, nullable=True)
    superseded_by = Column(String(64), nullable=False, default="", index=True)
    superseded_reason = Column(Text, nullable=False, default="")
    superseded_at = Column(DateTime, nullable=True)
    superseded_by_reviewer = Column(String(64), nullable=False, default="")
    publish_dry_run_status = Column(String(32), nullable=False, default="not_run", index=True)
    publish_dry_run_result_json = Column(Text, nullable=False, default="{}")
    publish_block_reasons_json = Column(Text, nullable=False, default="[]")
    ready_for_publish = Column(Boolean, nullable=False, default=False, index=True)
    last_dry_run_at = Column(DateTime, nullable=True)
    dry_run_by = Column(String(64), nullable=False, default="")
    pre_publish_retest_status = Column(String(32), nullable=False, default="not_run", index=True)
    pre_publish_retest_run_uid = Column(String(64), nullable=False, default="", index=True)
    pre_publish_retest_summary_json = Column(Text, nullable=False, default="{}")
    pre_publish_block_reasons_json = Column(Text, nullable=False, default="[]")
    approved_to_publish = Column(Boolean, nullable=False, default=False, index=True)
    approved_to_publish_at = Column(DateTime, nullable=True)
    approved_to_publish_by = Column(String(64), nullable=False, default="")
    locked_payload_fingerprint = Column(String(64), nullable=False, default="", index=True)
    approval_status = Column(String(32), nullable=False, default="not_ready", index=True)
    metadata_json = Column(Text, nullable=False, default="{}")
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    def get_payload(self):
        return _json_load(self.payload_json, {})

    def set_payload(self, value):
        self.payload_json = _json_dump(value, {})

    def get_readiness_snapshot(self):
        return _json_load(self.readiness_snapshot_json, {})

    def set_readiness_snapshot(self, value):
        self.readiness_snapshot_json = _json_dump(value, {})

    def get_metadata(self):
        return _json_load(self.metadata_json, {})

    def set_metadata(self, value):
        self.metadata_json = _json_dump(value, {})

    def get_publish_dry_run_result(self):
        return _json_load(self.publish_dry_run_result_json, {})

    def set_publish_dry_run_result(self, value):
        self.publish_dry_run_result_json = _json_dump(value, {})

    def get_publish_block_reasons(self):
        return _json_load(self.publish_block_reasons_json, [])

    def set_publish_block_reasons(self, value):
        self.publish_block_reasons_json = _json_dump(value, [])

    def get_pre_publish_retest_summary(self):
        return _json_load(self.pre_publish_retest_summary_json, {})

    def set_pre_publish_retest_summary(self, value):
        self.pre_publish_retest_summary_json = _json_dump(value, {})

    def get_pre_publish_block_reasons(self):
        return _json_load(self.pre_publish_block_reasons_json, [])

    def set_pre_publish_block_reasons(self, value):
        self.pre_publish_block_reasons_json = _json_dump(value, [])

    def to_dict(self):
        return {
            "id": self.id,
            "queue_uid": self.queue_uid,
            "task_uid": self.task_uid,
            "draft_uid": self.draft_uid,
            "source_run_uid": self.source_run_uid,
            "publish_target": self.publish_target,
            "payload_fingerprint": self.payload_fingerprint,
            "payload": self.get_payload(),
            "readiness_snapshot": self.get_readiness_snapshot(),
            "reviewer": self.reviewer,
            "review_note": self.review_note,
            "risk_level": self.risk_level,
            "status": self.status,
            "export_status": self.export_status,
            "exported_at": self.exported_at.isoformat() if self.exported_at else None,
            "superseded_by": self.superseded_by,
            "superseded_reason": self.superseded_reason,
            "superseded_at": self.superseded_at.isoformat() if self.superseded_at else None,
            "superseded_by_reviewer": self.superseded_by_reviewer,
            "publish_dry_run_status": self.publish_dry_run_status,
            "publish_dry_run_result": self.get_publish_dry_run_result(),
            "publish_block_reasons": self.get_publish_block_reasons(),
            "ready_for_publish": bool(self.ready_for_publish),
            "last_dry_run_at": self.last_dry_run_at.isoformat() if self.last_dry_run_at else None,
            "dry_run_by": self.dry_run_by,
            "pre_publish_retest_status": self.pre_publish_retest_status,
            "pre_publish_retest_run_uid": self.pre_publish_retest_run_uid,
            "pre_publish_retest_summary": self.get_pre_publish_retest_summary(),
            "pre_publish_block_reasons": self.get_pre_publish_block_reasons(),
            "approved_to_publish": bool(self.approved_to_publish),
            "approved_to_publish_at": self.approved_to_publish_at.isoformat() if self.approved_to_publish_at else None,
            "approved_to_publish_by": self.approved_to_publish_by,
            "locked_payload_fingerprint": self.locked_payload_fingerprint,
            "approval_status": self.approval_status,
            "metadata": self.get_metadata(),
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
