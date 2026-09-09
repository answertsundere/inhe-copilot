"""Product manuals must be discoverable without claiming they fit every SKU."""
from copy import deepcopy
from io import BytesIO
from urllib.error import HTTPError
from urllib.parse import parse_qs, quote, urlencode, urlsplit

import pytest

from app.integrations.product_hub import reviewed_facts_client as client
from app.services import product_context_pack_service as pack


@pytest.fixture
def source(monkeypatch):
    monkeypatch.setenv("COPILOT_PRODUCT_HUB_REVIEWED_MEDIA_ENABLED", "true")
    monkeypatch.setenv("COPILOT_PRODUCT_HUB_BASE_URL", "http://127.0.0.1:8795")
    sku, code = "SKU-B", "PRODUCT-B"
    manual = {
        "id": "manual-b", "assetType": "manual", "status": "approved",
        "canonicalName": "installation guide.pdf", "productId": "product-record-b",
        "skuId": None, "sizeBytes": 123,
        "originalUrl": "/api/asset?" + urlencode({
            "scope": "normalized", "relative": "catalog/manual/installation guide.pdf",
        }),
    }
    data = {
        "sku": {"ok": True, "sku": {"id": "sku-record-b", "skuCode": sku,
                 "productCode": code, "status": "active"}},
        "product": {"ok": True, "product": {"id": "product-record-b",
                     "productCode": code, "status": "active"}},
        "assets": {"ok": True, "items": [manual], "total": 1}, "urls": [],
        "file_urls": [], "file_response": {},
    }

    def read(url, *, timeout):
        assert 0 < timeout <= 5
        data["urls"].append(url)
        parsed = urlsplit(url)
        if parsed.path == f"/api/agent/skus/{quote(data['sku']['sku']['skuCode'], safe='')}":
            return deepcopy(data["sku"]), ""
        if parsed.path == f"/api/agent/products/{quote(data['sku']['sku']['productCode'], safe='')}":
            return deepcopy(data["product"]), ""
        assert parsed.path == "/api/agent/assets"
        assert parse_qs(parsed.query) == {"productCode": [data["sku"]["sku"]["productCode"]],
               "type": ["manual"], "page": ["1"], "pageSize": ["200"]}
        return deepcopy(data["assets"]), ""

    monkeypatch.setattr(client, "_read_json", read)

    class Response:
        def __init__(self, request):
            self.url = request.full_url
            values = data["file_response"]
            self.status = values.get("status", 206)
            self.headers = {"Content-Type": "application/pdf", "Content-Length": "5",
                            "Content-Range": "bytes 0-4/123", **values.get("headers", {})}

        def __enter__(self):
            return self

        def __exit__(self, *args):
            data["file_closed"] = True

        def geturl(self):
            return data["file_response"].get("url", self.url)

        def read(self, size):
            assert size == 5
            return data["file_response"].get("prefix", b"%PDF-")

    class Opener:
        def open(self, request, *, timeout):
            assert 0 < timeout <= 5
            assert request.get_header("Range") == "bytes=0-4"
            data["file_urls"].append(request.full_url)
            error = data["file_response"].get("error")
            if error:
                raise error
            return Response(request)

    def opener(handler):
        assert isinstance(handler, client._NoManualRedirect)
        return Opener()

    monkeypatch.setattr(client, "build_opener", opener)
    return data


def fetch():
    return client.ProductHubReviewedFactsClient().fetch_manuals_for_sku("SKU-B")


def test_product_pdf_without_sku_or_preview_is_discovered(source):
    result = fetch()
    assert result["state"] == "ready"
    assert len(result["assets"]) == 1
    item = result["assets"][0]
    assert item["asset_type"] == "product_manual"
    assert item["binding_scope"] == "product"
    assert item["availability"] == "header_verified"
    assert item["file_checked_at"] and item["size_bytes"] == 123
    assert item["applicability"] == "needs_review"
    assert len(source["urls"]) == 3
    assert all("/api/asset?" not in url for url in source["urls"])
    assert len(source["file_urls"]) == 1 and source["file_closed"]


@pytest.mark.parametrize("field,value", [
    ("productId", "another-product"), ("skuId", "another-sku"),
    ("status", "archived"), ("status", None), ("status", []),
    ("assetType", "video"), ("canonicalName", "source.ai"),
    ("sizeBytes", 0), ("sizeBytes", True), ("sizeBytes", "123"),
])
def test_manual_rejects_wrong_identity_status_format_or_size(source, field, value):
    source["assets"]["items"][0][field] = value
    assert fetch()["assets"] == []
    assert source["file_urls"] == []


