from tests.test_model_ops_routes import _client, _seed_calls


def test_model_ops_blocks_operator(monkeypatch):
    client = _client(monkeypatch)
    _seed_calls()

    response = client.get("/api/model-ops/calls", headers={"X-User-Role": "operator"})

    assert response.status_code == 403


def test_model_ops_blocks_missing_role_header(monkeypatch):
    client = _client(monkeypatch)
    _seed_calls()

    response = client.get("/api/model-ops/calls")

    assert response.status_code == 403


def test_model_ops_allows_supervisor(monkeypatch):
    client = _client(monkeypatch)
    _seed_calls()

    response = client.get("/api/model-ops/summary", headers={"X-User-Role": "supervisor"})

    assert response.status_code == 200
    assert response.get_json()["total_calls"] == 2


def test_model_ops_allows_admin(monkeypatch):
    client = _client(monkeypatch)
    _seed_calls()

    response = client.get("/api/model-ops/summary", headers={"X-User-Role": "admin"})

    assert response.status_code == 200
    assert response.get_json()["total_calls"] == 2
