"""
Trace Repository — SQLite persistence for traces, spans, and snapshots.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import create_engine, event as sa_event, text
from sqlalchemy.orm import sessionmaker, Session

from app.config import BASE_DIR

logger = logging.getLogger(__name__)

TRACE_DB_PATH = os.environ.get(
    "COPILOT_TRACE_DB",
    os.path.join(BASE_DIR, "data", "traces.db"),
)

_engine = None
_SessionLocal = None
_lock = threading.Lock()


def _get_engine():
    global _engine, _SessionLocal
    if _engine is not None:
        return _engine
    with _lock:
        if _engine is not None:
            return _engine
        os.makedirs(os.path.dirname(TRACE_DB_PATH), exist_ok=True)
        _engine = create_engine(
            f"sqlite:///{TRACE_DB_PATH}",
            connect_args={"check_same_thread": False},
            pool_pre_ping=True,
        )
        # WAL mode for better concurrent read/write
        @sa_event.listens_for(_engine, "connect")
        def _set_sqlite_pragma(dbapi_conn, connection_record):
            cursor = dbapi_conn.cursor()
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA synchronous=NORMAL")
            cursor.close()
        _SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=_engine)
        return _engine


def init_trace_tables():
    """Create trace tables if they don't exist."""
    from app.tracing.models import Base
    engine = _get_engine()
    Base.metadata.create_all(bind=engine)


def get_session() -> Session:
    _get_engine()
    return _SessionLocal()


# ========== Trace Run CRUD ==========

def save_trace_run(trace_run_dict: dict) -> None:
    """Insert or update a trace run."""
    from app.tracing.models import TraceRun
    session = get_session()
    try:
        existing = session.query(TraceRun).filter_by(trace_id=trace_run_dict["trace_id"]).first()
        if existing:
            for k, v in trace_run_dict.items():
                if k != "trace_id" and hasattr(existing, k):
                    setattr(existing, k, v)
        else:
            run = TraceRun(**trace_run_dict)
            session.add(run)
        session.commit()
    except Exception as e:
        session.rollback()
        logger.warning("save_trace_run failed: %s", e)
    finally:
        session.close()


def get_trace_run(trace_id: str) -> Optional[dict]:
    from app.tracing.models import TraceRun
    session = get_session()
    try:
        run = session.query(TraceRun).filter_by(trace_id=trace_id).first()
        if not run:
            return None
        return {
            "trace_id": run.trace_id,
            "request_id": run.request_id,
            "message_id": run.message_id,
            "conversation_id": run.conversation_id,
            "linked_trace_id": run.linked_trace_id,
            "source": run.source,
            "scenario": run.scenario,
            "status": run.status,
            "started_at": run.started_at,
            "ended_at": run.ended_at,
            "duration_ms": run.duration_ms,
            "versions": run.get_versions(),
            "outcome": run.get_outcome(),
            "created_at": run.created_at,
        }
    finally:
        session.close()


def query_traces(
    conversation_id: str = "",
    request_id: str = "",
    message_id: str = "",
    status: str = "",
    source: str = "",
    intent: str = "",
    risk_level: str = "",
    min_duration_ms: int = 0,
    has_error: bool = False,
    date_from: str = "",
    date_to: str = "",
    page: int = 1,
    page_size: int = 20,
) -> dict:
    from app.tracing.models import TraceRun
    session = get_session()
    try:
        q = session.query(TraceRun)
        if conversation_id:
            q = q.filter(TraceRun.conversation_id == conversation_id)
        if request_id:
            q = q.filter(TraceRun.request_id == request_id)
        if message_id:
            q = q.filter(TraceRun.message_id == message_id)
        if status:
            q = q.filter(TraceRun.status == status)
        if source:
            q = q.filter(TraceRun.source == source)
        if min_duration_ms:
            q = q.filter(TraceRun.duration_ms >= min_duration_ms)
        if has_error:
            q = q.filter(TraceRun.status == "error")
        if date_from:
            q = q.filter(TraceRun.started_at >= date_from)
        if date_to:
            q = q.filter(TraceRun.started_at <= date_to)
        if intent or risk_level:
            # Filter on outcome JSON — SQLite json_extract
            if intent:
                q = q.filter(text("json_extract(outcome_json, '$.intent') = :intent").bindparams(intent=intent))
            if risk_level:
                q = q.filter(text("json_extract(outcome_json, '$.risk_level') = :risk").bindparams(risk=risk_level))

        total = q.count()
        rows = q.order_by(TraceRun.started_at.desc()).offset((page - 1) * page_size).limit(page_size).all()

        items = []
        for r in rows:
            items.append({
                "trace_id": r.trace_id,
                "request_id": r.request_id,
                "message_id": r.message_id,
                "conversation_id": r.conversation_id,
                "source": r.source,
                "scenario": r.scenario,
                "status": r.status,
                "started_at": r.started_at,
                "duration_ms": r.duration_ms,
                "outcome": r.get_outcome(),
            })
        return {"items": items, "total": total, "page": page, "page_size": page_size}
    finally:
        session.close()


