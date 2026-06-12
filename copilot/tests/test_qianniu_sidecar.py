from __future__ import annotations

from scripts.qianniu_sidecar import QianNiuSnapshot, build_payload


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
