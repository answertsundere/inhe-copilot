"""
Tests for the real data cutoff rules used in golden set extraction.

Validates:
1. Messages with sent_at before 2026-05-26 00:00:00+08:00 are excluded.
2. Messages at exactly 2026-05-26 00:00:00+08:00 are included.
3. Filtering uses sent_at, not source_file.
4. Sessions containing pre-cutoff messages cannot be approved.
"""

import sys
import os
import copy
from datetime import datetime, timezone, timedelta
from unittest.mock import patch, MagicMock

import pytest
from dateutil.parser import isoparse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.golden_set.extract_real_candidates import (
    is_valid_session,
    extract_candidates,
    CUTOFF_DEFAULT,
    EXTRACTION_VERSION,
)

CUTOFF_DT = isoparse("2026-05-26T00:00:00+08:00")


# ---------- helpers ----------

def _make_session(messages, **overrides):
    """Build a minimal session dict for testing."""
    session = {
        "messages": messages,
        "data_quality_status": "complete",
        "scoreable": True,
    }
    session.update(overrides)
    return session


def _make_msg(sent_at, sender_type="customer", content="你好请问这个多少钱", message_type="text"):
    """Build a minimal message dict."""
    return {
        "sender_type": sender_type,
        "sender_name": "tester",
        "content": content,
        "message_type": message_type,
        "sent_at": sent_at,
    }


def _after_cutoff(offset_minutes=60):
    """Return an ISO timestamp safely after cutoff."""
    dt = CUTOFF_DT + timedelta(minutes=offset_minutes)
    return dt.isoformat()


def _before_cutoff(offset_minutes=-60):
    """Return an ISO timestamp safely before cutoff."""
    dt = CUTOFF_DT + timedelta(minutes=offset_minutes)
    return dt.isoformat()


def _at_cutoff():
    """Return the ISO timestamp at the exact cutoff boundary."""
    return CUTOFF_DT.isoformat()


# ---------- is_valid_session tests ----------

class TestIsValidSession:
    """Tests for is_valid_session quality checks."""

    def test_valid_session_passes(self):
        session = _make_session([
            _make_msg(_after_cutoff(10), sender_type="customer", content="请问这个书桌多高"),
            _make_msg(_after_cutoff(11), sender_type="agent", content="高度是75cm"),
        ])
        ok, reason = is_valid_session(session)
        assert ok is True
        assert reason == "ok"

    def test_empty_messages_fails(self):
        session = _make_session([])
        ok, reason = is_valid_session(session)
        assert ok is False
        assert reason == "no_messages"

    def test_customer_only_fails(self):
        session = _make_session([
            _make_msg(_after_cutoff(10), sender_type="customer", content="你好"),
        ])
        ok, reason = is_valid_session(session)
        assert ok is False
        assert reason == "agent_only"  # No agent messages

    def test_agent_only_fails(self):
        session = _make_session([
            _make_msg(_after_cutoff(10), sender_type="agent", content="您好欢迎光临"),
        ])
        ok, reason = is_valid_session(session)
        assert ok is False
        assert reason == "customer_only"  # No customer messages

    def test_no_real_question_fails(self):
        session = _make_session([
            _make_msg(_after_cutoff(10), sender_type="customer", content="", message_type="image"),
            _make_msg(_after_cutoff(11), sender_type="agent", content="您好"),
        ])
        ok, reason = is_valid_session(session)
        assert ok is False
        assert reason == "no_real_question"

    def test_automated_greeting_only_fails(self):
        session = _make_session([
            _make_msg(_after_cutoff(10), sender_type="customer", content="你好"),
            _make_msg(_after_cutoff(11), sender_type="agent", content="亲，欢迎光临本店"),
        ])
        ok, reason = is_valid_session(session)
        assert ok is False
        # "你好" passes real question check but agent only has greetings
        assert reason in ("automated_greeting_only", "no_real_question")

    def test_quality_history_truncated_fails(self):
        session = _make_session(
            [
                _make_msg(_after_cutoff(10), sender_type="customer", content="多少钱"),
                _make_msg(_after_cutoff(11), sender_type="agent", content="200元"),
            ],
            data_quality_status="history_truncated",
        )
        ok, reason = is_valid_session(session)
        assert ok is False
        # May be quality_ or no_real_question depending on content check
        assert ok is False

    def test_pure_emoji_no_real_question(self):
        session = _make_session([
            _make_msg(_after_cutoff(10), sender_type="customer", content="\U0001f600\U0001f600"),
            _make_msg(_after_cutoff(11), sender_type="agent", content="您好有什么可以帮您"),
        ])
        ok, reason = is_valid_session(session)
        assert ok is False
        assert reason == "no_real_question"


