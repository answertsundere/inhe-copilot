from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, Integer, String, Text

from app.db import Base


class EvalCase(Base):
    __tablename__ = "eval_cases"

    id = Column(Integer, primary_key=True, autoincrement=True)
    case_uid = Column(String(128), nullable=False, unique=True, index=True)
    source = Column(String(64), nullable=False, default="", index=True)
    source_ref = Column(String(255), nullable=False, default="")
    status = Column(String(32), nullable=False, default="active", index=True)
    priority = Column(Integer, nullable=False, default=50, index=True)
    category = Column(String(128), nullable=False, default="", index=True)
    customer_message_sanitized = Column(Text, nullable=False, default="")
    context_sanitized_json = Column(Text, nullable=False, default="{}")
    expected_intent = Column(String(64), nullable=False, default="", index=True)
    expected_fact_types_json = Column(Text, nullable=False, default="[]")
    expected_behavior_json = Column(Text, nullable=False, default="{}")
    forbidden_terms_json = Column(Text, nullable=False, default="[]")
    required_evidence_types_json = Column(Text, nullable=False, default="[]")
    product_scope_json = Column(Text, nullable=False, default="[]")
    created_by = Column(String(64), nullable=False, default="")
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    metadata_json = Column(Text, nullable=False, default="{}")


class EvalRun(Base):
    __tablename__ = "eval_runs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    run_uid = Column(String(128), nullable=False, unique=True, index=True)
    run_type = Column(String(64), nullable=False, default="manual", index=True)
    status = Column(String(32), nullable=False, default="running", index=True)
    started_at = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)
    finished_at = Column(DateTime, nullable=True)
    total_cases = Column(Integer, nullable=False, default=0)
    passed_cases = Column(Integer, nullable=False, default=0)
    failed_cases = Column(Integer, nullable=False, default=0)
    error_cases = Column(Integer, nullable=False, default=0)
    code_version = Column(String(64), nullable=False, default="")
    branch_name = Column(String(128), nullable=False, default="")
    config_snapshot_json = Column(Text, nullable=False, default="{}")
    summary_json = Column(Text, nullable=False, default="{}")


class EvalTrace(Base):
    __tablename__ = "eval_traces"

    id = Column(Integer, primary_key=True, autoincrement=True)
    run_uid = Column(String(128), nullable=False, index=True)
    case_uid = Column(String(128), nullable=False, index=True)
    status = Column(String(32), nullable=False, default="", index=True)
    latency_ms = Column(Integer, nullable=False, default=0)
    intent = Column(String(64), nullable=False, default="", index=True)
    query_fact_type = Column(String(64), nullable=False, default="", index=True)
    required_fact_types_json = Column(Text, nullable=False, default="[]")
    requires_human_review = Column(Boolean, nullable=False, default=False)
    final_quality_pass = Column(Boolean, nullable=False, default=False)
    answer_trace_summary_json = Column(Text, nullable=False, default="{}")
    model_trace_summary_json = Column(Text, nullable=False, default="{}")
    tool_trace_summary_json = Column(Text, nullable=False, default="{}")
    evidence_summary_json = Column(Text, nullable=False, default="{}")
    reply_preview = Column(Text, nullable=False, default="")
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)


class EvalFailure(Base):
    __tablename__ = "eval_failures"

    id = Column(Integer, primary_key=True, autoincrement=True)
    run_uid = Column(String(128), nullable=False, index=True)
    case_uid = Column(String(128), nullable=False, index=True)
    failure_type = Column(String(64), nullable=False, default="unknown", index=True)
    severity = Column(String(32), nullable=False, default="medium", index=True)
    root_cause_hint = Column(Text, nullable=False, default="")
    failed_contract = Column(String(128), nullable=False, default="")
    expected_json = Column(Text, nullable=False, default="{}")
    actual_json = Column(Text, nullable=False, default="{}")
    suggested_fix_area = Column(String(128), nullable=False, default="unknown", index=True)
    repair_task_uid = Column(String(128), nullable=False, default="", index=True)
    status = Column(String(32), nullable=False, default="open", index=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)


class EvalRepairTask(Base):
    __tablename__ = "eval_repair_tasks"

    id = Column(Integer, primary_key=True, autoincrement=True)
    repair_task_uid = Column(String(128), nullable=False, unique=True, index=True)
    title = Column(String(255), nullable=False, default="")
    description = Column(Text, nullable=False, default="")
    failure_count = Column(Integer, nullable=False, default=0)
    suggested_owner = Column(String(64), nullable=False, default="")
    suggested_files_json = Column(Text, nullable=False, default="[]")
    status = Column(String(32), nullable=False, default="open", index=True)
    priority = Column(Integer, nullable=False, default=50, index=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
