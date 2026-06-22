from tests.test_eval_routes import _client


def test_eval_routes_block_operator(monkeypatch):
    client = _client(monkeypatch)

    response = client.get("/api/eval/cases", headers={"X-User-Role": "operator"})

    assert response.status_code == 403


def test_eval_routes_allow_supervisor_for_dry_run(monkeypatch):
    client = _client(monkeypatch)
    client.post(
        "/api/eval/cases",
        json={"case_uid": "auth_case", "customer_message": "尺寸多大？"},
        headers={"X-User-Role": "supervisor"},
    )

    response = client.post(
        "/api/eval/runs",
        json={"limit": 5, "apply": False},
        headers={"X-User-Role": "supervisor"},
    )

    assert response.status_code == 201
    assert response.get_json()["status"] == "dry_run"


def test_eval_run_apply_true_requires_supervisor(monkeypatch):
    client = _client(monkeypatch)

    denied = client.post("/api/eval/runs", json={"limit": 1, "apply": True}, headers={"X-User-Role": "operator"})
    allowed = client.post("/api/eval/runs", json={"limit": 1, "apply": False}, headers={"X-User-Role": "supervisor"})

    assert denied.status_code == 403
    assert allowed.status_code == 201
