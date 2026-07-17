"""Public health endpoint tests."""

from __future__ import annotations

import os
import tempfile

import pytest


@pytest.fixture
def client():
    from app.main import create_app

    with tempfile.TemporaryDirectory() as tmpdir:
        os.environ["COPILOT_FEEDBACK_FILE"] = os.path.join(tmpdir, "feedback.jsonl")
        os.environ["COPILOT_REVIEW_QUEUE_FILE"] = os.path.join(tmpdir, "review_queue.jsonl")
        app = create_app()
        app.config["TESTING"] = True
        with app.test_client() as test_client:
            yield test_client
        os.environ.pop("COPILOT_FEEDBACK_FILE", None)
        os.environ.pop("COPILOT_REVIEW_QUEUE_FILE", None)


def test_health_is_public_liveness_with_minimal_readiness(client):
    response = client.get("/api/health")

    assert response.status_code == 200
    payload = response.get_json()
    assert set(payload) == {"status", "version", "ready", "readiness_status", "readiness_reasons"}
    assert payload["status"] == "ok"
    assert payload["version"] == "copilot-v2"
    assert isinstance(payload["ready"], bool)
    assert isinstance(payload["readiness_reasons"], list)


def test_health_does_not_expose_runtime_or_secret_details(client):
    text = client.get("/api/health").get_data(as_text=True).lower()

    for prohibited in (
        "content_sha256",
        "schema_fingerprint",
        "knowledge_base",
        "access_token",
        "api_key",
        "client_secret",
        "bearer ",
        "sk-",
    ):
        assert prohibited not in text
