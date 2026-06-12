from __future__ import annotations

import json
from types import SimpleNamespace

import app.api.copilot_routes as routes
from app.main import create_app
from scripts.sidecar.context_parser import (
    build_extract_status,
    is_customer_message_candidate,
    is_system_text,
)


class TestContextParserSystemFilter:
    def test_system_text_filter_import(self):
        assert is_system_text("1天内暂无导入或导出的文件") is True

    def test_system_text_filter_consult(self):
        assert is_system_text("咨询宝贝") is True

    def test_system_text_filter_module(self):
        assert is_system_text("模块可以手动展开收起") is True

    def test_normal_text_not_system(self):
        assert is_system_text("我的快递什么时候到") is False

    def test_customer_message_candidate_normal(self):
        assert is_customer_message_candidate("我的快递什么时候到") is True

    def test_customer_message_rejects_agent_prefix(self):
        assert is_customer_message_candidate("客服: 好的") is False

    def test_customer_message_rejects_system(self):
        assert is_customer_message_candidate("咨询宝贝") is False


class TestBuildExtractStatus:
    def test_ok_when_customer_message(self):
        result = build_extract_status("我的快递呢", has_uia_sidebar=True, has_vision=True)
        assert result["extract_status"] == "ok"
        assert result["should_call_copilot_context"] is True

    def test_no_customer_message(self):
        result = build_extract_status("", has_uia_sidebar=True, has_vision=False)
        assert result["extract_status"] == "no_customer_message"
        assert result["needs_manual_confirm"] is True
        assert result["should_call_copilot_context"] is False

    def test_vision_only_no_customer(self):
        result = build_extract_status("", has_uia_sidebar=True, has_vision=True)
        assert result["extract_status"] == "vision_only_no_customer_message"
        assert result["needs_manual_confirm"] is True


class TestBackendCandidatesSupport:
    def _make_fake_reply_service(self, calls):
        class FakeReplyService:
            def analyze(self, message, order_id="", tracking_no="", conversation_id="default", **kwargs):
                calls["message"] = message
                calls["order_id"] = order_id
                calls["tracking_no"] = tracking_no
                calls["conversation_id"] = conversation_id
                return SimpleNamespace(to_dict=lambda: {
                    "suggested_reply": "亲，已收到，我帮您核实。",
                    "intent": "logistics_eta",
                    "risk_level": "low",
                    "requires_human_review": False,
                    "evidence_debug": {},
                    "trace_steps": [],
                })
        return FakeReplyService()

    def test_candidates_accepted_by_backend(self):
        calls = {}
        fake_service = self._make_fake_reply_service(calls)
        routes.get_reply_service = lambda: fake_service

        app = create_app()
        app.config["TESTING"] = True
        with app.test_client() as client:
            resp = client.post("/api/copilot/context", json={
                "source": "sidecar_mixed",
                "customer_message": "我的快递什么时候到",
                "order_candidates": [
                    {"value": "5116887975001001001", "source": "uia_sidebar", "confidence": 0.99, "verified": False}
                ],
                "tracking_candidates": [
                    {"value": "SF5196840812297", "carrier": "顺丰速运", "source": "uia_sidebar", "confidence": 0.99, "verified": False}
                ],
            })

        assert resp.status_code == 200
        data = resp.get_json()
        assert data["ok"] is True

    def test_unverified_candidates_passed_to_pipeline(self):
        """Unverified candidates are passed to the pipeline for JST verification."""
        calls = {}
        fake_service = self._make_fake_reply_service(calls)
        routes.get_reply_service = lambda: fake_service

        app = create_app()
        app.config["TESTING"] = True
        with app.test_client() as client:
            resp = client.post("/api/copilot/context", json={
                "source": "sidecar_mixed",
                "customer_message": "查一下快递",
                "tracking_candidates": [
                    {"value": "SF5196840812297", "source": "vision", "confidence": 0.9, "verified": False}
                ],
            })

        assert resp.status_code == 200
        # Unverified candidate is passed to pipeline for JST verification
        assert calls["tracking_no"] == "SF5196840812297"

    def test_verified_candidates_used(self):
        calls = {}
        fake_service = self._make_fake_reply_service(calls)
        routes.get_reply_service = lambda: fake_service

        app = create_app()
        app.config["TESTING"] = True
        with app.test_client() as client:
            resp = client.post("/api/copilot/context", json={
                "source": "sidecar_mixed",
                "customer_message": "查一下快递",
                "tracking_candidates": [
                    {"value": "SF5196840812297", "source": "uia_sidebar", "confidence": 0.99, "verified": True}
                ],
            })

        assert resp.status_code == 200
        assert calls["tracking_no"] == "SF5196840812297"

    def test_evidence_debug_includes_candidates(self):
        calls = {}
        fake_service = self._make_fake_reply_service(calls)
        routes.get_reply_service = lambda: fake_service

        app = create_app()
        app.config["TESTING"] = True
        with app.test_client() as client:
            resp = client.post("/api/copilot/context", json={
                "source": "sidecar_mixed",
                "customer_message": "查快递",
                "tracking_candidates": [
                    {"value": "SF5196840812297", "source": "uia_sidebar", "confidence": 0.99, "verified": False}
                ],
            })

        data = resp.get_json()
        assert data["ok"] is True
        debug = data.get("evidence_debug", {})
        assert "tracking_candidates" in debug
