from __future__ import annotations

from scripts.sidecar.text_repair import repair_mojibake_obj, repair_mojibake_text


def test_repair_cp1252_utf8_mojibake():
    text = "\xe4\xbc\u0161\xe6\u017d\u2030\xe4\xb8\u2039\xe6\x9d\xa5\xe4\xb9\u02c6"
    assert repair_mojibake_text(text) == "\u4f1a\u6389\u4e0b\u6765\u4e48"


def test_repair_nested_vlm_payload():
    payload = {
        "latest_customer_message": "\xe4\xbc\u0161\xe6\u017d\u2030\xe4\xb8\u2039\xe6\x9d\xa5\xe4\xb9\u02c6",
        "messages": [{"role": "customer", "text": "\xe6\u02c6\u2018\xe5\xba\u0160\xe4\xb8\x8d\xe6\u02dc\xaf\xe5\u2020\u2026\xe5\xb5\u0152\xe7\u0161\u201e"}],
    }

    fixed = repair_mojibake_obj(payload)

    assert fixed["latest_customer_message"] == "\u4f1a\u6389\u4e0b\u6765\u4e48"
    assert fixed["messages"][0]["text"] == "\u6211\u5e8a\u4e0d\u662f\u5185\u5d4c\u7684"
