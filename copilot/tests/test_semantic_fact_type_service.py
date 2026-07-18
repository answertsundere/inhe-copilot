import json

from app.services import semantic_fact_type_service as service


class _FakeMessage:
    def __init__(self, content):
        self.content = content


class _FakeChoice:
    def __init__(self, content):
        self.message = _FakeMessage(content)


class _FakeResponse:
    def __init__(self, content):
        self.choices = [_FakeChoice(content)]


class _FakeCompletions:
    def __init__(self, payload):
        self.payload = payload

    def create(self, **kwargs):
        return _FakeResponse(json.dumps(self.payload, ensure_ascii=False))


class _FakeChat:
    def __init__(self, payload):
        self.completions = _FakeCompletions(payload)


class _FakeOpenAIClient:
    def __init__(self, payload):
        self.chat = _FakeChat(payload)


class _FakeLLMClient:
    api_key = "test-key"
    model = "test-model"

    def __init__(self, payload):
        self.client = _FakeOpenAIClient(payload)

    def create_chat_completion(self, **kwargs):
        return self.client.chat.completions.create(**kwargs)


def test_llm_first_fact_type_classification(monkeypatch):
    monkeypatch.setattr(service.config, "COPILOT_FACT_TYPE_LLM_ENABLED", True)
    monkeypatch.setattr(
        service,
        "get_llm_client",
        lambda: _FakeLLMClient({
            "query_fact_type": "stability",
            "confidence": 0.93,
            "risk_hint": "high",
            "secondary_fact_types": ["load_capacity"],
            "reason": "客户询问宝宝使用时是否会翻倒，属于稳定/防倾倒安全问题",
        }),
    )

    result = service.classify_query_fact_type_llm_first({
        "customer_message": "宝宝扶着它会不会翻？能不能保证不倒？",
        "intent": "product_question",
    })

    assert result["query_fact_type"] == "stability"
    assert result["source"] == "llm"
    assert result["confidence"] == 0.93
    assert result["secondary_fact_types"] == ["load_capacity"]


def test_fact_type_falls_back_when_llm_unavailable(monkeypatch):
    monkeypatch.setattr(service.config, "COPILOT_FACT_TYPE_LLM_ENABLED", True)
    monkeypatch.setattr(service, "get_llm_client", lambda: type("NoKey", (), {"api_key": ""})())

    # A keyword-free question cannot be classified deterministically (rule_precheck
    # only fires when a rule matches), so the LLM-first path is taken. With the LLM
    # client reporting no api_key it must fall back to the deterministic result.
    result = service.classify_query_fact_type_llm_first({
        "customer_message": "想了解一下这款",
        "intent": "product_question",
    })

    assert result["query_fact_type"] == ""
    assert result["source"] == "rule_fallback"
