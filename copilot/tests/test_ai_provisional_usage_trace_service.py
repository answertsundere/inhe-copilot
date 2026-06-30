from __future__ import annotations

from app.services.ai_provisional_usage_trace_service import extract_ai_provisional_usage


def _evidence(draft_uid: str = "aipk_trace_one", **overrides):
    item = {
        "evidence_id": draft_uid,
        "provisional_draft_uid": draft_uid,
        "source_table": "ai_provisional_knowledge",
        "protocol_source_type": "ai_prefill",
        "provisional_knowledge_used": True,
        "fact_type": "promotion",
        "i_id": "YH90K01",
        "sku_code": "YH90K01B01S01",
        "kb_product_id": 90,
        "identity_status": "resolved",
        "identity_sources": ["ai_provisional_identity_binding"],
        "usable_for_eval": True,
        "usable_for_auto_send": False,
        "needs_human_review": True,
    }
    item.update(overrides)
    return item


def test_extracts_from_top_level_product_first_pack():
    raw = {
        "can_send": False,
        "sendable_reply": "",
        "requires_human_review": True,
        "quality_bucket": {"quality_bucket": "knowledge_gap"},
        "product_first_evidence_pack": {
            "ai_provisional_knowledge": [_evidence()],
        },
    }

    usage = extract_ai_provisional_usage(raw_response=raw, failure_labels=["rag_miss"])

    assert usage["provisional_used_turn"] is True
    assert usage["provisional_evidence_count"] == 1
    assert usage["provisional_used_draft_count"] == 1
    assert usage["provisional_evidence"][0]["draft_uid"] == "aipk_trace_one"
    assert usage["provisional_evidence"][0]["i_id"] == "YH90K01"
    assert usage["quality_bucket"] == "knowledge_gap"
    assert usage["failure_labels"] == ["rag_miss"]


def test_extracts_from_nested_evidence_debug_pack():
    raw = {
        "evidence_debug": {
            "product_context_pack_summary": {
                "evidence_pack": {
                    "matched_facts": [_evidence("aipk_nested")],
                }
            }
        }
    }

    usage = extract_ai_provisional_usage(raw_response=raw)

    assert usage["provisional_used_turn"] is True
    assert usage["provisional_evidence"][0]["draft_uid"] == "aipk_nested"
    assert "evidence_debug.product_context_pack_summary.evidence_pack" in usage["provisional_evidence"][0]["source_path"]


def test_dedupes_same_evidence_across_pack_paths():
    item = _evidence("aipk_dupe")
    raw = {
        "product_first_evidence_pack": {
            "ai_provisional_knowledge": [item],
            "matched_facts": [dict(item)],
            "product_scoped_chunks": [dict(item)],
        },
        "selected_product_first_evidence": dict(item),
    }

    usage = extract_ai_provisional_usage(raw_response=raw)

    assert usage["provisional_evidence_count"] == 1
    assert usage["provisional_used_draft_count"] == 1


def test_missing_identity_is_preserved_not_guessed():
    raw = {
        "product_first_evidence_pack": {
            "ai_provisional_knowledge": [
                _evidence(
                    "aipk_no_identity",
                    i_id="",
                    sku_code="",
                    kb_product_id=None,
                    identity_status="",
                    identity_sources=[],
                )
            ],
        }
    }

    usage = extract_ai_provisional_usage(raw_response=raw)

    evidence = usage["provisional_evidence"][0]
    assert evidence["i_id"] == ""
    assert evidence["sku_code"] == ""
    assert evidence["identity_status"] == ""


def test_auto_send_with_provisional_is_detected():
    raw = {
        "can_send": True,
        "sendable_reply": "ok",
        "reply_delivery": {"auto_send_ready": True},
        "product_first_evidence_pack": {
            "ai_provisional_knowledge": [_evidence("aipk_auto", usable_for_auto_send=True)],
        },
    }

    usage = extract_ai_provisional_usage(raw_response=raw)

    assert usage["auto_send_with_provisional"] is True
    assert usage["provisional_evidence"][0]["usable_for_auto_send"] is True
