from __future__ import annotations

import sqlite3
import json
from pathlib import Path

import pytest

from app.services.real_accuracy_gold_set_service import (
    assert_label_not_in_agent_input,
    apply_approved_claim_labels,
    build_agent_payload,
    build_gold_dataset,
    classify_sample,
    hmac_identifier,
    load_reviewed_training_samples,
    query_coverage_rows,
    score_response,
    validate_gold_dataset,
)
from scripts import validate_real_accuracy_gold_set


SECRET = "test-only-hmac-key"


def _sample(**overrides):
    item = {
        "id": 1,
        "customer_quote": "商品少了一个配件，怎么处理？",
        "full_context": "买家：商品少了一个配件。客服：请描述缺少的位置。",
        "product_title": "测试商品",
        "sku": "SKU-TEST",
        "order_no": "ORDER-TEST",
        "question_type": "售后",
        "correct_answer": "先核对订单，并请买家拍照后交给售后处理。",
        "review_status": "已确认",
        "risk_level": "medium",
        "need_media": False,
        "auto_reply_type": "需人工确认",
        "notes": "",
    }
    item.update(overrides)
    return item


def test_classifies_reference_safety_context_media_and_invalid():
    assert classify_sample(_sample()) == "reference_available"
    assert classify_sample(_sample(correct_answer="")) == "safety_scorable"
    assert classify_sample(_sample(product_title="", sku="", order_no="")) == "context_gap"
    assert classify_sample(_sample(customer_quote="[图片消息]", correct_answer="")) == "media_only"
    assert classify_sample(_sample(customer_quote="", correct_answer="")) == "invalid"


def test_gold_dataset_pseudonymizes_identity_and_rejects_pii():
    dataset, queue = build_gold_dataset(SECRET, [_sample(customer_quote="请联系13800138000")])
    case = dataset["cases"][0]

    assert case["case_uid"] == hmac_identifier(SECRET, "training_sample", 1)
    assert case["sidecar_identity"]["sku"] != "SKU-TEST"
    assert case["sidecar_identity"]["order"] != "ORDER-TEST"
    assert "13800138000" not in case["customer_message"]
    assert "[PHONE_REDACTED]" in case["customer_message"]
    assert "conversation_context" not in case
    assert case["conversation"]["turns"]
    assert not validate_gold_dataset(dataset)
    assert queue[0]["case_uid"] == case["case_uid"]


def test_manifest_is_stable_and_tampering_fails_validation():
    dataset, _ = build_gold_dataset(SECRET, [_sample(), _sample(id=2, sku="SKU-2", order_no="ORDER-2")])
    assert not validate_gold_dataset(dataset)
    dataset["cases"][0]["customer_message"] = "tampered"
    assert "manifest_hash_mismatch" in validate_gold_dataset(dataset)


def test_gold_validation_requires_unique_stable_turn_uids():
    dataset, _ = build_gold_dataset(SECRET, [_sample()])
    dataset["cases"][0]["conversation"]["turns"][0].pop("turn_uid")
    assert "conversation_turn_uid_missing_or_duplicate" in validate_gold_dataset(dataset)


def test_validation_cli_exits_two_for_invalid_gold_set(tmp_path: Path):
    dataset, _ = build_gold_dataset(SECRET, [_sample()])
    dataset["privacy"]["privacy_scan_status"] = "passed"
    dataset["cases"][0]["customer_message"] = "https://invalid.example/raw"
    path = tmp_path / "tampered.json"
    path.write_text(json.dumps(dataset, ensure_ascii=False), encoding="utf-8")
    assert validate_real_accuracy_gold_set.main(["--input", str(path)]) == 2


def test_agent_payload_excludes_all_evaluation_labels():
    payload = build_agent_payload(_sample())
    assert_label_not_in_agent_input(payload)
    payload["copilot_context"]["reference_label"] = {"expected_claims": []}
    with pytest.raises(ValueError, match="evaluation_label_leaked"):
        assert_label_not_in_agent_input(payload)


def test_approved_target_turn_drives_message_and_excludes_future_turns():
    sample = _sample(full_context=(
        '<div class="imui-msg imui-msg-l"><div class="msg-body-text">前置问题</div></div>'
        '<div class="imui-msg imui-msg-r"><div class="msg-body-text">前置答复</div></div>'
        '<div class="imui-msg imui-msg-l"><div class="msg-body-text">真正评分问题</div></div>'
        '<div class="imui-msg imui-msg-r"><div class="msg-body-text">未来客服答复</div></div>'
        '<div class="imui-msg imui-msg-l"><div class="msg-body-text">未来买家问题</div></div>'
    ))
    dataset, _ = build_gold_dataset(SECRET, [sample])
    case = dataset["cases"][0]
    target = case["conversation"]["turns"][2]["turn_uid"]
    case["classification"] = "claim_accuracy_scorable"
    case["evaluation_target"] = {"target_turn_uids": [target]}
    payload = build_agent_payload(sample, case=case)
    assert payload["message"] == "真正评分问题"
    history_text = "\n".join(turn["content"] for turn in payload["conversation_history"])
    assert "前置问题" in history_text
    assert "真正评分问题" not in history_text
    assert "未来客服答复" not in history_text
    assert "未来买家问题" not in history_text
    assert_label_not_in_agent_input(payload)


