from __future__ import annotations

from copy import deepcopy

import pytest

from app.services.analysis_pipeline_service import AnalysisPipelineRequest, AnalysisPipelineService
from app.services.canonical_conversation_turn_service import (
    ConversationContextContractError,
    canonical_current_customer_turn_uid,
    is_strict_evaluation_source,
    normalize_conversation_turns,
    project_conversation_turns_for_external_model,
    project_provider_message_text,
    project_value_for_external_model,
)


def test_current_customer_turn_uid_ignores_caller_supplied_turn_uid():
    message = "继续确认这个问题"
    first = canonical_current_customer_turn_uid(
        message,
        conversation_history=[{
            "role": "agent",
            "content": "上一条回复",
            "turn_index": 3,
            "turn_uid": "turn-forged-first",
        }],
    )
    second = canonical_current_customer_turn_uid(
        message,
        conversation_history=[{
            "role": "agent",
            "content": "上一条回复",
            "turn_index": 3,
            "turn_uid": "turn-forged-second",
        }],
    )

    assert first == second
    assert first.startswith("turn-")


def test_normalizes_role_aware_turns_without_preserving_legacy_text_key():
    turns, diagnostics = normalize_conversation_turns([
        {"role": "BUYER", "text": "先问一下尺寸", "turn_index": 3},
        {"role": "AGENT", "message": "我给您看一下", "turn_index": 4},
        {"role": "customer", "content": "那上一条说的宽度是多少", "turn_index": 5},
    ], strict=True)

    assert [turn["role"] for turn in turns] == ["customer", "agent", "customer"]
    assert [turn["content"] for turn in turns][-1] == "那上一条说的宽度是多少"
    assert all("text" not in turn and turn["turn_uid"] for turn in turns)
    assert diagnostics["status"] == "valid"


@pytest.mark.parametrize("value,reason", [
    ("买家: 这个怎么样", "conversation_history_expected_list"),
    ([{"role": "unknown", "content": "这个"}], "conversation_turn_invalid_role"),
    ([{"role": "customer", "content": ""}], "conversation_turn_content_missing"),
])
def test_strict_contract_rejects_unrecoverable_history(value, reason):
    with pytest.raises(ConversationContextContractError, match=reason):
        normalize_conversation_turns(value, strict=True)


def test_legacy_string_is_degraded_only_for_non_evaluation_entrypoint():
    turns, diagnostics = normalize_conversation_turns("买家: 这个怎么样", strict=False)

    assert turns == []
    assert diagnostics["status"] == "degraded"
    assert diagnostics["degraded_context"] is True


def test_pipeline_rejects_string_history_for_evaluation_before_graph(monkeypatch):
    import app.services.analysis_execution_service as execution

    monkeypatch.setattr(execution, "execute_analysis", lambda **_kwargs: pytest.fail("graph must not run"))
    response = AnalysisPipelineService().run(AnalysisPipelineRequest(
        reply_service=object(),
        customer_message="这个呢",
        copilot_context={"conversation_history": "buyer: previous", "evaluation_context_contract": "strict"},
        source="tier_d_long_conversation_simulation",
    ))

    assert response["error"] == "invalid_conversation_context"
    assert response["error_reason"] == "conversation_history_expected_list"
    assert response["can_send"] is False
    assert response["requires_human_review"] is True


def test_pipeline_preserves_earliest_online_degraded_context_reason(monkeypatch):
    import app.services.analysis_execution_service as execution

    captured = {}

    def fake_execute_analysis(**kwargs):
        captured.update(kwargs["copilot_context"])
        return {"suggested_reply": "草稿", "can_send": False, "requires_human_review": True}

    monkeypatch.setattr(execution, "execute_analysis", fake_execute_analysis)
    monkeypatch.setattr(
        "app.services.runtime_knowledge_readiness_service.RuntimeKnowledgeReadinessService.inspect",
        lambda *_args, **_kwargs: {"ready": True, "reasons": [], "knowledge": {}, "database": {}},
    )
    AnalysisPipelineService().run(AnalysisPipelineRequest(
        reply_service=object(), customer_message="当前问题", source="online",
        copilot_context={
            "conversation_history": [],
            "conversation_context_contract": {
                "status": "degraded", "reason": "conversation_history_legacy_nonlist",
            },
        },
    ))

    contract = captured["conversation_context_contract"]
    assert contract["status"] == "degraded"
    assert contract["reason"] == "conversation_history_legacy_nonlist"
    assert contract["original_reason"] == "conversation_history_legacy_nonlist"
    assert contract["pipeline_revalidation_status"] == "valid"


