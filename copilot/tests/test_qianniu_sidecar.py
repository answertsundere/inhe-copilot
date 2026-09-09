from __future__ import annotations

from scripts.qianniu_sidecar import QianNiuSnapshot, build_payload
from scripts.sidecar import context_parser

import copy
import io
import json

import pytest


def _capture():
    return {
        "schema_version": "qianniu_uia_preview/v1",
        "scope": "visible_conversation_document",
        "binding_before": {"window_ref": "window-a", "conversation_ref": "chat-a"},
        "binding_after": {"window_ref": "window-a", "conversation_ref": "chat-a"},
        "buyer_ref": "buyer-a",
        "agent_refs": ["shop:staff-a", "shop:staff-b"],
        "truncated": False,
        "messages": [
            {"sender_ref": "buyer-a", "recipient_ref": "shop:staff-a",
             "timestamp": "2026-09-09 09:10:00", "parts": [{"type": "text", "content": "How wide is it?"}]},
            {"sender_ref": "shop:staff-b", "recipient_ref": "buyer-a",
             "timestamp": "2026-09-09 09:10:00", "parts": [{"type": "text", "content": "Which size?"}]},
            {"sender_ref": "buyer-a", "recipient_ref": "shop:staff-a",
             "timestamp": "2026-09-09 09:11:00", "parts": [{"type": "text", "content": "How wide is it?"}]},
        ],
        "order_candidates": ["123456789012345678", "234567890123456789"],
        "product_code_candidates": ["ITEM-TEST-1"],
    }


def _preview(capture):
    assert hasattr(context_parser, "build_uia_preview"), "structured preview contract is missing"
    return context_parser.build_uia_preview(capture)


def test_structured_preview_preserves_roles_repetition_order_and_unverified_candidates():
    capture = _capture()
    original = copy.deepcopy(capture)
    result = _preview(capture)
    assert capture == original
    assert result.diagnostics["status"] == "preview_ready"
    assert result.diagnostics["customer_turn_count"] == 2
    assert result.diagnostics["agent_turn_count"] == 1
    assert [t["role"] for t in result.context["conversation_history"]] == ["customer", "agent"]
    assert result.context["customer_message"] == "How wide is it?"
    assert result.context["conversation_history"][0]["content"] == "How wide is it?"
    assert all("text" not in t for t in result.context["conversation_history"])
    assert [item["value"] for item in result.context["order_candidates"]] == capture["order_candidates"]
    assert all(item["verified"] is False for item in result.context["order_candidates"])
    assert "order_id" not in result.context
    assert "sku_id" not in result.context
    assert result.diagnostics["can_send"] is False
    assert result.diagnostics["requires_human_review"] is True
    assert result.diagnostics["should_call_copilot_context"] is False
    assert result.diagnostics["new_message_detection_qualified"] is False


@pytest.mark.parametrize("mutation,reason", [
    (lambda c: c["binding_after"].update(window_ref="window-b"), "capture_binding_changed"),
    (lambda c: c["binding_after"].update(conversation_ref="chat-b"), "capture_binding_changed"),
    (lambda c: c.update(binding_before={}), "capture_binding_missing"),
    (lambda c: c.update(scope="whole_window"), "conversation_scope_required"),
    (lambda c: c.update(truncated=True), "capture_truncated_or_unknown"),
    (lambda c: c.pop("truncated"), "capture_truncated_or_unknown"),
    (lambda c: c["messages"][0].update(sender_ref="other-buyer"), "speaker_unresolved"),
    (lambda c: c["messages"][1].update(recipient_ref="other-buyer"), "speaker_unresolved"),
    (lambda c: c.update(agent_refs=["buyer-a"]), "actor_binding_invalid"),
    (lambda c: c["messages"][1].update(timestamp="2026-09-08 09:10:00"), "timestamp_out_of_order"),
    (lambda c: c["messages"][0].update(timestamp="not-a-date"), "timestamp_invalid"),
    (lambda c: c["messages"][0].update(parts=[]), "message_parts_invalid"),
    (lambda c: c["messages"][0]["parts"][0].update(type="unknown"), "message_part_type_unknown"),
    (lambda c: c["messages"][0]["parts"][0].update(content=" "), "message_text_invalid"),
    (lambda c: c.update(messages=c["messages"] * 100), "message_count_invalid"),
    (lambda c: c.update(order_candidates="12345"), "candidate_list_invalid"),
    (lambda c: c.update(schema_version="unrecognized"), "capture_schema_invalid"),
])
def test_structured_preview_fail_closed(mutation, reason):
    capture = _capture()
    mutation(capture)
    result = _preview(capture)
    assert result.context == {}
    assert result.diagnostics["status"] == "blocked"
    assert result.diagnostics["reason_code"] == reason
    assert result.diagnostics["should_call_copilot_context"] is False


