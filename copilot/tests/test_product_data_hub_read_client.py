from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest


class _HubHandler(BaseHTTPRequestHandler):
    products = [
        {
            "id": "product-1",
            "productCode": "P100",
            "productName": "内部商品甲",
            "brand": "英禾",
            "category": "家居用品",
            "catCode": "HOME-1",
            "catName": "家居用品",
            "note": "不得成为正式客服事实",
            "status": "active",
            "updatedAt": "2026-08-21T10:00:00Z",
        },
        {
            "id": "product-2",
            "productCode": "P200",
            "productName": "内部商品乙",
            "brand": "英禾",
            "category": "运动用品",
            "catCode": "SPORT-1",
            "catName": "运动用品",
            "note": "",
            "status": "active",
            "updatedAt": "2026-08-21T10:00:00Z",
        },
    ]
    skus = [
        {
            "id": "sku-1",
            "productId": "product-1",
            "skuCode": "S100-WHITE",
            "color": "白色",
            "size": "",
            "spec": "标准款",
            "attrs": {"材质": "PP", "承重": "测试值"},
            "status": "active",
        },
        {
            "id": "sku-2",
            "productId": "product-2",
            "skuCode": "S200-GREEN",
            "color": "绿色",
            "size": "",
            "spec": "标准款",
            "attrs": {},
            "status": "active",
        },
    ]
    request_paths: list[str] = []

    def do_GET(self):  # noqa: N802
        type(self).request_paths.append(self.path)
        if self.path == "/api/v2/products":
            self._json({"ok": True, "items": self.products})
            return
        if self.path == "/api/v2/skus":
            self._json({"ok": True, "items": self.skus})
            return
        self._json({"ok": False}, status=404)

    def log_message(self, _format, *_args):
        return

    def _json(self, payload, *, status=200):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


