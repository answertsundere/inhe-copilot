from __future__ import annotations

import json

import pytest

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
        "attr": "\u5c3a\u5bf8",
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


def _answer_context_payload(sku="SKU-Test/A"):
    return {
        "ok": True,
        "contractVersion": "answer-context-v1",
        "readOnly": True,
        "identity": {"skuCode": sku, "productCode": "PRODUCT-A", "productStatus": "active", "skuStatus": "active"},
        "directFacts": [_hub_fact(productCode="PRODUCT-A", skuCode=sku, skuId="record-a", evidenceRole="direct_product_fact")],
        "mediaCandidates": [{
            "assetId": "image-a", "productCode": "PRODUCT-A", "skuCode": "", "assetType": "detail",
            "status": "approved", "evidenceRole": "media_reference", "usage": "review_only_not_factual",
            "previewUrl": "/api/v2/media/preview/image-a", "labelNote": "private source note",
        }],
    }


def test_answer_context_shadow_off_has_no_transport(monkeypatch):
    import app.integrations.product_hub.reviewed_facts_client as module

    monkeypatch.delenv("COPILOT_PRODUCT_HUB_ANSWER_CONTEXT_SHADOW_ENABLED", raising=False)
    monkeypatch.setattr(module, "urlopen", lambda *_a, **_kw: pytest.fail("transport called"))
    result = module.ProductHubReviewedFactsClient().fetch_answer_context_for_sku("SKU-Test/A")
    assert result["state"] == "disabled"
    assert result["facts"] == result["assets"] == []


def test_answer_context_uses_one_exact_request_and_existing_safe_projections(monkeypatch):
    import app.integrations.product_hub.reviewed_facts_client as module

    monkeypatch.setenv("COPILOT_PRODUCT_HUB_ANSWER_CONTEXT_SHADOW_ENABLED", "true")
    monkeypatch.setenv("COPILOT_PRODUCT_HUB_BASE_URL", "http://127.0.0.1:8795")
    calls = []

    def transport(request, *, timeout):
        calls.append(request.full_url)
        assert 0 < timeout <= 5
        return _Response(_answer_context_payload())

    monkeypatch.setattr(module, "urlopen", transport)
    result = module.ProductHubReviewedFactsClient().fetch_answer_context_for_sku("SKU-Test/A")
    assert calls == ["http://127.0.0.1:8795/api/agent/answer-context?skuCode=SKU-Test%2FA"]
    assert result["state"] == "ready"
    assert result["resolved_sku_code"] == "SKU-Test/A"
    assert result["facts"][0]["hub_sku_id"] == "record-a"
    assert result["assets"][0]["source_review_status"] == "approved"
    assert "private source note" not in json.dumps(result)
    assert "sourceDetail" not in json.dumps(result)


@pytest.mark.parametrize("section,changes", [
    ("root", {"contractVersion": "unknown"}), ("root", {"readOnly": False}),
    ("root", {"directFacts": {}}), ("root", {"mediaCandidates": None}),
    ("identity", {"skuCode": "OTHER"}), ("identity", {"productCode": ""}),
    ("identity", {"skuStatus": "archived"}), ("identity", {"productStatus": ""}),
    ("fact", {"status": ""}), ("fact", {"status": "pending"}),
    ("fact", {"conflict": True}), ("fact", {"conflict": None}),
    ("fact", {"evidenceRole": "service_action"}), ("fact", {"evidenceRole": "media_reference"}),
    ("fact", {"productCode": "OTHER"}), ("fact", {"skuCode": "OTHER"}),
    ("fact", {"skuCode": ""}), ("fact", {"skuId": None}),
    ("fact", {"applies": "OTHER"}), ("fact", {"id": ""}),
    ("media", {"evidenceRole": "direct_product_fact"}), ("media", {"usage": "auto_send"}),
    ("media", {"productCode": "OTHER"}), ("media", {"skuCode": "OTHER"}),
    ("media", {"status": "pending"}), ("media", {"status": []}),
    ("media", {"assetId": 123}), ("fact", {"id": 123}),
    ("media", {"previewUrl": "https://example.invalid/image"}),
])
def test_answer_context_invalid_contract_fails_closed(monkeypatch, section, changes):
    import app.integrations.product_hub.reviewed_facts_client as module

    monkeypatch.setenv("COPILOT_PRODUCT_HUB_ANSWER_CONTEXT_SHADOW_ENABLED", "true")
    monkeypatch.setenv("COPILOT_PRODUCT_HUB_BASE_URL", "http://127.0.0.1:8795")
    payload = _answer_context_payload()
    target = {"root": payload, "identity": payload["identity"], "fact": payload["directFacts"][0], "media": payload["mediaCandidates"][0]}[section]
    target.update(changes)
    monkeypatch.setattr(module, "urlopen", lambda *_a, **_kw: _Response(payload))
    result = module.ProductHubReviewedFactsClient().fetch_answer_context_for_sku("SKU-Test/A")
    assert result["state"] == "invalid_response"
    assert result["facts"] == result["assets"] == []


@pytest.mark.parametrize("field", ["directFacts", "mediaCandidates"])
def test_answer_context_duplicate_ids_fail_closed(monkeypatch, field):
    import app.integrations.product_hub.reviewed_facts_client as module

    monkeypatch.setenv("COPILOT_PRODUCT_HUB_ANSWER_CONTEXT_SHADOW_ENABLED", "true")
    monkeypatch.setenv("COPILOT_PRODUCT_HUB_BASE_URL", "http://127.0.0.1:8795")
    payload = _answer_context_payload()
    payload[field].append(dict(payload[field][0]))
    monkeypatch.setattr(module, "urlopen", lambda *_a, **_kw: _Response(payload))
    result = module.ProductHubReviewedFactsClient().fetch_answer_context_for_sku("SKU-Test/A")
    assert result["state"] == "invalid_response"
    assert result["facts"] == result["assets"] == []


def test_answer_context_unknown_media_type_does_not_discard_direct_facts(monkeypatch):
    import app.integrations.product_hub.reviewed_facts_client as module

    monkeypatch.setenv("COPILOT_PRODUCT_HUB_ANSWER_CONTEXT_SHADOW_ENABLED", "true")
    monkeypatch.setenv("COPILOT_PRODUCT_HUB_BASE_URL", "http://127.0.0.1:8795")
    payload = _answer_context_payload()
    payload["mediaCandidates"][0]["assetType"] = "future_catalog_type"
    monkeypatch.setattr(module, "urlopen", lambda *_a, **_kw: _Response(payload))
    result = module.ProductHubReviewedFactsClient().fetch_answer_context_for_sku("SKU-Test/A")
    assert result["state"] == "ready"
    assert len(result["facts"]) == 1
    assert result["assets"] == []
    assert result["source_media_count"] == result["unsupported_media_type_count"] == 1


def test_answer_context_transport_failure_has_no_legacy_fallback(monkeypatch):
    import app.integrations.product_hub.reviewed_facts_client as module

    monkeypatch.setenv("COPILOT_PRODUCT_HUB_ANSWER_CONTEXT_SHADOW_ENABLED", "true")
    monkeypatch.setenv("COPILOT_PRODUCT_HUB_BASE_URL", "http://127.0.0.1:8795")
    calls = []

    def transport(request, **_kwargs):
        calls.append(request.full_url)
        raise TimeoutError()

    monkeypatch.setattr(module, "urlopen", transport)
    result = module.ProductHubReviewedFactsClient().fetch_answer_context_for_sku("SKU-Test/A")
    assert result["state"] == "unavailable"
    assert len(calls) == 1
    assert result["facts"] == result["assets"] == []


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
        "attr": "\u5c3a\u5bf8",
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


