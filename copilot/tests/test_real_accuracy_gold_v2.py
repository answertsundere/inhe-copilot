from __future__ import annotations

from scripts.build_real_accuracy_gold_v2_migration_manifest import build_migration_manifest

from app.services.real_accuracy_gold_set_service import (
    apply_approved_claim_labels,
    build_agent_payload,
    build_gold_dataset,
    build_gold_dataset_v2,
    upgrade_gold_dataset_v2,
    validate_gold_dataset,
)


SECRET = "gold-v2-test-key"


def _sample(**overrides):
    sample = {
        "id": 1,
        "customer_quote": "How wide is the product?",
        "full_context": (
            '<div class="imui-msg imui-msg-l"><div class="msg-body-text">Earlier question</div></div>'
            '<div class="imui-msg imui-msg-r"><div class="msg-body-text">Earlier answer</div></div>'
        ),
        "product_title": "Test product",
        "sku": "TEST-SKU",
        "order_no": "TEST-ORDER",
        "question_type": "dimensions",
        "correct_answer": "Use the reviewed dimensions.",
        "review_status": "已确认",
        "risk_level": "low",
        "need_media": False,
        "auto_reply_type": "",
        "notes": "",
    }
    sample.update(overrides)
    return sample


def _claim(status="approved"):
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
        "review_status": status,
        "proposal_status": "supervisor_approved" if status == "approved" else "policy_validated",
        "source_reference": "formal_evidence",
        "evidence_provenance": [],
        "risk_level": "low",
        "identity_scope": "matched",
        "can_support_auto_send": False,
        "strategy_group": "product_fact_direct",
    }


def test_v2_models_reviewed_customer_question_as_one_explicit_final_target():
    dataset, queue = build_gold_dataset_v2(SECRET, [_sample()])
    case = dataset["cases"][0]
    target = case["explicit_target"]
    turns = case["conversation"]["turns"]

    assert dataset["dataset_id"] == "real_customer_service_gold_v0_2"
    assert dataset["dataset_version"] == "0.2"
    assert target["target_source_type"] == "reviewed_sample_customer_question"
    assert target["target_speaker_role"] == "BUYER"
    assert target["history_end_turn_index"] < target["target_turn_index"]
    assert turns[-1]["turn_uid"] == target["target_turn_uid"]
    assert turns[-1]["text"] == "How wide is the product?"
    assert sum(turn["turn_uid"] == target["target_turn_uid"] for turn in turns) == 1
    assert queue[0]["target_turn_uid"] == target["target_turn_uid"]
    assert not validate_gold_dataset(dataset)


def test_v2_agent_payload_contains_history_before_target_and_current_target_once():
    dataset, _ = build_gold_dataset_v2(
        SECRET,
        [_sample(full_context=(
            '<div class="imui-msg imui-msg-l"><div class="msg-body-text">How wide is the product?</div></div>'
            '<div class="imui-msg imui-msg-r"><div class="msg-body-text">Old answer</div></div>'
        ))],
    )
    case = dataset["cases"][0]
    target_uid = case["explicit_target"]["target_turn_uid"]
    approved = apply_approved_claim_labels(dataset, [{
        "case_uid": case["case_uid"],
        "review_status": "approved",
        "label": {"claims": [_claim()], "target_turn_uids": [target_uid]},
    }])
    payload = build_agent_payload(_sample(), case=approved["cases"][0])

    assert payload["message"] == "How wide is the product?"
    history = [turn["content"] for turn in payload["conversation_history"]]
    assert history.count("How wide is the product?") == 1
    assert "Old answer" in history
    assert payload["message"] not in history[-1:]


def test_v2_excludes_media_only_target():
    dataset, queue = build_gold_dataset_v2(SECRET, [_sample(customer_quote="[图片消息]", correct_answer="")])
    case = dataset["cases"][0]
    assert case["explicit_target"] is None
    assert case["target_status"] == "target_missing"
    assert dataset["summary"]["missing_target_count"] == 1
    assert queue == []
    assert not validate_gold_dataset(dataset)


def test_v2_can_be_derived_from_frozen_v1_without_rebuilding_source_database():
    source, _ = build_gold_dataset(SECRET, [_sample()])

    dataset, queue = upgrade_gold_dataset_v2(SECRET, source)

    source_hash = source["manifest"]["content_sha256"]
    assert dataset["source_dataset"]["content_sha256"] == source_hash
    assert dataset["manifest"]["source_dataset_sha256"] == source_hash
    assert dataset["summary"]["automatically_approved_count"] == 0
    assert dataset["cases"][0]["explicit_target"]["target_provenance"]["source_kind"] == "reviewed_gold_v0_1"
    assert queue[0]["target_turn_uid"] == dataset["cases"][0]["explicit_target"]["target_turn_uid"]
    assert validate_gold_dataset(dataset) == []


def test_migration_creates_candidates_but_never_copies_approval():
    sample = _sample(full_context=(
        '<div class="imui-msg imui-msg-l"><div class="msg-body-text">How wide is the product?</div></div>'
        '<div class="imui-msg imui-msg-r"><div class="msg-body-text">Old answer</div></div>'
    ))
    v1, _ = build_gold_dataset(SECRET, [sample])
    v2, _ = build_gold_dataset_v2(SECRET, [sample])
    old_case = v1["cases"][0]
    old_target = next(turn["turn_uid"] for turn in old_case["conversation"]["turns"] if turn["speaker_role"] == "BUYER")
    label = {
        "case_uid": old_case["case_uid"],
        "dataset_version": "0.1",
        "review_status": "approved",
        "optimistic_lock_version": 1,
        "label": {"claims": [_claim()], "target_turn_uids": [old_target]},
    }
    event = {
        "case_uid": old_case["case_uid"],
        "dataset_version": "0.1",
        "event_type": "claim_approved",
        "actor_hash": "reviewer_ABCDEFGHIJKLMNOPQRST",
        "actor_role": "supervisor",
        "claim_uid": "claim-width",
        "version": 1,
        "created_at": "2026-01-01T00:00:00+00:00",
    }

    manifest = build_migration_manifest(v1, v2, [label], [event], label_db_sha256="a" * 64)

    assert manifest["summary"]["total_old_approved_claims"] == 1
    assert manifest["summary"]["reusable_candidates"] == 1
    assert manifest["summary"]["migrated_approved_count"] == 0
    assert manifest["candidates"][0]["migration_status"] == "migration_pending"
    assert manifest["candidates"][0]["classification"] == "exact_target_reusable"
    assert "How wide" not in str(manifest)