@pytest.fixture()
def product_hub_url():
    _HubHandler.request_paths = []
    server = ThreadingHTTPServer(("127.0.0.1", 0), _HubHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_exact_sku_and_product_codes_resolve_same_catalog_identity(product_hub_url):
    from app.integrations.product_data_hub.read_client import ProductDataHubReadClient

    result = ProductDataHubReadClient(product_hub_url, timeout_seconds=2).lookup_exact(
        i_id="p100",
        sku_id="s100-white",
    )

    assert result["status"] == "resolved"
    assert result["match_reason"] == "exact_product_and_sku_code"
    assert result["product"] == {
        "hub_product_id": "product-1",
        "product_code": "P100",
        "product_name": "内部商品甲",
        "brand": "英禾",
        "category_code": "HOME-1",
        "category_name": "家居用品",
        "status": "active",
        "updated_at": "2026-08-21T10:00:00Z",
    }
    assert result["sku"] == {
        "hub_sku_id": "sku-1",
        "sku_code": "S100-WHITE",
        "color": "白色",
        "size": "",
        "spec": "标准款",
        "status": "active",
    }
    assert result["reference_only"] is True
    assert result["used_for_fact"] is False
    assert "note" not in result["product"]
    assert "attrs" not in result["sku"]
    assert "/api/v2/cs/ask" not in _HubHandler.request_paths


def test_exact_sku_resolves_its_parent_without_title_matching(product_hub_url):
    from app.integrations.product_data_hub.read_client import ProductDataHubReadClient

    result = ProductDataHubReadClient(product_hub_url, timeout_seconds=2).lookup_exact(
        i_id="",
        sku_id="S200-GREEN",
    )

    assert result["status"] == "resolved"
    assert result["match_reason"] == "exact_sku_code"
    assert result["product"]["product_code"] == "P200"
    assert result["sku"]["sku_code"] == "S200-GREEN"


def test_mismatched_product_and_sku_fail_closed(product_hub_url):
    from app.integrations.product_data_hub.read_client import ProductDataHubReadClient

    result = ProductDataHubReadClient(product_hub_url, timeout_seconds=2).lookup_exact(
        i_id="P100",
        sku_id="S200-GREEN",
    )

    assert result["status"] == "identity_conflict"
    assert result["product"] == {}
    assert result["sku"] == {}
    assert result["reference_only"] is True
    assert result["used_for_fact"] is False


def test_unknown_product_code_cannot_be_ignored_when_sku_is_valid(product_hub_url):
    from app.integrations.product_data_hub.read_client import ProductDataHubReadClient

    result = ProductDataHubReadClient(product_hub_url, timeout_seconds=2).lookup_exact(
        i_id="P-DOES-NOT-EXIST",
        sku_id="S100-WHITE",
    )

    assert result["status"] == "not_found"
    assert result["reason"] == "product_code_not_found"
    assert result["product"] == {}
    assert result["sku"] == {}


def test_missing_exact_code_does_not_fall_back_to_product_name(product_hub_url):
    from app.integrations.product_data_hub.read_client import ProductDataHubReadClient

    result = ProductDataHubReadClient(product_hub_url, timeout_seconds=2).lookup_exact(
        i_id="内部商品甲",
        sku_id="",
    )

    assert result["status"] == "not_found"
    assert result["product"] == {}
    assert result["sku"] == {}


def test_malformed_catalog_response_is_unavailable(product_hub_url, monkeypatch):
    from app.integrations.product_data_hub import read_client

    monkeypatch.setattr(read_client.ProductDataHubReadClient, "_get_json", lambda *_args: {"ok": True})
    result = read_client.ProductDataHubReadClient(product_hub_url).lookup_exact(i_id="P100")

    assert result["status"] == "unavailable"
    assert result["reason"] == "invalid_products_contract"


def test_exact_bundle_exposes_only_confirmed_scope_compatible_facts_and_labeled_assets(product_hub_url, monkeypatch):
    """A resolved SKU must not admit pending, conflicting, or other-SKU Hub facts."""
    from app.integrations.product_data_hub.read_client import ProductDataHubReadClient

    client = ProductDataHubReadClient(product_hub_url, timeout_seconds=2)

    def fake_get_json(path):
        if path == "/api/v2/products":
            return {"ok": True, "items": _HubHandler.products}
        if path == "/api/v2/skus":
            return {"ok": True, "items": _HubHandler.skus}
        if path == "/api/v2/products/product-1/facts":
            return {
                "ok": True,
                "facts": [
                    {
                        "id": "fact-confirmed",
                        "productId": "product-1",
                        "skuId": "sku-1",
                        "type": "dimensions",
                        "attr": "width",
                        "value": "42",
                        "unit": "cm",
                        "scope": "商品整体",
                        "applies": "",
                        "source": "ai-label",
                        "sourceDetail": "尺寸参数图",
                        "status": "confirmed",
                        "conflict": False,
                        "updatedAt": "2026-08-22T10:00:00Z",
                    },
                    {
                        "id": "fact-pending",
                        "productId": "product-1",
                        "skuId": "sku-1",
                        "type": "dimensions",
                        "attr": "height",
                        "value": "70",
                        "unit": "cm",
                        "scope": "商品整体",
                        "status": "pending",
                        "conflict": False,
                    },
                    {
                        "id": "fact-conflict",
                        "productId": "product-1",
                        "skuId": "sku-1",
                        "type": "dimensions",
                        "attr": "depth",
                        "value": "28",
                        "unit": "cm",
                        "scope": "商品整体",
                        "status": "confirmed",
                        "conflict": True,
                    },
                    {
                        "id": "fact-other-sku",
                        "productId": "product-1",
                        "skuId": "sku-2",
                        "type": "color",
                        "attr": "color",
                        "value": "绿色",
                        "unit": "",
                        "scope": "SKU",
                        "status": "confirmed",
                        "conflict": False,
                    },
                ],
            }
        if path == "/api/v2/products/product-1/labeled-images":
            return {
                "ok": True,
                "items": [
                    {
                        "assetId": "asset-size",
                        "label": "尺寸参数图",
                        "labels": ["尺寸参数图"],
                        "labelNote": "整体宽高尺寸",
                        "specRef": "42 x 70 cm",
                        "canonicalName": "size.png",
                        "previewUrl": "/api/v2/media/preview/asset-size",
                    },
                    {
                        "assetId": "asset-unlabeled",
                        "label": "",
                        "labels": [],
                        "labelNote": "",
                        "specRef": "",
                        "canonicalName": "other.png",
                        "previewUrl": "/api/v2/media/preview/asset-unlabeled",
                    },
                ],
            }
        raise AssertionError(f"unexpected Hub path: {path}")

    monkeypatch.setattr(client, "_get_json", fake_get_json)

    result = client.lookup_exact_bundle(i_id="P100", sku_id="S100-WHITE")

    assert result["status"] == "resolved"
    assert result["used_for_fact"] is True
    assert result["facts"] == [{
        "fact_uid": "product_data_hub:fact-confirmed",
        "fact_type": "dimensions",
        "attribute_key": "width",
        "value": "42",
        "unit": "cm",
        "scope": "商品整体",
        "applies": "",
        "source": "product_data_hub:ai-label",
        "source_detail": "尺寸参数图",
        "review_status": "confirmed",
        "identity_scope": {"hub_product_id": "product-1", "hub_sku_id": "sku-1"},
        "updated_at": "2026-08-22T10:00:00Z",
    }]
    assert result["assets"] == [{
        "asset_id": "asset-size",
        "asset_type": "size_image",
        "labels": ["尺寸参数图"],
        "label_note": "整体宽高尺寸",
        "spec_ref": "42 x 70 cm",
        "asset_title": "size.png",
        "asset_url": f"{product_hub_url}/api/v2/media/preview/asset-size",
        "source": "product_data_hub",
        "product_code": "P100",
        "sku_code": "S100-WHITE",
        "auto_send_level": "auto",
    }]
