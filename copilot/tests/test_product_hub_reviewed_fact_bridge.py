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
