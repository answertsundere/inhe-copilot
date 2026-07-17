from __future__ import annotations

import sqlite3
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


def test_agent_payload_excludes_all_evaluation_labels():
    payload = build_agent_payload(_sample())
    assert_label_not_in_agent_input(payload)
    payload["copilot_context"]["reference_label"] = {"expected_claims": []}
    with pytest.raises(ValueError, match="evaluation_label_leaked"):
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
    assert case["classification"] == "claim_label_pending"
    enriched = apply_approved_claim_labels(dataset, [{
        "case_uid": case["case_uid"], "review_status": "approved",
        "label": {"claims": [{"claim_uid": "claim-1", "required_terms": ["核对订单"]}]},
    }])
    assert enriched["cases"][0]["classification"] == "claim_accuracy_scorable"
    assert dataset["cases"][0]["reference_label"]["expected_claims"] == []


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
