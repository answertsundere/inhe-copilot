import json
from types import SimpleNamespace

import pytest

from app import config
import app.llm.client as client_module
from app.llm.client import LLMClient


class _FakeCompletions:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return self.response


def _response(*, content="{}", finish_reason="stop"):
    return SimpleNamespace(
        choices=[SimpleNamespace(
            finish_reason=finish_reason,
            message=SimpleNamespace(content=content),
        )]
    )


def _client(api_base: str, response, **client_kwargs):
    client = LLMClient(
        api_key="test-key",
        api_base=api_base,
        model="test-model",
        **client_kwargs,
    )
    completions = _FakeCompletions(response)
    client._client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    return client, completions


def test_minimax_transport_separates_reasoning_and_expands_output_budget():
    client, completions = _client(
        "https://api.minimaxi.com/v1",
        _response(content='{"suggested_reply":"ok"}'),
    )

    client.create_chat_completion(
        model="MiniMax-M2.7",
        messages=[{"role": "user", "content": "hello"}],
        temperature=0,
        max_tokens=300,
        response_format={"type": "json_object"},
    )

    request = completions.calls[0]
    assert client.provider_name == "minimax"
    assert request["temperature"] == 0.1
    assert request["max_tokens"] == 1200
    assert request["extra_body"] == {"reasoning_split": True}
    assert request["response_format"] == {"type": "json_object"}


def test_minimax_m3_disables_thinking_and_uses_shorter_safe_budget():
    client, completions = _client(
        "https://api.minimaxi.com/v1",
        _response(content='{"suggested_reply":"ok"}'),
    )

    client.create_chat_completion(
        model="MiniMax-M3",
        messages=[{"role": "user", "content": "hello"}],
        temperature=0,
        max_tokens=300,
    )

    request = completions.calls[0]
    assert request["max_tokens"] == 800
    assert request["extra_body"] == {
        "reasoning_split": True,
        "thinking": {"type": "disabled"},
    }


def test_minimax_normalizes_only_complete_json_objects():
    response = _response(content='Here is the result:\n```json\n{"intent":"general"}\n```')
    client, _ = _client("https://api.minimaxi.com/v1", response)

    result = client.create_chat_completion(
        model="MiniMax-M3",
        messages=[{"role": "user", "content": "hello"}],
        response_format={"type": "json_object"},
    )

    assert result.choices[0].message.content == '{"intent": "general"}'


def test_minimax_retries_incomplete_json_once_without_repairing_it():
    content = '```json\n{"intent":"general"'
    client, completions = _client(
        "https://api.minimaxi.com/v1",
        _response(content=content),
    )

    with pytest.raises(RuntimeError, match="minimax_invalid_json_object"):
        client.create_chat_completion(
            model="MiniMax-M3",
            messages=[{"role": "user", "content": "hello"}],
            response_format={"type": "json_object"},
        )

    assert len(completions.calls) == 2


def test_minimax_json_retry_accepts_a_later_complete_object():
    client = LLMClient(
        api_key="test-key",
        api_base="https://api.minimaxi.com/v1",
        model="MiniMax-M3",
    )
    responses = iter([
        _response(content='```json\n{"intent":"general"'),
        _response(content='{"intent":"general"}'),
    ])

    class _RetryCompletions:
        def __init__(self):
            self.calls = []

        def create(self, **kwargs):
            self.calls.append(kwargs)
            return next(responses)

    completions = _RetryCompletions()
    client._client = SimpleNamespace(chat=SimpleNamespace(completions=completions))

    result = client.create_chat_completion(
        model="MiniMax-M3",
        messages=[{"role": "user", "content": "hello"}],
        response_format={"type": "json_object"},
    )

    assert result.choices[0].message.content == '{"intent": "general"}'
    assert len(completions.calls) == 2


def test_minimax_does_not_retry_truncated_json():
    client, completions = _client(
        "https://api.minimaxi.com/v1",
        _response(content='{"intent":"general"}', finish_reason="length"),
    )

    with pytest.raises(RuntimeError, match="minimax_response_truncated"):
        client.create_chat_completion(
            model="MiniMax-M3",
            messages=[{"role": "user", "content": "hello"}],
            response_format={"type": "json_object"},
        )

    assert len(completions.calls) == 1

def test_deepseek_transport_disables_default_thinking_without_changing_budget():
    client, completions = _client(
        "https://api.deepseek.com/v1",
        _response(content='{"suggested_reply":"ok"}'),
    )

    client.create_chat_completion(
        model="deepseek-chat",
        messages=[{"role": "user", "content": "hello"}],
        temperature=0,
        max_tokens=300,
    )

    request = completions.calls[0]
    assert client.provider_name == "deepseek"
    assert request["temperature"] == 0
    assert request["max_tokens"] == 300
    assert request["extra_body"] == {"thinking": {"type": "disabled"}}


def test_other_transport_is_not_rewritten():
    client, completions = _client(
        "https://api.example.test/v1",
        _response(content='{"suggested_reply":"ok"}'),
    )

    client.create_chat_completion(
        model="generic-model",
        messages=[{"role": "user", "content": "hello"}],
        temperature=0,
        max_tokens=300,
    )

    request = completions.calls[0]
    assert client.provider_name == "api"
    assert request["temperature"] == 0
    assert request["max_tokens"] == 300
    assert "extra_body" not in request


def test_explicit_composer_transport_capabilities_disable_thinking_and_expand_budget():
    client, completions = _client(
        "https://api.example.test/v1",
        _response(content='{"suggested_reply":"ok"}'),
        transport_thinking="disabled",
        minimum_output_tokens=1200,
    )

    client.create_chat_completion(
        model="candidate-model",
        messages=[{"role": "user", "content": "hello"}],
        temperature=0,
        max_tokens=500,
    )

    request = completions.calls[0]
    assert request["max_tokens"] == 1200
    assert request["extra_body"] == {"thinking": {"type": "disabled"}}