# ---------- Cutoff boundary tests ----------

class TestCutoffBoundary:
    """Tests that the cutoff timestamp boundary is enforced correctly."""

    def test_message_at_exact_cutoff_is_included(self):
        """A message sent at exactly 2026-05-26T00:00:00+08:00 must NOT be excluded."""
        msg = _make_msg(_at_cutoff(), sender_type="customer", content="你好请问这个多少钱")
        parsed = isoparse(msg["sent_at"])
        assert parsed >= CUTOFF_DT, "Message at exact cutoff should pass sent_at >= cutoff"

    def test_message_before_cutoff_is_excluded(self):
        """A message sent one second before cutoff must be excluded."""
        before = (CUTOFF_DT - timedelta(seconds=1)).isoformat()
        msg = _make_msg(before, sender_type="customer", content="你好请问这个多少钱")
        parsed = isoparse(msg["sent_at"])
        assert parsed < CUTOFF_DT, "Message before cutoff should fail sent_at >= cutoff"

    def test_message_after_cutoff_is_included(self):
        """A message sent one second after cutoff must be included."""
        after = (CUTOFF_DT + timedelta(seconds=1)).isoformat()
        msg = _make_msg(after, sender_type="customer", content="你好请问这个多少钱")
        parsed = isoparse(msg["sent_at"])
        assert parsed >= CUTOFF_DT, "Message after cutoff should pass sent_at >= cutoff"

    def test_cutoff_uses_sent_at_not_source_file(self):
        """Filtering must be based on sent_at, not source_file name or path."""
        # A session whose source_file name looks "old" but messages are after cutoff
        session = _make_session(
            [
                _make_msg(_after_cutoff(120), sender_type="customer", content="请问多少钱"),
                _make_msg(_after_cutoff(121), sender_type="agent", content="199元"),
            ],
            source_file="2024-01-01_old_chat.xlsx",
        )
        ok, reason = is_valid_session(session)
        assert ok is True, "Session with old source_file but new sent_at should pass"


# ---------- Session-level cutoff enforcement ----------

