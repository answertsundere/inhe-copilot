"""
Tests for Trace API endpoints.
"""

import json
import os
import tempfile
import unittest

os.environ["COPILOT_TRACE_DB"] = os.path.join(tempfile.gettempdir(), "test_traces_api.db")


class TestTraceAPIList(unittest.TestCase):
    """Test GET /api/traces endpoint."""

    @classmethod
    def setUpClass(cls):
        import app.tracing.repository as repo
        repo._engine = None
        repo._SessionLocal = None
        from app.tracing.repository import init_trace_tables
        init_trace_tables()

    def _get_app(self):
        from app.main import create_app
        app = create_app()
        app.config["TESTING"] = True
        return app

    def test_list_traces_empty(self):
        app = self._get_app()
        with app.test_client() as c:
            r = c.get("/api/traces")
            self.assertEqual(r.status_code, 200)
            data = r.get_json()
            self.assertIn("items", data)
            self.assertIn("total", data)

    def test_list_traces_pagination(self):
        app = self._get_app()
        with app.test_client() as c:
            r = c.get("/api/traces?page=1&page_size=10")
            self.assertEqual(r.status_code, 200)
            data = r.get_json()
            self.assertLessEqual(data.get("page_size", 10), 100)

    def test_list_traces_page_size_cap(self):
        app = self._get_app()
        with app.test_client() as c:
            r = c.get("/api/traces?page_size=200")
            data = r.get_json()
            self.assertLessEqual(data["page_size"], 100)

    def test_list_traces_status_filter(self):
        app = self._get_app()
        with app.test_client() as c:
            r = c.get("/api/traces?status=error")
            self.assertEqual(r.status_code, 200)

    def test_get_trace_not_found(self):
        app = self._get_app()
        with app.test_client() as c:
            r = c.get("/api/traces/tr_nonexistent")
            self.assertEqual(r.status_code, 404)

    def test_get_trace_spans_not_found(self):
        app = self._get_app()
        with app.test_client() as c:
            r = c.get("/api/traces/tr_none/spans")
            self.assertEqual(r.status_code, 200)
            data = r.get_json()
            self.assertEqual(data["spans"], [])

    def test_message_trace_not_found(self):
        app = self._get_app()
        with app.test_client() as c:
            r = c.get("/api/messages/msg_none/trace")
            self.assertEqual(r.status_code, 404)


class TestTraceAPICreateBadCase(unittest.TestCase):
    """Test POST /api/traces/<id>/create-bad-case."""

    @classmethod
    def setUpClass(cls):
        import app.tracing.repository as repo
        repo._engine = None
        repo._SessionLocal = None
        from app.tracing.repository import init_trace_tables
        init_trace_tables()

    def _get_app(self):
        from app.main import create_app
        app = create_app()
        app.config["TESTING"] = True
        return app

    def test_create_bad_case_trace_not_found(self):
        app = self._get_app()
        with app.test_client() as c:
            r = c.post("/api/traces/tr_none/create-bad-case",
                       json={"reason": "test"})
            self.assertEqual(r.status_code, 404)


if __name__ == "__main__":
    unittest.main()
