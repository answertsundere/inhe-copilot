from __future__ import annotations

import json

from flask import Flask

from app.api import admin_auth
from app.api.real_accuracy_label_routes import real_accuracy_label_bp
from app.services.real_accuracy_claim_review_service import (
    _target_recommendation,
    bounded_conversation_window,
    build_claim_review_plan,
    build_minimum_supervisor_queue,
    candidate_claims,
    strategy_group_for_case,
)
from app.services.real_accuracy_gold_set_service import build_gold_dataset
from app.services.real_accuracy_label_service import RealAccuracyLabelStore, reviewer_actor_hash


def _sample(**overrides):
    sample = {
        "id": 1,
        "customer_quote": "请协助核对当前问题。",
        "full_context": (
            '<div class="imui-msg imui-msg-l"><div class="msg-body-text">前置问题</div></div>'
            '<div class="imui-msg imui-msg-r"><div class="msg-body-text">前置回复</div></div>'
            '<div class="imui-msg imui-msg-l"><div class="msg-body-text">请协助核对当前问题。</div></div>'
            '<div class="imui-msg imui-msg-r"><div class="msg-body-text">已收到。</div></div>'
            '<div class="imui-msg imui-msg-l"><div class="msg-body-text">后续问题</div></div>'
        ),
        "product_title": "测试商品",
        "sku": "TEST-SKU",
        "order_no": "TEST-ORDER",
        "question_type": "尺寸",
        "correct_answer": "请以已审核资料为准。",
        "review_status": "已确认",
        "risk_level": "low",
        "need_media": False,
        "auto_reply_type": "",
        "notes": "",
    }
    sample.update(overrides)
    return sample


def _dataset(**overrides):
    dataset, _ = build_gold_dataset("claim-review-test-key", [_sample(**overrides)])
    return dataset


def test_grouping_uses_structured_query_class_not_buyer_text():
    dataset = _dataset(customer_quote="任意表述，不用于策略分组。", question_type="物流")
    case = dataset["cases"][0]
    assert strategy_group_for_case(case) == "order_logistics_service_action"


def test_product_fact_proposal_needs_explicit_admitted_evidence():
    case = _dataset()["cases"][0]
    claims = candidate_claims(case, "product_fact_direct")
    assert claims[0]["claim_kind"] == "factual_claim"
    assert claims[0]["expected_status"] == "unresolved"
    assert claims[0]["supporting_evidence_uids"] == []

    case["expected_evidence"] = [{
        "evidence_uid": "evidence-1",
        "review_status": "published",
        "evidence_role": "product_fact_direct",
        "direct_answer_allowed": True,
        "identity_matched": True,
        "fact_type": "dimensions",
        "attribute_key": "width",
    }]
    supported = candidate_claims(case, "product_fact_direct")[0]
    assert supported["expected_status"] == "supported"
    assert supported["supporting_evidence_uids"] == ["evidence-1"]


def test_high_risk_group_keeps_conclusion_unresolved_or_prohibited():
    case = _dataset(question_type="材质安全")["cases"][0]
    claims = candidate_claims(case, "known_fact_high_risk_remainder")
    assert {item["expected_status"] for item in claims} == {"unresolved", "prohibited"}
    assert any(item["must_handoff"] for item in claims)
    assert all(not item["supporting_evidence_uids"] for item in claims)


def test_plan_preserves_hmac_case_uid_and_limits_conversation_window():
    dataset = _dataset()
    case = dataset["cases"][0]
    plan = build_claim_review_plan(dataset)
    item = plan["items"][0]
    assert item["case_uid"] == case["case_uid"]
    assert item["conversation_window"]["total_turn_count"] == len(case["conversation"]["turns"])
    window = bounded_conversation_window(case, [case["conversation"]["turns"][2]["turn_uid"]], before=1, after=1)
    assert len(window["turns"]) == 3
    assert "sidecar_identity" not in item