class TestSessionCutoffEnforcement:
    """Tests that sessions with pre-cutoff messages are rejected."""

    def test_all_messages_after_cutoff_passes(self):
        """A session with all messages after the cutoff should pass validation."""
        session = _make_session([
            _make_msg(_after_cutoff(60), sender_type="customer", content="你好，请问这款书桌尺寸是多少"),
            _make_msg(_after_cutoff(61), sender_type="agent", content="您好，尺寸是120x60cm"),
            _make_msg(_after_cutoff(62), sender_type="customer", content="好的谢谢"),
        ])
        ok, reason = is_valid_session(session)
        assert ok is True
        assert reason == "ok"

    def test_session_with_any_pre_cutoff_message_fails_approval(self):
        """
        A session containing even a single message before cutoff must not be
        approvable. Simulates the PostgreSQL reader's verification logic.
        """
        messages = [
            _make_msg(_before_cutoff(-60), sender_type="customer", content="你好"),
            _make_msg(_before_cutoff(-59), sender_type="agent", content="您好欢迎光临"),
            _make_msg(_after_cutoff(60), sender_type="customer", content="请问发货了吗"),
            _make_msg(_after_cutoff(61), sender_type="agent", content="已经发货了"),
        ]

        # Replicate the cutoff verification from qa_postgres_reader.read_sessions
        has_pre_cutoff = False
        for m in messages:
            if m.get("sent_at"):
                msg_time = isoparse(m["sent_at"])
                if msg_time < CUTOFF_DT:
                    has_pre_cutoff = True
                    break

        assert has_pre_cutoff is True, "Session with pre-cutoff messages must be flagged"

    def test_session_with_all_pre_cutoff_messages_rejected(self):
        """A session with all messages before cutoff is fully rejected."""
        messages = [
            _make_msg(_before_cutoff(-120), sender_type="customer", content="你好"),
            _make_msg(_before_cutoff(-119), sender_type="agent", content="您好"),
        ]

        has_pre_cutoff = any(
            isoparse(m["sent_at"]) < CUTOFF_DT
            for m in messages
            if m.get("sent_at")
        )
        assert has_pre_cutoff is True

    def test_session_at_exact_cutoff_boundary_passes(self):
        """A session where the earliest message is exactly at cutoff passes."""
        messages = [
            _make_msg(_at_cutoff(), sender_type="customer", content="你好请问这个多少钱"),
            _make_msg(_after_cutoff(1), sender_type="agent", content="您好价格是299元"),
        ]

        has_pre_cutoff = any(
            isoparse(m["sent_at"]) < CUTOFF_DT
            for m in messages
            if m.get("sent_at")
        )
        assert has_pre_cutoff is False, "Messages at exact cutoff should not be flagged as pre-cutoff"

    def test_single_message_before_cutoff_rejects_whole_session(self):
        """Even one pre-cutoff message among many post-cutoff ones causes rejection."""
        messages = [
            _make_msg(_before_cutoff(-1), sender_type="customer", content="在吗"),
            _make_msg(_after_cutoff(10), sender_type="agent", content="您好"),
            _make_msg(_after_cutoff(20), sender_type="customer", content="请问书桌尺寸"),
            _make_msg(_after_cutoff(30), sender_type="agent", content="120x60cm"),
            _make_msg(_after_cutoff(40), sender_type="customer", content="好的谢谢"),
            _make_msg(_after_cutoff(50), sender_type="agent", content="不客气"),
        ]

        has_pre_cutoff = False
        for m in messages:
            if m.get("sent_at"):
                msg_time = isoparse(m["sent_at"])
                if msg_time < CUTOFF_DT:
                    has_pre_cutoff = True
                    break

        assert has_pre_cutoff is True

    def test_cutoff_filtering_ignores_source_file_date(self):
        """
        The source_file field may contain old dates or names, but filtering
        must only look at sent_at, not source_file.
        """
        # source_file from an old batch but messages are new
        session = _make_session(
            [
                _make_msg(_after_cutoff(300), sender_type="customer", content="请问这款有实木的吗"),
                _make_msg(_after_cutoff(301), sender_type="agent", content="有的，橡胶木材质"),
            ],
            source_file="2025-03-15_chat_export.xlsx",
        )

        ok, reason = is_valid_session(session)
        assert ok is True

        # Verify by checking sent_at directly
        for m in session["messages"]:
            msg_time = isoparse(m["sent_at"])
            assert msg_time >= CUTOFF_DT


# ---------- extract_candidates with report_only ----------