def test_hub_client_retains_sku_record_id_as_provenance_without_treating_it_as_sku_code(monkeypatch):
    from app.integrations.product_hub.reviewed_facts_client import ProductHubReviewedFactsClient
    import app.integrations.product_hub.reviewed_facts_client as module

    monkeypatch.setenv("COPILOT_PRODUCT_HUB_REVIEWED_FACTS_ENABLED", "true")
    monkeypatch.setenv("COPILOT_PRODUCT_HUB_BASE_URL", "http://127.0.0.1:8795")
    monkeypatch.setattr(module, "urlopen", lambda *_args, **_kwargs: _Response({
        "ok": True,
        "productCode": "YH-EXACT-01",
        "facts": [
            _hub_fact(
                type="parts",
                attr="配置说明",
                scope="配件",
                unit="",
                skuCode="",
                skuId="hub-sku-record-a",
                applies="YH-EXACT-01-SKU-A",
            )
        ],
    }))

    result = ProductHubReviewedFactsClient().fetch_confirmed_facts("YH-EXACT-01")

    assert result["facts"][0]["sku_code"] == ""
    assert result["facts"][0]["hub_sku_id"] == "hub-sku-record-a"
    assert "sourceDetail" not in result["facts"][0]


def test_hub_client_resolves_an_exact_sku_before_reading_confirmed_facts(monkeypatch):
    from app.integrations.product_hub.reviewed_facts_client import ProductHubReviewedFactsClient
    import app.integrations.product_hub.reviewed_facts_client as module

    monkeypatch.setenv("COPILOT_PRODUCT_HUB_REVIEWED_FACTS_ENABLED", "true")
    monkeypatch.setenv("COPILOT_PRODUCT_HUB_BASE_URL", "http://127.0.0.1:8795")
    observed_urls = []

    def matching_transport(request, *, timeout):
        observed_urls.append(request.full_url)
        if request.full_url.endswith("/api/agent/skus/JST-SKU-007"):
            return _Response({
                "ok": True,
                "sku": {
                    "skuCode": "JST-SKU-007",
                    "productCode": "HUB-PRODUCT-007",
                },
            })
        assert request.full_url.endswith(
            "/api/agent/products/HUB-PRODUCT-007/facts?status=confirmed"
        )
        return _Response({
            "ok": True,
            "productCode": "HUB-PRODUCT-007",
            "facts": [_hub_fact(productCode="HUB-PRODUCT-007", skuCode="JST-SKU-007")],
        })

    monkeypatch.setattr(module, "urlopen", matching_transport)

    result = ProductHubReviewedFactsClient().fetch_confirmed_facts_for_sku("JST-SKU-007")

    assert observed_urls == [
        "http://127.0.0.1:8795/api/agent/skus/JST-SKU-007",
        "http://127.0.0.1:8795/api/agent/products/HUB-PRODUCT-007/facts?status=confirmed",
    ]
    assert result["state"] == "ready"
    assert result["product_code"] == "HUB-PRODUCT-007"
    assert result["resolved_sku_code"] == "JST-SKU-007"
    assert len(result["facts"]) == 1


def test_hub_client_rejects_a_sku_resolution_with_a_different_exact_key(monkeypatch):
    from app.integrations.product_hub.reviewed_facts_client import ProductHubReviewedFactsClient
    import app.integrations.product_hub.reviewed_facts_client as module

    monkeypatch.setenv("COPILOT_PRODUCT_HUB_REVIEWED_FACTS_ENABLED", "true")
    monkeypatch.setenv("COPILOT_PRODUCT_HUB_BASE_URL", "http://127.0.0.1:8795")
    observed_urls = []

    def mismatched_transport(request, *, timeout):
        observed_urls.append(request.full_url)
        return _Response({
            "ok": True,
            "sku": {
                "skuCode": "OTHER-SKU-007",
                "productCode": "HUB-PRODUCT-007",
            },
        })

    monkeypatch.setattr(module, "urlopen", mismatched_transport)

    result = ProductHubReviewedFactsClient().fetch_confirmed_facts_for_sku("JST-SKU-007")

    assert observed_urls == ["http://127.0.0.1:8795/api/agent/skus/JST-SKU-007"]
    assert result["state"] == "invalid_response"
    assert result["reason_code"] == "product_hub_sku_code_mismatch"
    assert result["facts"] == []


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
    assert candidate["attribute_key"] == "overall_dimensions"
    assert candidate["subject_scope"] == "product"
    assert candidate["product_scope"] == ["YH-EXACT-01"]
    assert candidate["sku_scope"] == ["YH-EXACT-01-SKU-A"]
    assert candidate["metadata"]["product_evidence_protocol"] is True
    assert candidate["metadata"]["verification_status"] == "reviewed"
    assert candidate["metadata"]["source_review_status"] == "confirmed"
    assert candidate["metadata"]["source_field_keys"] == ["type:size", "attr:尺寸"]
    assert "sourceDetail" not in candidate["metadata"]
    assert "must not reach" not in candidate["chunk_text"]

    admitted = AdmittedAnswerContextService().build_for_response(
        {"product_context_pack": {"facts": candidates}},
        product_identity={"i_id": "YH-EXACT-01", "sku_code": "YH-EXACT-01-SKU-A"},
        understanding={"requested_claims": [{"claim_type": "dimensions", "question": "dimensions", "risk_level": "low"}]},
    )
    assert [item["evidence_uid"] for item in admitted["direct_product_facts"]] == ["producthub:fact-001"]


@pytest.mark.parametrize("scope", ["product", "component", "accessory", "商品整体"])
@pytest.mark.parametrize("attribute", ["erasability", "cleaning_method", "日常清洁"])
def test_hub_care_type_alone_cannot_bypass_missing_published_field_contract(scope, attribute):
    from app.services.product_context_pack_service import _product_hub_facts_for_query

    candidates = _product_hub_facts_for_query(
        {"state": "ready", "product_code": "YH-EXACT-01", "facts": [
            _client_fact(type="cleaning_care", attr=attribute, unit="", scope=scope, value="Fixture source annotation."),
        ]},
        identity={"i_id": "YH-EXACT-01", "sku": "YH-EXACT-01-SKU-A", "product_identity_resolution": {"status": "resolved"}},
        query_fact_type="cleaning_care",
    )
    assert candidates == []