def test_target_recommendation_does_not_fall_back_to_unrelated_latest_buyer_turn():
    case = {
        "customer_message": "current question",
        "conversation": {
            "turns": [
                {"turn_uid": "turn_history_buyer", "speaker_role": "BUYER", "text": "historical question"},
                {"turn_uid": "turn_history_agent", "speaker_role": "AGENT", "text": "historical answer"},
            ],
        },
    }

    recommendation = _target_recommendation(case, None)

    assert recommendation == {
        "turn_uids": [],
        "reason": "customer_message_turn_missing",
        "requires_confirmation": True,
    }
    assert bounded_conversation_window(case, recommendation["turn_uids"])["turns"] == []


def test_target_recommendation_fails_closed_for_ambiguity_and_invalid_saved_targets():
    case = {
        "customer_message": "same question",
        "conversation": {"turns": [
            {"turn_uid": "turn_AAAAAAAAAAAAAAAAAAAA", "speaker_role": "BUYER", "text": "same question"},
            {"turn_uid": "turn_BBBBBBBBBBBBBBBBBBBB", "speaker_role": "AGENT", "text": "answer"},
            {"turn_uid": "turn_CCCCCCCCCCCCCCCCCCCC", "speaker_role": "BUYER", "text": "same question"},
        ]},
    }
    assert _target_recommendation(case, None)["reason"] == "customer_message_turn_ambiguous"
    assert _target_recommendation(case, None)["turn_uids"] == []

    missing = {"dataset_version": "0.1", "label": {"target_turn_uids": ["turn_DDDDDDDDDDDDDDDDDDDD"]}}
    assert _target_recommendation(case, missing, dataset_version="0.1")["reason"] == "reviewer_selected_target_missing"

    agent = {"dataset_version": "0.1", "label": {"target_turn_uids": ["turn_BBBBBBBBBBBBBBBBBBBB"]}}
    assert _target_recommendation(case, agent, dataset_version="0.1")["reason"] == "reviewer_selected_target_not_buyer"

    other_dataset = {"dataset_version": "0.2", "label": {"target_turn_uids": ["turn_AAAAAAAAAAAAAAAAAAAA"]}}
    assert _target_recommendation(case, other_dataset, dataset_version="0.1")["reason"] == "reviewer_selected_dataset_mismatch"

    valid = {"dataset_version": "0.1", "label": {"target_turn_uids": ["turn_AAAAAAAAAAAAAAAAAAAA"]}}
    assert _target_recommendation(case, valid, dataset_version="0.1") == {
        "turn_uids": ["turn_AAAAAAAAAAAAAAAAAAAA"],
        "reason": "reviewer_selected",
        "requires_confirmation": False,
    }


def test_explicit_v2_target_flows_through_plan_and_queue_without_guessing():
    dataset = _dataset()
    dataset["dataset_version"] = "0.2"
    case = dataset["cases"][0]
    buyer = next(turn for turn in case["conversation"]["turns"] if turn["speaker_role"] == "BUYER")
    case["explicit_target"] = {"target_turn_uid": buyer["turn_uid"]}

    plan = build_claim_review_plan(dataset)
    assert plan["items"][0]["target_recommendation"] == {
        "turn_uids": [buyer["turn_uid"]],
        "reason": "explicit_target",
        "requires_confirmation": False,
    }
    queue = build_minimum_supervisor_queue(plan, target_claim_count=1, minimum_domain_count=1)
    assert queue["selected_claim_count"] == 1
    assert {item["target_turn_uid"] for item in queue["items"]} == {buyer["turn_uid"]}

    other_buyer = next(
        turn for turn in case["conversation"]["turns"]
        if turn["speaker_role"] == "BUYER" and turn["turn_uid"] != buyer["turn_uid"]
    )
    mismatched = {
        "dataset_version": "0.2",
        "label": {"target_turn_uids": [other_buyer["turn_uid"]]},
    }
    assert _target_recommendation(case, mismatched, dataset_version="0.2") == {
        "turn_uids": [],
        "reason": "reviewer_selected_target_mismatch",
        "requires_confirmation": True,
    }


