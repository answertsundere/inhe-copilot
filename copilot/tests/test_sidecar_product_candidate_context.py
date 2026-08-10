from __future__ import annotations


def _review_only_response() -> dict:
    return {
        "suggested_reply": "candidate reply",
        "intent": "product_question",
        "risk_level": "low",
        "requires_human_review": True,
        "can_send": False,
        "evidence_debug": {},
        "execution_debug": {},
        "trace_steps": [],
    }


def test_copilot_context_promotes_sidecar_product_candidate(monkeypatch):
    from app.main import create_app
    import app.api.copilot_routes as routes
    from app.services.analysis_pipeline_service import AnalysisPipelineService

    calls = {}
    product = "candidate product title 1046558780232"

    def fake_run(_self, analysis_request):
        calls["request"] = analysis_request
        return _review_only_response()

    monkeypatch.setattr(routes, "get_reply_service", lambda: object())
    monkeypatch.setattr(AnalysisPipelineService, "run", fake_run)
    app = create_app()
    app.config["TESTING"] = True

    with app.test_client() as client:
        response = client.post("/api/copilot/context", json={
            "window_title": "support sidecar",
            "customer_message": "how do I enable automatic sensing",
            "conversation_history": [
                {"role": "customer", "text": "this sensing light"},
                {"role": "customer", "text": "why is it manual only"},
                {"role": "customer", "text": "how do I enable automatic sensing"},
            ],
            "product_candidates": [
                {
                    "value": product,
                    "source": "uia_sidebar",
                    "confidence": 0.9,
                    "verified": True,
                }
            ],
        })

    assert response.status_code == 200
    data = response.get_json()
    request = calls["request"]
    assert data["context_echo"]["product_name"] == product
    assert data["evidence_debug"]["copilot_context"]["product_name"] == product
    assert data["evidence_debug"]["product_candidates"][0]["value"] == product
    assert request.product_name == product
    assert request.product_candidates[0]["value"] == product
    assert request.customer_message == "how do I enable automatic sensing"
    assert product not in request.customer_message
    assert [turn["content"] for turn in request.copilot_context["conversation_history"]] == [
        "this sensing light",
        "why is it manual only",
    ]


def test_copilot_context_promotes_platform_trade_candidate(monkeypatch):
    from app.main import create_app
    import app.api.copilot_routes as routes
    from app.services.analysis_pipeline_service import AnalysisPipelineService

    calls = {}

    def fake_run(_self, analysis_request):
        calls["request"] = analysis_request
        return _review_only_response()

    monkeypatch.setattr(routes, "get_reply_service", lambda: object())
    monkeypatch.setattr(AnalysisPipelineService, "run", fake_run)
    app = create_app()
    app.config["TESTING"] = True

    with app.test_client() as client:
        response = client.post("/api/copilot/context", json={
            "customer_message": "when will my delivery arrive",
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

    assert response.status_code == 200
    data = response.get_json()
    request = calls["request"]
    assert data["context_echo"]["platform_trade_id"] == "5118207015382036103"
    assert data["context_echo"]["identifier_type"] == "platform_trade_id"
    assert data["evidence_debug"]["copilot_context"]["platform_trade_id"] == (
        "5118207015382036103"
    )
    assert request.copilot_context["platform_trade_id"] == "5118207015382036103"