def test_hub_adapter_projects_exact_confirmed_age_and_load_facts_to_existing_claim_types():
    """A missing Hub tuple must not silently turn verified age/load facts into gaps."""
    from app.services.product_context_pack_service import _product_hub_facts_for_query

    identity = {
        "i_id": "YH-EXACT-01",
        "sku": "YH-EXACT-01-SKU-A",
        "product_identity_resolution": {"status": "resolved"},
    }
    source = {
        "state": "ready",
        "product_code": "YH-EXACT-01",
        "resolved_sku_code": "YH-EXACT-01-SKU-A",
        "facts": [
            _client_fact(
                id="age-range-001",
                type="age",
                attr="适用年龄",
                value="3岁以上",
                unit="",
                scope="商品整体",
            ),
            _client_fact(
                id="load-capacity-001",
                type="load",
                attr="承重",
                value="10",
                unit="",
                scope="商品整体",
            ),
        ],
    }

    age_candidates = _product_hub_facts_for_query(
        source,
        identity=identity,
        query_fact_type="age_range",
    )
    load_candidates = _product_hub_facts_for_query(
        source,
        identity=identity,
        query_fact_type="load_capacity",
    )

    assert [(item["evidence_uid"], item["fact_type"], item["subject_scope"])
        for item in age_candidates] == [
            ("producthub:age-range-001", "age_range", "product")
        ]
    assert [(item["evidence_uid"], item["fact_type"], item["subject_scope"])
        for item in load_candidates] == [
            ("producthub:load-capacity-001", "load_capacity", "product")
        ]

    admitted = AdmittedAnswerContextService().build_for_response(
        {"product_context_pack": {"facts": [*age_candidates, *load_candidates]}},
        product_identity={"i_id": "YH-EXACT-01", "sku_code": "YH-EXACT-01-SKU-A"},
        understanding={
            "requested_claims": [
                {"claim_type": "age_range", "question": "适用年龄", "risk_level": "medium"},
                {"claim_type": "load_capacity", "question": "承重", "risk_level": "medium"},
            ]
        },
    )

    assert {item["evidence_uid"] for item in admitted["direct_product_facts"]} == {
        "producthub:age-range-001",
        "producthub:load-capacity-001",
    }


def test_hub_adapter_does_not_promote_non_product_or_wrong_unit_load_to_capacity():
    """A field name alone cannot turn packaging data into a product limit."""
    from app.services.product_context_pack_service import _product_hub_facts_for_query

    candidates = _product_hub_facts_for_query(
        {
            "state": "ready",
            "product_code": "YH-EXACT-01",
            "resolved_sku_code": "YH-EXACT-01-SKU-A",
            "facts": [
                _client_fact(
                    id="packaging-load-001",
                    type="load",
                    attr="承重",
                    value="10",
                    unit="kg",
                    scope="包装",
                ),
                _client_fact(
                    id="wrong-unit-load-001",
                    type="load",
                    attr="承重",
                    value="10",
                    unit="lb",
                    scope="商品整体",
                ),
            ],
        },
        identity={
            "i_id": "YH-EXACT-01",
            "sku": "YH-EXACT-01-SKU-A",
            "product_identity_resolution": {"status": "resolved"},
        },
        query_fact_type="load_capacity",
    )

    assert candidates == []


def test_hub_overall_dimensions_resolve_a_broad_dimension_goal_with_legacy_unattributed_evidence():
    from app.services.claim_resolution_service import build_claim_resolutions
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

    resolution = build_claim_resolutions(
        [{
            "claim_type": "dimensions",
            "attribute_key": "",
            "question": "broad dimensions",
            "risk_level": "low",
        }],
        direct_product_facts=[
            *candidates,
            {
                "evidence_uid": "legacy-unattributed",
                "attribute_key": "",
                "claim_types_supported": ["dimensions"],
                "text": "legacy dimension fact",
                "subject_scope": "",
            },
        ],
        direct_policy_facts=[],
        conflicts=[],
    )

    assert resolution[0]["status"] == "supported"
    assert resolution[0]["evidence_uids"] == ["producthub:fact-001"]


def test_hub_adapter_builds_product_overview_only_from_exact_low_risk_facts():
    """A broad product question may expose facts, never a quality verdict."""
    from app.services.claim_resolution_service import build_claim_resolutions
    from app.services.product_context_pack_service import _product_hub_facts_for_query

    identity = {
        "i_id": "YH-EXACT-01",
        "sku": "YH-EXACT-01-SKU-A",
        "product_identity_resolution": {"status": "resolved"},
    }
    candidates = _product_hub_facts_for_query(
        {
            "state": "ready",
            "product_code": "YH-EXACT-01",
            "resolved_sku_code": "YH-EXACT-01-SKU-A",
            "facts": [
                _client_fact(
                    id="overview-material",
                    type="material",
                    attr="材质",
                    value="PP",
                    unit="",
                    scope="商品整体",
                ),
                _client_fact(
                    id="overview-dimensions",
                    type="size",
                    attr="尺寸",
                    value="120 x 60 x 90",
                    unit="cm",
                    scope="商品整体",
                ),
                _client_fact(
                    id="overview-color",
                    type="color",
                    attr="颜色",
                    value="option-a",
                    unit="",
                    scope="商品整体",
                ),
                _client_fact(
                    id="overview-installation",
                    type="installation",
                    attr="安装说明",
                    value="manual",
                    unit="",
                    scope="商品整体",
                ),
                _client_fact(
                    id="overview-packaging-weight",
                    type="weight",
                    attr="毛重",
                    value="2.5",
                    unit="kg",
                    scope="包装",
                ),
                _client_fact(
                    id="overview-pending-material",
                    type="material",
                    attr="材质",
                    value="ABS",
                    unit="",
                    scope="商品整体",
                    status="pending",
                ),
            ],
        },
        identity=identity,
        query_fact_type="product_overview",
    )

    assert {item["evidence_uid"] for item in candidates} == {
        "producthub:overview-material",
        "producthub:overview-dimensions",
    }
    assert {item["fact_type"] for item in candidates} == {"material", "dimensions"}
    assert all(
        "product_overview" in item["claim_types_supported"]
        for item in candidates
    )
    assert all(
        item["metadata"]["overview_context_eligible"] is True
        for item in candidates
    )

    admitted = AdmittedAnswerContextService().build_for_response(
        {"product_context_pack": {"facts": candidates}},
        product_identity={"i_id": "YH-EXACT-01", "sku_code": "YH-EXACT-01-SKU-A"},
        understanding={
            "requested_claims": [
                {
                    "claim_type": "product_overview",
                    "question": "broad product question",
                    "risk_level": "low",
                }
            ]
        },
    )
    assert {item["evidence_uid"] for item in admitted["direct_product_facts"]} == {
        "producthub:overview-material",
        "producthub:overview-dimensions",
    }

    unmarked = {**candidates[0], "overview_context_eligible": False}
    unmarked_admitted = AdmittedAnswerContextService().build_for_response(
        {"product_context_pack": {"facts": [unmarked]}},
        product_identity={"i_id": "YH-EXACT-01", "sku_code": "YH-EXACT-01-SKU-A"},
        understanding={
            "requested_claims": [
                {
                    "claim_type": "product_overview",
                    "question": "broad product question",
                    "risk_level": "low",
                }
            ]
        },
    )
    assert unmarked_admitted["direct_product_facts"] == []
    assert unmarked_admitted["rejected_evidence"][0]["reason"] == (
        "product_overview_context_not_eligible"
    )

    resolution = build_claim_resolutions(
        [
            {
                "goal_ref": "goal-product-overview",
                "goal_kind": "customer_goal",
                "claim_type_status": "canonical",
                "claim_type": "product_overview",
                "attribute_key": "",
                "goal_summary": "了解商品的已确认基础信息",
            }
        ],
        direct_product_facts=admitted["direct_product_facts"],
        direct_policy_facts=[],
        conflicts=[],
    )

    assert resolution[0]["status"] == "supported"
    assert set(resolution[0]["evidence_uids"]) == {
        "producthub:overview-material",
        "producthub:overview-dimensions",
    }