def test_plan_window_excludes_invisible_control_characters():
    dataset = _dataset(customer_quote="请核对\x03当前问题")
    plan = build_claim_review_plan(dataset)
    rendered = "".join(
        turn["text"]
        for turn in plan["items"][0]["conversation_window"]["turns"]
    )
    assert "\x03" not in rendered


def test_plan_marks_only_existing_supervisor_label_as_approved():
    dataset = _dataset()
    case = dataset["cases"][0]
    target = next(turn["turn_uid"] for turn in case["conversation"]["turns"] if turn["speaker_role"] == "BUYER")
    label = {
        "case_uid": case["case_uid"],
        "review_status": "approved",
        "label": {"target_turn_uids": [target], "claims": []},
    }
    plan = build_claim_review_plan(dataset, [label])
    assert plan["items"][0]["proposal_status"] == "supervisor_approved"
    assert plan["auto_approved_count"] == 0


def test_review_routes_return_bounded_window_and_batch_review_never_approves(monkeypatch, tmp_path):
    dataset = _dataset(question_type="安装")
    gold_path = tmp_path / "gold.json"
    gold_path.write_text(json.dumps(dataset, ensure_ascii=False), encoding="utf-8")
    label_path = tmp_path / "labels.db"
    monkeypatch.setenv("COPILOT_REAL_ACCURACY_GOLD_SET_PATH", str(gold_path))
    monkeypatch.setenv("COPILOT_REAL_ACCURACY_LABEL_DB", str(label_path))
    monkeypatch.setenv("COPILOT_REAL_ACCURACY_LABEL_AUDIT_HMAC_KEY", "audit-test-key")
    case = dataset["cases"][0]
    buyer_turn = next(turn["turn_uid"] for turn in case["conversation"]["turns"] if turn["speaker_role"] == "BUYER")
    store = RealAccuracyLabelStore(label_path)
    store.save(
        case_uid=case["case_uid"], dataset_version=dataset["dataset_version"],
        claims=candidate_claims(case, "installation_accessory"), target_turn_uids=[buyer_turn],
        review_status="draft", actor_hash=reviewer_actor_hash("reviewer", "audit-test-key"),
        expected_version=0, allow_approval=False,
    )
    app = Flask(__name__)
    app.register_blueprint(real_accuracy_label_bp)
    client = app.test_client()
    monkeypatch.setattr(admin_auth, "_verified_principal", lambda: admin_auth.AdminPrincipal("reviewer", "reviewer", frozenset({"reviewer"}), "test"))

    listed = client.get("/api/kb/real-accuracy/cases?strategy_group=installation_accessory")
    assert listed.status_code == 200
    item = listed.get_json()["items"][0]
    assert "conversation" not in item
    assert item["conversation_window"]["turns"]
    assert item["strategy"]["id"] == "installation_accessory"

    response = client.post("/api/kb/real-accuracy/batches/review", json={
        "strategy_group": "installation_accessory", "case_uids": [case["case_uid"]],
    })
    assert response.status_code == 200
    assert response.get_json()["reviewed_count"] == 1
    assert response.get_json()["supervisor_approved_count"] == 0
    assert store.get(case["case_uid"], dataset["dataset_version"])["review_status"] == "reviewed"


