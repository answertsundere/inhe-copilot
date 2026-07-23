from __future__ import annotations

import json
import sqlite3
from copy import deepcopy

import pytest
from flask import Flask

from app.api import admin_auth
from app.api.high_quality_long_conversation_review_routes import high_quality_review_bp
from app.services.high_quality_long_conversation_review_service import (
    HighQualityReviewLabelError,
    HighQualityReviewLabelStore,
    build_approved_review_manifest,
    build_review_inventory,
)
from app.services.long_conversation_simulation_service import _content_hash


def _dataset():
    scenario = {
        "scenario_uid": "scenario-0123456789abcdefabcd",
        "scenario_title": "材质事实和安全边界",
        "business_domain": "商品材质",
        "risk_level": "medium",
        "current_buyer_message": "这款是什么材质，能否确认安全？",
        "conversation_history": [
            {"turn_uid": "turn-0123456789abcdefabcd", "turn_index": 1, "role": "customer", "content": "之前问过尺寸。", "message_type": "text"},
            {"turn_uid": "turn-1123456789abcdefabcd", "turn_index": 2, "role": "agent", "content": "宽度是 80 厘米。", "message_type": "text"},
        ],
        "product_context": {"product_name": "测试收纳架", "i_id": "PRIVATE-ID", "sku_code": "PRIVATE-SKU", "product_id": 99},
        "order_context": {"order_id": "", "real_order_data_included": False},
        "gold_reply": "这款材质是 PP；仅凭材质名称不能确认无毒或认证。",
        "expected_claims": [{"claim_uid": "claim-0123456789abcdefabcd", "claim_type": "material", "expected_status": "supported", "required_answer_points": ["PP"]}],
        "source_evidence": [{"evidence_uid": "evidence-0123456789abcdefabcd", "fact_type": "material", "attribute_key": "material", "content": "PP", "review_status": "published", "evidence_role": "product_fact_direct", "direct_answer_allowed": True}],
        "required_actions": ["直接回答材质"],
        "forbidden_claims": ["保证无毒"],
        "must_handoff": False,
        "review": {"status": "draft"},
    }
    scenario["content_sha256"] = _content_hash(scenario)
    payload = {
        "schema_version": "high-quality-long-conversation-review/v1",
        "dataset_id": "hq-review-test",
        "dataset_version": "1.0.0",
        "manifest": {"scenario_count": 1, "approved_scenario_count": 0},
        "scenarios": [scenario],
    }
    payload["manifest"]["content_sha256"] = _content_hash(payload)
    return payload


def _save(store, dataset, *, status, version, auth_type="cloudflare_access", scenario_index=0, **overrides):
    scenario = dataset["scenarios"][scenario_index]
    values = {
        "dataset_id": dataset["dataset_id"],
        "dataset_version": dataset["dataset_version"],
        "dataset_sha256": dataset["manifest"]["content_sha256"],
        "scenario_uid": scenario["scenario_uid"],
        "gold_reply_original": scenario["gold_reply"],
        "gold_reply_revised": scenario["gold_reply"],
        "fact_correct": True,
        "business_action_correct": True,
        "safety_boundary_correct": True,
        "human_tone_correct": True,
        "notes": "人工核对完成",
        "requested_status": status,
        "actor_hmac": "reviewer_0123456789abcdefabcd",
        "actor_role": "supervisor",
        "auth_type": auth_type,
        "expected_version": version,
    }
    values.update(overrides)
    return store.save(**values)


def _dataset_with_scenario_count(count: int):
    payload = _dataset()
    template = payload["scenarios"][0]
    scenarios = []
    for index in range(count):
        scenario = deepcopy(template)
        scenario["scenario_uid"] = f"scenario-{index:020x}"
        scenario["business_domain"] = f"domain-{index % 7}"
        row = deepcopy(scenario)
        row.pop("content_sha256", None)
        scenario["content_sha256"] = _content_hash(row)
        scenarios.append(scenario)
    payload["scenarios"] = scenarios
    payload["manifest"] = {"scenario_count": count, "approved_scenario_count": 0}
    payload["manifest"]["content_sha256"] = _content_hash(payload)
    return payload


def test_inventory_and_store_are_independent_and_immutable(tmp_path):
    dataset = _dataset()
    source = tmp_path / "review.json"
    source.write_text(json.dumps(dataset, ensure_ascii=False), encoding="utf-8")
    original = source.read_bytes()
    store = HighQualityReviewLabelStore(tmp_path / "labels.sqlite")

    inventory = build_review_inventory(dataset)
    _save(store, dataset, status="draft", version=0)

    assert inventory["scenario_count"] == 1
    assert inventory["current_buyer_turn_count"] == 1
    assert inventory["conversation_history_turn_count"] == 2
    assert inventory["expected_claim_count"] == 1
    assert inventory["privacy_finding_count"] == 0
    assert source.read_bytes() == original
    assert not (tmp_path / "knowledge_base.db").exists()
    manifest = build_approved_review_manifest(dataset, store)
    assert manifest["draft_count"] == 1
    assert manifest["agent_call_allowed"] is False
    assert manifest["accuracy_claim_allowed"] is False


