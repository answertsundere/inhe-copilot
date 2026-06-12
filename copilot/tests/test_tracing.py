"""
Tests for Trace V2 infrastructure: models, context, recorder, repository, decorators.
"""

import json
import os
import tempfile
import threading
import time
import unittest

# Use a temp DB for tests
os.environ["COPILOT_TRACE_DB"] = os.path.join(tempfile.gettempdir(), "test_traces.db")


class TestTraceModels(unittest.TestCase):
    """Test trace models and ID generation."""

    def test_gen_trace_id_prefix(self):
        from app.tracing.models import gen_trace_id
        tid = gen_trace_id()
        self.assertTrue(tid.startswith("tr_"))
        self.assertEqual(len(tid), 15)

    def test_gen_span_id_prefix(self):
        from app.tracing.models import gen_span_id
        sid = gen_span_id()
        self.assertTrue(sid.startswith("sp_"))

    def test_gen_snapshot_id_prefix(self):
        from app.tracing.models import gen_snapshot_id
        snid = gen_snapshot_id()
        self.assertTrue(snid.startswith("snap_"))

    def test_trace_id_unique(self):
        from app.tracing.models import gen_trace_id
        ids = {gen_trace_id() for _ in range(100)}
        self.assertEqual(len(ids), 100)

    def test_utcnow_format(self):
        from app.tracing.models import utcnow
        ts = utcnow()
        self.assertIn("T", ts)
        self.assertTrue(ts.endswith("Z") or "+" in ts or ts.count("-") >= 2)

    def test_trace_run_set_versions(self):
        from app.tracing.models import TraceRun
        run = TraceRun()
        run.set_versions({"app_version": "1.0", "model_name": "qwen"})
        self.assertEqual(run.get_versions()["app_version"], "1.0")

    def test_trace_run_set_outcome(self):
        from app.tracing.models import TraceRun
        run = TraceRun()
        run.set_outcome({"intent": "product_question", "risk_level": "low"})
        self.assertEqual(run.get_outcome()["intent"], "product_question")

    def test_span_set_error(self):
        from app.tracing.models import TraceSpan
        span = TraceSpan()
        span.set_error("ValueError", "E001", "bad input", retryable=True)
        err = json.loads(span.error_json)
        self.assertEqual(err["type"], "ValueError")
        self.assertTrue(err["retryable"])


class TestTraceContext(unittest.TestCase):
    """Test contextvars-based trace context isolation."""

    def test_set_and_get(self):
        from app.tracing.context import set_trace_context, TraceContext
        set_trace_context("tr_test", "req_1", "msg_1", "conv_1", "api", "pre_sale")
        self.assertEqual(TraceContext.trace_id(), "tr_test")
        self.assertEqual(TraceContext.request_id(), "req_1")
        self.assertEqual(TraceContext.message_id(), "msg_1")
        self.assertEqual(TraceContext.source(), "api")

    def test_is_active(self):
        from app.tracing.context import set_trace_context, TraceContext, current_trace_id
        current_trace_id.set("")
        self.assertFalse(TraceContext.is_active())
        set_trace_context("tr_active")
        self.assertTrue(TraceContext.is_active())

    def test_concurrent_isolation(self):
        """Verify contextvars don't leak between threads."""
        from app.tracing.context import set_trace_context, TraceContext
        results = {}

        def worker(name, trace_id):
            set_trace_context(trace_id, request_id=name)
            time.sleep(0.01)
            results[name] = TraceContext.trace_id()

        t1 = threading.Thread(target=worker, args=("t1", "tr_alpha"))
        t2 = threading.Thread(target=worker, args=("t2", "tr_beta"))
        t1.start(); t2.start()
        t1.join(); t2.join()
        self.assertEqual(results["t1"], "tr_alpha")
        self.assertEqual(results["t2"], "tr_beta")