def test_apply_proposals_creates_draft_only(monkeypatch, tmp_path):
    dataset = _dataset()
    gold_path = tmp_path / "gold.json"
    gold_path.write_text(json.dumps(dataset, ensure_ascii=False), encoding="utf-8")
    label_path = tmp_path / "labels.db"
    monkeypatch.setenv("COPILOT_REAL_ACCURACY_GOLD_SET_PATH", str(gold_path))
    monkeypatch.setenv("COPILOT_REAL_ACCURACY_LABEL_DB", str(label_path))
    monkeypatch.setenv("COPILOT_REAL_ACCURACY_LABEL_AUDIT_HMAC_KEY", "audit-test-key")
    app = Flask(__name__)
    app.register_blueprint(real_accuracy_label_bp)
    client = app.test_client()
    monkeypatch.setattr(admin_auth, "_verified_principal", lambda: admin_auth.AdminPrincipal("reviewer", "reviewer", frozenset({"reviewer"}), "test"))
    case_uid = dataset["cases"][0]["case_uid"]

    response = client.post("/api/kb/real-accuracy/proposals/apply", json={"case_uids": [case_uid]})
    assert response.status_code == 200
    assert response.get_json()["created_draft_count"] == 1
    assert response.get_json()["auto_approved_count"] == 0
    saved = RealAccuracyLabelStore(label_path).get(case_uid, dataset["dataset_version"])
    assert saved["review_status"] == "draft"
    assert all(claim["proposal_status"] == "policy_validated" for claim in saved["label"]["claims"])


def test_supervisor_approval_requires_role_and_records_each_claim_event(monkeypatch, tmp_path):
    dataset = _dataset(question_type="安装")
    gold_path = tmp_path / "gold.json"
    gold_path.write_text(json.dumps(dataset, ensure_ascii=False), encoding="utf-8")
    label_path = tmp_path / "labels.db"
    monkeypatch.setenv("COPILOT_REAL_ACCURACY_GOLD_SET_PATH", str(gold_path))
    monkeypatch.setenv("COPILOT_REAL_ACCURACY_LABEL_DB", str(label_path))
    monkeypatch.setenv("COPILOT_REAL_ACCURACY_LABEL_AUDIT_HMAC_KEY", "audit-test-key")
    app = Flask(__name__)
    app.register_blueprint(real_accuracy_label_bp)
    client = app.test_client()
    case = dataset["cases"][0]
    buyer_turn = next(turn["turn_uid"] for turn in case["conversation"]["turns"] if turn["speaker_role"] == "BUYER")
    claims = [{**claim, "review_status": "approved"} for claim in candidate_claims(case, "installation_accessory")]
    payload = {"review_status": "approved", "claims": claims, "target_turn_uids": [buyer_turn], "optimistic_lock_version": 0}

    monkeypatch.setattr(admin_auth, "_verified_principal", lambda: admin_auth.AdminPrincipal("reviewer", "reviewer", frozenset({"reviewer"}), "test"))
    assert client.post(f"/api/kb/real-accuracy/cases/{case['case_uid']}/labels", json=payload).status_code == 422

    monkeypatch.setattr(admin_auth, "_verified_principal", lambda: admin_auth.AdminPrincipal("supervisor", "supervisor", frozenset({"supervisor"}), "test"))
    assert client.post(f"/api/kb/real-accuracy/cases/{case['case_uid']}/labels", json=payload).status_code == 201
    events = RealAccuracyLabelStore(label_path).list_events_for_dataset(dataset["dataset_version"])
    approved = [event for event in events if event["event_type"] == "claim_approved"]
    assert len(approved) == len(claims)
    assert {event["actor_role"] for event in approved} == {"supervisor"}