def test_approval_manifest_requires_all_checks_audit_and_contiguous_versions(tmp_path):
    dataset = _dataset()
    store = HighQualityReviewLabelStore(tmp_path / "labels.sqlite")
    _save(store, dataset, status="approved", version=0)

    manifest = build_approved_review_manifest(dataset, store)
    assert manifest["approved_count"] == 1
    assert manifest["approval_event_count"] == 1
    assert manifest["agent_call_allowed"] is True
    assert manifest["accuracy_claim_allowed"] is True
    assert manifest["status"] == "approved_for_evaluation"
    assert len(manifest["manifest_sha256"]) == 64

    with sqlite3.connect(store.path) as connection:
        connection.execute("DELETE FROM hq_review_audit_event")
        connection.commit()
    invalid = build_approved_review_manifest(dataset, store)
    assert invalid["approved_count"] == 0
    assert invalid["agent_call_allowed"] is False
    assert invalid["accuracy_claim_allowed"] is False


def test_manifest_rejects_missing_or_discontinuous_audit_history(tmp_path):
    dataset = _dataset()
    store = HighQualityReviewLabelStore(tmp_path / "labels.sqlite")
    _save(store, dataset, status="approved", version=0)
    with sqlite3.connect(store.path) as connection:
        connection.execute(
            "UPDATE hq_review_audit_event SET previous_version=7,new_version=8"
        )
        connection.commit()

    manifest = build_approved_review_manifest(dataset, store)

    assert manifest["approved_count"] == 0
    assert manifest["agent_call_allowed"] is False
    assert any(item.startswith("optimistic_lock_history_invalid:") for item in manifest["audit_findings"])


def test_manifest_requires_all_26_current_scenarios_to_be_approved(tmp_path):
    dataset = _dataset_with_scenario_count(26)
    store = HighQualityReviewLabelStore(tmp_path / "labels.sqlite")
    for index in range(25):
        _save(store, dataset, status="approved", version=0, scenario_index=index)

    partial = build_approved_review_manifest(dataset, store)
    assert partial["approved_count"] == 25
    assert partial["agent_call_allowed"] is False
    assert partial["accuracy_claim_allowed"] is False
    assert partial["status"] == "awaiting_supervisor_approval"

    _save(store, dataset, status="approved", version=0, scenario_index=25)
    complete = build_approved_review_manifest(dataset, store)
    assert complete["approved_count"] == 26
    assert complete["approval_event_count"] == 26
    assert complete["agent_call_allowed"] is True
    assert complete["accuracy_claim_allowed"] is True
    assert complete["status"] == "approved_for_evaluation"


def test_approved_revision_returns_to_reviewed_and_hash_change_invalidates(tmp_path):
    dataset = _dataset()
    store = HighQualityReviewLabelStore(tmp_path / "labels.sqlite")
    _save(store, dataset, status="approved", version=0)
    revised = _save(
        store, dataset, status="draft", version=1,
        gold_reply_revised="这款材质是 PP，安全认证信息仍需单独核对。",
    )
    assert revised["status"] == "reviewed"
    assert revised["version"] == 2
    assert build_approved_review_manifest(dataset, store)["approved_count"] == 0

    changed = deepcopy(dataset)
    changed["dataset_version"] = "1.0.1"
    changed["manifest"].pop("content_sha256")
    changed["manifest"]["content_sha256"] = _content_hash(changed)
    manifest = build_approved_review_manifest(changed, store)
    assert manifest["approved_count"] == 0
    assert manifest["status"] == "awaiting_supervisor_approval"


def test_approval_rejects_false_checks_and_non_cloudflare_identity(tmp_path):
    dataset = _dataset()
    store = HighQualityReviewLabelStore(tmp_path / "labels.sqlite")
    with pytest.raises(HighQualityReviewLabelError, match="all_manual_checks"):
        _save(store, dataset, status="approved", version=0, fact_correct=False)
    with pytest.raises(HighQualityReviewLabelError, match="authoritative_supervisor"):
        _save(store, dataset, status="approved", version=0, auth_type="development")
    with pytest.raises(HighQualityReviewLabelError, match="rejection_reason"):
        _save(store, dataset, status="rejected", version=0, notes="")


