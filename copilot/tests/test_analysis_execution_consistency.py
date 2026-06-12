"""
Tests for AnalysisExecutionService consistency across API endpoints.

Validates that /api/analyze and /api/copilot/context produce
consistent core results when given the same input.
"""

from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


@pytest.fixture
def app():
    from app.main import create_app
    app = create_app()
    app.config["TESTING"] = True
    return app


@pytest.fixture
def client(app):
    return app.test_client()


class TestAnalysisExecutionServiceConsistency:
    """Both API paths must produce consistent core results."""

    def test_analyze_route_uses_execute_analysis(self, client):
        """POST /api/analyze delegates to execute_analysis (has trace_id)."""
        resp = client.post("/api/analyze", json={"message": "你好"})
        assert resp.status_code == 200
        data = resp.get_json()
        assert "request_id" in data
        assert "message_id" in data
        assert "trace_id" in data

    def test_copilot_context_uses_execute_analysis(self, client):
        """POST /api/copilot/context delegates to execute_analysis (has trace_id)."""
        resp = client.post(
            "/api/copilot/context",
            json={"source": "test", "customer_message": "你好"},
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["ok"] is True
        assert "request_id" in data
        assert "message_id" in data
        assert "trace_id" in data

    def test_both_routes_produce_consistent_intent(self, client):
        """Same input via both routes should get the same intent classification."""
        message = "你们这个爬行垫什么时候能发货"

        resp_analyze = client.post("/api/analyze", json={"message": message})
        resp_copilot = client.post(
            "/api/copilot/context",
            json={"source": "test", "customer_message": message},
        )

        data_a = resp_analyze.get_json()
        data_c = resp_copilot.get_json()

        # Both should succeed
        assert resp_analyze.status_code == 200
        assert resp_copilot.status_code == 200

        # Core decision fields should match
        assert data_a.get("intent") == data_c.get("intent")
        assert data_a.get("risk_level") == data_c.get("risk_level")

    def test_both_routes_have_trace_lifecycle(self, client):
        """Both routes should create traces in the tracing system."""
        message = "我的订单怎么还没到"

        resp_analyze = client.post("/api/analyze", json={"message": message})
        data_a = resp_analyze.get_json()
        assert data_a.get("trace_id"), "analyze route should create a trace"

        resp_copilot = client.post(
            "/api/copilot/context",
            json={"source": "test", "customer_message": message},
        )
        data_c = resp_copilot.get_json()
        assert data_c.get("trace_id"), "copilot context route should create a trace"

    def test_both_routes_save_file_snapshot(self, client):
        """Both routes should save file-based snapshot for feedback lookups."""
        message = "退款怎么还没到账"

        resp = client.post(
            "/api/copilot/context",
            json={"source": "test", "customer_message": message},
        )
        data = resp.get_json()
        assert data["ok"] is True
        message_id = data["message_id"]
        assert message_id, "should have message_id for snapshot lookup"

        from app.services.analysis_snapshot import get_snapshot
        snapshot = get_snapshot(message_id)
        assert snapshot is not None, "file-based snapshot should exist"
        assert snapshot["customer_message"] == message

    def test_copilot_response_preserves_backward_compat(self, client):
        """Copilot response must include all legacy fields."""
        resp = client.post(
            "/api/copilot/context",
            json={"source": "test", "customer_message": "你好"},
        )
        data = resp.get_json()

        # Legacy fields
        assert "ok" in data
        assert "suggested_reply" in data
        assert "intent" in data
        assert "risk_level" in data
        assert "requires_human_review" in data
        assert "need_human_review" in data
        assert "used_knowledge_entry_ids" in data
        assert "used_knowledge_titles" in data
        assert "used_fact_tools" in data
        assert "evidence_debug" in data
        assert "execution_debug" in data
        assert "trace_steps" in data
        assert "context_echo" in data

        # Both human_review fields must have same value
        assert data["requires_human_review"] == data["need_human_review"]

    def test_copilot_response_includes_trace_id(self, client):
        """Copilot response must include trace_id from unified service."""
        resp = client.post(
            "/api/copilot/context",
            json={"source": "test", "customer_message": "你好"},
        )
        data = resp.get_json()
        assert "trace_id" in data
        assert data["trace_id"], "trace_id should not be empty"

    def test_analyze_response_has_execution_service_fields(self, client):
        """Analyze response should have fields from execute_analysis."""
        resp = client.post("/api/analyze", json={"message": "你好"})
        data = resp.get_json()
        assert "request_id" in data
        assert "message_id" in data
        assert "trace_id" in data
        assert "trace_summary" in data
