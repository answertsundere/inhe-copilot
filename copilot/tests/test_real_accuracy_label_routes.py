from __future__ import annotations

import json

from flask import Flask

from app.api import admin_auth
from app.api.real_accuracy_label_routes import real_accuracy_label_bp
from app.services.real_accuracy_gold_set_service import build_gold_dataset, build_gold_dataset_v2
from app.services.real_accuracy_label_service import RealAccuracyLabelStore


def _dataset():
    return build_gold_dataset("test-hmac", [{
        "id": 1, "customer_quote": "宽度是多少？", "full_context": (
            '<div class="imui-msg imui-msg-l"><div class="msg-body-text">宽度是多少？</div></div>'
            '<div class="imui-msg imui-msg-r"><div class="msg-body-text">我帮您查看。</div></div>'
        ),
        "product_title": "测试商品", "sku": "TEST-SKU", "order_no": "TEST-ORDER",
        "question_type": "尺寸", "correct_answer": "宽度请看商品资料。", "review_status": "已确认",
        "risk_level": "low", "need_media": False, "auto_reply_type": "需人工确认", "notes": "",
    }])[0]


def _claim():
    return [{
        "claim_uid": "claim-1", "claim_kind": "product_fact", "query_fact_type": "dimensions",
        "attribute_key": "width", "expected_status": "supported", "acceptable_values": ["80"],
        "normalized_value": "80", "unit": "cm", "required_terms": ["80"],
        "supporting_evidence_uids": ["evidence-1"], "required_tool": None, "required_action_points": [],
        "must_handoff": False, "forbidden_claims": [], "partial_answer_allowed": False, "review_status": "approved",
    }]


