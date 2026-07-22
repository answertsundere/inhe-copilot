from __future__ import annotations

import hashlib

from scripts.diagnose_real_accuracy_label_store import diagnose, diagnose_config

from app.services.real_accuracy_label_service import RealAccuracyLabelStore


def _claim():
    return {
        "claim_uid": "claim-1",
        "claim_kind": "service_action",
        "query_fact_type": "aftersales",
        "attribute_key": "verify_issue",
        "expected_status": "supported",
        "required_action_points": ["verify"],
        "review_status": "draft",
        "proposal_status": "policy_validated",
        "source_reference": "source_reviewed_candidate",
    }


def _hash(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_label_store_diagnostic_is_read_only_and_content_free(tmp_path):
    path = tmp_path / "labels.db"
    RealAccuracyLabelStore(path).save(
        case_uid="training_sample_AAAAAAAAAAAAAAAAAAAA",
        dataset_version="0.2",
        claims=[_claim()],
        target_turn_uids=[],
        review_status="draft",
        actor_hash="reviewer_AAAAAAAAAAAAAAAAAAAA",
        actor_role="reviewer",
        auth_type="development",
        dataset_hash="a" * 64,
        expected_version=0,
        allow_approval=False,
    )
    before = _hash(path)

    result = diagnose(path, "0.2")

    assert result["file_name"] == "labels.db"
    assert result["record_count"] == 1
    assert result["claim_counts"]["draft"] == 1
    assert result["event_count"] == 1
    assert "path" not in result
    assert _hash(path) == before


def test_label_store_diagnostic_reports_missing_without_creating_file(tmp_path):
    path = tmp_path / "missing.db"
    result = diagnose(path, "0.2")
    assert result["exists"] is False
    assert not path.exists()


def test_config_diagnostic_requires_one_definition_and_exposes_no_paths(tmp_path):
    labels = tmp_path / "labels.db"
    RealAccuracyLabelStore(labels).initialize()
    gold = tmp_path / "gold.json"
    gold.write_text('{"dataset_id":"d","dataset_version":"0.2","manifest":{"content_sha256":"x"},"cases":[]}', encoding="utf-8")
    env = tmp_path / ".env"
    env.write_text(
        "COPILOT_REAL_ACCURACY_GOLD_SET_PATH=gold.json\n"
        "COPILOT_REAL_ACCURACY_LABEL_DB=labels.db\n",
        encoding="utf-8",
    )

    result = diagnose_config(env, "0.2")

    assert result["config_status"] == "ready"
    assert result["gold_set"]["file_name"] == "gold.json"
    assert result["label_store"]["file_name"] == "labels.db"
    assert str(tmp_path) not in str(result)

    env.write_text(env.read_text(encoding="utf-8") + "COPILOT_REAL_ACCURACY_LABEL_DB=other.db\n", encoding="utf-8")
    assert diagnose_config(env, "0.2")["config_status"] == "invalid"