# ========== Span CRUD ==========

def save_span(span_dict: dict) -> None:
    from app.tracing.models import TraceSpan
    session = get_session()
    try:
        existing = session.query(TraceSpan).filter_by(span_id=span_dict["span_id"]).first()
        if existing:
            for k, v in span_dict.items():
                if k != "span_id" and hasattr(existing, k):
                    setattr(existing, k, v)
        else:
            span = TraceSpan(**span_dict)
            session.add(span)
        session.commit()
    except Exception as e:
        session.rollback()
        logger.warning("save_span failed: %s", e)
    finally:
        session.close()


def get_spans(trace_id: str) -> list[dict]:
    from app.tracing.models import TraceSpan
    session = get_session()
    try:
        spans = session.query(TraceSpan).filter_by(trace_id=trace_id).order_by(TraceSpan.sequence_no).all()
        result = []
        for s in spans:
            result.append({
                "span_id": s.span_id,
                "trace_id": s.trace_id,
                "parent_span_id": s.parent_span_id,
                "span_type": s.span_type,
                "name": s.name,
                "status": s.status,
                "started_at": s.started_at,
                "ended_at": s.ended_at,
                "duration_ms": s.duration_ms,
                "sequence_no": s.sequence_no,
                "input_summary": s.get_input(),
                "output_summary": json.loads(s.output_summary_json) if s.output_summary_json else {},
                "error": json.loads(s.error_json) if s.error_json else None,
            })
        return result
    finally:
        session.close()


# ========== Snapshot CRUD ==========

def save_snapshot(snap_dict: dict) -> None:
    from app.tracing.models import AnalysisSnapshot
    session = get_session()
    try:
        existing = session.query(AnalysisSnapshot).filter_by(message_id=snap_dict.get("message_id", "")).first()
        if existing:
            for k, v in snap_dict.items():
                if k != "snapshot_id" and hasattr(existing, k):
                    setattr(existing, k, v)
        else:
            snap = AnalysisSnapshot(**snap_dict)
            session.add(snap)
        session.commit()
    except Exception as e:
        session.rollback()
        logger.warning("save_snapshot failed: %s", e)
    finally:
        session.close()


def get_snapshot_by_message_id(message_id: str) -> Optional[dict]:
    from app.tracing.models import AnalysisSnapshot
    session = get_session()
    try:
        snap = session.query(AnalysisSnapshot).filter_by(message_id=message_id).first()
        if not snap:
            return None
        return {
            "snapshot_id": snap.snapshot_id,
            "trace_id": snap.trace_id,
            "request_id": snap.request_id,
            "message_id": snap.message_id,
            "conversation_id": snap.conversation_id,
            "source": snap.source,
            "scenario": snap.scenario,
            "customer_message": snap.customer_message,
            "suggested_reply": snap.suggested_reply,
            "intent": snap.intent,
            "risk_level": snap.risk_level,
            "need_human_review": bool(snap.need_human_review),
            "execution_debug": json.loads(snap.execution_debug_json) if snap.execution_debug_json else {},
            "evidence_debug": json.loads(snap.evidence_debug_json) if snap.evidence_debug_json else {},
            "used_knowledge_entry_ids": json.loads(snap.used_knowledge_entry_ids_json) if snap.used_knowledge_entry_ids_json else [],
            "used_fact_tools": snap.used_fact_tools_json,
            "created_at": snap.created_at,
        }
    finally:
        session.close()


def get_snapshot_by_trace_id(trace_id: str) -> Optional[dict]:
    from app.tracing.models import AnalysisSnapshot
    session = get_session()
    try:
        snap = session.query(AnalysisSnapshot).filter_by(trace_id=trace_id).first()
        if not snap:
            return None
        return get_snapshot_by_message_id(snap.message_id)
    finally:
        session.close()


# ========== Linked data ==========

def get_trace_detail(trace_id: str) -> Optional[dict]:
    run = get_trace_run(trace_id)
    if not run:
        return None
    spans = get_spans(trace_id)
    snapshot = get_snapshot_by_trace_id(trace_id)
    return {
        "trace": run,
        "spans": spans,
        "snapshot": snapshot,
    }
