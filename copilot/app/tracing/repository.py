"""
Trace Repository — SQLite persistence for traces, spans, and snapshots.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import re
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
TRACE_SQLITE_BUSY_TIMEOUT_SECONDS = 0.2
TRACE_SQLITE_BUSY_TIMEOUT_MS = 200
CONVERSATION_GOAL_LIFECYCLE_HMAC_ENV = (
    "COPILOT_CONVERSATION_GOAL_LIFECYCLE_HMAC_KEY"
)
_GOAL_LIFECYCLE_SCHEMA_VERSION = "conversation-goal-lifecycle/v1"
_GOAL_LIFECYCLE_STATES = frozenset({"open", "completed", "superseded"})
_GOAL_LIFECYCLE_METADATA_FIELDS = frozenset({
    "goal_ref",
    "goal_kind",
    "claim_type_status",
    "claim_type",
    "attribute_key",
    "subject_scope",
    "semantic_key",
    "policy_intent_ref",
    "policy_goal_family",
    "policy_intent_kind",
    "source_turn_uid",
    "source_span_sha256",
})


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
            connect_args={
                "check_same_thread": False,
                "timeout": TRACE_SQLITE_BUSY_TIMEOUT_SECONDS,
            },
            pool_pre_ping=True,
        )
        # WAL mode for better concurrent read/write
        @sa_event.listens_for(_engine, "connect")
        def _set_sqlite_pragma(dbapi_conn, connection_record):
            cursor = dbapi_conn.cursor()
            cursor.execute(f"PRAGMA busy_timeout={TRACE_SQLITE_BUSY_TIMEOUT_MS}")
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


def _goal_lifecycle_hmac_key() -> bytes:
    value = os.environ.get(CONVERSATION_GOAL_LIFECYCLE_HMAC_ENV, "")
    return value.encode("utf-8") if isinstance(value, str) and value else b""


def _goal_lifecycle_hmac(key: bytes, namespace: str, value: str) -> str:
    return hmac.new(
        key,
        f"{namespace}\x00{value}".encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def _conversation_goal_lifecycle_identity(
    conversation_id: object,
) -> tuple[bytes, str]:
    key = _goal_lifecycle_hmac_key()
    raw = str(conversation_id or "").strip()
    if not key or not raw or raw == "default" or len(raw) > 512:
        return b"", ""
    return key, "conversation-" + _goal_lifecycle_hmac(
        key, "conversation", raw
    )[:32]


def _goal_lifecycle_metadata(goal: object) -> dict[str, str]:
    if not isinstance(goal, dict):
        return {}
    if (
        goal.get("goal_kind") != "customer_goal"
        or goal.get("source") != "current_customer_message"
        or goal.get("owner") != "turn_understanding_owner"
        or goal.get("source_stage") != "semantic_fact_type_service"
    ):
        return {}
    metadata = {
        field: str(goal.get(field) or "").strip()
        for field in _GOAL_LIFECYCLE_METADATA_FIELDS
    }
    if (
        not re.fullmatch(r"goal-[0-9a-f]{16}", metadata["goal_ref"])
        or metadata["claim_type_status"] not in {"canonical", "unmapped"}
        or not re.fullmatch(r"turn-[0-9a-f]{20}", metadata["source_turn_uid"])
        or not re.fullmatch(
            r"[0-9a-f]{64}", metadata["source_span_sha256"]
        )
    ):
        return {}
    if metadata["claim_type_status"] == "canonical":
        if not metadata["claim_type"] or metadata["semantic_key"]:
            return {}
    elif metadata["claim_type"]:
        return {}
    return metadata


def _goal_lifecycle_alias(
    key: bytes,
    conversation_ref: str,
    goal_ref: str,
) -> str:
    return "open-goal-" + _goal_lifecycle_hmac(
        key,
        conversation_ref,
        goal_ref,
    )[:24]


def _goal_lifecycle_event_id(
    key: bytes,
    *,
    conversation_ref: str,
    goal_ref: str,
    state: str,
    successor_goal_ref: str = "",
) -> str:
    canonical = json.dumps(
        {
            "conversation_ref": conversation_ref,
            "goal_ref": goal_ref,
            "state": state,
            "successor_goal_ref": successor_goal_ref,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return "goal-event-" + _goal_lifecycle_hmac(
        key, "event", canonical
    )[:32]


def _goal_lifecycle_current_states(
    rows: list[object],
) -> tuple[dict[str, dict[str, object]], bool]:
    states: dict[str, dict[str, object]] = {}
    for row in rows:
        state = str(getattr(row, "state", "") or "").strip()
        goal_ref = str(getattr(row, "goal_ref", "") or "").strip()
        successor_goal_ref = str(
            getattr(row, "successor_goal_ref", "") or ""
        ).strip()
        getter = getattr(row, "get_goal_metadata", None)
        metadata = getter() if callable(getter) else {}
        legacy_metadata_fields = _GOAL_LIFECYCLE_METADATA_FIELDS - {
            "subject_scope"
        }
        if (
            state not in _GOAL_LIFECYCLE_STATES
            or (
                set(metadata) != _GOAL_LIFECYCLE_METADATA_FIELDS
                and set(metadata) != legacy_metadata_fields
            )
            or metadata.get("goal_ref") != goal_ref
        ):
            return {}, False
        current = states.get(goal_ref)
        if state == "open":
            if current:
                return {}, False
        elif (
            not current
            or current.get("state") != "open"
            or current.get("metadata") != metadata
            or (state == "completed" and successor_goal_ref)
            or (
                state == "superseded"
                and (
                    not successor_goal_ref
                    or successor_goal_ref == goal_ref
                )
            )
        ):
            return {}, False
        states[goal_ref] = {"state": state, "metadata": metadata}
    return states, True


def _goal_lifecycle_rows(session: Session, conversation_ref: str) -> list[object]:
    from app.tracing.models import ConversationGoalLifecycleEvent

    return (
        session.query(ConversationGoalLifecycleEvent)
        .filter_by(conversation_ref=conversation_ref)
        .order_by(ConversationGoalLifecycleEvent.sequence_no.asc())
        .all()
    )


def load_conversation_goal_lifecycle_context(
    conversation_id: object,
) -> tuple[dict[str, object], str]:
    """Load HMAC-addressed open goals without exposing conversation content."""
    key, conversation_ref = _conversation_goal_lifecycle_identity(conversation_id)
    if not key:
        return {}, "disabled"
    try:
        init_trace_tables()
        session = get_session()
        try:
            states, valid = _goal_lifecycle_current_states(
                _goal_lifecycle_rows(session, conversation_ref)
            )
        finally:
            session.close()
    except Exception as exc:
        logger.warning("conversation goal lifecycle load failed: %s", type(exc).__name__)
        return {}, "degraded"
    if not valid:
        return {}, "invalid"
    open_goals = [
        {
            "goal_alias": _goal_lifecycle_alias(key, conversation_ref, goal_ref),
            "conversation_ref": conversation_ref,
            "subject_scope": str(
                item["metadata"].get("subject_scope") or ""
            ).strip(),
            **dict(item["metadata"]),
        }
        for goal_ref, item in states.items()
        if item["state"] == "open"
    ]
    return {
        "schema_version": _GOAL_LIFECYCLE_SCHEMA_VERSION,
        "owner": "analysis_pipeline",
        "conversation_ref": conversation_ref,
        "open_goals": sorted(open_goals, key=lambda item: item["goal_alias"]),
    }, "loaded"


def complete_conversation_goal_lifecycle(
    conversation_id: object,
    goal_ref: object,
    goal_alias: object,
) -> dict[str, object]:
    """Close one open goal after a trusted delivery integration proves it sent.

    This repository function intentionally has no caller in candidate generation,
    feedback, or supervisor review. Those surfaces are not delivery receipts.
    """
    key, conversation_ref = _conversation_goal_lifecycle_identity(conversation_id)
    normalized_goal_ref = str(goal_ref or "").strip()
    normalized_goal_alias = str(goal_alias or "").strip()
    if not key:
        return {"status": "disabled", "write_count": 0}
    if (
        not re.fullmatch(r"goal-[0-9a-f]{16}", normalized_goal_ref)
        or not hmac.compare_digest(
            normalized_goal_alias,
            _goal_lifecycle_alias(key, conversation_ref, normalized_goal_ref),
        )
    ):
        return {"status": "invalid", "write_count": 0}

    from app.tracing.models import ConversationGoalLifecycleEvent, utcnow

    try:
        init_trace_tables()
        session = get_session()
        try:
            existing_rows = _goal_lifecycle_rows(session, conversation_ref)
            states, valid = _goal_lifecycle_current_states(existing_rows)
            if not valid:
                return {"status": "invalid", "write_count": 0}
            current = states.get(normalized_goal_ref)
            event_id = _goal_lifecycle_event_id(
                key,
                conversation_ref=conversation_ref,
                goal_ref=normalized_goal_ref,
                state="completed",
            )
            existing_event_ids = {str(row.event_id) for row in existing_rows}
            if (
                current
                and current.get("state") == "completed"
                and event_id in existing_event_ids
            ):
                return {"status": "recorded", "write_count": 0}
            if not current or current.get("state") != "open":
                return {"status": "invalid", "write_count": 0}
            session.add(ConversationGoalLifecycleEvent(
                event_id=event_id,
                conversation_ref=conversation_ref,
                goal_ref=normalized_goal_ref,
                successor_goal_ref="",
                state="completed",
                goal_metadata_json=json.dumps(
                    current["metadata"],
                    sort_keys=True,
                    separators=(",", ":"),
                ),
                created_at=utcnow(),
            ))
            session.commit()
            return {"status": "recorded", "write_count": 1}
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()
    except Exception as exc:
        logger.warning("conversation goal lifecycle completion failed: %s", type(exc).__name__)
        return {"status": "degraded", "write_count": 0}


def record_conversation_goal_lifecycle(
    conversation_id: object,
    goals: object,
    continuations: object = None,
) -> dict[str, object]:
    """Append verified goal state without writing formal knowledge or replies."""
    key, conversation_ref = _conversation_goal_lifecycle_identity(conversation_id)
    if not key:
        return {"status": "disabled", "write_count": 0}
    if not isinstance(goals, list):
        return {"status": "invalid", "write_count": 0}
    metadata_by_ref: dict[str, dict[str, str]] = {}
    for goal in goals:
        metadata = _goal_lifecycle_metadata(goal)
        if not metadata or metadata["goal_ref"] in metadata_by_ref:
            return {"status": "invalid", "write_count": 0}
        metadata_by_ref[metadata["goal_ref"]] = metadata

    continuation_by_goal: dict[str, dict[str, str]] = {}
    if continuations is not None:
        if not isinstance(continuations, list):
            return {"status": "invalid", "write_count": 0}
        for item in continuations:
            if not isinstance(item, dict) or set(item) != {
                "goal_ref",
                "continued_from_goal_ref",
                "continued_from_alias",
                "origin_source_turn_uid",
                "origin_source_span_sha256",
            }:
                return {"status": "invalid", "write_count": 0}
            goal_ref = str(item.get("goal_ref") or "").strip()
            predecessor = str(item.get("continued_from_goal_ref") or "").strip()
            if (
                goal_ref not in metadata_by_ref
                or not re.fullmatch(r"goal-[0-9a-f]{16}", predecessor)
                or predecessor == goal_ref
                or goal_ref in continuation_by_goal
                or predecessor in {
                    value["continued_from_goal_ref"]
                    for value in continuation_by_goal.values()
                }
            ):
                return {"status": "invalid", "write_count": 0}
            continuation_by_goal[goal_ref] = {
                key: str(item[key] or "").strip()
                for key in item
            }

    from app.tracing.models import ConversationGoalLifecycleEvent, utcnow

    try:
        init_trace_tables()
        session = get_session()
        try:
            existing_rows = _goal_lifecycle_rows(session, conversation_ref)
            states, valid = _goal_lifecycle_current_states(existing_rows)
            if not valid:
                return {"status": "invalid", "write_count": 0}
            existing_event_ids = {str(row.event_id) for row in existing_rows}
            for goal_ref, metadata in metadata_by_ref.items():
                current = states.get(goal_ref)
                if current and (
                    current.get("state") != "open"
                    or current.get("metadata") != metadata
                ):
                    return {"status": "invalid", "write_count": 0}
            for goal_ref, continuation in continuation_by_goal.items():
                predecessor = continuation["continued_from_goal_ref"]
                predecessor_state = states.get(predecessor)
                if not predecessor_state or predecessor_state.get("state") != "open":
                    return {"status": "invalid", "write_count": 0}
                predecessor_metadata = predecessor_state["metadata"]
                if (
                    continuation["continued_from_alias"]
                    != _goal_lifecycle_alias(key, conversation_ref, predecessor)
                    or continuation["origin_source_turn_uid"]
                    != predecessor_metadata["source_turn_uid"]
                    or continuation["origin_source_span_sha256"]
                    != predecessor_metadata["source_span_sha256"]
                ):
                    return {"status": "invalid", "write_count": 0}

            write_count = 0
            for goal_ref in sorted(metadata_by_ref):
                continuation = continuation_by_goal.get(goal_ref)
                predecessor = (
                    continuation["continued_from_goal_ref"]
                    if continuation else ""
                )
                if predecessor:
                    predecessor_metadata = states[predecessor]["metadata"]
                    event_id = _goal_lifecycle_event_id(
                        key,
                        conversation_ref=conversation_ref,
                        goal_ref=predecessor,
                        state="superseded",
                        successor_goal_ref=goal_ref,
                    )
                    if event_id not in existing_event_ids:
                        session.add(ConversationGoalLifecycleEvent(
                            event_id=event_id,
                            conversation_ref=conversation_ref,
                            goal_ref=predecessor,
                            successor_goal_ref=goal_ref,
                            state="superseded",
                            goal_metadata_json=json.dumps(
                                predecessor_metadata,
                                sort_keys=True,
                                separators=(",", ":"),
                            ),
                            created_at=utcnow(),
                        ))
                        existing_event_ids.add(event_id)
                        write_count += 1
                event_id = _goal_lifecycle_event_id(
                    key,
                    conversation_ref=conversation_ref,
                    goal_ref=goal_ref,
                    state="open",
                    successor_goal_ref=predecessor,
                )
                if event_id not in existing_event_ids:
                    session.add(ConversationGoalLifecycleEvent(
                        event_id=event_id,
                        conversation_ref=conversation_ref,
                        goal_ref=goal_ref,
                        successor_goal_ref=predecessor,
                        state="open",
                        goal_metadata_json=json.dumps(
                            metadata_by_ref[goal_ref],
                            sort_keys=True,
                            separators=(",", ":"),
                        ),
                        created_at=utcnow(),
                    ))
                    existing_event_ids.add(event_id)
                    write_count += 1
            session.commit()
            return {"status": "recorded", "write_count": write_count}
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()
    except Exception as exc:
        logger.warning("conversation goal lifecycle write failed: %s", type(exc).__name__)
        return {"status": "degraded", "write_count": 0}


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