def test_routes_fail_closed_and_enforce_reviewer_supervisor_boundaries(monkeypatch, tmp_path):
    dataset = _dataset()
    source = tmp_path / "review.json"
    source.write_text(json.dumps(dataset, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setenv("COPILOT_HQ_LONG_CONVERSATION_REVIEW_SET_PATH", str(source))
    monkeypatch.setenv("COPILOT_HQ_LONG_CONVERSATION_LABEL_DB", str(tmp_path / "labels.sqlite"))
    monkeypatch.setenv("COPILOT_REAL_ACCURACY_LABEL_AUDIT_HMAC_KEY", "audit-test-key")
    monkeypatch.setenv("COPILOT_ADMIN_ALLOWED_ORIGINS", "http://localhost")
    app = Flask(__name__)
    app.register_blueprint(high_quality_review_bp)
    client = app.test_client()
    uid = dataset["scenarios"][0]["scenario_uid"]
    payload = {
        "gold_reply_revised": dataset["scenarios"][0]["gold_reply"],
        "fact_correct": True,
        "business_action_correct": True,
        "safety_boundary_correct": True,
        "human_tone_correct": True,
        "notes": "人工核对完成",
        "version": 0,
    }

    monkeypatch.setattr(admin_auth, "_verified_principal", lambda: (_ for _ in ()).throw(admin_auth.AdminAuthError("access_assertion_missing")))
    assert client.get("/api/kb/hq-long-conversation-review", headers={"X-User-Role": "admin", "X-User-Name": "fake"}).status_code == 401

    monkeypatch.setattr(admin_auth, "_verified_principal", lambda: admin_auth.AdminPrincipal("operator", "operator", frozenset({"operator"}), "test"))
    assert client.get("/api/kb/hq-long-conversation-review").status_code == 403

    monkeypatch.setattr(admin_auth, "_verified_principal", lambda: admin_auth.AdminPrincipal("reviewer", "reviewer", frozenset({"reviewer"}), "test"))
    assert client.get("/api/kb/hq-long-conversation-review").status_code == 200
    assert client.post(f"/api/kb/hq-long-conversation-review/{uid}/draft", json=payload).status_code == 201
    payload["version"] = 1
    assert client.post(f"/api/kb/hq-long-conversation-review/{uid}/submit", json=payload).status_code == 201
    payload["version"] = 2
    assert client.post(f"/api/kb/hq-long-conversation-review/{uid}/approve", json=payload).status_code == 403

    monkeypatch.setattr(admin_auth, "_verified_principal", lambda: admin_auth.AdminPrincipal("supervisor", "supervisor", frozenset({"supervisor"}), "cloudflare_access"))
    headers = {"Origin": "http://localhost"}
    approved = client.post(f"/api/kb/hq-long-conversation-review/{uid}/approve", json=payload, headers=headers)
    assert approved.status_code == 201
    assert approved.get_json()["label"]["status"] == "approved"
    assert client.post(f"/api/kb/hq-long-conversation-review/{uid}/approve", json=payload, headers=headers).status_code == 409
    assert client.post("/api/kb/hq-long-conversation-review/batch-approve", json={}, headers=headers).status_code in {404, 405}

    listed = client.get("/api/kb/hq-long-conversation-review")
    assert "conversation_history" not in listed.get_json()["items"][0]
    row = client.get(f"/api/kb/hq-long-conversation-review/{uid}").get_json()["scenario"]
    assert "i_id" not in row["product_context"]
    assert "sku_code" not in row["product_context"]
    assert "product_id" not in row["product_context"]
    manifest = client.get("/api/kb/hq-long-conversation-review/manifest").get_json()
    assert manifest["approved_count"] == 1
    assert manifest["agent_call_allowed"] is True
    assert manifest["accuracy_claim_allowed"] is True


def test_full_app_registers_high_quality_review_routes():
    from app.main import create_app

    app = create_app()
    rules = {rule.rule for rule in app.url_map.iter_rules()}
    assert "/high-quality-conversation-review" in rules
    assert "/api/kb/hq-long-conversation-review" in rules


def test_frontend_uses_chinese_labels_instead_of_rendering_raw_enums():
    from pathlib import Path

    source = (Path(__file__).resolve().parents[1] / "frontend" / "src" / "views" / "HighQualityConversationReviewPage.vue").read_text(encoding="utf-8")
    assert "高质量长对话审核" in source
    assert "商品事实正确" in source
    assert "处理动作正确" in source
    assert "像真人金牌客服" in source
    assert "{{ claim.expected_status }}" not in source
    assert "{{ selected.risk_level }}" not in source
