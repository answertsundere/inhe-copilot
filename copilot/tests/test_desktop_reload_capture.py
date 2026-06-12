import os

import pytest


@pytest.fixture
def client():
    from app.main import create_app

    app = create_app()
    app.config["TESTING"] = True
    return app.test_client()


def test_desktop_bridge_exposes_capture_once():
    from desktop.api_bridge import ApiBridge

    bridge = ApiBridge()
    assert hasattr(bridge, "capture_qianniu_once")
    assert hasattr(bridge, "get_sidecar_latest")


def test_desktop_reload_button_calls_sidecar_capture():
    path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "desktop",
        "pages",
        "index.html",
    )
    with open(path, "r", encoding="utf-8") as f:
        html = f.read()

    assert "reloadQianniu" in html
    assert "capture_qianniu_once" in html
    assert "pollLatest" in html
    assert "get_sidecar_latest" in html
    assert "[重新读取中...]" not in html


def test_sidecar_latest_api_returns_latest_analysis(client):
    resp = client.post("/api/sidecar/status", json={
        "latest_customer_message": "我的快递什么时候到",
        "latest_message_hash": "hash-1",
        "latest_analyzed_at": "2026-06-04T10:00:00",
        "latest_analysis": {"ok": True, "suggested_reply": "亲，我帮您核实。"},
        "analysis_status": "analyzed",
        "auto_analyze_enabled": True,
    })
    assert resp.status_code == 200

    latest = client.get("/api/sidecar/latest")
    data = latest.get_json()
    assert data["ok"] is True
    assert data["latest_message_hash"] == "hash-1"
    assert data["latest_analysis"]["suggested_reply"] == "亲，我帮您核实。"
    assert data["auto_analyze_enabled"] is True
