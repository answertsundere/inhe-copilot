from __future__ import annotations

import json
from types import SimpleNamespace

from app.services.model_first_answer_composer_service import (
    ModelFirstAnswerComposerService,
)


def _response() -> dict:
    return {
        "suggested_reply": "旧回复",
        "can_send": True,
        "requires_human_review": False,
        "reply_blocks": [{"type": "text", "content": "旧回复"}],
        "minimal_decision_context": {
            "customer_goal": "尺寸和安全怎么样",
            "recent_conversation_turns": [
                {"role": "customer", "content": "我问的是宽度", "turn_index": 1},
            ],
            "product_identity": {"sku_code": "private-sku"},
            "admitted_evidence": [{
                "evidence_uid": "ev-width",
                "fact_type": "dimensions",
                "attribute_key": "width",
                "content": "商品宽度为80厘米",
            }],
            "claim_resolutions": [
                {
                    "claim_type": "dimensions",
                    "status": "supported",
                    "evidence_uids": ["ev-width"],
                },
                {
                    "claim_type": "child_safety",
                    "status": "unresolved",
                    "evidence_uids": [],
                },
            ],
            "context_stats": {"estimated_token_count": 40},
        },
    }


class _Client:
    api_key = "configured"
    model = "MiniMax-M3"

    def __init__(self, payload: dict):
        self.payload = payload
        self.messages = []

    def create_chat_completion(self, **kwargs):
        self.messages = kwargs["messages"]
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(
            content=json.dumps(self.payload, ensure_ascii=False),
        ))])


def test_composer_uses_admitted_refs_and_freezes_delivery_contract():
    client = _Client({
        "reply": "宽度是80厘米；儿童安全方面目前没有直接依据，建议按实际使用环境复核。",
        "used_evidence_refs": ["E1"],
        "unresolved_claim_types": ["child_safety"],
    })

    updated, result = ModelFirstAnswerComposerService().compose(
        _response(),
        customer_message="尺寸和安全怎么样",
        client=client,
    )

    assert result["status"] == "accepted"
    assert result["used_evidence_uids"] == ["ev-width"]
    assert updated["suggested_reply"].startswith("宽度是80厘米")
    assert updated["can_send"] is False
    assert updated["sendable_reply"] == ""
    assert updated["requires_human_review"] is True
    prompt = json.loads(client.messages[1]["content"])
    assert prompt["product_scope"] == {
        "resolved": True,
        "variant_context_present": False,
    }
    assert "private-sku" not in client.messages[1]["content"]


def test_composer_rejects_supported_fact_omission_without_changing_reply():
    client = _Client({
        "reply": "儿童安全方面目前无法确认。",
        "used_evidence_refs": [],
        "unresolved_claim_types": ["child_safety"],
    })

    updated, result = ModelFirstAnswerComposerService().compose(
        _response(),
        customer_message="尺寸和安全怎么样",
        client=client,
    )

    assert result["rejection_reason"] == "composer_supported_claim_omitted"
    assert updated["suggested_reply"] == "旧回复"
    assert updated["can_send"] is True


def test_composer_rejects_unresolved_claim_omission_and_unknown_evidence():
    for payload, reason in (
        ({
            "reply": "宽度是80厘米。",
            "used_evidence_refs": ["E1"],
            "unresolved_claim_types": [],
        }, "composer_unresolved_claim_omitted"),
        ({
            "reply": "宽度是80厘米。",
            "used_evidence_refs": ["E1", "E9"],
            "unresolved_claim_types": ["child_safety"],
        }, "composer_unknown_evidence_reference"),
    ):
        _, result = ModelFirstAnswerComposerService().compose(
            _response(),
            customer_message="尺寸和安全怎么样",
            client=_Client(payload),
        )
        assert result["rejection_reason"] == reason


def test_composer_rejects_media_promise_without_actual_block():
    client = _Client({
        "reply": "宽度是80厘米，尺寸图已经发给您了；儿童安全目前无法确认。",
        "used_evidence_refs": ["E1"],
        "unresolved_claim_types": ["child_safety"],
    })

    _, result = ModelFirstAnswerComposerService().compose(
        _response(),
        customer_message="尺寸和安全怎么样",
        client=client,
    )

    assert result["rejection_reason"] == "composer_unsupported_media_promise"


def test_composer_rejects_verification_process_copy_instead_of_direct_answer():
    client = _Client({
        "reply": "我先帮您核对一下宽度，确认后回复。",
        "used_evidence_refs": ["E1"],
        "unresolved_claim_types": ["child_safety"],
    })

    _, result = ModelFirstAnswerComposerService().compose(
        _response(),
        customer_message="尺寸和安全怎么样",
        client=client,
    )

    assert result["rejection_reason"] == "composer_process_language"


def test_composer_requires_minimal_context():
    original = {"suggested_reply": "旧回复", "can_send": False}

    updated, result = ModelFirstAnswerComposerService().compose(
        original,
        customer_message="这个多宽",
        client=_Client({}),
    )

    assert updated == original
    assert result["rejection_reason"] == "minimal_decision_context_missing"