@pytest.mark.parametrize("url", [
    "https://external.invalid/guide.pdf", "//external.invalid/guide.pdf",
    "/api/asset?scope=source&relative=guide.pdf",
    "/api/asset?scope=normalized&relative=../guide.pdf",
    "/api/asset?scope=normalized&relative=C%3A%5Cguide.pdf",
    "/api/asset?scope=normalized&relative=%5C%5Cserver%5Cguide.pdf",
    "/api/asset?scope=normalized&relative=%252e%252e%252fguide.pdf",
    "/api/asset?scope=normalized&relative=guide.pdf&relative=other.pdf",
    "/api/asset?scope=normalized&relative=guide.pdf#fragment",
])
def test_manual_rejects_untrusted_file_urls(source, url):
    source["assets"]["items"][0]["originalUrl"] = url
    assert fetch()["assets"] == []
    assert source["file_urls"] == []


@pytest.mark.parametrize("total", [2, -1, True, None, "1"])
def test_incomplete_or_invalid_pagination_is_not_empty_success(source, total):
    source["assets"]["total"] = total
    result = fetch()
    assert result["state"] == "invalid_response"
    assert result["assets"] == []


def test_duplicate_asset_ids_rejected(source):
    source["assets"]["items"] *= 2
    source["assets"]["total"] = 2
    assert fetch()["state"] == "invalid_response"


@pytest.mark.parametrize("resource", ["sku", "product"])
def test_inactive_identity_stops_before_asset_read(source, resource):
    source[resource][resource]["status"] = "archived"
    assert fetch()["state"] == "invalid_response"
    assert len(source["urls"]) <= 2


def test_product_identity_mismatch_stops_before_asset_read(source):
    source["product"]["product"]["productCode"] = "OTHER"
    assert fetch()["state"] == "invalid_response"
    assert len(source["urls"]) == 2


def test_disabled_reader_makes_no_calls(source, monkeypatch):
    monkeypatch.delenv("COPILOT_PRODUCT_HUB_REVIEWED_MEDIA_ENABLED")
    assert fetch()["state"] == "disabled"
    assert source["urls"] == []


def test_source_error_is_not_no_manuals(source, monkeypatch):
    monkeypatch.setattr(client, "_read_json", lambda *a, **kw: (None, "unavailable"))
    result = fetch()
    assert result["state"] == "unavailable"
    assert result["assets"] == []


def test_different_identifiers_chinese_filename_and_exact_sku(source):
    sku, code = "SKU C/4", "PRODUCT C"
    source["sku"]["sku"].update(skuCode=sku, productCode=code)
    source["product"]["product"]["productCode"] = code
    item = source["assets"]["items"][0]
    item["skuId"] = "sku-record-b"
    item["canonicalName"] = "\u5b89\u88c5 \u8bf4\u660e\u4e66.pdf"
    item["originalUrl"] = "/api/asset?" + urlencode({
        "scope": "normalized", "relative": "catalog\\manual\\" + item["canonicalName"],
    })
    result = client.ProductHubReviewedFactsClient().fetch_manuals_for_sku(sku)
    assert result["assets"][0]["binding_scope"] == "sku"
    assert result["assets"][0]["asset_title"] == item["canonicalName"]


def test_installation_loader_uses_pdf_path_but_other_queries_keep_images(monkeypatch):
    calls = []
    monkeypatch.setattr(client.ProductHubReviewedFactsClient, "fetch_manuals_for_sku",
                        lambda self, sku: calls.append(("manual", sku)) or {})
    monkeypatch.setattr(client.ProductHubReviewedFactsClient, "fetch_reviewable_assets_for_sku",
                        lambda self, sku: calls.append(("image", sku)) or {})
    identity = {"sku": "SKU-X", "product_identity_resolution": {"status": "resolved"}}
    pack._load_product_hub_reviewed_media(identity, query_fact_type="installation")
    pack._load_product_hub_reviewed_media(identity, query_fact_type="material_composition")
    pack._load_product_hub_reviewed_media({"sku": "SKU-X"}, query_fact_type="installation")
    assert calls == [("manual", "SKU-X"), ("image", "SKU-X")]


def test_manual_is_review_reference_not_fact_sku_fit_or_sent_media(source):
    from app.services.admitted_answer_context_service import AdmittedAnswerContextService, canonical_selected_evidence
    from app.services.media_asset_service import build_reply_blocks

    identity = {"i_id": "internal-B", "sku": "SKU-B",
                "product_identity_resolution": {"status": "resolved"}}
    media = pack._product_hub_media_for_context(fetch(), identity=identity)
    assert len(media) == 1
    item = media[0]
    assert item["sku_scope"] == [] and item["sku_code"] == ""
    assert item["applicable_style"]["scope_type"] == "product"
    assert item["thumbnail_url"] == ""
    assert item["reference_only"] is True and item["usable_for_agent"] is False
    assert item["can_direct_answer"] is False and item["needs_human_review"] is True
    assert item["availability"] == "header_verified"
    admitted = AdmittedAnswerContextService().build_for_response(
        {"product_context_pack": {"media_assets": media}},
        product_identity={"i_id": "internal-B", "sku_code": "SKU-B"},
    )
    assert admitted["direct_product_facts"] == []
    assert canonical_selected_evidence(admitted) == []
    delivery = build_reply_blocks("review only", media, requires_human_review=True,
                                 query_fact_type="installation", product_identity=identity)
    assert all(block["type"] == "text" for block in delivery["reply_blocks"])
    assert delivery["reply_delivery"]["auto_send_ready"] is False


