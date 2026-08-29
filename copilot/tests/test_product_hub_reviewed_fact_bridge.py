from __future__ import annotations

import json

from app.services.admitted_answer_context_service import AdmittedAnswerContextService


class _Response:
    status = 200

    def __init__(self, payload: dict):
        self._payload = payload

    def read(self, _limit: int = -1) -> bytes:
        return json.dumps(self._payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


def _hub_fact(**overrides):
    value = {
        "id": "fact-001",
        "productCode": "YH-EXACT-01",
        "skuCode": "YH-EXACT-01-SKU-A",
        "type": "size",
        "attr": "overall_dimensions",
        "value": "120 x 60 x 90",
        "unit": "cm",
        "scope": "商品整体",
        "applies": "",
        "source": "manual",
        "sourceDetail": "must not reach the candidate context",
        "status": "confirmed",
        "conflict": False,
        "updatedAt": "2026-08-29T00:00:00Z",
    }
    value.update(overrides)
    return value


def _client_fact(**overrides):
    raw = _hub_fact(**overrides)
    return {
        "id": raw["id"],
        "product_code": raw["productCode"],
        "sku_code": raw["skuCode"],
        "type": raw["type"],
        "attr": raw["attr"],
        "value": raw["value"],
        "unit": raw["unit"],
        "scope": raw["scope"],
        "applies": raw["applies"],
        "source": raw["source"],
        "status": raw["status"],
        "conflict": raw["conflict"],
        "updated_at": raw["updatedAt"],
    }


def test_hub_client_is_disabled_without_explicit_runtime_flag(monkeypatch):
    from app.integrations.product_hub.reviewed_facts_client import ProductHubReviewedFactsClient
    import app.integrations.product_hub.reviewed_facts_client as module

    monkeypatch.delenv("COPILOT_PRODUCT_HUB_REVIEWED_FACTS_ENABLED", raising=False)
    monkeypatch.delenv("COPILOT_PRODUCT_HUB_BASE_URL", raising=False)
    monkeypatch.setattr(module, "urlopen", lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("transport called")))

    result = ProductHubReviewedFactsClient().fetch_confirmed_facts("YH-EXACT-01")

    assert result == {
        "state": "disabled",
        "reason_code": "product_hub_read_disabled",
        "product_code": "YH-EXACT-01",
        "facts": [],
    }


def test_hub_client_requires_exact_returned_product_code_and_drops_source_detail(monkeypatch):
    from app.integrations.product_hub.reviewed_facts_client import ProductHubReviewedFactsClient
    import app.integrations.product_hub.reviewed_facts_client as module

    monkeypatch.setenv("COPILOT_PRODUCT_HUB_REVIEWED_FACTS_ENABLED", "true")
    monkeypatch.setenv("COPILOT_PRODUCT_HUB_BASE_URL", "http://127.0.0.1:8795")
    observed = {}

    def matching_transport(request, *, timeout):
        observed["url"] = request.full_url
        observed["timeout"] = timeout
        return _Response({
            "ok": True,
            "productCode": "YH-EXACT-01",
            "facts": [_hub_fact()],
        })

    monkeypatch.setattr(module, "urlopen", matching_transport)
    result = ProductHubReviewedFactsClient().fetch_confirmed_facts("YH-EXACT-01")

    assert observed["url"].endswith("/api/agent/products/YH-EXACT-01/facts?status=confirmed")
    assert 0 < observed["timeout"] <= 5
    assert result["state"] == "ready"
    assert result["product_code"] == "YH-EXACT-01"
    assert result["facts"] == [{
        "id": "fact-001",
        "product_code": "YH-EXACT-01",
        "sku_code": "YH-EXACT-01-SKU-A",
        "type": "size",
        "attr": "overall_dimensions",
        "value": "120 x 60 x 90",
        "unit": "cm",
        "scope": "商品整体",
        "applies": "",
        "source": "manual",
        "status": "confirmed",
        "conflict": False,
        "updated_at": "2026-08-29T00:00:00Z",
    }]

    monkeypatch.setattr(module, "urlopen", lambda *_args, **_kwargs: _Response({
        "ok": True,
        "productCode": "YH-OTHER-01",
        "facts": [_hub_fact(productCode="YH-OTHER-01")],
    }))
    mismatch = ProductHubReviewedFactsClient().fetch_confirmed_facts("YH-EXACT-01")
    assert mismatch["state"] == "invalid_response"
    assert mismatch["reason_code"] == "product_code_mismatch"
    assert mismatch["facts"] == []


