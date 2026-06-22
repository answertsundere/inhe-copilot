from __future__ import annotations

from datetime import datetime

from sqlalchemy import Column, DateTime, Float, Integer, String, Text

from app.db import Base


class ModelCallLog(Base):
    __tablename__ = "llm_call_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    trace_id = Column(String(64), nullable=False, default="", index=True)
    conversation_id = Column(String(128), nullable=False, default="", index=True)
    request_id = Column(String(128), nullable=False, default="", index=True)
    node_name = Column(String(128), nullable=False, default="", index=True)
    alias = Column(String(64), nullable=False, default="", index=True)
    provider = Column(String(64), nullable=False, default="")
    model = Column(String(128), nullable=False, default="")
    api_base_host = Column(String(255), nullable=False, default="")
    prompt_tokens = Column(Integer, nullable=False, default=0)
    completion_tokens = Column(Integer, nullable=False, default=0)
    total_tokens = Column(Integer, nullable=False, default=0)
    estimated_cost = Column(Float, nullable=False, default=0.0)
    currency = Column(String(16), nullable=False, default="USD")
    latency_ms = Column(Integer, nullable=False, default=0)
    status = Column(String(32), nullable=False, default="")
    error_type = Column(String(128), nullable=False, default="")
    error_message = Column(Text, nullable=False, default="")
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)
    metadata_json = Column(Text, nullable=False, default="{}")
