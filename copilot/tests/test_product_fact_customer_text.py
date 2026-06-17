from app.agent.nodes.evidence_builder import _profile_fact_text


def test_profile_fact_text_is_customer_facing_without_internal_source_words():
    text, missing = _profile_fact_text(
        {
            "product_name": "\u4e00\u53f7\u5c0f\u718a\u5e8a\u62a4\u680f",
            "status": "published",
            "specs": {
                "odor_note": "\u65e0\u6bd2\u65e0\u5473\uff0c\u65b0\u54c1\u5bc6\u5c01\u540e\u5982\u6709\u8f7b\u5fae\u5305\u88c5\u6c14\u5473\u53ef\u901a\u98ce\u6563\u5473\u3002",
                "material": "\u73af\u4fddPP",
            },
        },
        "odor",
        "\u4ea7\u54c1\u6709\u6c14\u5473\u5417",
    )

    assert not missing
    assert "\u6c14\u5473\u8bf4\u660e" in text
    assert "\u65e0\u6bd2\u65e0\u5473" in text
    assert "\u5546\u54c1\u8d44\u6599\u5e93" not in text
    assert "published" not in text
