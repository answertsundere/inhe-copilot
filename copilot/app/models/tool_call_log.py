from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, Integer, String, Text

from app.db import Base


class ToolCallLog(Base):
    __tablename__ = "tool_call_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)
    trace_id = Column(String(64), nullable=False, default="", index=True)
    conversation_id = Column(String(128), nullable=False, default="", index=True)
    request_id = Column(String(128), nullable=False, default="", index=True)
    node_name = Column(String(128), nullable=False, default="", index=True)
    tool_name = Column(String(128), nullable=False, default="", index=True)
    tool_risk_level = Column(String(64), nullable=False, default="")
    intent = Column(String(64), nullable=False, default="", index=True)
    query_fact_type = Column(String(64), nullable=False, default="", index=True)
    allowed = Column(Boolean, nullable=False, default=False)
    blocked_reason = Column(String(255), nullable=False, default="")
    status = Column(String(32), nullable=False, default="", index=True)
    error_type = Column(String(128), nullable=False, default="")
    error_message = Column(Text, nullable=False, default="")
    latency_ms = Column(Integer, nullable=False, default=0)
    input_summary_json = Column(Text, nullable=False, default="{}")
    output_summary_json = Column(Text, nullable=False, default="{}")
    entity_summary_json = Column(Text, nullable=False, default="{}")
    evidence_summary_json = Column(Text, nullable=False, default="{}")