def test_minimum_supervisor_queue_balances_atomic_claims_without_approval():
    def item(domain, number, *, readable=True):
        return {
            "case_uid": f"case-{domain}-{number}",
            "scenario_domain": domain,
            "label_eligibility": "ready_for_reviewer",
            "buyer_question": "可审核问题" if readable else "[图片]",
            "target_recommendation": {"turn_uids": ["turn_ABCDEFGHIJKLMNOPQRST"]},
            "conversation_window": {"turns": [
                {"speaker_role": "BUYER"}, {"speaker_role": "AGENT"},
            ]},
            "sidecar_quality": "identity_present",
            "risk_level": "medium",
            "candidate_claims": [{
                "claim_uid": f"claim-{domain}-{number}",
                "query_fact_type": domain,
                "required_action_points": [],
                "forbidden_claims": [],
                "evidence_provenance": [],
                "supporting_evidence_uids": [],
                "risk_level": "medium",
            }],
        }

    domains = ["dimensions", "installation", "logistics", "aftersales", "promotion", "media"]
    items = [item(domain, number) for domain in domains for number in range(10)]
    queue = build_minimum_supervisor_queue({"dataset_id": "d", "dataset_version": "v", "items": items})
    reversed_queue = build_minimum_supervisor_queue({"dataset_id": "d", "dataset_version": "v", "items": list(reversed(items))})

    assert queue["queue_status"] == "insufficient_reviewable_claims"
    assert queue["selected_claim_count"] == 30
    assert queue["selected_domain_count"] >= 5
    assert max(queue["domain_distribution"].values()) <= 9
    assert queue["supervisor_approved_claim_count"] == 0
    assert queue["formal_knowledge_writes"] == 0
    assert queue["can_change_can_send"] is False
    assert queue["schema_version"] == "real-accuracy-minimum-supervisor-queue-v2"
    assert queue["coverage_metrics"]["multi_turn_claim_count"] == 30
    assert queue["coverage_metrics"]["partial_answer_claim_count"] == 0
    first = queue["items"][0]
    assert first["deidentified_case_uid"] == first["case_uid"]
    assert first["target_turn_uid"] == first["target_turn_uids"][0]
    assert first["business_domain"] == first["scenario_domain"]
    assert first["expected_claim_status"] == first["atomic_claim"].get("expected_status", "")
    assert first["approval_state"] == "draft"
    assert first["privacy_scan_status"] == "passed"
    assert [item["atomic_claim"]["claim_uid"] for item in queue["items"]] == [
        item["atomic_claim"]["claim_uid"] for item in reversed_queue["items"]
    ]


def test_minimum_supervisor_queue_excludes_token_only_question_and_incomplete_window():
    plan = {"dataset_id": "d", "dataset_version": "v", "items": [{
        "case_uid": "case-1", "scenario_domain": "aftersales", "label_eligibility": "ready_for_reviewer",
        "buyer_question": "[图片]", "target_recommendation": {"turn_uids": ["turn_ABCDEFGHIJKLMNOPQRST"]},
        "conversation_window": {"turns": [{"speaker_role": "BUYER"}]}, "candidate_claims": [{"claim_uid": "c"}],
    }]}
    queue = build_minimum_supervisor_queue(plan)
    assert queue["selected_claim_count"] == 0
    assert queue["queue_status"] == "insufficient_reviewable_claims"
    assert queue["excluded_candidate_reasons"]["buyer_question_not_readable"] == 1


def test_minimum_supervisor_queue_requires_declared_gold_30_coverage():
    domains = [
        "product_fact_direct", "known_fact_high_risk_remainder", "order_logistics_service_action",
        "aftersales_verification", "installation_accessory", "media_evidence",
    ]
    items = []
    for number in range(36):
        domain = domains[number % len(domains)]
        high_risk = domain == "known_fact_high_risk_remainder"
        service = domain in {"order_logistics_service_action", "aftersales_verification"}
        items.append({
            "case_uid": f"case-{number}",
            "scenario_domain": domain,
            "label_eligibility": "ready_for_reviewer",
            "buyer_question": "可审核问题",
            "target_recommendation": {"turn_uids": ["turn_ABCDEFGHIJKLMNOPQRST"]},
            "conversation_window": {"turns": [
                {"speaker_role": "BUYER"}, {"speaker_role": "AGENT"},
            ], "total_turn_count": 3, "truncated": False},
            "sidecar_quality": "identity_present",
            "risk_level": "high" if high_risk else "medium",
            "candidate_claims": [{
                "claim_uid": f"claim-{number}",
                "claim_kind": "service_action" if service else "factual_claim",
                "query_fact_type": domain,
                "expected_status": "unresolved" if high_risk else "supported",
                "partial_answer_allowed": True,
                "must_handoff": high_risk,
                "required_action_points": ["verify"] if service else [],
                "forbidden_claims": [],
                "evidence_provenance": [],
                "supporting_evidence_uids": [],
                "risk_level": "high" if high_risk else "medium",
                "source_reference": "source_reviewed_candidate",
            }],
        })

    queue = build_minimum_supervisor_queue({"dataset_id": "d", "dataset_version": "v", "items": items})

    assert queue["queue_status"] == "ready_for_supervisor_review"
    assert queue["coverage_metrics"]["selected_claim_count"] == 30
    assert queue["coverage_metrics"]["selected_domain_count"] >= 5
    assert queue["coverage_metrics"]["multi_turn_claim_count"] >= 8
    assert queue["coverage_metrics"]["partial_answer_claim_count"] >= 5
    assert queue["coverage_metrics"]["high_risk_or_handoff_claim_count"] >= 5
    assert queue["coverage_metrics"]["service_action_claim_count"] >= 5
    assert queue["coverage_requirements_met"] is True


