"""HTTP normalization preserves typed identifiers without inventing titles."""
import pytest
from flask import Flask

from app.api import analyze_routes
from app.services.analysis_pipeline_service import AnalysisPipelineService


@pytest.fixture
def captured_request(monkeypatch):
    captured = []
    monkeypatch.setattr(analyze_routes, "get_services", lambda: object())
    def capture(_self, request):
        captured.append(request)
        return {"can_send": False, "requires_human_review": True}
    monkeypatch.setattr(AnalysisPipelineService, "run", capture)
    app = Flask(__name__)
    app.register_blueprint(analyze_routes.analyze_bp)
    def submit(payload):
        response = app.test_client().post("/api/analyze", json={"message": "What is the material?", **payload})
        assert response.status_code == 200
        assert len(captured) == 1
        return captured[0]
    return submit


@pytest.mark.parametrize("field", ["sku_code", "sku", "sku_id", "internal_sku_code"])
def test_top_level_sku_is_not_a_product_name(captured_request, field):
    request = captured_request({field: "LONG-SKU-CODE-123456789"})
    assert request.product_name == ""
    assert request.copilot_context["sku_code"] == "LONG-SKU-CODE-123456789"
    assert not request.copilot_context.get("platform_product_title")
    assert not request.copilot_context.get("display_product_name")


@pytest.mark.parametrize("kind", ["sku_code", "sku_id", "i_id", "product_id", "platform_product_id", "order_id", "tracking_no"])
def test_typed_candidate_value_is_not_a_title(captured_request, kind):
    candidate = {"type": kind, "value": "IDENTIFIER-WITH-LONG-VALUE"}
    request = captured_request({"product_candidates": [candidate]})
    assert request.product_name == ""
    assert request.product_candidates == [candidate]
    assert not request.copilot_context.get("platform_product_title")


@pytest.mark.parametrize("candidate", [
    {"type": "product_name", "value": "Current verified product name"},
    {"type": "product_title", "value": "Current verified product name"},
    {"value": "Current verified product name"},
    {"type": "sku_code", "value": "SKU-A", "product_name": "Current verified product name"},
])
def test_actual_named_candidate_is_preserved(captured_request, candidate):
    request = captured_request({"product_candidates": [candidate]})
    assert request.product_name == "Current verified product name"


def test_explicit_title_is_not_suppressed_by_sku(captured_request):
    request = captured_request({"sku_code": "SKU-A", "product_name": "Potentially conflicting title"})
    assert request.product_name == "Potentially conflicting title"
    assert request.copilot_context["explicit_product_name"] == "Potentially conflicting title"


def test_nested_sku_stays_typed(captured_request):
    request = captured_request({"copilot_context": {"sku_code": "SKU-B"}})
    assert request.product_name == ""
    assert request.copilot_context["sku_code"] == "SKU-B"
