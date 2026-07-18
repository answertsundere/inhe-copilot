from __future__ import annotations

import json

import pytest

from app.services.real_accuracy_label_service import (
    LabelConflictError,
    LabelValidationError,
    RealAccuracyLabelStore,
    reviewer_actor_hash,
)
from app.services.real_accuracy_privacy_service import (
    parse_conversation_context,
    scan_privacy_output,
    validate_controlled_identifiers,
)


SECRET = "test-only-privacy-key"
TARGET_TURN_UID = "turn_ABCDEFGHIJKLMNOPQRST"


def test_html_conversation_is_structured_and_removes_identity_urls_and_style():
    parsed = parse_conversation_context(
        '<style>.buyer{color:red}</style><div class="buyer">买家：请联系 test@example.com 或 https://shop.test/item/123</div>'
        '<p>客服：收到，电话 13800138000</p><img src="data:image/png;base64,AAAA"/>',
        hmac_key=SECRET,
    )
    rendered = json.dumps(parsed, ensure_ascii=False)
    assert "buyer{" not in rendered
    assert "test@example.com" not in rendered
    assert "13800138000" not in rendered
    assert "https://" not in rendered
    assert "[PRODUCT_LINK]" in rendered
    assert any(turn["message_type"] == "image" for turn in parsed["turns"])
    assert {turn["speaker_role"] for turn in parsed["turns"]} >= {"BUYER", "AGENT"}
    assert not parsed["privacy_review_required"]


def test_parser_handles_normal_chinese_and_legacy_garbled_text_without_retaining_html():
    parsed = parse_conversation_context("<div>买家：安装步骤怎么做？</div><div>客服：请查看说明。</div>", hmac_key=SECRET)
    assert parsed["turns"][0]["text"] == "安装步骤怎么做？"
    legacy = parse_conversation_context("<div>�����：������</div>", hmac_key=SECRET)
    assert legacy["turns"]
    assert "<div" not in legacy["turns"][0]["text"]


def test_parser_prefers_message_direction_merges_body_fragments_and_marks_unknown_role():
    parsed = parse_conversation_context(
        '<div class="imui-msg imui-msg-l" data-fromnick="x"><div class="msg-body-text"><span>尺寸</span><span>多大</span></div></div>'
        '<div class="imui-msg imui-msg-r" data-tonick="x"><div class="msg-body-html">请看规格页</div></div>'
        '<div class="imui-msg"><div class="msg-body-text">没有可用方向</div></div>',
        hmac_key=SECRET,
    )
    assert [turn["speaker_role"] for turn in parsed["turns"]] == ["BUYER", "AGENT", None]
    assert parsed["turns"][0]["text"] == "尺寸多大"
    assert parsed["turns"][0]["role_resolution"] == "dom_direction"
    assert parsed["turns"][2]["role_resolution"] == "role_unresolved"
    assert parsed["role_unresolved_count"] == 1


def test_turn_uid_is_stable_scoped_and_privacy_safe():
    raw = '<div class="imui-msg imui-msg-l"><div class="msg-body-text">请问尺寸</div></div>'
    first = parse_conversation_context(raw, hmac_key=SECRET, conversation_uid="training_sample_AAAAAAAAAAAAAAAAAAAA")
    repeated = parse_conversation_context(raw, hmac_key=SECRET, conversation_uid="training_sample_AAAAAAAAAAAAAAAAAAAA")
    other = parse_conversation_context(raw, hmac_key=SECRET, conversation_uid="training_sample_BBBBBBBBBBBBBBBBBBBB")
    assert first["turns"][0]["turn_uid"] == repeated["turns"][0]["turn_uid"]
    assert first["turns"][0]["turn_uid"] != other["turns"][0]["turn_uid"]
    assert not validate_controlled_identifiers(first)
    assert validate_controlled_identifiers({"target_turn_uids": ["turn-invalid"]})[0]["reason_code"] == "controlled_turn_identifier_invalid"


def test_hmac_actor_identifier_is_excluded_from_content_scan_but_uses_stable_format():
    parsed = parse_conversation_context('<div>买家：请问尺寸</div>', hmac_key=SECRET)
    actor = parsed["turns"][0]["speaker_uid"]
    assert actor.startswith("actor_")
    assert not scan_privacy_output({"speaker_uid": actor, "conversation": parsed})


