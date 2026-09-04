from __future__ import annotations


def test_runtime_version_exposes_only_public_deployment_metadata(monkeypatch):
    from flask import Flask
    from app.api import runtime_routes

    monkeypatch.setattr(runtime_routes, "_BOOT_BUILD_IDENTITY", {
        "app_version": "1.0.0",
        "runtime_commit": "test-value",
        "formal_model": "test-model",
        "formal_provider_identity": {
            "provider_name": "formal_agent",
            "host_fingerprint": "host-fingerprint",
            "model_name": "test-model",
            "configured": True,
            "identity": "host-fingerprint:test-model",
        },
        "action_policy_provider_identity": {
            "provider_name": "action_policy",
            "host_fingerprint": "action-host",
            "model_name": "action-model",
            "configured": True,
            "identity": "action-host:action-model",
        },
        "evidence_action_shadow_status": "paused_not_qualified",
        "feature_flags": {"answer_memory_shadow": False},
        "boot_worktree_dirty": False,
        "boot_source_tree_sha256": "boot-hash",
        "build_identity_status": "clean_commit",
        "formal_knowledge_query_only": True,
    })
    monkeypatch.setattr(runtime_routes, "_source_tree_sha256", lambda: "boot-hash")
    monkeypatch.setattr(runtime_routes, "_runtime_worktree_dirty", lambda: False)
    monkeypatch.setattr(
        "app.api.admin_auth.admin_auth_readiness",
        lambda: {"admin_auth_ready": True, "reason": ""},
    )
    monkeypatch.setattr(
        "app.services.runtime_knowledge_readiness_service.RuntimeKnowledgeReadinessService.inspect",
        lambda *_args: {
            "ready": True,
            "status": "ready",
            "reasons": [],
            "knowledge": {"entries": 1, "chunks": 1, "kb_qa": 1},
            "database": {"basename": "runtime.db"},
        },
    )

    app = Flask(__name__)
    with app.app_context():
        payload = runtime_routes.runtime_version().get_json()

    assert payload["runtime_commit"] == "test-value"
    assert payload["readiness"]["ready"] is True
    assert set(payload) == {
        "app_version", "runtime_commit", "formal_model", "formal_provider_identity",
        "action_policy_provider_identity", "evidence_action_shadow_status", "readiness", "feature_flags",
        "worktree_dirty", "source_tree_sha256", "boot_worktree_dirty", "boot_source_tree_sha256",
        "current_source_tree_sha256", "current_worktree_dirty", "source_tree_drift", "build_identity_status",
        "formal_knowledge_query_only",
    }
    assert isinstance(payload["feature_flags"], dict)
    assert payload["formal_provider_identity"] == {
        "provider_name": "formal_agent",
        "host_fingerprint": "host-fingerprint",
        "model_name": "test-model",
        "configured": True,
        "identity": "host-fingerprint:test-model",
    }
    assert isinstance(payload["source_tree_sha256"], str)
    assert payload["build_identity_status"] in {"clean_commit", "dirty_candidate", "source_identity_unavailable"}
    assert payload["formal_knowledge_query_only"] is True
    assert "database" not in payload["readiness"]
    assert "knowledge" not in payload["readiness"]


def test_runtime_identity_keeps_boot_hash_and_reports_disk_drift(monkeypatch):
    from app.api import runtime_routes

    monkeypatch.setattr(runtime_routes, "_BOOT_BUILD_IDENTITY", {
        "app_version": "1.0.0",
        "runtime_commit": "boot-commit",
        "formal_model": "model-a",
        "formal_provider_identity": {},
        "action_policy_provider_identity": {},
        "evidence_action_shadow_status": "paused_not_qualified",
        "feature_flags": {},
        "boot_worktree_dirty": True,
        "boot_source_tree_sha256": "hash-a",
        "build_identity_status": "dirty_candidate",
        "formal_knowledge_query_only": False,
    })
    monkeypatch.setattr(runtime_routes, "_source_tree_sha256", lambda: "hash-b")
    monkeypatch.setattr(runtime_routes, "_runtime_worktree_dirty", lambda: True)

    identity = runtime_routes._runtime_identity()

    assert identity["runtime_commit"] == "boot-commit"
    assert identity["source_tree_sha256"] == "hash-a"
    assert identity["boot_source_tree_sha256"] == "hash-a"
    assert identity["current_source_tree_sha256"] == "hash-b"
    assert identity["source_tree_drift"] is True


def test_runtime_feature_flags_expose_product_hub_read_bridge(monkeypatch):
    from app.api import runtime_routes

    monkeypatch.setenv("COPILOT_PRODUCT_HUB_REVIEWED_FACTS_ENABLED", "true")

    assert runtime_routes._feature_flags()["product_hub_reviewed_facts"] is True


def test_runtime_readiness_uses_503_without_exposing_database_path(monkeypatch):
    from flask import Flask
    from app.api import runtime_routes

    monkeypatch.setattr(
        "app.services.runtime_knowledge_readiness_service.RuntimeKnowledgeReadinessService.inspect",
        lambda *_args: {
            "ready": False,
            "status": "not_ready",
            "reasons": ["knowledge_db_missing"],
            "knowledge": {"entries": 0, "chunks": 0, "kb_qa": 0},
            "database": {"basename": "knowledge_base.db"},
        },
    )
    monkeypatch.setattr("app.api.admin_auth.admin_auth_readiness", lambda: {"admin_auth_ready": True, "reason": ""})
    app = Flask(__name__)
    app.register_blueprint(runtime_routes.runtime_bp)

    response = app.test_client().get("/api/runtime/readiness")

    assert response.status_code == 503
    assert response.get_json()["reasons"] == ["knowledge_db_missing"]
    assert set(response.get_json()) == {"ready", "status", "reasons"}
    assert "knowledge_base.db" not in response.get_data(as_text=True)


def test_runtime_diagnostics_keeps_database_fingerprint_off_public_routes(monkeypatch):
    from flask import Flask
    from app.api import runtime_routes

    monkeypatch.setattr(
        "app.services.runtime_knowledge_readiness_service.RuntimeKnowledgeReadinessService.inspect",
        lambda *_args: {
            "ready": True,
            "status": "ready",
            "reasons": [],
            "knowledge": {"entries": 1, "chunks": 1, "kb_qa": 1},
            "database": {"basename": "runtime.db", "content_sha256": "fingerprint"},
        },
    )
    monkeypatch.setattr("app.api.admin_auth.admin_auth_readiness", lambda: {"admin_auth_ready": True, "reason": ""})
    app = Flask(__name__)
    with app.app_context():
        payload = runtime_routes.runtime_diagnostics().get_json()

    assert payload["readiness"]["database"]["content_sha256"] == "fingerprint"
