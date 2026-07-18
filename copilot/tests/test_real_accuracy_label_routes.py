from __future__ import annotations

import json

from flask import Flask

from app.api import admin_auth
from app.api.real_accuracy_label_routes import real_accuracy_label_bp
from app.services.real_accuracy_gold_set_service import build_gold_dataset


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
    assert client.get("/api/kb/real-accuracy/cases").status_code == 200
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
    assert not (tmp_path / "knowledge_base.db").exists()