class TestTraceRecorder(unittest.TestCase):
    """Test trace lifecycle: start, span, end, snapshot."""

    @classmethod
    def setUpClass(cls):
        from app.tracing.repository import _get_engine, init_trace_tables
        # Reset engine for test DB
        import app.tracing.repository as repo
        repo._engine = None
        repo._SessionLocal = None
        os.environ["COPILOT_TRACE_DB"] = os.path.join(tempfile.gettempdir(), "test_traces.db")
        init_trace_tables()

    def test_start_and_end_trace(self):
        from app.tracing.recorder import start_trace, end_trace
        from app.tracing.repository import get_trace_run
        tid = start_trace("req_1", "msg_1", "conv_1", source="test")
        self.assertTrue(tid.startswith("tr_"))
        end_trace(tid, status="success", outcome={"intent": "test"})
        run = get_trace_run(tid)
        self.assertIsNotNone(run)
        self.assertEqual(run["status"], "success")
        self.assertEqual(run["outcome"]["intent"], "test")

    def test_span_lifecycle(self):
        from app.tracing.recorder import start_trace, start_span, end_span, end_trace
        from app.tracing.repository import get_spans
        tid = start_trace("req_2", "msg_2", "conv_2")
        sid = start_span("test_node", "graph_node", input_summary={"key": "val"})
        end_span(sid, status="success", output_summary={"result": "ok"})
        end_trace(tid)
        spans = get_spans(tid)
        self.assertTrue(any(s["name"] == "test_node" for s in spans))
        node = next(s for s in spans if s["name"] == "test_node")
        self.assertEqual(node["status"], "success")

    def test_span_error_on_exception(self):
        from app.tracing.recorder import SpanGuard
        from app.tracing.repository import get_session, save_span
        from app.tracing.models import TraceSpan
        # Simulate SpanGuard catching an exception
        guard = SpanGuard("sp_test", "tr_test", "failing_node")
        try:
            with guard:
                raise ValueError("test error")
        except ValueError:
            pass
        # SpanGuard should have ended the span with error status

    def test_trace_failure_does_not_block(self):
        """Trace errors should never block business logic."""
        from app.tracing.recorder import start_span
        # Should not raise even if context is empty
        try:
            sid = start_span("test", "tool")
            # No exception expected
        except Exception:
            self.fail("start_span raised an exception")


class TestTraceRepository(unittest.TestCase):
    """Test SQLite persistence and queries."""

    @classmethod
    def setUpClass(cls):
        import app.tracing.repository as repo
        repo._engine = None
        repo._SessionLocal = None
        os.environ["COPILOT_TRACE_DB"] = os.path.join(tempfile.gettempdir(), "test_traces.db")
        from app.tracing.repository import init_trace_tables
        init_trace_tables()

    def test_save_and_get_trace_run(self):
        from app.tracing.repository import save_trace_run, get_trace_run
        save_trace_run({"trace_id": "tr_repo_test", "request_id": "req_r", "message_id": "msg_r", "conversation_id": "conv_r", "status": "running", "started_at": "2026-01-01T00:00:00.000Z"})
        run = get_trace_run("tr_repo_test")
        self.assertIsNotNone(run)
        self.assertEqual(run["request_id"], "req_r")

    def test_update_trace_run(self):
        from app.tracing.repository import save_trace_run, get_trace_run
        save_trace_run({"trace_id": "tr_update", "request_id": "req_u", "message_id": "msg_u", "conversation_id": "conv_u", "status": "running", "started_at": "2026-01-01T00:00:00.000Z"})
        save_trace_run({"trace_id": "tr_update", "status": "success", "ended_at": "2026-01-01T00:00:01.000Z", "duration_ms": 1000})
        run = get_trace_run("tr_update")
        self.assertEqual(run["status"], "success")
        self.assertEqual(run["duration_ms"], 1000)

    def test_query_traces_pagination(self):
        from app.tracing.repository import query_traces, save_trace_run
        for i in range(5):
            save_trace_run({"trace_id": f"tr_page_{i}", "request_id": f"req_p{i}", "message_id": f"msg_p{i}", "conversation_id": "conv_p", "status": "success", "started_at": "2026-01-01T00:00:00.000Z"})
        result = query_traces(conversation_id="conv_p", page=1, page_size=3)
        self.assertEqual(len(result["items"]), 3)
        self.assertEqual(result["total"], 5)

    def test_query_traces_status_filter(self):
        from app.tracing.repository import query_traces, save_trace_run
        save_trace_run({"trace_id": "tr_err_1", "request_id": "req_e", "message_id": "msg_e", "conversation_id": "conv_e", "status": "error", "started_at": "2026-01-01T00:00:00.000Z"})
        result = query_traces(status="error")
        self.assertTrue(any(t["trace_id"] == "tr_err_1" for t in result["items"]))

    def test_save_span(self):
        from app.tracing.repository import save_span, get_spans
        save_span({"span_id": "sp_repo_test", "trace_id": "tr_repo_test", "span_type": "tool", "name": "test_tool", "status": "success", "started_at": "2026-01-01T00:00:00.000Z", "sequence_no": 1})
        spans = get_spans("tr_repo_test")
        self.assertTrue(any(s["span_id"] == "sp_repo_test" for s in spans))

    def test_get_trace_detail(self):
        from app.tracing.repository import get_trace_detail, save_trace_run, save_span
        save_trace_run({"trace_id": "tr_detail", "request_id": "req_d", "message_id": "msg_d", "conversation_id": "conv_d", "status": "success", "started_at": "2026-01-01T00:00:00.000Z"})
        save_span({"span_id": "sp_detail", "trace_id": "tr_detail", "span_type": "graph_node", "name": "node1", "status": "success", "started_at": "2026-01-01T00:00:00.000Z", "sequence_no": 1})
        detail = get_trace_detail("tr_detail")
        self.assertIsNotNone(detail)
        self.assertEqual(len(detail["spans"]), 1)

    def test_message_id_lookup(self):
        from app.tracing.repository import save_trace_run, get_session
        from app.tracing.models import TraceRun
        save_trace_run({"trace_id": "tr_msg_lookup", "request_id": "req_ml", "message_id": "msg_unique_123", "conversation_id": "conv_ml", "status": "success", "started_at": "2026-01-01T00:00:00.000Z"})
        session = get_session()
        run = session.query(TraceRun).filter_by(message_id="msg_unique_123").first()
        session.close()
        self.assertIsNotNone(run)
        self.assertEqual(run.trace_id, "tr_msg_lookup")