def test_score_requires_explicit_claim_contract_and_never_uses_reference_text():
    dataset, _ = build_gold_dataset(SECRET, [_sample()])
    case = dataset["cases"][0]
    response = {"suggested_reply": "先核对订单并请您拍照。", "analysis_pipeline": {"version": "v1"}}
    score = score_response(case, response)
    assert score["claim_score_available"] is False
    assert score["passed"] is False

    case["reference_label"]["expected_claims"] = [{"claim_uid": "claim-1", "required_terms": ["核对订单", "拍照"]}]
    score = score_response(case, response)
    assert score["passed"] is True
    assert score["formal_pipeline_verified"] is True


def test_only_approved_human_claim_labels_create_accuracy_denominator():
    dataset, _ = build_gold_dataset(SECRET, [_sample()])
    case = dataset["cases"][0]
    target_turn_uid = next(
        turn["turn_uid"] for turn in case["conversation"]["turns"]
        if turn["speaker_role"] == "BUYER"
    )
    assert case["classification"] == "claim_label_pending"
    enriched = apply_approved_claim_labels(dataset, [{
        "case_uid": case["case_uid"], "review_status": "approved",
        "label": {
            "claims": [{"claim_uid": "claim-1", "required_terms": ["核对订单"]}],
            "target_turn_uids": [target_turn_uid],
        },
    }])
    assert enriched["cases"][0]["classification"] == "claim_accuracy_scorable"
    assert enriched["cases"][0]["evaluation_target"]["target_turn_uids"] == [target_turn_uid]
    assert dataset["cases"][0]["reference_label"]["expected_claims"] == []


def test_role_unresolved_case_is_excluded_from_manual_claim_queue():
    dataset, queue = build_gold_dataset(
        SECRET,
        [_sample(full_context='<div class="imui-msg"><div class="msg-body-text">没有可靠角色</div></div>')],
    )
    assert dataset["cases"][0]["classification"] == "role_unresolved"
    assert dataset["summary"]["role_unresolved_case_count"] == 1
    assert queue == []


def test_truncated_conversation_is_excluded_from_manual_claim_queue():
    raw = "".join(
        f'<div class="imui-msg imui-msg-l"><div class="msg-body-text">{index}</div></div>'
        for index in range(501)
    )
    dataset, queue = build_gold_dataset(SECRET, [_sample(full_context=raw)])
    assert dataset["cases"][0]["classification"] == "conversation_truncated"
    assert queue == []


def test_coverage_matrix_tracks_context_and_formal_selection_without_agent_logic():
    dataset, _ = build_gold_dataset(SECRET, [_sample(question_type="尺寸"), _sample(id=2, question_type="尺寸", sku="SKU-2", order_no="ORDER-2")])
    case_uids = [item["case_uid"] for item in dataset["cases"]]
    rows = query_coverage_rows(dataset["cases"], [{
        "case_uid": case_uids[0], "formal_pipeline_verified": True,
        "formal_selected_evidence_count": 1, "admitted_evidence_count": 1,
        "requires_human_review": True,
    }])
    assert rows[0]["question_count"] == 2
    assert rows[0]["formal_pipeline_count"] == 1
    assert rows[0]["formal_selected_evidence_count"] == 1


def test_reads_training_samples_readonly_from_explicit_sqlite_source(tmp_path: Path):
    source = tmp_path / "source.db"
    connection = sqlite3.connect(source)
    connection.execute(
        """CREATE TABLE kb_training_sample (
        id INTEGER, customer_quote TEXT, full_context TEXT, product_title TEXT, sku TEXT,
        order_no TEXT, question_type TEXT, correct_answer TEXT, review_status TEXT,
        risk_level TEXT, need_media INTEGER, auto_reply_type TEXT, notes TEXT)"""
    )
    connection.execute(
        "INSERT INTO kb_training_sample VALUES (1, '问题', '上下文', '商品', 'SKU', 'ORDER', '售后', '答案', '已确认', 'medium', 0, '需人工确认', '')"
    )
    connection.commit()
    connection.close()

    loaded = load_reviewed_training_samples(source)
    assert loaded == [_sample(customer_quote="问题", full_context="上下文", product_title="商品", sku="SKU", order_no="ORDER", question_type="售后", correct_answer="答案")]
    check = sqlite3.connect(source)
    assert check.execute("SELECT count(*) FROM kb_training_sample").fetchone()[0] == 1
    check.close()