def test_historical_agent_tail_is_not_a_new_customer_question():
    capture = _capture()
    capture["messages"] = capture["messages"][:2]
    result = _preview(capture)
    assert result.context["customer_message"] == ""
    assert len(result.context["conversation_history"]) == 2
    assert result.diagnostics["should_call_copilot_context"] is False


def test_structured_preview_media_tokens_no_card_fact_or_url_injection():
    capture = _capture()
    capture["messages"][-1]["parts"] = [
        {"type": "text", "content": "订单信息不是我的问题"},
        {"type": "product_card", "content": "unsupported fact"},
        {"type": "link", "content": "https://private.invalid/account"},
        {"type": "image", "content": "private image location"},
    ]
    result = _preview(capture)
    assert result.context["customer_message"] == "订单信息不是我的问题 [PRODUCT_CARD] [LINK] [IMAGE]"
    assert "unsupported fact" not in repr(result.context)
    assert "private.invalid" not in repr(result.context)


def test_preview_repr_and_diagnostics_do_not_expose_customer_data():
    result = _preview(_capture())
    public = repr(result) + json.dumps(result.diagnostics)
    for secret in ("buyer-a", "shop:staff", "123456789012345678", "ITEM-TEST-1", "How wide"):
        assert secret not in public


def test_preview_cli_does_not_log_post_or_start_legacy_loop(monkeypatch, capsys):
    from scripts import qianniu_sidecar
    def prohibited(*args, **kwargs):
        pytest.fail("read-only preview invoked a side effect")
    monkeypatch.setattr(qianniu_sidecar, "configure_logging", prohibited)
    monkeypatch.setattr(qianniu_sidecar, "run_loop", prohibited)
    monkeypatch.setattr(qianniu_sidecar, "post_context", prohibited)
    monkeypatch.setattr("sys.argv", ["qianniu_sidecar", "--structured-preview-stdin"])
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(_capture())))
    assert qianniu_sidecar.main() == 0
    report = json.loads(capsys.readouterr().out)
    assert report["status"] == "preview_ready"
    assert "conversation_history" not in report


def test_preview_cli_rejects_invalid_json_without_echo(monkeypatch, capsys):
    from scripts import qianniu_sidecar
    monkeypatch.setattr("sys.argv", ["qianniu_sidecar", "--structured-preview-stdin"])
    monkeypatch.setattr("sys.stdin", io.StringIO("secret-raw-payload"))
    assert qianniu_sidecar.main() == 2
    output = capsys.readouterr().out
    assert "secret-raw-payload" not in output
    assert json.loads(output)["reason_code"] == "capture_json_invalid"


def test_build_payload_from_snapshot():
    payload = build_payload(QianNiuSnapshot(
        window_title="千牛接待 - 测试买家",
        chat_text="客服: 您好\n买家: SF0229477422177我的快递什么时候到",
        raw_context={"text_line_count": 2},
    ))
    assert payload["source"] == "qianniu_sidecar"
    assert payload["window_title"] == "千牛接待 - 测试买家"
    assert payload["customer_message"] == "SF0229477422177我的快递什么时候到"
    assert payload["tracking_no"] == "SF0229477422177"
    assert payload["identifier_type"] == "tracking_no"