class TestTraceSanitizer(unittest.TestCase):
    """Test sensitive data sanitization."""

    def test_redact_api_key(self):
        from app.tracing.sanitizer import sanitize_dict
        d = {"api_key": "sk-12345", "name": "test"}
        result = sanitize_dict(d)
        self.assertEqual(result["api_key"], "***REDACTED***")
        self.assertEqual(result["name"], "test")

    def test_redact_authorization(self):
        from app.tracing.sanitizer import sanitize_dict
        d = {"authorization": "Bearer token123", "data": "ok"}
        result = sanitize_dict(d)
        self.assertEqual(result["authorization"], "***REDACTED***")

    def test_redact_phone(self):
        from app.tracing.sanitizer import sanitize_text
        text = "客户手机号是13812345678"
        result = sanitize_text(text)
        self.assertNotIn("13812345678", result)
        self.assertIn("138****5678", result)

    def test_redact_id_card(self):
        from app.tracing.sanitizer import sanitize_text
        text = "身份证号110101199001011234"
        result = sanitize_text(text)
        self.assertNotIn("110101199001011234", result)

    def test_truncate_long_text(self):
        from app.tracing.sanitizer import sanitize_text
        text = "x" * 1000
        result = sanitize_text(text, max_len=100)
        self.assertTrue(len(result) < 120)
        self.assertTrue(result.endswith("...[truncated]"))

    def test_nested_redact(self):
        from app.tracing.sanitizer import sanitize_dict
        d = {"config": {"secret": "mysecret", "token": "abc"}, "data": "ok"}
        result = sanitize_dict(d)
        self.assertEqual(result["config"]["secret"], "***REDACTED***")
        self.assertEqual(result["config"]["token"], "***REDACTED***")

    def test_list_truncation(self):
        from app.tracing.sanitizer import sanitize_dict
        d = {"items": list(range(30))}
        result = sanitize_dict(d)
        self.assertEqual(len(result["items"]), 20)