def test_hub_product_overview_marker_survives_compact_evidence_projection():
    """A compact Pack row must not shadow its admissible source row."""
    from app.services.product_context_pack_service import (
        _compact_fact_for_evidence,
        _product_hub_facts_for_query,
    )

    identity = {
        "i_id": "YH-EXACT-01",
        "sku": "YH-EXACT-01-SKU-A",
        "product_identity_resolution": {"status": "resolved"},
    }
    candidates = _product_hub_facts_for_query(
        {
            "state": "ready",
            "product_code": "YH-EXACT-01",
            "resolved_sku_code": "YH-EXACT-01-SKU-A",
            "facts": [
                _client_fact(
                    id="compact-overview-material",
                    type="material",
                    attr="材质",
                    value="PP",
                    unit="",
                    scope="商品整体",
                )
            ],
        },
        identity=identity,
        query_fact_type="product_overview",
    )
    compact = [_compact_fact_for_evidence(item) for item in candidates]

    admitted = AdmittedAnswerContextService().build_for_response(
        {
            "product_context_pack": {
                "facts": candidates,
                "evidence_pack": {"matched_facts": compact},
            }
        },
        product_identity={"i_id": "YH-EXACT-01", "sku_code": "YH-EXACT-01-SKU-A"},
        understanding={
            "requested_claims": [
                {
                    "goal_ref": "goal-product-overview",
                    "goal_kind": "customer_goal",
                    "claim_type": "product_overview",
                    "question": "broad product question",
                    "risk_level": "low",
                }
            ]
        },
    )

    assert [item["evidence_uid"] for item in admitted["direct_product_facts"]] == [
        "producthub:compact-overview-material"
    ]
    assert admitted["claim_resolutions"][0]["status"] == "supported"


def test_hub_adapter_admits_exact_product_color_only_for_color_options_goal():
    from app.services.product_context_pack_service import _product_hub_facts_for_query

    identity = {
        "i_id": "YH-EXACT-01",
        "sku": "YH-EXACT-01-SKU-A",
        "product_identity_resolution": {"status": "resolved"},
    }
    hub_read = {
        "state": "ready",
        "product_code": "YH-EXACT-01",
        "resolved_sku_code": "YH-EXACT-01-SKU-A",
        "facts": [
            _client_fact(
                id="fact-color-a",
                type="color",
                attr="\u989c\u8272",
                value="option-a",
                unit="",
                scope="\u5546\u54c1\u6574\u4f53",
                skuCode="YH-EXACT-01-SKU-A",
                applies="YH-EXACT-01-SKU-A",
            ),
            _client_fact(
                id="fact-color-b",
                type="color",
                attr="\u989c\u8272",
                value="option-b",
                unit="",
                scope="\u5546\u54c1\u6574\u4f53",
                skuCode="YH-EXACT-01-SKU-B",
                applies="YH-EXACT-01-SKU-B",
            ),
            _client_fact(
                id="fact-color-c",
                type="color",
                attr="\u989c\u8272",
                value="option-a",
                unit="",
                scope="\u5546\u54c1\u6574\u4f53",
                skuCode="YH-EXACT-01-SKU-C",
                applies="YH-EXACT-01-SKU-C",
            )
        ],
    }

    candidates = _product_hub_facts_for_query(
        hub_read,
        identity=identity,
        query_fact_type="color_options",
    )

    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate["fact_type"] == "color_options"
    assert candidate["subject_scope"] == "product"
    assert candidate["sku_scope"] == ["YH-EXACT-01-SKU-A"]
    assert candidate["chunk_text"] == "option-a\u3001option-b"
    assert candidate["evidence_uid"].startswith("producthub:color-options:")
    assert candidate["metadata"]["hub_color_option_source_fact_ids"] == [
        "fact-color-a",
        "fact-color-b",
        "fact-color-c",
    ]
    assert candidate["metadata"]["hub_color_option_source_count"] == 3

    reversed_candidates = _product_hub_facts_for_query(
        {**hub_read, "facts": list(reversed(hub_read["facts"]))},
        identity=identity,
        query_fact_type="color_options",
    )
    assert len(reversed_candidates) == 1
    assert reversed_candidates[0]["evidence_uid"] == candidate["evidence_uid"]
    assert reversed_candidates[0]["chunk_text"] == candidate["chunk_text"]
    assert reversed_candidates[0]["metadata"] == candidate["metadata"]

    assert _product_hub_facts_for_query(
        {
            **hub_read,
            "facts": [
                _client_fact(
                    id="fact-color-wrong-scope",
                    type="color",
                    attr="\u989c\u8272",
                    value="option-c",
                    unit="",
                    scope="\u5305\u88c5",
                    skuCode="YH-EXACT-01-SKU-A",
                    applies="YH-EXACT-01-SKU-A",
                )
            ],
        },
        identity=identity,
        query_fact_type="color_options",
    ) == []

    admitted = AdmittedAnswerContextService().build_for_response(
        {"product_context_pack": {"facts": candidates}},
        product_identity={"i_id": "YH-EXACT-01", "sku_code": "YH-EXACT-01-SKU-A"},
        understanding={
            "requested_claims": [
                {"claim_type": "color_options", "question": "color options", "risk_level": "low"}
            ]
        },
    )
    assert [item["evidence_uid"] for item in admitted["direct_product_facts"]] == [candidate["evidence_uid"]]

    assert _product_hub_facts_for_query(
        hub_read,
        identity=identity,
        query_fact_type="dimensions",
    ) == []


def test_hub_adapter_admits_only_confirmed_packaging_gross_weight():
    from app.services.product_context_pack_service import _product_hub_facts_for_query

    identity = {
        "i_id": "YH-EXACT-01",
        "sku": "YH-EXACT-01-SKU-A",
        "product_identity_resolution": {"status": "resolved"},
    }
    candidates = _product_hub_facts_for_query(
        {
            "state": "ready",
            "product_code": "YH-EXACT-01",
            "resolved_sku_code": "YH-EXACT-01-SKU-A",
            "facts": [
                _client_fact(
                    id="fact-gross-weight",
                    type="weight",
                    attr="\u6bdb\u91cd",
                    value="2.5",
                    unit="kg",
                    scope="\u5305\u88c5",
                ),
                _client_fact(
                    id="fact-net-weight",
                    type="weight",
                    attr="\u51c0\u91cd",
                    value="1.8",
                    unit="kg",
                    scope="\u5546\u54c1\u6574\u4f53",
                ),
            ],
        },
        identity=identity,
        query_fact_type="gross_weight",
    )

    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate["evidence_uid"] == "producthub:fact-gross-weight"
    assert candidate["fact_type"] == "gross_weight"
    assert candidate["subject_scope"] == "packaging"
    assert candidate["value"] == "2.5kg"


def test_hub_adapter_does_not_use_weight_for_an_unrelated_fact_type():
    from app.services.product_context_pack_service import _product_hub_facts_for_query

    result = _product_hub_facts_for_query(
        {
            "state": "ready",
            "product_code": "YH-EXACT-01",
            "resolved_sku_code": "YH-EXACT-01-SKU-A",
            "facts": [
                _client_fact(
                    id="fact-gross-weight",
                    type="weight",
                    attr="\u6bdb\u91cd",
                    value="2.5",
                    unit="kg",
                    scope="\u5305\u88c5",
                ),
            ],
        },
        identity={
            "i_id": "YH-EXACT-01",
            "sku": "YH-EXACT-01-SKU-A",
            "product_identity_resolution": {"status": "resolved"},
        },
        query_fact_type="dimensions",
    )

    assert result == []