def test_formal_client_uses_explicit_transport_capabilities(monkeypatch):
    monkeypatch.setattr(config, "COPILOT_LLM_TRANSPORT_THINKING", "disabled")
    monkeypatch.setattr(config, "COPILOT_LLM_MIN_OUTPUT_TOKENS", 1200)
    monkeypatch.setattr(client_module, "_client", None)

    client = client_module.get_llm_client()

    assert client.transport_thinking == "disabled"
    assert client.minimum_output_tokens == 1200


def test_formal_client_transport_defaults_preserve_existing_behavior(monkeypatch):
    monkeypatch.setattr(config, "COPILOT_LLM_TRANSPORT_THINKING", "")
    monkeypatch.setattr(config, "COPILOT_LLM_MIN_OUTPUT_TOKENS", 0)
    monkeypatch.setattr(client_module, "_client", None)

    client = client_module.get_llm_client()

    assert client.transport_thinking == ""
    assert client.minimum_output_tokens == 0


def test_client_projects_private_customer_text_before_provider_call():
    client, completions = _client(
        "https://api.deepseek.com/v1",
        _response(content='{"suggested_reply":"ok"}'),
    )

    client.create_chat_completion(
        model="deepseek-chat",
        messages=[{"role": "user", "content": "订单号 A-12345，手机号 13812345678，改寄上海市浦东新区测试路88号"}],
    )

    rendered = str(completions.calls[0]["messages"])
    assert "A-12345" not in rendered
    assert "13812345678" not in rendered


def test_client_uses_field_aware_projection_for_json_system_and_multimodal_text_parts():
    client, completions = _client(
        "https://api.deepseek.com/v1",
        _response(content='{"suggested_reply":"ok"}'),
    )
    evidence = {
        "product_title": "英禾防夹收纳柜，客厅卧室可用",
        "material": "PP 材质，适合客厅卧室收纳",
        "order_id": "2026071900012345",
    }

    client.create_chat_completion(
        model="deepseek-chat",
        messages=[
            {"role": "system", "content": "仅使用商品资料回答，不要泄露 api_key=secret-value。"},
            {"role": "user", "content": json.dumps(evidence, ensure_ascii=False)},
            {"role": "user", "content": [
                {"type": "text", "text": json.dumps(evidence, ensure_ascii=False)},
                {"type": "image_url", "image_url": {"url": "https://example.test/image.png"}},
            ]},
        ],
    )

    rendered = str(completions.calls[0]["messages"])
    assert "英禾防夹收纳柜，客厅卧室可用" in rendered
    assert "PP 材质，适合客厅卧室收纳" in rendered
    assert "secret-value" not in rendered
    assert "2026071900012345" not in rendered


def test_client_preserves_room_semantics_and_redacts_structured_private_fields():
    client, completions = _client(
        "https://api.deepseek.com/v1",
        _response(content='{"suggested_reply":"ok"}'),
    )
    payload = {
        "customer_message": "放浴室是不是就不怕水",
        "product_title": "客厅卧室浴室收纳凳",
        "fact": "主体材质为PP，宽80厘米，颜色为白色",
        "buyer_id": "buyer-private-001",
        "account": "buyer-account-001",
        "email": "buyer@example.test",
        "address": "北京市朝阳区幸福路12号",
        "tracking_no": "SF1234567890123",
        "url": "https://example.test/private/path?token=value",
    }

    client.create_chat_completion(
        model="deepseek-chat",
        messages=[
            {"role": "system", "content": "保留卧室、浴室、客厅等商品使用语义。"},
            {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": json.dumps(payload, ensure_ascii=False),
                    },
                ],
            },
        ],
    )

    rendered = str(completions.calls[0]["messages"])
    assert "放浴室是不是就不怕水" in rendered
    assert "客厅卧室浴室收纳凳" in rendered
    assert "主体材质为PP，宽80厘米，颜色为白色" in rendered
    assert "buyer-private-001" not in rendered
    assert "buyer-account-001" not in rendered
    assert "buyer@example.test" not in rendered
    assert "幸福路12号" not in rendered
    assert "SF1234567890123" not in rendered
    assert "https://example.test/private/path?token=value" not in rendered


def test_client_projects_fenced_json_and_label_lines_in_text_parts_without_mutating_product_facts():
    client, completions = _client(
        "https://api.deepseek.com/v1",
        _response(content='{"suggested_reply":"ok"}'),
    )
    text = '说明 ```json {"order_id":"O-1234","sku_code":"SKU-ABC","product_title":"客厅收纳柜"} ``` 订单号: O-1234'

    client.create_chat_completion(
        model="deepseek-chat",
        messages=[{"role": "user", "content": [{"type": "text", "text": text}]}],
    )

    rendered = str(completions.calls[0]["messages"])
    assert "O-1234" not in rendered
    assert "SKU-ABC" not in rendered
    assert "客厅收纳柜" in rendered


@pytest.mark.parametrize(
    ("content", "finish_reason", "reason"),
    [
        ('{"suggested_reply":"partial"}', "length", "minimax_response_truncated"),
        ("", "stop", "minimax_empty_response"),
    ],
)
def test_minimax_incomplete_output_fails_closed(content, finish_reason, reason):
    client, _ = _client(
        "https://api.minimaxi.com/v1",
        _response(content=content, finish_reason=finish_reason),
    )

    with pytest.raises(RuntimeError, match=reason):
        client.create_chat_completion(
            model="MiniMax-M2.7",
            messages=[{"role": "user", "content": "hello"}],
            max_tokens=1200,
        )