def test_pipeline_canonicalizes_same_context_for_api_benchmark_replay_and_gold(monkeypatch):
    import app.services.analysis_execution_service as execution

    captured = []

    def fake_execute_analysis(**kwargs):
        captured.append(deepcopy(kwargs["copilot_context"]))
        return {"suggested_reply": "草稿", "can_send": False, "requires_human_review": True}

    monkeypatch.setattr(execution, "execute_analysis", fake_execute_analysis)
    monkeypatch.setattr(
        "app.services.runtime_knowledge_readiness_service.RuntimeKnowledgeReadinessService.inspect",
        lambda *_args, **_kwargs: {"ready": True, "reasons": [], "knowledge": {}, "database": {}},
    )
    service = AnalysisPipelineService()
    for source in ("api", "agent_benchmark", "real_conversation_eval", "real_accuracy_baseline"):
        service.run(AnalysisPipelineRequest(
            reply_service=object(), customer_message="这层呢", source=source,
            copilot_context={"conversation_history": [{"role": "customer", "text": "上一个尺寸", "turn_index": 0}]},
        ))

    assert len(captured) == 4
    for context in captured:
        assert context["conversation_history"] == [
            {**context["conversation_history"][0], "role": "customer", "content": "上一个尺寸", "turn_index": 0}
        ]
        assert context["conversation_context_contract"]["status"] == "valid"


def test_online_order_repairs_preserve_input_order_but_strict_rejects_it():
    value = [
        {"role": "customer", "content": "first", "turn_index": 3},
        {"role": "agent", "content": "second", "turn_index": 3},
        {"role": "customer", "content": "third"},
    ]
    turns, diagnostics = normalize_conversation_turns(value)

    assert [item["content"] for item in turns] == ["first", "second", "third"]
    assert [item["turn_index"] for item in turns] == [3, 4, 5]
    assert diagnostics["status"] == "degraded"
    assert diagnostics["repairs"][0]["reason"] == "conversation_turn_index_duplicate"
    with pytest.raises(ConversationContextContractError, match="conversation_turn_index_duplicate"):
        normalize_conversation_turns(value, strict=True)


def test_external_model_projection_redacts_private_text_without_mutating_formal_turn():
    turns, _ = normalize_conversation_turns([{
        "role": "customer",
        "content": "订单号 A-12345，手机 13812345678，改寄到上海市浦东新区测试路88号",
        "turn_index": 1,
    }], strict=True)
    projected = project_conversation_turns_for_external_model(turns)

    assert "A-12345" in turns[0]["content"]
    assert "13812345678" not in projected[0]["content"]
    assert "A-12345" not in projected[0]["content"]
    assert "turn_uid" not in projected[0]


def test_external_projection_preserves_product_titles_and_admitted_facts_with_room_words():
    value = {
        "product_title": "英禾防夹收纳柜，客厅卧室都能使用",
        "admitted_evidence": [{"attribute_key": "material", "value": "PP 材质，适合客厅卧室收纳"}],
        "sku_code": "SKU-IDENTITY-001",
    }

    projected = project_value_for_external_model(value)

    assert projected["product_title"] == value["product_title"]
    assert projected["admitted_evidence"][0]["value"] == value["admitted_evidence"][0]["value"]
    assert projected["sku_code"].startswith("[PRODUCT_ID_REDACTED:")


def test_external_projection_redacts_explicit_private_values_but_not_product_facts():
    value = {
        "product_name": "客厅卧室收纳架",
        "order_id": "2026071900012345",
        "phone": "13812345678",
        "address": "上海市浦东新区测试路88号",
        "tracking_no": "SF1234567890123",
        "fact": "商品材质是 PP，适合客厅卧室收纳",
    }

    projected = project_value_for_external_model(value)

    assert projected["product_name"] == "客厅卧室收纳架"
    assert projected["fact"] == value["fact"]
    assert projected["order_id"].startswith("[STRUCTURED_PRIVATE_ID_REDACTED:")
    assert projected["phone"].startswith("[STRUCTURED_PRIVATE_ID_REDACTED:")
    assert "13812345678" not in str(projected)
    assert "浦东新区测试路88号" not in str(projected)


def test_provider_projection_handles_fenced_prefixed_and_multiple_json_without_losing_product_facts():
    text = '''说明文字
```json
{"order_id":"O-1234","sku_code":"SKU-ABC","product_title":"客厅卧室收纳柜","fact":"PP 材质"}
```
另一个数据块 {"tracking_no":"SF1234567890123","i_id":"IID-1"}。'''

    projected = project_provider_message_text(text)

    assert "O-1234" not in projected
    assert "SKU-ABC" not in projected
    assert "SF1234567890123" not in projected
    assert "IID-1" not in projected
    assert "客厅卧室收纳柜" in projected
    assert "PP 材质" in projected


def test_provider_projection_redacts_label_lines_and_malformed_json_without_repairing_it():
    text = '订单号\nO-1234\nSKU: SKU-ABC\n```json\n{"order_id":"O-1234",}\n```'

    projected = project_provider_message_text(text)

    assert "O-1234" not in projected
    assert "SKU-ABC" not in projected
    assert '{"order_id":"O-1234",}' not in projected
    assert "[REFERENCE_REDACTED:" in projected
    assert "[PRODUCT_ID_REDACTED:" in projected


def test_known_evaluation_sources_are_strict_without_a_caller_flag():
    assert is_strict_evaluation_source("agent_benchmark") is True
    assert is_strict_evaluation_source("real_conversation_eval") is True
    assert is_strict_evaluation_source("real_accuracy_baseline") is True
    assert is_strict_evaluation_source("tier_d_long_conversation_simulation") is True
    assert is_strict_evaluation_source("online", {"evaluation_context_contract": "strict"}) is True
    assert is_strict_evaluation_source("copilot_panel") is False