def test_hub_adapter_builds_packaging_dimensions_only_for_an_explicit_packaging_goal():
    """Exact carton axes can support only an explicitly scoped packaging goal."""
    from app.services.product_context_pack_service import _product_hub_facts_for_query

    identity = {
        "i_id": "YH-EXACT-01",
        "sku": "YH-EXACT-01-SKU-A",
        "product_identity_resolution": {"status": "resolved"},
    }
    hub_read = {
        "state": "ready",
        "product_code": "YH-EXACT-01",
        "resolved_sku_code": "YH-EXACT-01-SKU-A",
        "facts": [
            _client_fact(
                id="carton-length",
                type="pack_size",
                attr="纸箱长",
                value="100",
                unit="cm",
                scope="包装",
            ),
            _client_fact(
                id="carton-width",
                type="pack_size",
                attr="纸箱宽",
                value="50",
                unit="cm",
                scope="包装",
            ),
            _client_fact(
                id="carton-height",
                type="pack_size",
                attr="纸箱高",
                value="30",
                unit="cm",
                scope="包装",
            ),
        ],
    }
    packaging_goal = [{
        "goal_ref": "goal-packaging-dimensions",
        "goal_kind": "customer_goal",
        "claim_type": "dimensions",
        "attribute_key": "",
        "subject_scope": "packaging",
        "question": "包装尺寸",
        "risk_level": "low",
    }]

    candidates = _product_hub_facts_for_query(
        hub_read,
        identity=identity,
        query_fact_type="dimensions",
        requested_claims=packaging_goal,
    )

    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate["fact_type"] == "dimensions"
    assert candidate["attribute_key"] == "overall_dimensions"
    assert candidate["subject_scope"] == "packaging"
    assert candidate["value"] == "100 x 50 x 30cm"
    assert candidate["metadata"]["hub_packaging_dimension_source_fact_ids"] == [
        "carton-height",
        "carton-length",
        "carton-width",
    ]

    admitted = AdmittedAnswerContextService().build_for_response(
        {"product_context_pack": {"facts": candidates}},
        product_identity={"i_id": "YH-EXACT-01", "sku_code": "YH-EXACT-01-SKU-A"},
        understanding={"requested_claims": packaging_goal},
    )
    assert [item["evidence_uid"] for item in admitted["direct_product_facts"]] == [
        candidate["evidence_uid"]
    ]

    resolution = admitted["claim_resolutions"]
    assert resolution[0]["status"] == "supported"
    assert resolution[0]["evidence_uids"] == [candidate["evidence_uid"]]

    product_scope_candidates = _product_hub_facts_for_query(
        hub_read,
        identity=identity,
        query_fact_type="dimensions",
        requested_claims=[{
            **packaging_goal[0],
            "goal_ref": "goal-product-dimensions",
            "subject_scope": "product",
        }],
    )
    assert product_scope_candidates == []


def test_hub_adapter_rejects_incomplete_or_conflicting_carton_axes():
    from app.services.product_context_pack_service import _product_hub_facts_for_query

    identity = {
        "i_id": "YH-EXACT-01",
        "sku": "YH-EXACT-01-SKU-A",
        "product_identity_resolution": {"status": "resolved"},
    }
    packaging_goal = [{
        "goal_ref": "goal-packaging-dimensions",
        "goal_kind": "customer_goal",
        "claim_type": "dimensions",
        "attribute_key": "",
        "subject_scope": "packaging",
        "question": "包装尺寸",
        "risk_level": "low",
    }]
    base = {
        "state": "ready",
        "product_code": "YH-EXACT-01",
        "resolved_sku_code": "YH-EXACT-01-SKU-A",
    }
    complete_axes = [
        _client_fact(
            id="carton-length", type="pack_size", attr="纸箱长",
            value="100", unit="cm", scope="包装",
        ),
        _client_fact(
            id="carton-width", type="pack_size", attr="纸箱宽",
            value="50", unit="cm", scope="包装",
        ),
        _client_fact(
            id="carton-height", type="pack_size", attr="纸箱高",
            value="30", unit="cm", scope="包装",
        ),
    ]

    incomplete = _product_hub_facts_for_query(
        {**base, "facts": complete_axes[:-1]},
        identity=identity,
        query_fact_type="dimensions",
        requested_claims=packaging_goal,
    )
    conflicting = _product_hub_facts_for_query(
        {
            **base,
            "facts": [
                *complete_axes,
                _client_fact(
                    id="carton-width-conflict", type="pack_size", attr="纸箱宽",
                    value="55", unit="cm", scope="包装",
                ),
            ],
        },
        identity=identity,
        query_fact_type="dimensions",
        requested_claims=packaging_goal,
    )

    assert incomplete == []
    assert conflicting == []


def test_hub_adapter_accepts_a_jst_identity_only_after_exact_sku_resolution():
    from app.services.product_context_pack_service import _product_hub_facts_for_query

    candidates = _product_hub_facts_for_query(
        {
            "state": "ready",
            "product_code": "HUB-PRODUCT-007",
            "resolved_sku_code": "JST-SKU-007",
            "facts": [_client_fact(productCode="HUB-PRODUCT-007", skuCode="JST-SKU-007")],
        },
        identity={
            "i_id": "JST-INTERNAL-PRODUCT-007",
            "sku": "JST-SKU-007",
            "product_identity_resolution": {"status": "resolved"},
        },
        query_fact_type="dimensions",
    )

    assert len(candidates) == 1
    assert candidates[0]["product_scope"] == ["HUB-PRODUCT-007"]
    assert candidates[0]["sku_scope"] == ["JST-SKU-007"]


def test_hub_exact_sku_mapping_scopes_product_level_fact_for_existing_admission():
    from app.services.product_context_pack_service import _product_hub_facts_for_query

    identity = {
        "source": "jst_order_item",
        "i_id": "JST-INTERNAL-PRODUCT-007",
        "sku": "JST-SKU-007",
        "product_identity_resolution": {"status": "resolved"},
    }
    candidates = _product_hub_facts_for_query(
        {
            "state": "ready",
            "product_code": "HUB-PRODUCT-007",
            "resolved_sku_code": "JST-SKU-007",
            "facts": [
                _client_fact(
                    productCode="HUB-PRODUCT-007",
                    skuCode="",
                )
            ],
        },
        identity=identity,
        query_fact_type="dimensions",
    )

    assert candidates[0]["product_scope"] == ["HUB-PRODUCT-007"]
    assert candidates[0]["sku_scope"] == ["JST-SKU-007"]
    assert candidates[0]["metadata"]["hub_fact_sku_scope"] == []
    assert candidates[0]["metadata"]["hub_identity_binding"] == "exact_sku"

    admitted = AdmittedAnswerContextService().build_for_response(
        {"product_context_pack": {"facts": candidates}},
        product_identity={
            "i_id": "JST-INTERNAL-PRODUCT-007",
            "sku_code": "JST-SKU-007",
        },
        understanding={
            "requested_claims": [
                {
                    "claim_type": "dimensions",
                    "question": "dimensions",
                    "risk_level": "low",
                }
            ]
        },
    )

    assert [item["evidence_uid"] for item in admitted["direct_product_facts"]] == [
        "producthub:fact-001"
    ]


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


