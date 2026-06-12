from __future__ import annotations

from types import SimpleNamespace


def test_copilot_context_promotes_sidecar_product_candidate(monkeypatch):
    from app.main import create_app
    import app.api.copilot_routes as routes

    calls = {}
    product = "ID 1046558780232 英禾喂养多功能收纳柜玩具柜"

    class FakeReplyService:
        def analyze(self, message, order_id="", tracking_no="", conversation_id="default", **kwargs):
            calls["message"] = message
            calls["product_name"] = kwargs.get("product_name", "")
            calls["product_candidates"] = kwargs.get("product_candidates", [])
            calls["copilot_context"] = kwargs.get("copilot_context", {})
            return SimpleNamespace(to_dict=lambda: {
                "suggested_reply": "ok",
                "intent": "product_question",
                "risk_level": "low",
                "requires_human_review": False,
                "evidence_debug": {},
                "trace_steps": [],
            })

    monkeypatch.setattr(routes, "get_reply_service", lambda: FakeReplyService())
    app = create_app()
    app.config["TESTING"] = True

    with app.test_client() as client:
        resp = client.post("/api/copilot/context", json={
            "window_title": "千牛接待",
            "customer_message": "我没找到，怎么让他自动感应",
            "conversation_history": [
                {"role": "customer", "text": "这个感应灯"},
                {"role": "customer", "text": "为什么只能手动摁呢"},
                {"role": "customer", "text": "我没找到，怎么让他自动感应"},
            ],
            "product_candidates": [
                {"value": product, "source": "uia_sidebar", "confidence": 0.9, "verified": True}
            ],
        })

    assert resp.status_code == 200
    data = resp.get_json()
    assert data["context_echo"]["product_name"] == product
    assert data["evidence_debug"]["copilot_context"]["product_name"] == product
    assert data["evidence_debug"]["product_candidates"][0]["value"] == product
    assert calls["product_name"] == product
    assert calls["product_candidates"][0]["value"] == product
    assert product in calls["message"]


def test_copilot_context_promotes_platform_trade_candidate(monkeypatch):
    from app.main import create_app
    import app.api.copilot_routes as routes

    calls = {}

    class FakeReplyService:
        def analyze(self, message, order_id="", tracking_no="", conversation_id="default", **kwargs):
            calls["message"] = message
            calls["order_id"] = order_id
            calls["copilot_context"] = kwargs.get("copilot_context", {})
            return SimpleNamespace(to_dict=lambda: {
                "suggested_reply": "ok",
                "intent": "logistics_eta",
                "risk_level": "low",
                "requires_human_review": False,
                "evidence_debug": {},
                "trace_steps": [],
            })

    monkeypatch.setattr(routes, "get_reply_service", lambda: FakeReplyService())
    app = create_app()
    app.config["TESTING"] = True

    with app.test_client() as client:
        resp = client.post("/api/copilot/context", json={
            "customer_message": "我的快递什么时候到",
            "order_candidates": [
                {
                    "value": "5118207015382036103",
                    "type": "platform_trade_id_candidate",
                    "source": "uia_sidebar",
                    "confidence": 0.95,
                    "verified": True,
                }
            ],
        })

    assert resp.status_code == 200
    data = resp.get_json()
    assert data["context_echo"]["platform_trade_id"] == "5118207015382036103"
    assert data["context_echo"]["identifier_type"] == "platform_trade_id"
    assert data["evidence_debug"]["copilot_context"]["platform_trade_id"] == "5118207015382036103"
    assert calls["copilot_context"]["platform_trade_id"] == "5118207015382036103"
