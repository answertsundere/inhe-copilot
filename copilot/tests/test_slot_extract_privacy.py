from __future__ import annotations


def test_slot_extract_keeps_structured_order_reference_out_of_trace_summary():
    from app.agent.nodes.slot_extract import slot_extract

    reference = "opaque-sidebar-order-reference"
    result = slot_extract(
        {
            "customer_message": "请查一下物流进度",
            "normalized_message": "请查一下物流进度",
            "order_id": reference,
            "tracking_no": "",
            "copilot_context": {
                "order_id": reference,
                "order_identifier_type": "unknown_identifier",
                "order_reference_source": "explicit_request",
            },
            "_runtime_explicit_order_reference": {
                "source": "explicit_request",
                "identifier_type": "unknown_identifier",
            },
            "trace_steps": [],
        }
    )

    assert result["slots"]["order_id"] == reference
    assert result["slots"]["identifier_type"] == "unknown_identifier"
    assert reference not in result["trace_steps"][-1]["summary"]