def test_hub_adapter_requires_the_exact_published_source_field_contract():
    from app.services.product_context_pack_service import _product_hub_facts_for_query

    identity = {
        "i_id": "YH-EXACT-01",
        "sku": "YH-EXACT-01-SKU-A",
        "product_identity_resolution": {"status": "resolved"},
    }

    def candidates_for(fact, query_fact_type):
        return _product_hub_facts_for_query(
            {
                "state": "ready",
                "product_code": "YH-EXACT-01",
                "resolved_sku_code": "YH-EXACT-01-SKU-A",
                "facts": [fact],
            },
            identity=identity,
            query_fact_type=query_fact_type,
        )

    valid_cases = [
        (_client_fact(type="size", attr="\u5c3a\u5bf8", unit="cm", scope="\u5546\u54c1\u6574\u4f53"), "dimensions"),
        (_client_fact(type="material", attr="\u6750\u8d28", unit="", scope="\u5546\u54c1\u6574\u4f53"), "material"),
        (_client_fact(type="installation", attr="\u5b89\u88c5\u8bf4\u660e", unit="", scope="\u5546\u54c1\u6574\u4f53"), "installation"),
        (_client_fact(type="color", attr="\u989c\u8272", unit="", scope="\u5546\u54c1\u6574\u4f53"), "color_options"),
        (_client_fact(type="weight", attr="\u6bdb\u91cd", unit="kg", scope="\u5305\u88c5"), "gross_weight"),
    ]
    for fact, query_fact_type in valid_cases:
        assert len(candidates_for(fact, query_fact_type)) == 1

    invalid_cases = [
        (_client_fact(type="size", attr="\u5bbd\u5ea6", value="12", unit="cm", scope="\u5546\u54c1\u6574\u4f53"), "dimensions"),
        (_client_fact(type="size", attr="\u5c3a\u5bf8", unit="mm", scope="\u5546\u54c1\u6574\u4f53"), "dimensions"),
        (_client_fact(type="material", attr="\u6750\u8d28\u8bf4\u660e", unit="", scope="\u5546\u54c1\u6574\u4f53"), "material"),
        (_client_fact(type="installation", attr="\u5b89\u88c5\u65b9\u5f0f", unit="", scope="\u5546\u54c1\u6574\u4f53"), "installation"),
        (_client_fact(type="color", attr="\u8272\u5f69", unit="", scope="\u5546\u54c1\u6574\u4f53"), "color_options"),
        (_client_fact(type="weight", attr="gross_weight", unit="kg", scope="\u5305\u88c5"), "gross_weight"),
    ]
    for fact, query_fact_type in invalid_cases:
        assert candidates_for(fact, query_fact_type) == []


def test_hub_adapter_admits_only_exact_sku_bound_parts_configuration():
    from app.services.product_context_pack_service import _product_hub_facts_for_query

    identity = {
        "i_id": "YH-EXACT-01",
        "sku": "YH-EXACT-01-SKU-A",
        "product_identity_resolution": {"status": "resolved"},
    }
    hub_read = {
        "state": "ready",
        "product_code": "YH-EXACT-01",
        "resolved_sku_code": "YH-EXACT-01-SKU-A",
        "facts": [
            _client_fact(
                id="fact-parts-001",
                type="parts",
                attr="\u914d\u7f6e\u8bf4\u660e",
                value="configuration",
                unit="",
                scope="\u914d\u4ef6",
                skuCode="YH-EXACT-01-SKU-A",
                applies="YH-EXACT-01-SKU-A",
            ),
        ],
    }

    candidates = _product_hub_facts_for_query(
        hub_read,
        identity=identity,
        query_fact_type="accessories",
    )

    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate["fact_type"] == "accessories"
    assert candidate["subject_scope"] == "accessory"
    assert candidate["sku_scope"] == ["YH-EXACT-01-SKU-A"]

    admitted = AdmittedAnswerContextService().build_for_response(
        {"product_context_pack": {"facts": candidates}},
        product_identity={"i_id": "YH-EXACT-01", "sku_code": "YH-EXACT-01-SKU-A"},
        understanding={
            "requested_claims": [
                {"claim_type": "accessories", "question": "configuration", "risk_level": "low"}
            ]
        },
    )
    assert [item["evidence_uid"] for item in admitted["direct_product_facts"]] == [
        "producthub:fact-parts-001"
    ]
    for incompatible_query in ("installation", "aftersales_policy", "accessory_availability"):
        assert _product_hub_facts_for_query(
            hub_read,
            identity=identity,
            query_fact_type=incompatible_query,
        ) == []

    for invalid in [
        _client_fact(
            id="parts-missing-applies",
            type="parts",
            attr="\u914d\u7f6e\u8bf4\u660e",
            value="configuration",
            unit="",
            scope="\u914d\u4ef6",
            skuCode="YH-EXACT-01-SKU-A",
            applies="",
        ),
        _client_fact(
            id="parts-wrong-sku",
            type="parts",
            attr="\u914d\u7f6e\u8bf4\u660e",
            value="configuration",
            unit="",
            scope="\u914d\u4ef6",
            skuCode="YH-EXACT-01-SKU-B",
            applies="YH-EXACT-01-SKU-B",
        ),
        _client_fact(
            id="parts-wrong-attribute",
            type="parts",
            attr="\u914d\u4ef6\u6e05\u5355",
            value="configuration",
            unit="",
            scope="\u914d\u4ef6",
            skuCode="YH-EXACT-01-SKU-A",
            applies="YH-EXACT-01-SKU-A",
        ),
    ]:
        assert _product_hub_facts_for_query(
            {**hub_read, "facts": [invalid]},
            identity=identity,
            query_fact_type="accessories",
        ) == []


def test_hub_adapter_accepts_parts_configuration_with_exact_applies_and_hub_sku_provenance():
    from app.services.product_context_pack_service import _product_hub_facts_for_query

    identity = {
        "i_id": "YH-EXACT-01",
        "sku": "YH-EXACT-01-SKU-A",
        "product_identity_resolution": {"status": "resolved"},
    }
    exact_applies = _client_fact(
        id="parts-exact-applies",
        type="parts",
        attr="配置说明",
        value="configuration",
        unit="",
        scope="配件",
        skuCode="",
        applies="YH-EXACT-01-SKU-A",
    )
    exact_applies["hub_sku_id"] = "hub-sku-record-a"
    hub_read = {
        "state": "ready",
        "product_code": "YH-EXACT-01",
        "resolved_sku_code": "YH-EXACT-01-SKU-A",
        "facts": [exact_applies],
    }

    candidates = _product_hub_facts_for_query(
        hub_read,
        identity=identity,
        query_fact_type="accessories",
    )

    assert len(candidates) == 1
    assert candidates[0]["sku_scope"] == ["YH-EXACT-01-SKU-A"]
    assert candidates[0]["metadata"]["hub_sku_binding_source"] == "applies"

    missing_provenance = dict(exact_applies)
    missing_provenance.pop("hub_sku_id")
    assert _product_hub_facts_for_query(
        {**hub_read, "facts": [missing_provenance]},
        identity=identity,
        query_fact_type="accessories",
    ) == []


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


def test_hub_loader_prefers_resolved_exact_sku_over_jst_product_identifier(monkeypatch):
    from app.services.product_context_pack_service import _load_product_hub_reviewed_facts
    from app.integrations.product_hub.reviewed_facts_client import ProductHubReviewedFactsClient

    sku_calls = []
    monkeypatch.setattr(
        ProductHubReviewedFactsClient,
        "fetch_confirmed_facts_for_sku",
        lambda _self, code: sku_calls.append(code) or {
            "state": "ready",
            "reason_code": "",
            "product_code": "HUB-PRODUCT-007",
            "resolved_sku_code": code,
            "facts": [],
        },
        raising=False,
    )
    monkeypatch.setattr(
        ProductHubReviewedFactsClient,
        "fetch_confirmed_facts",
        lambda *_args: (_ for _ in ()).throw(AssertionError("product code fallback called")),
    )

    result = _load_product_hub_reviewed_facts({
        "i_id": "JST-INTERNAL-PRODUCT-007",
        "sku": "JST-SKU-007",
        "product_identity_resolution": {"status": "resolved"},
    })

    assert result["state"] == "ready"
    assert sku_calls == ["JST-SKU-007"]