class TestTraceDecorators(unittest.TestCase):
    """Test trace decorators."""

    @classmethod
    def setUpClass(cls):
        import app.tracing.repository as repo
        repo._engine = None
        repo._SessionLocal = None
        os.environ["COPILOT_TRACE_DB"] = os.path.join(tempfile.gettempdir(), "test_traces.db")
        from app.tracing.repository import init_trace_tables
        init_trace_tables()

    def test_trace_node_decorator(self):
        from app.tracing.decorators import trace_node
        from app.tracing.recorder import start_trace, end_trace
        from app.tracing.context import set_trace_context

        tid = start_trace("req_dec", "msg_dec", "conv_dec")

        @trace_node("test_node_fn")
        def my_node(state):
            return {"result": "ok", "intent": state.get("intent", "")}

        result = my_node({"customer_message": "test", "intent": "product_question"})
        self.assertEqual(result["result"], "ok")
        end_trace(tid)

    def test_trace_tool_decorator(self):
        from app.tracing.decorators import trace_tool
        from app.tracing.recorder import start_trace, end_trace

        tid = start_trace("req_tool", "msg_tool", "conv_tool")

        @trace_tool("test_tool_fn")
        def my_tool(inputs, state):
            return {"found": True, "count": 1}

        result = my_tool({"order_id": "123"}, {})
        self.assertTrue(result["found"])
        end_trace(tid)

    def test_trace_decorator_error_handling(self):
        from app.tracing.decorators import trace_node
        from app.tracing.recorder import start_trace, end_trace

        tid = start_trace("req_err", "msg_err", "conv_err")

        @trace_node("failing_node")
        def failing_node(state):
            raise ValueError("intentional error")

        with self.assertRaises(ValueError):
            failing_node({"customer_message": "test"})
        end_trace(tid)

    def test_trace_llm_decorator(self):
        from app.tracing.decorators import trace_llm
        from app.tracing.recorder import start_trace, end_trace

        tid = start_trace("req_llm", "msg_llm", "conv_llm")

        @trace_llm("intent_classifier")
        def llm_fn(prompt, **kwargs):
            return {"text": "intent=product_question", "usage": {"input_tokens": 10, "output_tokens": 5}, "model": "qwen-plus"}

        result = llm_fn("test prompt")
        self.assertIn("intent", result["text"])
        end_trace(tid)


class TestAnalysisSnapshot(unittest.TestCase):
    """Test snapshot persistence."""

    @classmethod
    def setUpClass(cls):
        import app.tracing.repository as repo
        repo._engine = None
        repo._SessionLocal = None
        os.environ["COPILOT_TRACE_DB"] = os.path.join(tempfile.gettempdir(), "test_traces.db")
        from app.tracing.repository import init_trace_tables
        init_trace_tables()

    def test_save_and_get_snapshot(self):
        from app.tracing.repository import save_snapshot, get_snapshot_by_message_id
        msg_id = "msg_snap_test_001"
        save_snapshot({
            "snapshot_id": "snap_test",
            "trace_id": "tr_snap",
            "request_id": "req_snap",
            "message_id": msg_id,
            "conversation_id": "conv_snap",
            "source": "test",
            "scenario": "",
            "customer_message": "围兜防水吗",
            "suggested_reply": "是的，采用防水面料",
            "intent": "product_question",
            "risk_level": "low",
            "need_human_review": 0,
            "execution_debug_json": "{}",
            "evidence_debug_json": "{}",
            "trace_steps_json": "[]",
            "used_knowledge_entry_ids_json": "[]",
            "used_fact_tools_json": "",
        })
        snap = get_snapshot_by_message_id(msg_id)
        self.assertIsNotNone(snap)
        self.assertEqual(snap["intent"], "product_question")
        self.assertFalse(snap["need_human_review"])

    def test_snapshot_update(self):
        from app.tracing.repository import save_snapshot, get_snapshot_by_message_id
        msg_id = "msg_snap_update_002"
        save_snapshot({
            "snapshot_id": "snap_u1",
            "message_id": msg_id,
            "intent": "logistics",
            "risk_level": "low",
            "need_human_review": 0,
        })
        save_snapshot({
            "snapshot_id": "snap_u2",
            "message_id": msg_id,
            "intent": "product_question",
            "risk_level": "high",
            "need_human_review": 1,
        })
        snap = get_snapshot_by_message_id(msg_id)
        self.assertEqual(snap["intent"], "product_question")
        self.assertTrue(snap["need_human_review"])


if __name__ == "__main__":
    unittest.main()