def test_parser_caps_message_containers_and_marks_the_context_truncated():
    raw = "".join(
        f'<div class="imui-msg imui-msg-l"><div class="msg-body-text">{index}</div></div>'
        for index in range(501)
    )
    parsed = parse_conversation_context(raw, hmac_key=SECRET)
    assert len(parsed["turns"]) == 500
    assert parsed["conversation_truncated"] is True


@pytest.mark.parametrize("value,reason", [
    ("电话 13800138000", "phone_number_detected"),
    ("邮箱 a@example.com", "email_detected"),
    ("地址 北京市朝阳区幸福路12号", "address_detected"),
    ("https://example.test/a?token=x", "url_detected"),
    ("<div class='buyer'>x</div>", "html_or_entity_detected"),
    ("data:image/png;base64,AAAA", "data_url_detected"),
])
def test_scanner_reports_reason_without_echoing_source(value, reason):
    findings = scan_privacy_output({"field": value})
    assert {item["reason_code"] for item in findings} >= {reason}
    assert all(value not in json.dumps(item, ensure_ascii=False) for item in findings)


def _claim(**overrides):
    result = {
        "claim_uid": "claim-1", "claim_kind": "product_fact", "query_fact_type": "dimensions",
        "attribute_key": "width", "expected_status": "supported", "acceptable_values": ["80"],
        "normalized_value": "80", "unit": "cm", "required_terms": ["80"],
        "supporting_evidence_uids": ["evidence-1"], "required_tool": None,
        "required_action_points": [], "must_handoff": False, "forbidden_claims": [],
        "partial_answer_allowed": False, "review_status": "approved",
    }
    result.update(overrides)
    return result


def test_label_store_requires_evidence_and_optimistic_lock(tmp_path):
    store = RealAccuracyLabelStore(tmp_path / "labels.db")
    actor = reviewer_actor_hash("reviewer", "test-audit-key")
    with pytest.raises(LabelValidationError, match="evidence_required"):
        store.save(case_uid="case-1", dataset_version="v1", claims=[_claim(supporting_evidence_uids=[])],
                   target_turn_uids=[TARGET_TURN_UID], review_status="approved", actor_hash=actor, expected_version=0, allow_approval=True)
    saved = store.save(case_uid="case-1", dataset_version="v1", claims=[_claim()], review_status="approved",
                       target_turn_uids=[TARGET_TURN_UID], actor_hash=actor, expected_version=0, allow_approval=True)
    assert saved["optimistic_lock_version"] == 1
    assert saved["label"]["target_turn_uids"] == [TARGET_TURN_UID]
    with pytest.raises(LabelConflictError):
        store.save(case_uid="case-1", dataset_version="v1", claims=[_claim()], review_status="approved",
                   target_turn_uids=[TARGET_TURN_UID], actor_hash=actor, expected_version=0, allow_approval=True)


def test_reviewer_cannot_approve_and_high_risk_without_evidence_is_unresolved(tmp_path):
    store = RealAccuracyLabelStore(tmp_path / "labels.db")
    actor = reviewer_actor_hash("reviewer", "test-audit-key")
    with pytest.raises(LabelValidationError, match="supervisor_approval_required"):
        store.save(case_uid="case-1", dataset_version="v1", claims=[_claim()], review_status="approved",
                   target_turn_uids=[TARGET_TURN_UID], actor_hash=actor, expected_version=0, allow_approval=False)
    with pytest.raises(LabelValidationError, match="unsupported_high_risk"):
        store.save(case_uid="case-1", dataset_version="v1", claims=[_claim(attribute_key="child_safety", supporting_evidence_uids=[], review_status="draft")],
                   review_status="draft", actor_hash=actor, expected_version=0, allow_approval=False)


def test_reviewed_and_approved_labels_require_a_target_buyer_turn(tmp_path):
    store = RealAccuracyLabelStore(tmp_path / "labels.db")
    actor = reviewer_actor_hash("reviewer", "test-audit-key")
    store.save(
        case_uid="case-1", dataset_version="v1", claims=[_claim(review_status="draft")],
        review_status="draft", actor_hash=actor, expected_version=0, allow_approval=False,
    )
    with pytest.raises(LabelValidationError, match="target_buyer_turn_required"):
        store.save(
            case_uid="case-2", dataset_version="v1", claims=[_claim(review_status="draft")],
            review_status="reviewed", actor_hash=actor, expected_version=0, allow_approval=False,
        )