def test_hub_loader_never_treats_a_jst_i_id_as_a_hub_product_code(monkeypatch):
    from app.services.product_context_pack_service import _load_product_hub_reviewed_facts
    from app.integrations.product_hub.reviewed_facts_client import ProductHubReviewedFactsClient

    monkeypatch.setattr(
        ProductHubReviewedFactsClient,
        "fetch_confirmed_facts",
        lambda *_args: (_ for _ in ()).throw(AssertionError("jst i_id was used as a hub product code")),
    )

    result = _load_product_hub_reviewed_facts({
        "i_id": "JST-INTERNAL-PRODUCT-ONLY",
        "source": "jst_product_query",
        "product_identity_resolution": {"status": "resolved"},
    })

    assert result["state"] == "not_attempted"
    assert result["reason_code"] == "product_hub_jst_sku_code_missing"


def test_state_identity_preserves_the_order_identity_source_for_hub_scoping():
    from app.services.product_context_pack_service import _state_identity

    identity = _state_identity({
        "order_product_identity": {
            "source": "jst_order_items",
            "sku_id": "JST-SKU-007",
            "i_id": "JST-INTERNAL-PRODUCT-007",
        },
    })

    assert identity["source"] == "jst_order_items"


def test_exact_snapshot_item_identity_can_seed_matching_hub_sku_scope():
    from app.services.product_context_pack_service import _trusted_exact_jst_order_item_identity

    identity = {
        "source": "jst_snapshot_order_items",
        "sku": "SKU-SNAPSHOT-1",
        "sku_family": "SKU-SNAPSHOT",
        "i_id": "PRODUCT-SNAPSHOT-1",
        "product_name": "snapshot product",
    }
    result = _trusted_exact_jst_order_item_identity(
        {
            "order_product_identity": {
                "status": "resolved",
                "source": "jst_snapshot_order_items",
                "reason": "exact_jst_snapshot_order_item",
                "confidence": 1.0,
                "snapshot_identity_only": True,
                "sku_id": "SKU-SNAPSHOT-1",
            }
        },
        identity,
    )

    assert result["sku"] == "SKU-SNAPSHOT-1"
    assert result["product_identity_resolution"]["source"] == "jst_snapshot_order_items_exact_sku"
    assert result["product_identity_resolution"]["match_reason"] == "exact_jst_snapshot_order_item_sku"


def test_exact_snapshot_order_reference_can_seed_matching_hub_sku_scope():
    """An HMAC-matched sidebar order may scope facts, never order state."""
    from app.services.product_context_pack_service import _trusted_exact_jst_order_item_identity

    identity = {
        "source": "jst_snapshot_order_reference",
        "sku": "SKU-SNAPSHOT-1",
        "sku_family": "SKU-SNAPSHOT",
        "i_id": "PRODUCT-SNAPSHOT-1",
        "product_name": "snapshot product",
    }
    result = _trusted_exact_jst_order_item_identity(
        {
            "order_product_identity": {
                "status": "resolved",
                "source": "jst_snapshot_order_reference",
                "reason": "exact_jst_snapshot_order_reference",
                "confidence": 1.0,
                "snapshot_identity_only": True,
                "sku_id": "SKU-SNAPSHOT-1",
            }
        },
        identity,
    )

    assert result["sku"] == "SKU-SNAPSHOT-1"
    assert result["product_identity_resolution"]["source"] == "jst_snapshot_order_reference_exact_sku"
    assert result["product_identity_resolution"]["match_reason"] == "exact_jst_snapshot_order_reference_sku"
    assert result["product_identity_resolution"]["snapshot_identity_only"] is True


def test_snapshot_item_identity_without_identity_only_marker_cannot_seed_hub_scope():
    from app.services.product_context_pack_service import _trusted_exact_jst_order_item_identity

    result = _trusted_exact_jst_order_item_identity(
        {
            "order_product_identity": {
                "status": "resolved",
                "source": "jst_snapshot_order_items",
                "reason": "exact_jst_snapshot_order_item",
                "confidence": 1.0,
                "sku_id": "SKU-SNAPSHOT-1",
            }
        },
        {
            "source": "jst_snapshot_order_items",
            "sku": "SKU-SNAPSHOT-1",
            "sku_family": "SKU-SNAPSHOT",
            "i_id": "",
            "product_name": "",
        },
    )

    assert result is None


def _hub_asset(**overrides):
    value = {
        "id": "asset-001",
        "canonicalName": "must_not_be_projected",
        "assetType": "main",
        "status": "approved",
        "label": "main product view",
        "scene": "appearance",
        "platform": "shop",
        "width": 1200,
        "height": 1200,
        "sizeBytes": 1024,
        "skuId": "hub-sku-record-001",
        "productId": "hub-product-record-001",
        "thumbUrl": "/api/v2/media/thumb/asset-001",
        "previewUrl": "/api/v2/media/preview/asset-001",
        "originalUrl": "/api/asset?scope=normalized&relative=must-not-project",
        "createdAt": "2026-09-05T00:00:00Z",
    }
    value.update(overrides)
    return value


def test_hub_client_projects_only_exact_sku_approved_images_as_review_candidates(monkeypatch):
    """Catch a bridge that reads a broad asset list or exposes original media URLs."""
    from app.integrations.product_hub.reviewed_facts_client import ProductHubReviewedFactsClient
    import app.integrations.product_hub.reviewed_facts_client as module

    monkeypatch.setenv("COPILOT_PRODUCT_HUB_REVIEWED_MEDIA_ENABLED", "true")
    monkeypatch.setenv("COPILOT_PRODUCT_HUB_BASE_URL", "http://127.0.0.1:8795")
    observed_urls = []

    def matching_transport(request, *, timeout):
        observed_urls.append(request.full_url)
        if request.full_url.endswith("/api/agent/skus/JST-SKU-007"):
            return _Response({
                "ok": True,
                "sku": {
                    "skuCode": "JST-SKU-007",
                    "productCode": "HUB-PRODUCT-007",
                },
            })
        assert request.full_url.endswith("/api/agent/skus/JST-SKU-007/assets")
        return _Response({
            "ok": True,
            "skuCode": "JST-SKU-007",
            "total": 5,
            "items": [
                _hub_asset(),
                _hub_asset(id="asset-live", assetType="qc", status="live", previewUrl="/api/v2/media/preview/asset-live"),
                _hub_asset(id="asset-video", assetType="video", previewUrl="/api/v2/media/preview/asset-video"),
                _hub_asset(id="asset-pending", status="pending_review", previewUrl="/api/v2/media/preview/asset-pending"),
                _hub_asset(id="asset-without-preview", previewUrl=""),
            ],
        })

    monkeypatch.setattr(module, "urlopen", matching_transport)

    result = ProductHubReviewedFactsClient().fetch_reviewable_assets_for_sku("JST-SKU-007")

    assert observed_urls == [
        "http://127.0.0.1:8795/api/agent/skus/JST-SKU-007",
        "http://127.0.0.1:8795/api/agent/skus/JST-SKU-007/assets",
    ]
    assert result["state"] == "ready"
    assert result["product_code"] == "HUB-PRODUCT-007"
    assert result["resolved_sku_code"] == "JST-SKU-007"
    assert result["assets"] == [
        {
            "asset_id": "asset-001",
            "asset_type": "sku_image",
            "media_purpose": "appearance_image",
            "asset_title": "main product view",
            "scene_tags": ["appearance"],
            "asset_url": "http://127.0.0.1:8795/api/v2/media/preview/asset-001",
            "source": "product_hub.agent_assets",
            "source_table": "product_hub.assets",
            "source_review_status": "approved",
            "product_code": "HUB-PRODUCT-007",
            "resolved_sku_code": "JST-SKU-007",
        },
        {
            "asset_id": "asset-live",
            "asset_type": "certificate_image",
            "media_purpose": "certificate_image",
            "asset_title": "main product view",
            "scene_tags": ["appearance"],
            "asset_url": "http://127.0.0.1:8795/api/v2/media/preview/asset-live",
            "source": "product_hub.agent_assets",
            "source_table": "product_hub.assets",
            "source_review_status": "live",
            "product_code": "HUB-PRODUCT-007",
            "resolved_sku_code": "JST-SKU-007",
        },
    ]


