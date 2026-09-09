from __future__ import annotations

from types import SimpleNamespace

from app.services.sidecar_context_service import (
    build_sidecar_context,
    extract_latest_customer_message,
    make_conversation_id,
)


def test_extract_latest_customer_message_prefers_customer_prefix():
    chat_text = """
客服: 您好
买家: 5118207015382036103我的快递大概什么时候到
客服: 我帮您查一下
客户: SF0229477422177 到哪了
"""
    assert extract_latest_customer_message(chat_text) == "SF0229477422177 到哪了"


def test_build_sidecar_context_extracts_platform_trade_id():
    context = build_sidecar_context({
        "window_title": "千牛接待 - 订单咨询",
        "chat_text": "买家: 5118207015382036103我的快递大概什么时候到",
    })
    assert context["customer_message"] == "5118207015382036103我的快递大概什么时候到"
    assert context["platform_trade_id"] == "5118207015382036103"
    assert context["identifier_type"] == "platform_trade_id"
    assert context["conversation_id"].startswith("qianniu-")


def test_build_sidecar_context_marks_untyped_explicit_order_as_unknown_reference():
    context = build_sidecar_context({
        "source": "manual_sidebar",
        "customer_message": "请帮我看一下订单进度",
        "order_id": "9876543210987654321",
    })

    assert context["order_id"] == "9876543210987654321"
    assert context["order_identifier_type"] == "unknown_identifier"
    assert context["order_reference_source"] == "explicit_request"


def test_build_sidecar_context_preserves_structured_shop_identity_without_promoting_it_to_evidence():
    context = build_sidecar_context({
        "source": "manual_sidebar",
        "customer_message": "请帮我看一下订单进度",
        "order_id": "9876543210987654321",
        "shop_name": "测试店铺",
        "shop_id": "shop-007",
    })

    assert context["shop_name"] == "测试店铺"
    assert context["shop_id"] == "shop-007"
    candidate_values = [
        str(candidate.get("value") or "")
        for group in ("product_candidates", "order_candidates")
        for candidate in context.get(group, [])
        if isinstance(candidate, dict)
    ]
    assert "测试店铺" not in candidate_values
    assert "shop-007" not in candidate_values


def test_make_conversation_id_is_stable():
    assert make_conversation_id("千牛 - A", "buyer1") == make_conversation_id("千牛 - A", "buyer1")


def test_copilot_context_endpoint_calls_reply_service(monkeypatch):
    from app.main import create_app
    import app.api.copilot_routes as routes

    calls = {}

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

    monkeypatch.setattr(routes, "get_reply_service", lambda: FakeReplyService())
    app = create_app()
    app.config["TESTING"] = True

    with app.test_client() as client:
        resp = client.post("/api/copilot/context", json={
            "window_title": "千牛接待",
            "chat_text": "买家: 5118207015382036103我的快递大概什么时候到",
        })

    assert resp.status_code == 200
    data = resp.get_json()
    assert data["ok"] is True
    assert data["suggested_reply"]
    assert calls["message"] == "5118207015382036103我的快递大概什么时候到"
    assert calls["order_id"] == ""
    assert calls["tracking_no"] == ""
    assert calls["conversation_id"].startswith("qianniu-")


def test_copilot_context_keeps_history_structured_and_current_message_once(monkeypatch):
    from app.main import create_app
    import app.api.copilot_routes as routes

    calls = {}

    class FakeReplyService:
        def analyze(self, message, order_id="", tracking_no="", conversation_id="default", **kwargs):
            calls["message"] = message
            return SimpleNamespace(to_dict=lambda: {
                "suggested_reply": "亲，咨询有礼这边我帮您确认。",
                "intent": "general",
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
                {"role": "customer", "text": "为什么只能手动提现呢"},
                {"role": "agent", "text": "拍下这边看下"},
                {"role": "customer", "text": "我没找到，怎么让他自动感应"},
            ],
        })

    assert resp.status_code == 200
    assert calls["message"] == "我没找到，怎么让他自动感应"


def test_sidecar_marks_online_bad_history_degraded_without_silently_erasing_reason():
    context = build_sidecar_context({
        "customer_message": "当前问题",
        "conversation_history": "buyer: legacy text",
    })

    assert context["conversation_history"] == []
    assert context["conversation_context_contract"]["status"] == "degraded"
    assert context["conversation_context_contract"]["reason"] == "conversation_history_legacy_nonlist"


def test_sidecar_evaluation_history_fails_closed_before_analysis(monkeypatch):
    from app.main import create_app
    import app.api.copilot_routes as routes

    monkeypatch.setattr(routes, "get_reply_service", lambda: (_ for _ in ()).throw(AssertionError("must not run")))
    app = create_app()
    app.config["TESTING"] = True

    with app.test_client() as client:
        response = client.post("/api/copilot/context", json={
            "customer_message": "当前问题",
            "evaluation_context_contract": "strict",
            "conversation_history": "buyer: malformed",
        })

    assert response.status_code == 422
    assert response.get_json()["error_reason"] == "conversation_history_expected_list"


def test_known_evaluation_source_fails_closed_without_explicit_contract_flag(monkeypatch):
    from app.main import create_app
    import app.api.copilot_routes as routes

    monkeypatch.setattr(routes, "get_reply_service", lambda: (_ for _ in ()).throw(AssertionError("must not run")))
    app = create_app()
    app.config["TESTING"] = True

    with app.test_client() as client:
        response = client.post("/api/copilot/context", json={
            "source": "tier_d_long_conversation_simulation",
            "customer_message": "当前问题",
            "conversation_history": "buyer: malformed",
        })

    assert response.status_code == 422
    assert response.get_json()["error_reason"] == "conversation_history_expected_list"
