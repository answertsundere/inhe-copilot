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


def test_llm_goal_understanding_preserves_multiple_customer_goals_and_dependency(monkeypatch):
    monkeypatch.setattr(service.config, "COPILOT_FACT_TYPE_LLM_ENABLED", True)
    client = _FakeLLMClient({
        "query_fact_type": "material",
        "confidence": 0.91,
        "risk_hint": "medium",
        "secondary_fact_types": ["moisture_resistance"],
        "reason": "multiple explicit needs",
        "customer_goals": [
            {
                "goal_kind": "customer_goal",
                "claim_type": "moisture_resistance",
                "claim_type_exact_match": True,
                "attribute_key": "",
                "semantic_key": "",
                "goal_summary": "confirm moisture boundary",
                "source_text": "customer turn",
                "confidence": 0.9,
            },
            {
                "goal_kind": "evidence_dependency",
                "claim_type": "material_composition",
                "claim_type_exact_match": True,
                "attribute_key": "material",
                "semantic_key": "",
                "goal_summary": "material supports the moisture answer",
                "source_text": "multi-goal",
                "confidence": 0.8,
            },
            {
                "goal_kind": "customer_goal",
                "claim_type": "material_composition",
                "claim_type_exact_match": True,
                "attribute_key": "material",
                "semantic_key": "",
                "goal_summary": "confirm material",
                "source_text": "multi-goal",
                "confidence": 0.95,
            },
        ],
    })
    monkeypatch.setattr(service, "get_llm_client", lambda: client)

    result = service.classify_query_fact_type_llm_first({
        "customer_message": "multi-goal customer turn",
        "intent": "product_question",
    })

    assert result["goal_understanding_status"] == "valid"
    assert {item["goal_kind"] for item in result["customer_goals"]} == {
        "customer_goal",
        "evidence_dependency",
    }
    assert {
        item["claim_type"]
        for item in result["customer_goals"]
        if item["goal_kind"] == "customer_goal"
    } == {"material_composition", "moisture_resistance"}


def test_llm_goal_refs_are_deduplicated_and_input_order_independent():
    first = [
        {
            "goal_kind": "customer_goal",
            "claim_type": "material",
            "claim_type_exact_match": True,
            "attribute_key": "",
            "semantic_key": "",
            "goal_summary": "confirm material",
            "source_text": "material question",
            "confidence": 0.9,
        },
        {
            "goal_kind": "customer_goal",
            "claim_type": "",
            "claim_type_exact_match": False,
            "attribute_key": "durability",
            "semantic_key": "durability",
            "goal_summary": "confirm durability boundary",
            "source_text": "durability question",
            "confidence": 0.8,
        },
    ]

    message = "material question and durability question"
    forward, status, diagnostics = service._sanitize_customer_goals(
        [*first, first[0]],
        message=message,
    )
    reverse, reverse_status, reverse_diagnostics = service._sanitize_customer_goals(
        list(reversed(first)),
        message=message,
    )

    assert status == reverse_status == "valid"
    assert diagnostics == reverse_diagnostics == []
    assert forward == reverse
    assert len(forward) == 2
    assert len({item["goal_ref"] for item in forward}) == 2


def test_invalid_goal_schema_fails_closed_without_inventing_goal():
    goals, status, diagnostics = service._sanitize_customer_goals([
        {
            "goal_kind": "customer_goal",
            "claim_type": "not-a-fact-type",
            "claim_type_exact_match": True,
            "semantic_key": "",
        },
        {
            "goal_kind": "unknown-kind",
            "claim_type": "material",
            "claim_type_exact_match": True,
        },
    ], message="invalid goal")

    assert goals == []
    assert status == "invalid"
    assert diagnostics == [
        "customer_goal_claim_type_invalid",
        "customer_goal_kind_invalid",
        "customer_goal_semantics_missing",
    ]


def test_customer_goal_source_span_is_verified_and_raw_text_is_not_retained():
    message = "这款本身是什么材质，能不能保证摔不坏？"
    source_text = "能不能保证摔不坏？"
    goals, status, diagnostics = service._sanitize_customer_goals([
        {
            "goal_kind": "customer_goal",
            "claim_type": "",
            "claim_type_exact_match": False,
            "attribute_key": "durability",
            "semantic_key": "drop_durability",
            "goal_summary": "confirm durability boundary",
            "source_text": source_text,
            "confidence": 0.8,
        },
    ], message=message)

    assert status == "valid"
    assert diagnostics == []
    assert len(goals) == 1
    assert goals[0]["source_span_start"] == message.index(source_text)
    assert goals[0]["source_span_end"] == message.index(source_text) + len(source_text)
    assert len(goals[0]["source_span_sha256"]) == 64
    assert "source_text" not in goals[0]


def test_customer_goal_with_paraphrased_source_span_fails_closed():
    goals, status, diagnostics = service._sanitize_customer_goals([
        {
            "goal_kind": "customer_goal",
            "claim_type": "material",
            "claim_type_exact_match": True,
            "attribute_key": "material",
            "semantic_key": "",
            "goal_summary": "confirm material",
            "source_text": "询问商品材质",
            "confidence": 0.9,
        },
    ], message="这款是什么材质？")

    assert goals == []
    assert status == "invalid"
    assert diagnostics == ["customer_goal_source_span_invalid"]


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