def test_label_routes_require_reviewer_and_keep_labels_out_of_knowledge(monkeypatch, tmp_path):
    dataset = _dataset()
    gold_path = tmp_path / "gold.json"
    gold_path.write_text(json.dumps(dataset, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setenv("COPILOT_REAL_ACCURACY_GOLD_SET_PATH", str(gold_path))
    monkeypatch.setenv("COPILOT_REAL_ACCURACY_LABEL_DB", str(tmp_path / "labels.db"))
    monkeypatch.setenv("COPILOT_REAL_ACCURACY_LABEL_AUDIT_HMAC_KEY", "audit-test-key")
    app = Flask(__name__)
    app.register_blueprint(real_accuracy_label_bp)
    client = app.test_client()
    case_uid = dataset["cases"][0]["case_uid"]
    buyer_turn_uid = next(
        turn["turn_uid"] for turn in dataset["cases"][0]["conversation"]["turns"]
        if turn["speaker_role"] == "BUYER"
    )
    agent_turn_uid = next(
        turn["turn_uid"] for turn in dataset["cases"][0]["conversation"]["turns"]
        if turn["speaker_role"] == "AGENT"
    )

    monkeypatch.setattr(admin_auth, "_verified_principal", lambda: admin_auth.AdminPrincipal("operator", "operator", frozenset({"operator"}), "test"))
    with app.app_context():
        assert admin_auth.route_policy("real_accuracy_labels.list_cases", "GET")[0] == "reviewer_write"
    assert client.get("/api/kb/real-accuracy/cases").status_code == 403
    assert client.post(f"/api/kb/real-accuracy/cases/{case_uid}/labels", json={"claims": _claim()}).status_code == 403

    monkeypatch.setattr(admin_auth, "_verified_principal", lambda: admin_auth.AdminPrincipal("reviewer", "reviewer", frozenset({"reviewer"}), "test"))
    list_response = client.get("/api/kb/real-accuracy/cases")
    assert list_response.status_code == 200
    summary = list_response.get_json()["workflow_summary"]
    assert summary["review_scope"] == "gold_30"
    assert summary["selected_claim_count"] > 0
    assert summary["approved_claim_count"] == 0
    assert summary["pending_claim_count"] == summary["selected_claim_count"]
    assert summary["auth_mode"] == "test"
    assert summary["cloudflare_access_verified"] is False
    assert summary["authoritative_approval_allowed"] is False
    forbidden = client.post(f"/api/kb/real-accuracy/cases/{case_uid}/labels", json={
        "claims": _claim(), "target_turn_uids": [buyer_turn_uid], "review_status": "approved", "optimistic_lock_version": 0,
    })
    assert forbidden.status_code == 422

    monkeypatch.setattr(admin_auth, "_verified_principal", lambda: admin_auth.AdminPrincipal("supervisor", "supervisor", frozenset({"supervisor"}), "test"))
    assert client.post(f"/api/kb/real-accuracy/cases/{case_uid}/labels", json={
        "claims": _claim(), "target_turn_uids": [agent_turn_uid], "review_status": "approved", "optimistic_lock_version": 0,
    }).get_json()["error"] == "target_turn_must_be_buyer"
    assert client.post(f"/api/kb/real-accuracy/cases/{case_uid}/labels", json={
        "claims": _claim(), "target_turn_uids": ["turn_AAAAAAAAAAAAAAAAAAAA"], "review_status": "approved", "optimistic_lock_version": 0,
    }).get_json()["error"] == "target_turn_not_in_case"
    response = client.post(f"/api/kb/real-accuracy/cases/{case_uid}/labels", json={
        "claims": _claim(), "target_turn_uids": [buyer_turn_uid], "review_status": "approved", "optimistic_lock_version": 0,
    })
    assert response.status_code == 201
    assert response.get_json()["label"]["review_status"] == "approved"
    assert response.get_json()["label"]["label"]["target_turn_uids"] == [buyer_turn_uid]
    events = RealAccuracyLabelStore(tmp_path / "labels.db").list_events_for_dataset(dataset["dataset_version"])
    assert {event["auth_type"] for event in events} == {"test"}
    assert {event["dataset_hash"] for event in events} == {dataset["manifest"]["content_sha256"]}
    assert not (tmp_path / "knowledge_base.db").exists()


def test_full_app_registers_real_accuracy_workbench_spa_route():
    from app.main import create_app

    app = create_app()

    assert "/real-accuracy-labels" in {rule.rule for rule in app.url_map.iter_rules()}


def test_v2_api_exposes_explicit_target_and_rejects_historical_buyer_rebinding(monkeypatch, tmp_path):
    sample = {
        "id": 2, "customer_quote": "宽度是多少？", "full_context": (
            '<div class="imui-msg imui-msg-l"><div class="msg-body-text">之前的问题</div></div>'
            '<div class="imui-msg imui-msg-r"><div class="msg-body-text">之前的回复</div></div>'
        ),
        "product_title": "测试商品", "sku": "TEST-SKU", "order_no": "TEST-ORDER",
        "question_type": "尺寸", "correct_answer": "宽度请看商品资料。", "review_status": "已确认",
        "risk_level": "low", "need_media": False, "auto_reply_type": "需人工确认", "notes": "",
    }
    dataset = build_gold_dataset_v2("test-hmac", [sample])[0]
    gold_path = tmp_path / "gold-v2.json"
    gold_path.write_text(json.dumps(dataset, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setenv("COPILOT_REAL_ACCURACY_GOLD_SET_PATH", str(gold_path))
    monkeypatch.setenv("COPILOT_REAL_ACCURACY_LABEL_DB", str(tmp_path / "labels-v2.db"))
    monkeypatch.setenv("COPILOT_REAL_ACCURACY_LABEL_AUDIT_HMAC_KEY", "audit-test-key")
    monkeypatch.setattr(
        admin_auth,
        "_verified_principal",
        lambda: admin_auth.AdminPrincipal("supervisor", "supervisor", frozenset({"supervisor"}), "test"),
    )
    app = Flask(__name__)
    app.register_blueprint(real_accuracy_label_bp)
    client = app.test_client()
    case = dataset["cases"][0]
    explicit_uid = case["explicit_target"]["target_turn_uid"]
    historical_uid = next(
        turn["turn_uid"] for turn in case["conversation"]["turns"]
        if turn["speaker_role"] == "BUYER" and turn["turn_uid"] != explicit_uid
    )

    listed = client.get("/api/kb/real-accuracy/cases")
    assert listed.status_code == 200
    row = next(item for item in listed.get_json()["items"] if item["case_uid"] == case["case_uid"])
    assert row["explicit_target"]["target_turn_uid"] == explicit_uid
    rejected = client.post(f"/api/kb/real-accuracy/cases/{case['case_uid']}/labels", json={
        "claims": _claim(),
        "target_turn_uids": [historical_uid],
        "review_status": "approved",
        "optimistic_lock_version": 0,
    })
    assert rejected.status_code == 422
    assert rejected.get_json()["error"] == "target_turn_must_match_explicit_target"


def test_rejected_claim_is_reported_as_history_but_does_not_occupy_active_queue(monkeypatch, tmp_path):
    dataset = _dataset()
    gold_path = tmp_path / "gold.json"
    gold_path.write_text(json.dumps(dataset, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setenv("COPILOT_REAL_ACCURACY_GOLD_SET_PATH", str(gold_path))
    monkeypatch.setenv("COPILOT_REAL_ACCURACY_LABEL_DB", str(tmp_path / "labels.db"))
    monkeypatch.setenv("COPILOT_REAL_ACCURACY_LABEL_AUDIT_HMAC_KEY", "audit-test-key")
    monkeypatch.setattr(
        admin_auth,
        "_verified_principal",
        lambda: admin_auth.AdminPrincipal("supervisor", "supervisor", frozenset({"supervisor"}), "test"),
    )
    app = Flask(__name__)
    app.register_blueprint(real_accuracy_label_bp)
    client = app.test_client()
    case_uid = dataset["cases"][0]["case_uid"]
    rejected_claims = [{**claim, "review_status": "rejected"} for claim in _claim()]

    response = client.post(f"/api/kb/real-accuracy/cases/{case_uid}/labels", json={
        "claims": rejected_claims,
        "target_turn_uids": [],
        "review_status": "rejected",
        "optimistic_lock_version": 0,
    })
    assert response.status_code == 201

    summary = client.get("/api/kb/real-accuracy/cases").get_json()["workflow_summary"]
    assert summary["selected_claim_count"] == 0
    assert summary["pending_claim_count"] == 0
    assert summary["rejected_claim_count"] == 1
    assert summary["active_queue_rejected_claim_count"] == 0
