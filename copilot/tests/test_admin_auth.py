from flask import Flask


def test_require_supervisor_blocks_operator():
    from app.api.admin_auth import require_supervisor

    app = Flask(__name__)
    with app.test_request_context("/", headers={"X-User-Role": "operator"}):
        response = require_supervisor()

    assert response is not None
    body, status = response
    assert status == 403
    assert body.get_json()["required_role"] == "supervisor"


def test_require_supervisor_blocks_missing_role_header():
    from app.api.admin_auth import get_user_role, require_supervisor

    app = Flask(__name__)
    with app.test_request_context("/"):
        response = require_supervisor()
        role = get_user_role()

    assert role == "operator"
    assert response is not None
    assert response[1] == 403


def test_require_supervisor_allows_supervisor_and_admin():
    from app.api.admin_auth import require_supervisor

    app = Flask(__name__)
    for role in ("supervisor", "admin"):
        with app.test_request_context("/", headers={"X-User-Role": role}):
            assert require_supervisor() is None


def test_require_admin_blocks_supervisor():
    from app.api.admin_auth import require_admin

    app = Flask(__name__)
    with app.test_request_context("/", headers={"X-User-Role": "supervisor"}):
        response = require_admin()

    assert response is not None
    assert response[1] == 403