def test_hub_adapter_reuses_existing_product_context_and_admission_contract():
    from app.services.product_context_pack_service import _product_hub_facts_for_query

    candidates = _product_hub_facts_for_query(
        {
            "state": "ready",
            "product_code": "YH-EXACT-01",
            "facts": [_client_fact()],
        },
        identity={
            "i_id": "YH-EXACT-01",
            "sku": "YH-EXACT-01-SKU-A",
            "product_identity_resolution": {"status": "resolved"},
        },
        query_fact_type="dimensions",
    )

    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate["source_type"] == "product_facts"
    assert candidate["fact_type"] == "dimensions"
    assert candidate["subject_scope"] == "product"
    assert candidate["product_scope"] == ["YH-EXACT-01"]
    assert candidate["sku_scope"] == ["YH-EXACT-01-SKU-A"]
    assert candidate["metadata"]["product_evidence_protocol"] is True
    assert candidate["metadata"]["verification_status"] == "reviewed"
    assert candidate["metadata"]["source_review_status"] == "confirmed"
    assert "sourceDetail" not in candidate["metadata"]
    assert "must not reach" not in candidate["chunk_text"]

    admitted = AdmittedAnswerContextService().build_for_response(
        {"product_context_pack": {"facts": candidates}},
        product_identity={"i_id": "YH-EXACT-01", "sku_code": "YH-EXACT-01-SKU-A"},
        understanding={"requested_claims": [{"claim_type": "dimensions", "question": "dimensions", "risk_level": "low"}]},
    )
    assert [item["evidence_uid"] for item in admitted["direct_product_facts"]] == ["producthub:fact-001"]


def test_hub_adapter_rejects_nonexact_or_noneligible_rows_before_admission():
    from app.services.product_context_pack_service import _product_hub_facts_for_query

    identity = {
        "i_id": "YH-EXACT-01",
        "sku": "YH-EXACT-01-SKU-A",
        "product_identity_resolution": {"status": "resolved"},
    }
    result = _product_hub_facts_for_query(
        {
            "state": "ready",
            "product_code": "YH-EXACT-01",
            "facts": [
                _client_fact(status="pending"),
                _client_fact(id="fact-conflict", conflict=True),
                _client_fact(id="fact-other-sku", skuCode="YH-EXACT-01-SKU-B"),
                _client_fact(id="fact-packaging", scope="包装"),
                _client_fact(id="fact-unknown-type", type="color"),
            ],
        },
        identity=identity,
        query_fact_type="dimensions",
    )
    assert result == []


def test_hub_loader_never_uses_a_title_or_unresolved_identity(monkeypatch):
    from app.services.product_context_pack_service import _load_product_hub_reviewed_facts
    from app.integrations.product_hub.reviewed_facts_client import ProductHubReviewedFactsClient

    called = []
    monkeypatch.setattr(
        ProductHubReviewedFactsClient,
        "fetch_confirmed_facts",
        lambda _self, code: called.append(code) or {"state": "ready", "reason_code": "", "product_code": code, "facts": []},
    )

    unresolved = _load_product_hub_reviewed_facts({
        "i_id": "YH-EXACT-01",
        "product_name": "untrusted title",
        "product_identity_resolution": {"status": "ambiguous"},
    })
    assert unresolved["state"] == "not_attempted"
    assert unresolved["reason_code"] == "product_identity_not_resolved"
    assert called == []

    resolved = _load_product_hub_reviewed_facts({
        "i_id": "YH-EXACT-01",
        "product_identity_resolution": {"status": "resolved"},
    })
    assert resolved["state"] == "ready"
    assert called == ["YH-EXACT-01"]
