from __future__ import annotations

import json
import sqlite3

import scripts.build_approved_real_accuracy_gold_manifest as manifest_script
from app.services.real_accuracy_gold_set_service import build_gold_dataset
from app.services.real_accuracy_label_service import RealAccuracyLabelStore, reviewer_actor_hash


def _dataset():
    samples = [{
        "id": 1,
        "customer_quote": "请问尺寸是多少",
        "full_context": '<div class="imui-msg imui-msg-l"><div class="msg-body-text">请问尺寸是多少</div></div>',
        "product_title": "测试商品",
        "sku": "SKU-1",
        "order_no": "ORDER-1",
        "question_type": "尺寸",
        "correct_answer": "请以规格页为准",
        "review_status": "已确认",
        "risk_level": "low",
        "need_media": False,
        "auto_reply_type": "",
        "notes": "",
    }]
    return build_gold_dataset("manifest-test-key", samples)[0]


def _approved_claim():
    return {
        "claim_uid": "claim-width",
        "claim_kind": "product_fact",
        "query_fact_type": "dimensions",
        "attribute_key": "width",
        "expected_status": "supported",
        "acceptable_values": ["80"],
        "normalized_value": "80",
        "unit": "cm",
        "required_terms": ["80"],
        "supporting_evidence_uids": ["evidence-width"],
        "required_tool": None,
        "required_action_points": [],
        "must_handoff": False,
        "forbidden_claims": [],
        "partial_answer_allowed": False,
        "review_status": "approved",
        "proposal_status": "policy_validated",
        "source_reference": "formal_evidence",
        "evidence_provenance": [],
        "risk_level": "low",
        "identity_scope": "matched",
        "can_support_auto_send": False,
        "strategy_group": "product_fact_direct",
    }


def test_manifest_requires_independent_supervisor_claim_audit(tmp_path):
    dataset = _dataset()
    gold_path = tmp_path / "gold.json"
    gold_path.write_text(json.dumps(dataset, ensure_ascii=False), encoding="utf-8")
    label_path = tmp_path / "labels.db"
    store = RealAccuracyLabelStore(label_path)
    case = dataset["cases"][0]
    buyer_turn = next(turn["turn_uid"] for turn in case["conversation"]["turns"] if turn["speaker_role"] == "BUYER")
    store.save(
        case_uid=case["case_uid"],
        dataset_version=dataset["dataset_version"],
        claims=[_approved_claim()],
        target_turn_uids=[buyer_turn],
        review_status="approved",
        actor_hash=reviewer_actor_hash("supervisor", "manifest-test-audit-key"),
        actor_role="supervisor",
        expected_version=0,
        allow_approval=True,
    )
    output = tmp_path / "manifest.json"
    assert manifest_script.main(["--gold-set", str(gold_path), "--label-db", str(label_path), "--json-output", str(output)]) == 0
    manifest = json.loads(output.read_text(encoding="utf-8"))
    assert manifest["approved_claim_count"] == 1
    assert manifest["approval_event_count"] == 1
    assert manifest["approved_domain_count"] == 1
    assert manifest["approved_domain_distribution"] == {"product_fact_direct": 1}
    assert manifest["publish_status"] == "awaiting_supervisor_approval"
    assert manifest["missing_approved_claim_count"] == 29
    assert manifest["missing_approved_domain_count"] == 4

    with sqlite3.connect(label_path) as connection:
        connection.execute("DELETE FROM real_accuracy_label_event WHERE event_type='claim_approved'")
        connection.commit()
    assert manifest_script.main(["--gold-set", str(gold_path), "--label-db", str(label_path), "--json-output", str(output)]) == 2