def test_hub_client_rejects_cross_sku_asset_response_before_projecting_media(monkeypatch):
    """Catch a bridge that trusts a mismatched asset endpoint response."""
    from app.integrations.product_hub.reviewed_facts_client import ProductHubReviewedFactsClient
    import app.integrations.product_hub.reviewed_facts_client as module

    monkeypatch.setenv("COPILOT_PRODUCT_HUB_REVIEWED_MEDIA_ENABLED", "true")
    monkeypatch.setenv("COPILOT_PRODUCT_HUB_BASE_URL", "http://127.0.0.1:8795")

    def mismatched_transport(request, *, timeout):
        if request.full_url.endswith("/api/agent/skus/JST-SKU-007"):
            return _Response({
                "ok": True,
                "sku": {
                    "skuCode": "JST-SKU-007",
                    "productCode": "HUB-PRODUCT-007",
                },
            })
        return _Response({
            "ok": True,
            "skuCode": "JST-SKU-OTHER",
            "total": 1,
            "items": [_hub_asset()],
        })

    monkeypatch.setattr(module, "urlopen", mismatched_transport)

    result = ProductHubReviewedFactsClient().fetch_reviewable_assets_for_sku("JST-SKU-007")

    assert result["state"] == "invalid_response"
    assert result["reason_code"] == "product_hub_asset_sku_code_mismatch"
    assert result["assets"] == []


def test_hub_media_context_is_reference_only_and_never_builds_a_delivery_block():
    """Catch a bridge that accidentally promotes a Hub image into evidence or delivery."""
    from app.services.admitted_answer_context_service import (
        AdmittedAnswerContextService,
        canonical_selected_evidence,
    )
    from app.services.media_asset_service import build_reply_blocks
    from app.services.product_context_pack_service import _product_hub_media_for_context

    sku_code = "JST-SKU-007"
    media = _product_hub_media_for_context(
        {
            "state": "ready",
            "product_code": "HUB-PRODUCT-007",
            "resolved_sku_code": sku_code,
            "assets": [{
                "asset_id": "asset-001",
                "asset_type": "sku_image",
                "media_purpose": "appearance_image",
                "asset_title": "main product view",
                "scene_tags": ["appearance"],
                "asset_url": "http://127.0.0.1:8795/api/v2/media/preview/asset-001",
                "source": "product_hub.agent_assets",
                "source_table": "product_hub.assets",
                "source_review_status": "approved",
                "product_code": "HUB-PRODUCT-007",
                "resolved_sku_code": sku_code,
            }],
        },
        identity={
            "i_id": "HUB-PRODUCT-007",
            "sku": sku_code,
            "product_identity_resolution": {"status": "resolved"},
        },
    )

    assert len(media) == 1
    candidate = media[0]
    assert candidate["reference_only"] is True
    assert candidate["evidence_role"] == "media_reference"
    assert candidate["can_direct_answer"] is False
    assert candidate["auto_send_level"] == "review"
    assert candidate["usable_for_agent"] is False

    admitted = AdmittedAnswerContextService().build_for_response(
        {"product_context_pack": {"media_assets": media}},
        product_identity={"i_id": "HUB-PRODUCT-007", "sku_code": sku_code},
    )
    assert admitted["direct_product_facts"] == []
    assert canonical_selected_evidence(admitted) == []
    assert len(admitted["media_candidates"]) == 1

    delivery = build_reply_blocks(
        "candidate reply",
        media,
        requires_human_review=True,
        query_fact_type="appearance",
        product_identity={"i_id": "HUB-PRODUCT-007", "sku_code": sku_code},
    )
    assert delivery["reply_blocks"] == [{
        "type": "text",
        "content": "candidate reply",
        "send_mode": "auto_when_platform_connected",
    }]
    assert delivery["reply_delivery"]["auto_send_ready"] is False
    assert delivery["reply_delivery"]["reason"] == "requires_human_review"


def test_hub_media_candidates_keep_distinct_assets_for_human_review():
    """Catch admission dedupe collapsing distinct exact-SKU review images."""
    from app.services.admitted_answer_context_service import (
        AdmittedAnswerContextService,
        canonical_selected_evidence,
    )
    from app.services.product_context_pack_service import _product_hub_media_for_context

    sku_code = "JST-SKU-007"
    media = _product_hub_media_for_context(
        {
            "state": "ready",
            "product_code": "HUB-PRODUCT-007",
            "resolved_sku_code": sku_code,
            "assets": [
                {
                    "asset_id": "asset-001",
                    "asset_type": "sku_image",
                    "media_purpose": "appearance_image",
                    "asset_title": "same review label",
                    "scene_tags": ["appearance"],
                    "asset_url": "http://127.0.0.1:8795/api/v2/media/preview/asset-001",
                    "source": "product_hub.agent_assets",
                    "source_table": "product_hub.assets",
                    "source_review_status": "approved",
                    "product_code": "HUB-PRODUCT-007",
                    "resolved_sku_code": sku_code,
                },
                {
                    "asset_id": "asset-002",
                    "asset_type": "sku_image",
                    "media_purpose": "appearance_image",
                    "asset_title": "same review label",
                    "scene_tags": ["appearance"],
                    "asset_url": "http://127.0.0.1:8795/api/v2/media/preview/asset-002",
                    "source": "product_hub.agent_assets",
                    "source_table": "product_hub.assets",
                    "source_review_status": "approved",
                    "product_code": "HUB-PRODUCT-007",
                    "resolved_sku_code": sku_code,
                },
            ],
        },
        identity={
            "i_id": "HUB-PRODUCT-007",
            "sku": sku_code,
            "product_identity_resolution": {"status": "resolved"},
        },
    )

    admitted = AdmittedAnswerContextService().build_for_response(
        {"product_context_pack": {"media_assets": media}},
        product_identity={"i_id": "HUB-PRODUCT-007", "sku_code": sku_code},
    )

    assert len(admitted["media_candidates"]) == 2
    assert all(item["reference_only"] is True for item in admitted["media_candidates"])
    assert canonical_selected_evidence(admitted) == []
