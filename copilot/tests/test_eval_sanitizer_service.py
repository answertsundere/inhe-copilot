from app.services.eval_sanitizer_service import has_sensitive_leak, sanitize_case_payload, sanitize_payload, sanitize_text


def test_eval_sanitizer_redacts_phone_order_url_base64_and_token():
    raw = (
        "电话13812345678，订单9876543210123456，地址杭州市西湖区文三路1号，"
        "https://oss.example/a.png?signature=SECRET&token=ABC "
        "data:image/png;base64,QUJDREVGRw== api_key=SECRET"
    )

    sanitized = sanitize_text(raw)

    assert "13812345678" not in sanitized
    assert "9876543210123456" not in sanitized
    assert "signature=SECRET" not in sanitized
    assert "QUJDREVGRw==" not in sanitized
    assert "api_key=SECRET" not in sanitized
    assert "***3456#" in sanitized
    assert "url_host:oss.example" in sanitized
    assert "[phone_redacted]" in sanitized
    assert not has_sensitive_leak(sanitized)


def test_eval_sanitizer_removes_sensitive_payload_keys():
    payload = sanitize_payload({
        "intent": "product_question",
        "fact_type": "material",
        "token": "SECRET",
        "image_url": "https://oss.example/a.jpg?signature=SECRET",
        "nested": {"phone": "13812345678", "safe": "ok"},
    })

    assert payload["intent"] == "product_question"
    assert payload["fact_type"] == "material"
    assert "token" not in payload
    assert "image_url" not in payload
    assert "phone" not in payload["nested"]
    assert payload["nested"]["safe"] == "ok"


def test_sanitize_case_payload_keeps_contract_shape_without_raw_private_text():
    case = sanitize_case_payload({
        "customer_message": "我的订单9876543210123456到哪了，电话13812345678",
        "context": {"query_fact_type": "logistics", "address": "杭州市西湖区文三路1号"},
        "product_scope": ["SKU9876543210123456"],
    })

    assert "9876543210123456" not in case["customer_message_sanitized"]
    assert "13812345678" not in case["customer_message_sanitized"]
    assert case["context_sanitized"]["query_fact_type"] == "logistics"
    assert "address" not in case["context_sanitized"]
