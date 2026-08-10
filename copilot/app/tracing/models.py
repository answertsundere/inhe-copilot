"""
Trace V2 数据模型。

trace_runs: 一次请求对应一条 trace
trace_spans: trace 内的层级 span
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

from sqlalchemy import Column, String, Integer, Text, Index, Float
from sqlalchemy.orm import declarative_base

Base = declarative_base()


def _gen_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def gen_trace_id() -> str:
    return _gen_id("tr")


def gen_span_id() -> str:
    return _gen_id("sp")


def gen_snapshot_id() -> str:
    return _gen_id("snap")


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


SPAN_TYPES = (
    "api", "graph", "graph_node", "tool", "llm", "rag", "guard", "storage",
)

SPAN_STATUSES = (
    "running", "success", "miss", "error", "timeout", "skipped", "fallback",
)

TRACE_STATUSES = (
    "running", "success", "error", "timeout",
)


class TraceRun(Base):
    __tablename__ = "trace_runs"

    trace_id = Column(String(32), primary_key=True)
    request_id = Column(String(64), index=True, nullable=False, default="")
    message_id = Column(String(64), index=True, nullable=False, default="")
    conversation_id = Column(String(128), index=True, nullable=False, default="")
    linked_trace_id = Column(String(32), index=True, nullable=True)
    source = Column(String(32), nullable=False, default="")
    scenario = Column(String(32), nullable=False, default="")
    status = Column(String(16), nullable=False, default="running", index=True)
    started_at = Column(String(32), nullable=False)
    ended_at = Column(String(32), nullable=True)
    duration_ms = Column(Integer, nullable=True)
    versions_json = Column(Text, nullable=False, default="{}")
    outcome_json = Column(Text, nullable=False, default="{}")
    created_at = Column(String(32), nullable=False, default=utcnow)

    def set_versions(self, v: dict):
        self.versions_json = json.dumps(v, ensure_ascii=False)

    def get_versions(self) -> dict:
        try:
            return json.loads(self.versions_json)
        except Exception:
            return {}

    def set_outcome(self, o: dict):
        self.outcome_json = json.dumps(o, ensure_ascii=False)

    def get_outcome(self) -> dict:
        try:
            return json.loads(self.outcome_json)
        except Exception:
            return {}


class TraceSpan(Base):
    __tablename__ = "trace_spans"

    span_id = Column(String(32), primary_key=True)
    trace_id = Column(String(32), index=True, nullable=False)
    parent_span_id = Column(String(32), index=True, nullable=True)
    span_type = Column(String(16), index=True, nullable=False)
    name = Column(String(128), index=True, nullable=False)
    status = Column(String(16), index=True, nullable=False, default="running")
    started_at = Column(String(32), nullable=False)
    ended_at = Column(String(32), nullable=True)
    duration_ms = Column(Integer, nullable=True)
    sequence_no = Column(Integer, nullable=False, default=0)
    input_summary_json = Column(Text, nullable=False, default="{}")
    output_summary_json = Column(Text, nullable=False, default="{}")
    decision_json = Column(Text, nullable=False, default="{}")
    evidence_ids_json = Column(Text, nullable=False, default="[]")
    error_json = Column(Text, nullable=True)
    attributes_json = Column(Text, nullable=False, default="{}")

    __table_args__ = (
        Index("ix_spans_trace_name", "trace_id", "name"),
        Index("ix_spans_trace_type", "trace_id", "span_type"),
    )

    def set_input(self, v: dict):
        self.input_summary_json = json.dumps(v, ensure_ascii=False)

    def get_input(self) -> dict:
        try:
            return json.loads(self.input_summary_json)
        except Exception:
            return {}

    def set_output(self, v: dict):
        self.output_summary_json = json.dumps(v, ensure_ascii=False)

    def get_output(self) -> dict:
        try:
            return json.loads(self.output_summary_json)
        except Exception:
            return {}

    def set_decision(self, v: dict):
        self.decision_json = json.dumps(v, ensure_ascii=False)

    def set_error(self, err_type: str, code: str, message: str, retryable: bool = False):
        self.error_json = json.dumps({
            "type": err_type, "code": code, "message": message, "retryable": retryable,
        }, ensure_ascii=False)

    def set_attributes(self, v: dict):
        self.attributes_json = json.dumps(v, ensure_ascii=False)

    def set_evidence_ids(self, ids: list):
        self.evidence_ids_json = json.dumps(ids, ensure_ascii=False)


class AnalysisSnapshot(Base):
    __tablename__ = "analysis_snapshots"

    snapshot_id = Column(String(32), primary_key=True)
    trace_id = Column(String(32), index=True, nullable=True)
    request_id = Column(String(64), index=True, nullable=False, default="")
    message_id = Column(String(64), unique=True, nullable=False)
    conversation_id = Column(String(128), index=True, nullable=False, default="")
    source = Column(String(32), nullable=False, default="")
    scenario = Column(String(32), nullable=False, default="")
    customer_message = Column(Text, nullable=False, default="")
    suggested_reply = Column(Text, nullable=False, default="")
    intent = Column(String(64), nullable=False, default="")
    risk_level = Column(String(16), nullable=False, default="low")
    need_human_review = Column(Integer, nullable=False, default=0)
    execution_debug_json = Column(Text, nullable=False, default="{}")
    evidence_debug_json = Column(Text, nullable=False, default="{}")
    trace_steps_json = Column(Text, nullable=False, default="[]")
    used_knowledge_entry_ids_json = Column(Text, nullable=False, default="[]")
    used_fact_tools_json = Column(Text, nullable=False, default="")
    copilot_context_json = Column(Text, nullable=False, default="{}")
    created_at = Column(String(32), nullable=False, default=utcnow)


class ConversationGoalLifecycleEvent(Base):
    """Privacy-minimal event journal for server-owned conversation goals."""

    __tablename__ = "conversation_goal_lifecycle_events"

    sequence_no = Column(Integer, primary_key=True, autoincrement=True)
    event_id = Column(String(64), unique=True, nullable=False, index=True)
    conversation_ref = Column(String(96), nullable=False, index=True)
    goal_ref = Column(String(96), nullable=False, index=True)
    predecessor_goal_ref = Column(String(96), nullable=False, default="")
    state = Column(String(16), nullable=False, index=True)
    goal_metadata_json = Column(Text, nullable=False, default="{}")
    created_at = Column(String(32), nullable=False, default=utcnow)

    __table_args__ = (
        Index(
            "ix_conversation_goal_lifecycle_current",
            "conversation_ref",
            "sequence_no",
        ),
    )

    def get_goal_metadata(self) -> dict:
        try:
            value = json.loads(self.goal_metadata_json)
        except Exception:
            return {}
        return value if isinstance(value, dict) else {}
