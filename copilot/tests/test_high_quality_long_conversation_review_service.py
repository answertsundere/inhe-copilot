from __future__ import annotations

from copy import deepcopy

import pytest

from app.services.high_quality_long_conversation_review_service import validate_review_dataset
from app.services.long_conversation_simulation_service import _content_hash


def _dataset(*, approved: bool = False):
    review = {
        "status": "approved" if approved else "draft",
        "reviewer_decision": "approve" if approved else "",
        "fact_boundary_approved": approved,
        "action_boundary_approved": approved,
        "gold_reply_approved": approved,
        "optimistic_lock_version": 2 if approved else 0,
        "approval_audit": {
            "event_type": "scenario_approved",
            "actor_role": "supervisor",
            "version": 2,
        } if approved else {},
    }
    scenario = {
        "scenario_uid": "scenario-0123456789abcdefabcd",
        "scenario_title": "材质事实和安全边界",
        "business_domain": "商品材质",
        "current_buyer_message": "这款是什么材质，能否确认安全？",
        "gold_reply": "材质是 PP；仅凭材质名称不能确认无毒或认证结论。",
        "review": review,
    }
    scenario["content_sha256"] = _content_hash(scenario)
    payload = {
        "schema_version": "high-quality-long-conversation-review/v1",
        "dataset_id": "review-set-test",
        "dataset_version": "1.0.0",
        "manifest": {"scenario_count": 1, "approved_scenario_count": int(approved)},
        "scenarios": [scenario],
    }
    hash_payload = deepcopy(payload)
    payload["manifest"]["content_sha256"] = _content_hash(hash_payload)
    return payload


def test_unapproved_review_set_exits_before_agent_execution():
    report = validate_review_dataset(_dataset())

    assert report["validation_status"] == "passed"
    assert report["evaluation_status"] == "awaiting_supervisor_approval"
    assert report["agent_call_allowed"] is False
    assert report["accuracy_claim_allowed"] is False
    assert report["exit_code"] == 2


def test_embedded_approved_review_never_grants_evaluation_authority():
    report = validate_review_dataset(_dataset(approved=True))
    assert report["validation_status"] == "failed"
    assert "embedded_authoritative_review_forbidden" in report["findings"]
    assert report["evaluation_status"] == "invalid_dataset"
    assert report["agent_call_allowed"] is False
    assert report["accuracy_claim_allowed"] is False
    assert report["exit_code"] == 2


@pytest.mark.parametrize(
    "forged_review",
    [
        {"status": "approved", "reviewer_role": "supervisor"},
        {"status": "approved", "auth_type": "cloudflare_access"},
        {
            "status": "approved",
            "approval_audit": {"event_type": "scenario_approved", "version": 1},
            "optimistic_lock_version": 1,
        },
    ],
)
def test_embedded_authority_forgery_is_rejected_even_with_valid_hashes(forged_review):
    payload = _dataset()
    payload["scenarios"][0]["review"].update(forged_review)
    row = deepcopy(payload["scenarios"][0])
    row.pop("content_sha256")
    payload["scenarios"][0]["content_sha256"] = _content_hash(row)
    payload["manifest"].pop("content_sha256")
    payload["manifest"]["content_sha256"] = _content_hash(payload)

    report = validate_review_dataset(payload)

    assert "embedded_authoritative_review_forbidden" in report["findings"]
    assert report["agent_call_allowed"] is False
    assert report["accuracy_claim_allowed"] is False
    assert report["exit_code"] == 2


def test_mojibake_fails_before_review_or_agent_call():
    payload = _dataset()
    payload["scenarios"][0]["gold_reply"] = "���ϲ�����"
    row = deepcopy(payload["scenarios"][0])
    row.pop("content_sha256")
    payload["scenarios"][0]["content_sha256"] = _content_hash(row)
    payload["manifest"].pop("content_sha256")
    payload["manifest"]["content_sha256"] = _content_hash(payload)

    report = validate_review_dataset(payload)

    assert "mojibake_customer_content" in report["findings"]
    assert report["evaluation_status"] == "invalid_dataset"
    assert report["agent_call_allowed"] is False
    assert report["exit_code"] == 2


def test_fake_approval_without_supervisor_audit_is_still_forbidden_source_data():
    payload = _dataset(approved=True)
    payload["scenarios"][0]["review"]["approval_audit"] = {}
    row = deepcopy(payload["scenarios"][0])
    row.pop("content_sha256")
    payload["scenarios"][0]["content_sha256"] = _content_hash(row)
    payload["manifest"]["approved_scenario_count"] = 0
    payload["manifest"].pop("content_sha256")
    payload["manifest"]["content_sha256"] = _content_hash(payload)

    report = validate_review_dataset(payload)

    assert "embedded_authoritative_review_forbidden" in report["findings"]
    assert report["agent_call_allowed"] is False


def test_manifest_privacy_is_scanned_while_hash_fields_remain_allowed():
    payload = _dataset()
    payload["manifest"]["source_note"] = "https://private.example.test/source"
    payload["manifest"].pop("content_sha256")
    payload["manifest"]["content_sha256"] = _content_hash(payload)

    report = validate_review_dataset(payload)

    assert report["privacy_finding_count"] > 0
    assert "privacy_scan_failed" in report["findings"]
    assert report["agent_call_allowed"] is False


def test_unvalidated_controlled_digest_cannot_bypass_privacy_scan():
    payload = _dataset()
    payload["scenarios"][0]["source_conversation_digest"] = "not-a-valid-sha256"
    row = deepcopy(payload["scenarios"][0])
    row.pop("content_sha256")
    payload["scenarios"][0]["content_sha256"] = _content_hash(row)
    payload["manifest"].pop("content_sha256")
    payload["manifest"]["content_sha256"] = _content_hash(payload)

    report = validate_review_dataset(payload)

    assert "controlled_hash_invalid:source_conversation_digest" in report["findings"]
    assert report["agent_call_allowed"] is False
