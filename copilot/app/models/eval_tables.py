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

    def to_dict(self):
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
            "answer_trace": self.get_answer_trace(),
            "final_audit": self.get_final_audit(),
            "semantic_compiler": self.get_semantic_compiler(),
            "requires_human_review": self.requires_human_review,
            "latency_ms": self.latency_ms,
            "product_identity": self.get_product_identity(),
            "order_identity_hash": self.order_identity_hash,
            "passed": self.passed,
            "failure_labels": self.get_failure_labels(),
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
