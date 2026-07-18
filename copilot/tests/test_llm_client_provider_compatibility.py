from types import SimpleNamespace

import pytest

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


def _client(api_base: str, response):
    client = LLMClient(api_key="test-key", api_base=api_base, model="test-model")
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


def test_minimax_does_not_repair_incomplete_json():
    content = '```json\n{"intent":"general"'
    client, _ = _client(
        "https://api.minimaxi.com/v1",
        _response(content=content),
    )

    result = client.create_chat_completion(
        model="MiniMax-M3",
        messages=[{"role": "user", "content": "hello"}],
        response_format={"type": "json_object"},
    )

    assert result.choices[0].message.content == content


def test_non_minimax_transport_is_not_rewritten():
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
    assert "extra_body" not in request


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
