import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_retired_legacy_pages_are_not_served():
    from app.main import create_app

    app = create_app()
    app.config["TESTING"] = True

    with app.test_client() as client:
        for path in ("/graph", "/api-test", "/api-debug"):
            resp = client.get(path)
            assert resp.status_code == 404


def test_kb_admin_spa_is_served_from_ask_root():
    from app.main import create_app

    app = create_app()
    app.config["TESTING"] = True

    with app.test_client() as client:
        assert client.get("/").status_code == 200
        assert client.get("/products").status_code == 200
        assert client.get("/media-observation-review").status_code == 200

        legacy = client.get("/kb-admin/products", follow_redirects=False)
        assert legacy.status_code == 302
        assert legacy.headers["Location"].endswith("/ask/products")