def test_minimum_supervisor_queue_replaces_rejected_claims_and_pins_approved_claims():
    def item(number, review_status="draft"):
        claim_uid = f"claim-{number:02d}"
        saved_claim = {
            "claim_uid": claim_uid,
            "claim_kind": "service_action",
            "query_fact_type": "aftersales",
            "expected_status": "unresolved",
            "required_action_points": ["verify"],
            "forbidden_claims": [],
            "evidence_provenance": [],
            "supporting_evidence_uids": [],
            "partial_answer_allowed": True,
            "must_handoff": number % 6 == 0,
            "risk_level": "high" if number % 6 == 0 else "medium",
            "review_status": review_status,
            "strategy_group": f"domain-{number % 6}",
        }
        return {
            "case_uid": f"case-{number:02d}",
            "scenario_domain": f"domain-{number % 6}",
            "label_eligibility": "ready_for_reviewer",
            "buyer_question": "可审核问题",
            "target_recommendation": {"turn_uids": ["turn_ABCDEFGHIJKLMNOPQRST"]},
            "conversation_window": {
                "turns": [{"speaker_role": "BUYER"}, {"speaker_role": "AGENT"}],
            },
            "sidecar_quality": "identity_present",
            "risk_level": saved_claim["risk_level"],
            "candidate_claims": [{**saved_claim, "review_status": "draft"}],
            "saved_label": None if review_status == "draft" else {
                "review_status": review_status,
                "label": {"claims": [saved_claim]},
            },
        }

    statuses = {0: "approved", 1: "approved", 2: "rejected", 3: "rejected"}
    items = [item(number, statuses.get(number, "draft")) for number in range(36)]
    items[0]["candidate_claims"].append({
        **items[0]["candidate_claims"][0],
        "claim_uid": "claim-not-in-approved-decision",
    })
    plan = {"dataset_id": "d", "dataset_version": "v", "items": items}

    queue = build_minimum_supervisor_queue(plan)
    reversed_queue = build_minimum_supervisor_queue({**plan, "items": list(reversed(items))})
    selected_uids = [entry["atomic_claim"]["claim_uid"] for entry in queue["items"]]

    assert queue["selected_claim_count"] == 30
    assert queue["supervisor_approved_claim_count"] == 2
    assert {"claim-00", "claim-01"}.issubset(selected_uids)
    assert {"claim-02", "claim-03"}.isdisjoint(selected_uids)
    assert "claim-not-in-approved-decision" not in selected_uids
    assert queue["excluded_candidate_reasons"]["supervisor_rejected"] == 2
    assert queue["excluded_candidate_reasons"]["claim_missing_from_terminal_decision"] == 1
    assert all(entry["approval_state"] != "rejected" for entry in queue["items"])
    assert selected_uids == [entry["atomic_claim"]["claim_uid"] for entry in reversed_queue["items"]]