@pytest.mark.parametrize("override", [
    {"status": 204}, {"status": 302}, {"url": "https://external.invalid/manual.pdf"},
    {"prefix": b"<html"}, {"prefix": b"%PD"},
    {"headers": {"Content-Length": ""}}, {"headers": {"Content-Length": "6"}},
    {"headers": {"Content-Range": "bytes 0-4/124"}},
    {"headers": {"Content-Range": "bytes 5-9/123"}},
    {"headers": {"Content-Range": "bytes 0-4/*"}},
    {"headers": {"Content-Type": "text/html"}},
    {"headers": {"Content-Encoding": "gzip"}},
    {"status": 200, "headers": {"Content-Length": "122"}},
    {"error": TimeoutError()},
])
def test_bad_file_response_never_projects_a_reference(source, override):
    source["file_response"] = override
    result = fetch()
    assert result["state"] == "unavailable"
    assert result["assets"] == []
    assert result["catalog_candidate_count"] == 1
    assert len(result["file_failures"]) == 1


@pytest.mark.parametrize("status", [404, 500, 302])
def test_http_failures_are_closed_and_distinct_from_no_catalog(source, status):
    body = BytesIO(b"error")
    source["file_response"] = {"error": HTTPError("http://127.0.0.1/file", status, "error", {}, body)}
    result = fetch()
    assert result["assets"] == [] and body.closed
    assert result["state"] == "unavailable"
    assert result["file_failures"][0]["reason_code"] == ("not_found" if status == 404 else "http_unavailable")


def test_ignored_range_is_bounded_and_requires_catalog_length(source):
    source["file_response"] = {"status": 200, "headers": {"Content-Length": "123"}}
    assert fetch()["assets"][0]["availability"] == "header_verified"


def test_redirect_handler_refuses_even_same_origin_redirects():
    assert client._NoManualRedirect().redirect_request(None, None, 302, "", {}, "http://127.0.0.1/other") is None


def add_manuals(source, count):
    item = source["assets"]["items"][0]
    source["assets"].update(items=[{**deepcopy(item), "id": f"manual-{i}"} for i in range(count)], total=count)


def test_bad_file_does_not_hide_other_readable_files(source, monkeypatch):
    add_manuals(source, 3)
    monkeypatch.setattr(client, "_check_manual_file", lambda asset, **kw: "not_found" if asset["asset_id"] == "manual-1" else "")
    result = fetch()
    assert [x["asset_id"] for x in result["assets"]] == ["manual-0", "manual-2"]
    assert result["state"] == "ready" and len(result["file_failures"]) == 1


def test_file_checks_are_capped_and_independent_of_list_order(source):
    add_manuals(source, 6)
    source["assets"]["items"].reverse()
    result = fetch()
    assert len(source["file_urls"]) == 3
    assert [x["asset_id"] for x in result["assets"]] == ["manual-0", "manual-1", "manual-2"]
    assert result["unchecked_file_count"] == 3


def test_exhausted_budget_does_not_start_more_file_requests(source, monkeypatch):
    add_manuals(source, 3)
    clock = iter([0, 0, 6])
    monkeypatch.setattr(client, "monotonic", lambda: next(clock))
    result = fetch()
    assert len(source["file_urls"]) == 1 and result["unchecked_file_count"] == 2


@pytest.mark.parametrize("availability", ["not_checked", "unavailable", "content_verified"])
def test_context_pack_does_not_trust_old_or_unsupported_file_status(source, availability):
    result = fetch()
    result["assets"][0]["availability"] = availability
    identity = {"i_id": "internal-B", "sku": "SKU-B", "product_identity_resolution": {"status": "resolved"}}
    assert pack._product_hub_media_for_context(result, identity=identity) == []


def test_real_http_redirect_is_not_followed():
    from http.server import BaseHTTPRequestHandler, HTTPServer
    from threading import Thread

    paths = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            paths.append(self.path)
            self.send_response(302)
            self.send_header("Location", "/forbidden-target")
            self.send_header("Content-Length", "0")
            self.end_headers()

        def log_message(self, *args):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        asset = {"asset_url": f"http://127.0.0.1:{server.server_port}/api/asset", "size_bytes": 123}
        assert client._check_manual_file(asset, timeout=1) == "http_unavailable"
        assert paths == ["/api/asset"]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
