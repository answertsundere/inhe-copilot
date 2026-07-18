from flask import Flask

from app.api import admin_auth
from app.api.material_review_routes import material_review_bp
from app.services.material_review_batch_service import MaterialReviewStagingStore


def _principal(role):
    return admin_auth.AdminPrincipal(
        subject="test-subject",
        display_name="reviewer-hmac",
        roles=frozenset({role}),
        auth_type="test",
    )


def test_operator_cannot_decide_but_supervisor_can(monkeypatch, tmp_path):
    store = MaterialReviewStagingStore(tmp_path / "material-review.db")
    store.seed([{
        "batch_uid": "material-batch-test",
        "decision_scope": {},
        "impacted_count": 1,
        "status_distribution": {},
        "sample_entry_uids": [],
        "available_actions": ["downgrade_to_human_review"],
        "dry_run": {"formal_kb_writes": 0},
        "version": 1,
    }])
    monkeypatch.setenv("COPILOT_MATERIAL_REVIEW_STAGING_DB", str(tmp_path / "material-review.db"))
    monkeypatch.setattr(admin_auth, "_csrf_allowed", lambda _principal: True)
    app = Flask(__name__)
    app.register_blueprint(material_review_bp)

    monkeypatch.setattr(admin_auth, "_verified_principal", lambda: _principal("operator"))
    denied = app.test_client().post(
        "/api/kb/material-review/batches/material-batch-test/decision",
        json={"action": "downgrade_to_human_review", "expected_version": 1},
    )
    assert denied.status_code == 403

    monkeypatch.setattr(admin_auth, "_verified_principal", lambda: _principal("supervisor"))
    allowed = app.test_client().post(
        "/api/kb/material-review/batches/material-batch-test/decision",
        json={"action": "downgrade_to_human_review", "expected_version": 1},
    )
    assert allowed.status_code == 200
    assert allowed.get_json()["formal_kb_writes"] == 0
