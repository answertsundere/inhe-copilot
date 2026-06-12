"""
Tests for simulation API endpoints.
"""

import json
import os
import unittest

import app.tracing.repository as _trace_repo


class TestSimulationAPI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Reset trace DB for tests
        _trace_repo._engine = None
        _trace_repo._SessionLocal = None
        os.environ["COPILOT_TRACE_DB"] = os.path.join(
            tempfile.gettempdir(), "test_sim_api_traces.db"
        )
        from app.main import create_app
        cls.app = create_app()
        cls.app.config["TESTING"] = True

    def test_list_runs_empty(self):
        with self.app.test_client() as c:
            r = c.get("/api/simulation/runs")
            self.assertEqual(r.status_code, 200)
            data = r.get_json()
            self.assertIn("runs", data)
            self.assertIn("total", data)

    def test_get_nonexistent_run(self):
        with self.app.test_client() as c:
            r = c.get("/api/simulation/runs/nonexistent_run")
            self.assertEqual(r.status_code, 404)
            data = r.get_json()
            self.assertIn("error", data)

    def test_golden_candidates_list(self):
        with self.app.test_client() as c:
            r = c.get("/api/simulation/golden-candidates")
            self.assertEqual(r.status_code, 200)
            data = r.get_json()
            self.assertIn("candidates", data)
            self.assertIn("total", data)

    def test_simulation_page_loads(self):
        with self.app.test_client() as c:
            r = c.get("/simulation-runs")
            self.assertEqual(r.status_code, 200)

    def test_runs_api_returns_json(self):
        with self.app.test_client() as c:
            r = c.get("/api/simulation/runs")
            self.assertEqual(r.content_type, "application/json")


import tempfile


if __name__ == "__main__":
    unittest.main()