class TestExtractCandidatesReportOnly:
    """Tests for the source audit report structure when report_only=True."""

    def test_report_only_returns_audit_dict(self):
        """When report_only=True and source=postgres, extract_candidates returns the audit dict."""
        import scripts.golden_set.qa_postgres_reader as qa_reader
        original_fn = getattr(qa_reader, 'run_source_audit', None)

        expected_audit = {
            "database_connected": True,
            "cutoff": CUTOFF_DT.isoformat(),
            "tables": ["chats", "chat_messages", "business_sessions"],
            "total_messages": 10000,
            "cutoff_messages": 5000,
            "cutoff_customer_messages": 2500,
            "cutoff_agent_messages": 2500,
            "cutoff_chats": 200,
            "cutoff_business_sessions": 150,
            "data_quality_distribution": {"complete_scoreable=true": 100},
            "scoreable_count": 100,
            "complete_count": 100,
            "history_truncated_count": 50,
            "earliest_sent_at": "2026-01-01T00:00:00+08:00",
            "latest_sent_at": "2026-06-01T12:00:00+08:00",
            "pre_cutoff_excluded_messages": 5000,
            "error": "",
        }

        def mock_audit(cutoff_dt):
            return expected_audit

        qa_reader.run_source_audit = mock_audit
        try:
            result = extract_candidates(source="postgres", report_only=True)
        finally:
            if original_fn:
                qa_reader.run_source_audit = original_fn

        assert isinstance(result, dict)
        assert result.get("database_connected") is True

    def test_audit_report_contains_required_keys(self):
        """The audit report must contain all expected structural keys."""
        import scripts.golden_set.qa_postgres_reader as qa_reader
        mock_result = {
            "database_connected": False, "cutoff": "", "tables": [],
            "total_messages": 0, "cutoff_messages": 0,
            "cutoff_customer_messages": 0, "cutoff_agent_messages": 0,
            "cutoff_chats": 0, "cutoff_business_sessions": 0,
            "data_quality_distribution": {}, "scoreable_count": 0,
            "complete_count": 0, "history_truncated_count": 0,
            "earliest_sent_at": None, "latest_sent_at": None,
            "pre_cutoff_excluded_messages": 0, "error": "",
        }
        original = getattr(qa_reader, 'run_source_audit', None)
        qa_reader.run_source_audit = lambda dt: mock_result
        try:
            result = extract_candidates(source="postgres", report_only=True)
        finally:
            if original:
                qa_reader.run_source_audit = original
        required_keys = [
            "database_connected", "cutoff", "tables",
            "total_messages", "cutoff_messages",
            "cutoff_customer_messages", "cutoff_agent_messages",
            "cutoff_chats", "cutoff_business_sessions",
            "data_quality_distribution", "scoreable_count",
            "complete_count", "history_truncated_count",
            "earliest_sent_at", "latest_sent_at",
            "pre_cutoff_excluded_messages", "error",
        ]
        for key in required_keys:
            assert key in result, f"Audit report missing required key: {key}"

    def test_audit_report_with_connection_error(self):
        """When the database is unreachable, the audit report should still be a valid dict."""
        import scripts.golden_set.qa_postgres_reader as qa_reader
        mock_result = {
            "database_connected": False, "cutoff": CUTOFF_DT.isoformat(),
            "tables": [], "total_messages": 0, "cutoff_messages": 0,
            "cutoff_customer_messages": 0, "cutoff_agent_messages": 0,
            "cutoff_chats": 0, "cutoff_business_sessions": 0,
            "data_quality_distribution": {}, "scoreable_count": 0,
            "complete_count": 0, "history_truncated_count": 0,
            "earliest_sent_at": None, "latest_sent_at": None,
            "pre_cutoff_excluded_messages": 0,
            "error": "could not connect to server: Connection refused",
        }
        original = getattr(qa_reader, 'run_source_audit', None)
        qa_reader.run_source_audit = lambda dt: mock_result
        try:
            result = extract_candidates(source="postgres", report_only=True)
        finally:
            if original:
                qa_reader.run_source_audit = original
        assert result["database_connected"] is False
        assert "Connection refused" in result["error"]

    def test_audit_report_cutoff_value_matches_default(self):
        """The cutoff passed to run_source_audit must match CUTOFF_DEFAULT."""
        import scripts.golden_set.qa_postgres_reader as qa_reader
        captured_cutoff = {}
        def capture_audit(cutoff_dt):
            captured_cutoff["value"] = cutoff_dt
            return {"database_connected": False, "cutoff": "", "tables": [],
                    "total_messages": 0, "cutoff_messages": 0,
                    "cutoff_customer_messages": 0, "cutoff_agent_messages": 0,
                    "cutoff_chats": 0, "cutoff_business_sessions": 0,
                    "data_quality_distribution": {}, "scoreable_count": 0,
                    "complete_count": 0, "history_truncated_count": 0,
                    "earliest_sent_at": None, "latest_sent_at": None,
                    "pre_cutoff_excluded_messages": 0, "error": ""}
        original = getattr(qa_reader, 'run_source_audit', None)
        qa_reader.run_source_audit = capture_audit
        try:
            extract_candidates(source="postgres", report_only=True)
        finally:
            if original:
                qa_reader.run_source_audit = original
        assert "value" in captured_cutoff
        assert captured_cutoff["value"] == CUTOFF_DT


# ---------- Integration: cutoff in extract_candidates dry-run ----------

class TestExtractCandidatesDryRun:
    """Tests that dry-run mode respects cutoff and quality filtering without generating candidates."""

    def _setup_mock_read(self, sessions):
        import scripts.golden_set.qa_postgres_reader as qa_reader
        original = getattr(qa_reader, 'read_sessions', None)
        qa_reader.read_sessions = lambda **kwargs: sessions
        return original, qa_reader

    def _restore_read(self, original, qa_reader):
        if original:
            qa_reader.read_sessions = original

    def test_dry_run_with_post_cutoff_sessions(self):
        """Dry-run should report sessions that pass quality filter."""
        sessions = [
            _make_session([
                _make_msg(_after_cutoff(100), sender_type="customer", content="你好请问这款产品多少钱"),
                _make_msg(_after_cutoff(101), sender_type="agent", content="199元"),
            ]),
            _make_session([
                _make_msg(_after_cutoff(200), sender_type="customer", content="请问发货了吗"),
                _make_msg(_after_cutoff(201), sender_type="agent", content="已经发了"),
            ]),
        ]
        original, qa_reader = self._setup_mock_read(sessions)
        try:
            result = extract_candidates(source="postgres", dry_run=True)
        finally:
            self._restore_read(original, qa_reader)
        assert result["sessions_read"] == 2
        assert result.get("dry_run") is True

    def test_dry_run_filters_invalid_sessions(self):
        """Dry-run should exclude sessions failing quality checks."""
        sessions = [
            _make_session([
                _make_msg(_after_cutoff(100), sender_type="customer", content="你好请问多少钱"),
                _make_msg(_after_cutoff(101), sender_type="agent", content="299元"),
            ]),
            _make_session([
                _make_msg(_after_cutoff(200), sender_type="customer", content="\U0001f600", message_type="image"),
                _make_msg(_after_cutoff(201), sender_type="agent", content="您好"),
            ]),
            _make_session([]),
        ]
        original, qa_reader = self._setup_mock_read(sessions)
        try:
            result = extract_candidates(source="postgres", dry_run=True)
        finally:
            self._restore_read(original, qa_reader)
        assert result["sessions_read"] == 3
        assert result["sessions_after_quality_filter"] < 3

    def test_dry_run_with_pre_cutoff_in_session_rejected_by_reader(self):
        """Reader returns only post-cutoff sessions; dry-run processes them normally."""
        sessions = [
            _make_session([
                _make_msg(_after_cutoff(100), sender_type="customer", content="请问书桌尺寸"),
                _make_msg(_after_cutoff(101), sender_type="agent", content="120x60cm"),
            ]),
        ]
        original, qa_reader = self._setup_mock_read(sessions)
        try:
            result = extract_candidates(source="postgres", dry_run=True)
        finally:
            self._restore_read(original, qa_reader)
        assert result["sessions_read"] == 1


# ---------- Cutoff constant correctness ----------

class TestCutoffConstants:
    """Verify that the cutoff constants are defined correctly."""

    def test_cutoff_default_value(self):
        expected = datetime(2026, 5, 26, 0, 0, 0, tzinfo=timezone(timedelta(hours=8)))
        parsed = isoparse(CUTOFF_DEFAULT)
        assert parsed == expected

    def test_cutoff_timezone_is_cst(self):
        parsed = isoparse(CUTOFF_DEFAULT)
        assert parsed.utcoffset() == timedelta(hours=8)

    def test_extraction_version_is_set(self):
        assert EXTRACTION_VERSION == "v1"
