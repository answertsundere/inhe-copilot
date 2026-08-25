import json

from app.repositories.file_policy_repository import FilePolicyRepository
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
        self.kwargs = None

    def create(self, **kwargs):
        self.kwargs = kwargs
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


class _FakeStrictTurnProvider:
    def __init__(self, payload=None, error=""):
        self.payload = payload or {"goals": []}
        self.error = error
        self.calls = []
        self.last_latency_ms = 12.5

    def metadata(self):
        return {
            "provider_name": "strict-turn-test",
            "host_fingerprint": "a" * 12,
            "model_name": "strict-turn-model",
            "configured": True,
            "qualified": not self.error,
        }

    def request(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise service.StrictDecisionProviderError(self.error)
        return self.payload


def _complete_llm_payload(**overrides):
    payload = {"goals": []}
    payload.update(overrides)
    return payload


def test_semantic_query_preserves_unique_dimension_subject_scope():
    semantic_query = service._semantic_query_from_result(
        {
            "query_fact_type": "dimensions",
            "customer_goals": [{
                "goal_kind": "customer_goal",
                "claim_type_status": "canonical",
                "claim_type": "dimensions",
                "subject_scope": "packaging",
            }],
        },
        "请告诉我外包装长宽高",
    )

    assert semantic_query["subject_scope"] == "packaging"


def test_semantic_query_does_not_guess_between_multiple_dimension_subject_scopes():
    semantic_query = service._semantic_query_from_result(
        {
            "query_fact_type": "dimensions",
            "customer_goals": [
                {
                    "goal_kind": "customer_goal",
                    "claim_type_status": "canonical",
                    "claim_type": "dimensions",
                    "subject_scope": "product",
                },
                {
                    "goal_kind": "customer_goal",
                    "claim_type_status": "canonical",
                    "claim_type": "dimensions",
                    "subject_scope": "packaging",
                },
            ],
        },
        "商品和外包装分别多大",
    )

    assert "subject_scope" not in semantic_query


def test_llm_first_fact_type_classification(monkeypatch):
    message = "宝宝扶着它会不会翻？能不能保证不倒？"
    monkeypatch.setattr(service.config, "COPILOT_FACT_TYPE_LLM_ENABLED", True)
    monkeypatch.setattr(
        service,
        "get_llm_client",
        lambda: _FakeLLMClient(_complete_llm_payload(**{
            "goals": [{
                "goal_kind": "customer_goal",
                "claim_type_status": "canonical",
                "claim_type": "stability",
                "attribute_key": "",
                "semantic_key": "",
                "policy_intent_ref": "",
                "source_text": message,
            }],
        })),
    )

    result = service.classify_query_fact_type_llm_first({
        "customer_message": message,
        "intent": "product_question",
    })

    assert result["query_fact_type"] == "stability"
    assert result["source"] == "llm"
    assert result["confidence"] == 1.0
    assert result["secondary_fact_types"] == []


def test_product_overview_is_a_canonical_model_selectable_fact_type(monkeypatch):
    message = "Give me a general assessment of the identified product."
    monkeypatch.setattr(service.config, "COPILOT_FACT_TYPE_LLM_ENABLED", True)
    monkeypatch.setattr(
        service,
        "get_llm_client",
        lambda: _FakeLLMClient(_complete_llm_payload(**{
            "goals": [{
                "goal_kind": "customer_goal",
                "claim_type_status": "canonical",
                "claim_type": "product_overview",
                "attribute_key": "",
                "semantic_key": "",
                "policy_intent_ref": "",
                "source_text": message,
            }],
        })),
    )

    result = service.classify_query_fact_type_llm_first({
        "customer_message": message,
        "intent": "product_question",
    })

    assert result["query_fact_type"] == "product_overview"
    assert result["customer_goals"][0]["claim_type"] == "product_overview"
    overview = next(
        item
        for item in service._canonical_fact_type_candidates()
        if item["fact_type_id"] == "product_overview"
    )
    assert overview["meaning"].startswith("商品质量/综合情况")
    assert "broad" in overview["classification_boundary"].lower()
    assert "guarantee" in overview["classification_boundary"].lower()


def test_strict_turn_understanding_reuses_schema_prompt_and_normalizer(
    monkeypatch,
):
    message = "现在怎么说"
    strict = _FakeStrictTurnProvider({
        "goals": [{
            "goal_kind": "contextual_constraint",
            "claim_type_status": "unmapped",
            "claim_type": "",
            "attribute_key": "",
            "subject_scope": "",
            "semantic_key": "confirmation",
            "policy_intent_ref": "",
            "source_start_ref": "char-0000",
            "source_end_ref": "char-0004",
            "continued_from": "",
        }],
    })
    monkeypatch.setattr(service.config, "COPILOT_FACT_TYPE_LLM_ENABLED", True)
    monkeypatch.setattr(
        service.config,
        "COPILOT_TURN_UNDERSTANDING_STRICT_ENABLED",
        True,
    )
    monkeypatch.setattr(
        service.StrictDecisionProviderConfig,
        "from_turn_understanding_environment",
        classmethod(lambda cls: object()),
    )
    monkeypatch.setattr(
        service,
        "StrictDecisionProviderService",
        lambda config: strict,
    )
    monkeypatch.setattr(
        service,
        "get_llm_client",
        lambda: (_ for _ in ()).throw(
            AssertionError("legacy provider must not be used")
        ),
    )
    diagnostics = {}

    result = service.classify_query_fact_type_llm_first(
        {
            "customer_message": message,
            "intent": "general",
            "conversation_history": [
                {"role": "agent", "content": "核实后给您消息。"},
            ],
        },
        diagnostics_sink=diagnostics,
    )

    assert len(strict.calls) == 1
    assert strict.calls[0]["schema"] == (
        service.STRICT_PROVIDER_OUTPUT_SCHEMA
    )
    assert strict.calls[0]["system_prompt"] == service.SYSTEM_PROMPT
    assert strict.calls[0]["payload"]["customer_message"] == message
    assert strict.calls[0]["payload"]["source_units"] == [
        {"ref": f"char-{index:04d}", "text": character}
        for index, character in enumerate(message)
    ]
    assert result["goal_understanding_status"] == "valid"
    goal = result["customer_goals"][0]
    assert goal["source_span_start"] == 0
    assert goal["source_span_end"] == len(message)
    assert len(goal["source_span_sha256"]) == 64
    assert "source_text" not in goal
    assert diagnostics["provider"]["provider_family"] == "strict-turn-test"
    assert diagnostics["model_call_count"] == 1


def test_turn_understanding_prompt_preserves_coexisting_customer_boundary():
    normalized_prompt = " ".join(service.SYSTEM_PROMPT.split())
    assert (
        "A conversational boundary may coexist with a factual, media, or "
        "service request"
    ) in normalized_prompt
    assert (
        "emit it as a separate contextual_constraint"
        in normalized_prompt
    )
    assert (
        "forbids what customer service may say, claim, imply, promise, or "
        "represent as completed"
    ) in normalized_prompt


def test_turn_understanding_prompt_requires_aggregate_dimension_attribute():
    normalized_prompt = " ".join(service.SYSTEM_PROMPT.split())

    assert (
        "For a dimensions goal, attribute_key is required when the buyer "
        "asks for the aggregate size of the scoped object"
    ) in normalized_prompt
    assert "overall_dimensions" in normalized_prompt


def test_strict_source_refs_restore_two_exact_non_overlapping_spans(
    monkeypatch,
):
    message = "能保证不坏吗？日常使用能确认到什么程度？"
    strict = _FakeStrictTurnProvider({
        "goals": [
            {
                "goal_kind": "customer_goal",
                "claim_type_status": "unmapped",
                "claim_type": "",
                "attribute_key": "",
                "subject_scope": "",
                "semantic_key": "absolute_guarantee",
                "policy_intent_ref": "",
                "source_start_ref": "char-0000",
                "source_end_ref": "char-0006",
                "continued_from": "",
            },
            {
                "goal_kind": "customer_goal",
                "claim_type_status": "unmapped",
                "claim_type": "",
                "attribute_key": "",
                "subject_scope": "",
                "semantic_key": "practical_guidance",
                "policy_intent_ref": "",
                "source_start_ref": "char-0007",
                "source_end_ref": f"char-{len(message) - 1:04d}",
                "continued_from": "",
            },
        ],
    })
    monkeypatch.setattr(service.config, "COPILOT_FACT_TYPE_LLM_ENABLED", True)
    monkeypatch.setattr(
        service.config,
        "COPILOT_TURN_UNDERSTANDING_STRICT_ENABLED",
        True,
    )
    monkeypatch.setattr(
        service.StrictDecisionProviderConfig,
        "from_turn_understanding_environment",
        classmethod(lambda cls: object()),
    )
    monkeypatch.setattr(
        service,
        "StrictDecisionProviderService",
        lambda config: strict,
    )

    result = service.classify_query_fact_type_llm_first({
        "customer_message": message,
        "intent": "product_question",
    })

    goals = result["customer_goals"]
    assert result["goal_understanding_status"] == "valid"
    assert [
        message[goal["source_span_start"]:goal["source_span_end"]]
        for goal in sorted(goals, key=lambda item: item["source_span_start"])
    ] == ["能保证不坏吗？", "日常使用能确认到什么程度？"]


def test_strict_source_refs_fail_closed_for_unknown_or_reversed_refs(
    monkeypatch,
):
    message = "现在怎么说"
    responses = [
        {
            "source_start_ref": "char-9999",
            "source_end_ref": "char-0005",
        },
        {
            "source_start_ref": "char-0005",
            "source_end_ref": "char-0000",
        },
    ]
    for source_refs in responses:
        strict = _FakeStrictTurnProvider({
            "goals": [{
                "goal_kind": "contextual_constraint",
                "claim_type_status": "unmapped",
                "claim_type": "",
                "attribute_key": "",
                "subject_scope": "",
                "semantic_key": "confirmation",
                "policy_intent_ref": "",
                **source_refs,
                "continued_from": "",
            }],
        })
        monkeypatch.setattr(
            service.config,
            "COPILOT_FACT_TYPE_LLM_ENABLED",
            True,
        )
        monkeypatch.setattr(
            service.config,
            "COPILOT_TURN_UNDERSTANDING_STRICT_ENABLED",
            True,
        )
        monkeypatch.setattr(
            service.StrictDecisionProviderConfig,
            "from_turn_understanding_environment",
            classmethod(lambda cls: object()),
        )
        monkeypatch.setattr(
            service,
            "StrictDecisionProviderService",
            lambda config: strict,
        )
        diagnostics = {}

        result = service.classify_query_fact_type_llm_first(
            {"customer_message": message, "intent": "general"},
            diagnostics_sink=diagnostics,
        )

        assert result["goal_understanding_status"] == "invalid"
        assert result["customer_goals"] == []
        assert diagnostics["reason_code"] in {
            "source_reference_unknown",
            "source_reference_range_invalid",
        }


def test_strict_turn_understanding_unqualified_fails_without_legacy_fallback(
    monkeypatch,
):
    strict = _FakeStrictTurnProvider(error="provider_not_qualified")
    monkeypatch.setattr(service.config, "COPILOT_FACT_TYPE_LLM_ENABLED", True)
    monkeypatch.setattr(
        service.config,
        "COPILOT_TURN_UNDERSTANDING_STRICT_ENABLED",
        True,
    )
    monkeypatch.setattr(
        service.StrictDecisionProviderConfig,
        "from_turn_understanding_environment",
        classmethod(lambda cls: object()),
    )
    monkeypatch.setattr(
        service,
        "StrictDecisionProviderService",
        lambda config: strict,
    )
    monkeypatch.setattr(
        service,
        "get_llm_client",
        lambda: (_ for _ in ()).throw(
            AssertionError("legacy provider must not be used")
        ),
    )
    diagnostics = {}

    result = service.classify_query_fact_type_llm_first(
        {"customer_message": "现在怎么说", "intent": "general"},
        diagnostics_sink=diagnostics,
    )

    assert len(strict.calls) == 1
    assert result["goal_understanding_status"] == "degraded"
    assert result["customer_goals"] == []
    assert diagnostics["reason_code"] == "provider_not_qualified"
    assert diagnostics["model_call_count"] == 1


def test_llm_goal_understanding_preserves_multiple_customer_goals_and_dependency(monkeypatch):
    monkeypatch.setattr(service.config, "COPILOT_FACT_TYPE_LLM_ENABLED", True)
    message = (
        "moisture question with material request and "
        "supporting material evidence"
    )
    client = _FakeLLMClient(_complete_llm_payload(**{
        "goals": [
            {
                "goal_kind": "customer_goal",
                "claim_type_status": "canonical",
                "claim_type": "moisture_resistance",
                "attribute_key": "",
                "semantic_key": "",
                "policy_intent_ref": "",
                "source_text": "moisture question",
            },
            {
                "goal_kind": "evidence_dependency",
                "claim_type_status": "canonical",
                "claim_type": "material_composition",
                "attribute_key": "material",
                "semantic_key": "",
                "policy_intent_ref": "",
                "source_text": "supporting material evidence",
            },
            {
                "goal_kind": "customer_goal",
                "claim_type_status": "canonical",
                "claim_type": "material_composition",
                "attribute_key": "material",
                "semantic_key": "",
                "policy_intent_ref": "",
                "source_text": "material request",
            },
        ],
    }))
    monkeypatch.setattr(service, "get_llm_client", lambda: client)

    result = service.classify_query_fact_type_llm_first({
        "customer_message": message,
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


def test_turn_understanding_prompt_requires_atomic_multi_goal_coverage():
    prompt = " ".join(service.SYSTEM_PROMPT.split())

    assert "each independently answerable request as a separate goal" in prompt
    assert "every explicit request is represented exactly once" in prompt
    assert "must not replace or suppress a separate fact request" in prompt
    assert "media_request, service_action, or contextual_constraint" in prompt
    assert "media_request, not a customer_goal" in prompt
    assert "Keep a separate factual customer_goal" in prompt
    assert "For a media_request, semantic_key is required" in prompt
    assert "installation_video" in prompt
    assert "semantic_key is optional except for media_request" in prompt
    assert "A media_request must never be canonical" in prompt
    assert (
        "A request to determine which service outcome applies is a customer_goal"
        in prompt
    )
    assert (
        "request to execute an external side effect now is a service_action"
        in prompt
    )
    assert (
        "Never emit only service_action when the buyer also asks which resolution"
        in prompt
    )
    assert (
        "A request that asks the business to choose among alternative remedies is an outcome-selection customer_goal"
        in prompt
    )
    assert (
        "A service_action requires one definite external operation"
        in prompt
    )
    assert "classification of one goal must not determine, merge, or erase another" in prompt
    assert "For a canonical goal, omit semantic_key or return it as an empty string" in prompt
    assert "Only an unmapped goal may use" in prompt
    assert "A contextual_constraint always uses claim_type_status unmapped" in prompt
    assert "must not carry a claim_type or policy_intent_ref" in prompt
    assert "source_text must be a non-empty exact substring of customer_message" in prompt
    assert "Never copy source_text from recent_conversation" in prompt
    assert "Before choosing unmapped, compare the goal against every supplied canonical_fact_type_candidates ID and meaning" in prompt
    assert "goal_family and allowed_scope directly match" in prompt
    assert "do not substitute a merely related policy" in prompt
    assert "Preserve a specific requested property or performance condition as unmapped" in prompt
    assert "do not collapse it into a broader related action" in prompt
    assert "an explicit buyer request must never be relabeled" in prompt
    assert "not the product, product category, component" in prompt
    assert "Leave it empty when claim_type already identifies" in prompt
    assert "must set subject_scope to the named measured object" in prompt
    assert "Do not nominate practical_guidance for a direct factual identity" in prompt
    assert "It may be empty only when this is a direct factual identity/value request" in prompt
    assert "as a fallback when media or a service action is unavailable" in prompt
    assert "does not create a practical-guidance intent" in prompt
    assert "changes their precedence, not the number of goals" in prompt
    assert "action, method, handling, care, fit, use, or suitability" in prompt
    assert "whether its claim type is canonical or unmapped" in prompt
    assert "unconditional or extreme performance outcome" in prompt
    assert "what can be said under ordinary use" in prompt
    assert "classification metadata, not evidence, a conclusion, or authorization" in prompt


def test_strict_provider_schema_requires_media_request_role_identity():
    goal_variants = service.STRICT_PROVIDER_OUTPUT_SCHEMA["properties"][
        "goals"
    ]["items"]["oneOf"]
    non_fact_role_rule = next(
        rule
        for rule in goal_variants
        if set(rule["properties"]["goal_kind"].get("enum") or [])
        == {"contextual_constraint", "media_request"}
    )
    non_media_rule = next(
        rule
        for rule in goal_variants
        if "media_request"
        not in (rule["properties"]["goal_kind"].get("enum") or [])
    )

    assert "semantic_key" in non_fact_role_rule["required"]
    assert non_fact_role_rule["properties"]["claim_type_status"]["const"] == (
        "unmapped"
    )
    assert non_fact_role_rule["properties"]["claim_type"]["const"] == ""
    assert "installation_video" in non_fact_role_rule["properties"][
        "semantic_key"
    ]["enum"]
    assert "media_request" not in non_media_rule["properties"]["goal_kind"][
        "enum"
    ]
    assert all(rule["additionalProperties"] is False for rule in goal_variants)
    assert all("source_start_ref" in rule["properties"] for rule in goal_variants)
    assert all("source_end_ref" in rule["properties"] for rule in goal_variants)


def test_strict_provider_schema_requires_contextual_boundary_identity():
    goal_variants = service.STRICT_PROVIDER_OUTPUT_SCHEMA["properties"][
        "goals"
    ]["items"]["oneOf"]
    non_fact_role_rule = next(
        rule
        for rule in goal_variants
        if set(rule["properties"]["goal_kind"].get("enum") or [])
        == {"contextual_constraint", "media_request"}
    )
    generic_rule = next(
        rule
        for rule in goal_variants
        if "contextual_constraint"
        not in (rule["properties"]["goal_kind"].get("enum") or [])
    )

    assert len(goal_variants) == 2
    assert "semantic_key" in non_fact_role_rule["required"]
    assert non_fact_role_rule["properties"]["claim_type_status"]["const"] == (
        "unmapped"
    )
    assert non_fact_role_rule["properties"]["claim_type"]["const"] == ""
    assert non_fact_role_rule["properties"]["policy_intent_ref"]["const"] == ""
    assert set(non_fact_role_rule["properties"]["semantic_key"]["enum"]) == (
        service.ALLOWED_CONTEXTUAL_SEMANTIC_KEYS
        | service.ALLOWED_MEDIA_REQUEST_SEMANTIC_KEYS
    )
    assert "contextual_constraint" not in generic_rule["properties"][
        "goal_kind"
    ]["enum"]


def test_turn_understanding_prompt_maps_broad_assessment_to_overview_contract():
    prompt = " ".join(service.SYSTEM_PROMPT.split())

    assert "broad assessment" in prompt
    assert "product_overview" in prompt
    assert "does not authorize a quality" in prompt


def test_turn_understanding_schema_places_dimension_scope_boundary_on_field():
    goal_schema = service.MINIMAL_PROVIDER_OUTPUT_SCHEMA["properties"]["goals"][
        "items"
    ]
    subject_scope_schema = goal_schema["properties"]["subject_scope"]

    description = str(subject_scope_schema.get("description") or "")
    assert "dimension request" in description
    assert "non-dimension goal must use an empty string" in description


def test_turn_understanding_candidates_expose_one_canonical_material_choice():
    candidates = service._canonical_fact_type_candidates()
    material_candidates = [
        item
        for item in candidates
        if item["meaning"] == "材质"
    ]

    assert material_candidates == [{
        "fact_type_id": "material_composition",
        "meaning": "材质",
        "attribute_contract": "optional_explicit_attribute_key",
        "attribute_candidates": ["material_composition"],
    }]
    dimension_candidates = [
        item
        for item in candidates
        if item["fact_type_id"] == "dimensions"
    ]
    assert len(dimension_candidates) == 1
    assert set(dimension_candidates[0]["attribute_candidates"]) == {
        "width",
        "height",
        "depth",
        "length",
        "diameter",
        "thickness",
        "layer_count",
        "compartment_count",
        "overall_width",
        "overall_height",
        "overall_depth",
        "overall_length",
        "overall_diameter",
        "overall_thickness",
        "overall_dimensions",
    }
    assert len({item["fact_type_id"] for item in candidates}) == len(candidates)


def test_turn_understanding_candidates_describe_live_logistics_status_explicitly():
    candidates = {
        item["fact_type_id"]: item
        for item in service._canonical_fact_type_candidates()
    }

    assert "物流" in candidates["stock_shipping"]["meaning"]
    assert "轨迹" in candidates["stock_shipping"]["meaning"]


def test_fact_type_candidates_distinguish_measurements_from_fit_conclusions():
    candidates = {
        item["fact_type_id"]: item
        for item in service._canonical_fact_type_candidates()
    }

    assert "measurement value" in candidates["dimensions"][
        "classification_boundary"
    ]
    assert "fit conclusion" in candidates["space_fit"][
        "classification_boundary"
    ]
    assert "supplied measurements are premises" in candidates[
        "space_fit"
    ]["classification_boundary"]


def test_turn_understanding_normalizes_known_dimension_display_attribute():
    message = "dimension request"
    goals, status, diagnostics = service._sanitize_customer_goals(
        [{
            "goal_kind": "customer_goal",
            "claim_type_status": "canonical",
            "claim_type": "dimensions",
            "attribute_key": "\u5bbd\u5ea6",
            "semantic_key": "",
            "policy_intent_ref": "",
            "source_text": message,
        }],
        message=message,
    )

    assert status == "valid"
    assert diagnostics == []
    assert goals[0]["attribute_key"] == "width"


def test_turn_understanding_normalizes_explicit_dimension_subject_scope_from_source():
    message = "外箱有多大？商品本身展开后的整体尺寸也一起告诉我。"
    goals, status, diagnostics = service._sanitize_customer_goals(
        [
            {
                "goal_kind": "customer_goal",
                "claim_type_status": "canonical",
                "claim_type": "dimensions",
                "attribute_key": "overall_dimensions",
                "subject_scope": "product",
                "semantic_key": "",
                "policy_intent_ref": "",
                "source_text": "外箱有多大",
            },
            {
                "goal_kind": "customer_goal",
                "claim_type_status": "canonical",
                "claim_type": "dimensions",
                "attribute_key": "overall_dimensions",
                "subject_scope": "packaging",
                "semantic_key": "",
                "policy_intent_ref": "",
                "source_text": "商品本身展开后的整体尺寸",
            },
        ],
        message=message,
    )

    assert status == "valid"
    assert diagnostics == []
    assert {
        goal["goal_summary"]: goal["subject_scope"]
        for goal in goals
    } == {
        "外箱有多大": "packaging",
        "商品本身展开后的整体尺寸": "product",
    }


def test_turn_understanding_does_not_guess_dimension_scope_for_mixed_source():
    message = "包装和商品本身的尺寸都要确认。"
    goals, status, diagnostics = service._sanitize_customer_goals(
        [
            {
                "goal_kind": "customer_goal",
                "claim_type_status": "canonical",
                "claim_type": "dimensions",
                "attribute_key": "overall_dimensions",
                "subject_scope": "packaging",
                "semantic_key": "",
                "policy_intent_ref": "",
                "source_text": message,
            },
        ],
        message=message,
    )

    assert status == "valid"
    assert diagnostics == []
    assert goals[0]["subject_scope"] == "packaging"


def test_single_provider_goal_is_not_completed_from_legacy_fact_type(monkeypatch):
    monkeypatch.setattr(service.config, "COPILOT_FACT_TYPE_LLM_ENABLED", True)
    message = "first independent request and second independent request"
    client = _FakeLLMClient(_complete_llm_payload(**{
        "goals": [{
            "goal_kind": "customer_goal",
            "claim_type_status": "canonical",
            "claim_type": "material",
            "attribute_key": "",
            "semantic_key": "",
            "policy_intent_ref": "",
            "source_text": "first independent request",
        }],
    }))
    monkeypatch.setattr(service, "get_llm_client", lambda: client)

    result = service.classify_query_fact_type_llm_first({
        "customer_message": message,
        "intent": "product_question",
        "query_fact_type": "dimensions",
    })

    assert result["goal_understanding_status"] == "valid"
    assert len(result["customer_goals"]) == 1
    assert result["customer_goals"][0]["claim_type"] == "material"
    assert result["secondary_fact_types"] == []


def test_llm_goal_refs_are_deduplicated_and_input_order_independent():
    message = "material question and durability question"
    first = [
        {
            "goal_kind": "customer_goal",
            "claim_type_status": "canonical",
            "claim_type": "material",
            "attribute_key": "",
            "semantic_key": "",
            "policy_intent_ref": "",
            "source_text": "material question",
        },
        {
            "goal_kind": "customer_goal",
            "claim_type_status": "unmapped",
            "claim_type": "",
            "attribute_key": "durability",
            "semantic_key": "durability",
            "policy_intent_ref": "",
            "source_text": "durability question",
        },
    ]

    duplicated = [*first, first[0]]
    forward, status, diagnostics = service._sanitize_customer_goals(
        duplicated,
        message=message,
    )
    reverse, reverse_status, reverse_diagnostics = service._sanitize_customer_goals(
        list(reversed(duplicated)),
        message=message,
    )

    assert status == "invalid"
    assert diagnostics == ["duplicate_resolved_provenance"]
    assert reverse_status == "invalid"
    assert reverse_diagnostics == ["duplicate_resolved_provenance"]
    assert forward == reverse == []


def test_invalid_goal_kind_or_source_fails_closed_without_inventing_goal():
    goals, status, diagnostics = service._sanitize_customer_goals([
        {
            "goal_kind": "customer_goal",
            "claim_type_status": "canonical",
            "claim_type": "not-a-fact-type",
            "attribute_key": "",
            "semantic_key": "",
            "policy_intent_ref": "",
            "source_text": "not present",
        },
        {
            "goal_kind": "unknown-kind",
            "claim_type_status": "canonical",
            "claim_type": "material",
            "attribute_key": "",
            "semantic_key": "",
            "policy_intent_ref": "",
            "source_text": "invalid goal",
        },
    ], message="invalid goal")

    assert goals == []
    assert status == "invalid"
    assert diagnostics == [
        "source_text_not_found",
        "customer_goal_kind_invalid",
    ]


def test_customer_goal_source_span_is_verified_and_raw_text_is_not_retained():
    message = "这款本身是什么材质，能不能保证摔不坏？"
    source_text = "能不能保证摔不坏？"
    goals, status, diagnostics = service._sanitize_customer_goals([
        {
            "goal_kind": "customer_goal",
            "claim_type_status": "unmapped",
            "claim_type": "",
            "attribute_key": "durability",
            "semantic_key": "drop_durability",
            "policy_intent_ref": "",
            "source_text": source_text,
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
            "claim_type_status": "canonical",
            "claim_type": "material",
            "attribute_key": "material",
            "semantic_key": "",
            "policy_intent_ref": "",
            "source_text": "询问商品材质",
        },
    ], message="这款是什么材质？")

    assert goals == []
    assert status == "invalid"
    assert diagnostics == ["source_text_not_found"]


def _policy_candidate() -> dict:
    return {
        "policy_intent_ref": "product_durability_practical_guidance",
        "goal_family": "product_durability",
        "intent_kind": "practical_guidance",
        "allowed_scope": "ordinary_minor_accidental_impact",
        "allowed_conclusion_family": "ordinary_minor_impact_tolerance",
        "required_qualifiers": [
            "avoid_high_or_repeated_impact",
            "no_absolute_guarantee",
        ],
        "prohibited_claim_families": [
            "child_safety",
            "load_capacity",
        ],
        "unmapped_semantic_keys": [
            "ordinary_use_durability_confirmation",
            "impact_durability",
        ],
        "description": "low-risk practical guidance",
    }


def _policy_goal(*, semantic_key: str, policy_intent_ref: str) -> dict:
    return {
        "goal_kind": "customer_goal",
        "claim_type_status": "unmapped",
        "claim_type": "",
        "attribute_key": "drop_durability",
        "semantic_key": semantic_key,
        "policy_intent_ref": policy_intent_ref,
        "source_text": "durability question",
    }


def test_policy_intent_nomination_is_bound_to_trusted_candidate():
    goals, status, diagnostics = service._sanitize_customer_goals(
        [_policy_goal(
            semantic_key="ordinary_use_durability_confirmation",
            policy_intent_ref=(
                "product_durability_practical_guidance"
            ),
        )],
        message="durability question",
        policy_intent_candidates=[_policy_candidate()],
    )

    assert status == "valid"
    assert diagnostics == []
    assert goals[0]["policy_intent_ref"] == (
        "product_durability_practical_guidance"
    )
    assert goals[0]["policy_goal_family"] == "product_durability"
    assert goals[0]["policy_intent_kind"] == "practical_guidance"


def test_unmapped_goal_rejects_policy_outside_pack_semantic_boundary():
    policy = {
        **_policy_candidate(),
        "unmapped_semantic_keys": ["ordinary_use_durability_confirmation"],
    }
    goals, status, diagnostics = service._sanitize_customer_goals(
        [_policy_goal(
            semantic_key="safety_guarantee",
            policy_intent_ref=(
                "product_durability_practical_guidance"
            ),
        )],
        message="durability question",
        policy_intent_candidates=[policy],
    )

    assert status == "degraded"
    assert diagnostics == [
        "customer_goal_policy_intent_semantic_boundary_mismatch"
    ]
    assert goals[0]["policy_intent_ref"] == ""
    assert goals[0]["policy_goal_family"] == ""
    assert goals[0]["policy_intent_kind"] == ""


def test_canonical_goal_rejects_nominated_policy_from_another_goal_family():
    goals, status, diagnostics = service._sanitize_customer_goals(
        [{
            "goal_kind": "customer_goal",
            "claim_type_status": "canonical",
            "claim_type": "material_safety",
            "attribute_key": "",
            "semantic_key": "",
            "policy_intent_ref": "product_durability_practical_guidance",
            "source_text": "material safety request",
        }],
        message="material safety request",
        policy_intent_candidates=[_policy_candidate()],
    )

    assert status == "degraded"
    assert diagnostics == ["customer_goal_policy_intent_family_mismatch"]
    assert goals[0]["policy_intent_ref"] == ""
    assert goals[0]["policy_goal_family"] == ""
    assert goals[0]["policy_intent_kind"] == ""


def test_canonical_goal_uses_declared_cross_family_policy_applicability():
    policy = {
        **_policy_candidate(),
        "policy_intent_ref": "product_dimensions_practical_guidance",
        "goal_family": "product_dimensions_and_space",
        "canonical_claim_types": ["dimensions", "space_fit"],
    }
    goals, status, diagnostics = service._sanitize_customer_goals(
        [{
            "goal_kind": "customer_goal",
            "claim_type_status": "canonical",
            "claim_type": "dimensions",
            "attribute_key": "height",
            "semantic_key": "",
            "policy_intent_ref": "",
            "source_text": "height fit request",
        }],
        message="height fit request",
        policy_intent_candidates=[policy],
    )

    assert status == "valid"
    assert diagnostics == []
    assert goals[0]["policy_intent_ref"] == ""
    assert goals[0]["policy_goal_family"] == (
        "product_dimensions_and_space"
    )
    assert goals[0]["policy_intent_kind"] == "practical_guidance"


def test_canonical_goal_rejects_policy_without_declared_applicability():
    policy = {
        **_policy_candidate(),
        "policy_intent_ref": "product_dimensions_practical_guidance",
        "goal_family": "product_dimensions_and_space",
        "canonical_claim_types": ["dimensions"],
    }
    goals, status, diagnostics = service._sanitize_customer_goals(
        [{
            "goal_kind": "customer_goal",
            "claim_type_status": "canonical",
            "claim_type": "material_safety",
            "attribute_key": "",
            "semantic_key": "",
            "policy_intent_ref": (
                "product_dimensions_practical_guidance"
            ),
            "source_text": "material safety request",
        }],
        message="material safety request",
        policy_intent_candidates=[policy],
    )

    assert status == "degraded"
    assert diagnostics == ["customer_goal_policy_intent_family_mismatch"]
    assert goals[0]["policy_intent_ref"] == ""
    assert goals[0]["policy_goal_family"] == ""


def test_matching_high_risk_goal_can_retain_a_safety_handling_policy():
    policy = {
        **_policy_candidate(),
        "policy_intent_ref": "oral_exposure_safety_handling",
        "goal_family": "bite_or_toxicity",
        "allowed_conclusion_family": "general_oral_exposure_risk_mitigation",
        "prohibited_claim_families": ["bite_or_toxicity"],
    }
    goals, status, diagnostics = service._sanitize_customer_goals(
        [{
            "goal_kind": "customer_goal",
            "claim_type_status": "canonical",
            "claim_type": "bite_or_toxicity",
            "attribute_key": "",
            "semantic_key": "",
            "policy_intent_ref": "oral_exposure_safety_handling",
            "source_text": "oral exposure request",
        }],
        message="oral exposure request",
        policy_intent_candidates=[policy],
    )

    assert status == "valid"
    assert diagnostics == []
    assert goals[0]["policy_intent_ref"] == "oral_exposure_safety_handling"
    assert goals[0]["policy_goal_family"] == "bite_or_toxicity"


def test_canonical_goal_derives_only_exact_trusted_policy_family_and_kind():
    goal = {
        "goal_kind": "customer_goal",
        "claim_type_status": "canonical",
        "claim_type": "moisture_resistance",
        "attribute_key": "",
        "semantic_key": "",
        "policy_intent_ref": "",
        "source_text": "moisture question",
    }
    exact = {
        **_policy_candidate(),
        "policy_intent_ref": "moisture_exposure_practical_guidance",
        "goal_family": "moisture_resistance",
    }

    goals, status, diagnostics = service._sanitize_customer_goals(
        [goal],
        message="moisture question",
        policy_intent_candidates=[exact],
    )

    assert status == "valid"
    assert diagnostics == []
    assert goals[0]["policy_intent_ref"] == ""
    assert goals[0]["policy_goal_family"] == "moisture_resistance"
    assert goals[0]["policy_intent_kind"] == "practical_guidance"


def test_canonical_goal_does_not_derive_ambiguous_policy_intent_kind():
    goal = {
        "goal_kind": "customer_goal",
        "claim_type_status": "canonical",
        "claim_type": "moisture_resistance",
        "attribute_key": "",
        "semantic_key": "",
        "policy_intent_ref": "",
        "source_text": "moisture question",
    }
    practical = {
        **_policy_candidate(),
        "policy_intent_ref": "moisture_exposure_practical_guidance",
        "goal_family": "moisture_resistance",
    }
    guarantee = {
        **practical,
        "policy_intent_ref": "moisture_exposure_absolute_guarantee",
        "intent_kind": "absolute_guarantee",
    }

    goals, status, diagnostics = service._sanitize_customer_goals(
        [goal],
        message="moisture question",
        policy_intent_candidates=[practical, guarantee],
    )

    assert status == "valid"
    assert diagnostics == []
    assert goals[0]["policy_intent_ref"] == ""
    assert goals[0]["policy_goal_family"] == "moisture_resistance"
    assert goals[0]["policy_intent_kind"] == ""


def test_canonical_goal_does_not_derive_related_or_dependency_policy_family():
    candidate = {
        **_policy_candidate(),
        "policy_intent_ref": "material_daily_use_practical_guidance",
        "goal_family": "material_daily_use",
    }
    base_goal = {
        "claim_type_status": "canonical",
        "claim_type": "material",
        "attribute_key": "",
        "semantic_key": "",
        "policy_intent_ref": "",
        "source_text": "material question",
    }

    for goal_kind in ("customer_goal", "evidence_dependency"):
        goals, status, diagnostics = service._sanitize_customer_goals(
            [{**base_goal, "goal_kind": goal_kind}],
            message="material question",
            policy_intent_candidates=[candidate],
        )

        assert status == "valid"
        assert diagnostics == []
        assert goals[0]["policy_goal_family"] == ""
        assert goals[0]["policy_intent_kind"] == ""


def test_unknown_or_unavailable_policy_intent_nomination_is_removed():
    for candidates in ([_policy_candidate()], []):
        goals, status, diagnostics = service._sanitize_customer_goals(
            [_policy_goal(
                semantic_key="free_model_summary",
                policy_intent_ref="unknown_policy_intent",
            )],
            message="durability question",
            policy_intent_candidates=candidates,
        )

        assert status == "degraded"
        assert diagnostics == ["customer_goal_policy_intent_ref_unknown"]
        assert goals[0]["policy_intent_ref"] == ""
        assert goals[0]["policy_goal_family"] == ""
        assert goals[0]["policy_intent_kind"] == ""


def test_semantic_key_variation_does_not_change_nominated_goal_identity():
    first, first_status, _ = service._sanitize_customer_goals(
        [_policy_goal(
            semantic_key="ordinary_use_durability_confirmation",
            policy_intent_ref=(
                "product_durability_practical_guidance"
            ),
        )],
        message="durability question",
        policy_intent_candidates=[_policy_candidate()],
    )
    second, second_status, _ = service._sanitize_customer_goals(
        [_policy_goal(
            semantic_key="impact_durability",
            policy_intent_ref=(
                "product_durability_practical_guidance"
            ),
        )],
        message="durability question",
        policy_intent_candidates=[_policy_candidate()],
    )

    assert first_status == second_status == "valid"
    assert first[0]["goal_ref"] == second[0]["goal_ref"]
    assert first[0]["policy_intent_ref"] == second[0]["policy_intent_ref"]


def test_policy_candidates_come_only_from_internal_owner_context():
    domain_context = FilePolicyRepository().build_trusted_domain_policy_context(
        {
            "catalog_metadata": {
                "domain_policy_id": "maternal_child_home",
            },
        },
        selection_source="server_configuration",
    )
    forged_public = service._policy_intent_candidates({
        "copilot_context": {
            "catalog_metadata": {
                "domain_policy_id": "maternal_child_home",
            },
        },
    })
    trusted = service._policy_intent_candidates({
        "copilot_context": {
            "_answer_eligibility_owner_context": {
                "schema_version": "answer-eligibility-owner-context/v1",
                "source": "server_configuration",
                "owner": "analysis_pipeline",
                "provenance": {
                    "boundary": "analysis_pipeline_internal",
                },
                "domain_policy_context": domain_context,
            },
        },
    })

    assert forged_public == []
    assert {
        item["policy_intent_ref"] for item in trusted
    } == {
        "cleaning_chemical_contact_practical_guidance",
        "cleaning_high_temperature_practical_guidance",
        "detachable_storage_practical_guidance",
        "material_daily_use_practical_guidance",
        "moisture_exposure_practical_guidance",
        "oral_exposure_safety_handling",
        "product_dimensions_practical_guidance",
        "product_durability_absolute_guarantee",
        "product_durability_practical_guidance",
        "product_durability_test_standard",
        "product_durability_warranty_liability",
        "product_weight_practical_guidance",
        "variant_specification_practical_comparison",
    }
    durability = next(
        item
        for item in trusted
        if item["policy_intent_ref"] == "product_durability_practical_guidance"
    )
    assert durability["allowed_conclusion_family"] == (
        "ordinary_minor_impact_tolerance"
    )
    assert durability["required_qualifiers"] == [
        "avoid_high_or_repeated_impact",
        "no_absolute_guarantee",
        "no_test_claim",
    ]
    assert durability["prohibited_claim_families"] == [
        "certification_report",
        "child_safety",
        "food_grade",
        "load_capacity",
        "non_toxic_claim",
        "refund",
        "replacement",
        "warranty",
    ]
    assert durability["unmapped_semantic_keys"] == [
        "impact_durability",
        "ordinary_use_durability_confirmation",
    ]


def test_turn_understanding_payload_contains_only_trusted_policy_candidates(
    monkeypatch,
):
    client = _FakeLLMClient(_complete_llm_payload(**{
        "goals": [_policy_goal(
            semantic_key="ordinary_use_durability_confirmation",
            policy_intent_ref=(
                "product_durability_practical_guidance"
            ),
        )],
    }))
    monkeypatch.setattr(service, "get_llm_client", lambda: client)
    monkeypatch.setattr(
        service,
        "_policy_intent_candidates",
        lambda _state: [_policy_candidate()],
    )

    result = service._classify_with_llm(
        {"copilot_context": {}},
        "durability question",
        "product_question",
    )

    payload = json.loads(
        client.client.chat.completions.kwargs["messages"][1]["content"]
    )
    assert payload["policy_intent_candidates"] == [_policy_candidate()]
    assert result["customer_goals"][0]["policy_intent_ref"] == (
        "product_durability_practical_guidance"
    )


def test_turn_understanding_prompt_requires_policy_family_and_conclusion_bounds():
    prompt = " ".join(service.SYSTEM_PROMPT.split())

    assert "allowed_conclusion_family" in prompt
    assert "prohibited_claim_families" in prompt
    assert "must either have that same goal_family" in prompt
    assert "canonical_claim_types" in prompt


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


def test_selected_configuration_contents_rejects_an_off_topic_material_classification():
    guarded = service._semantic_consistency_guard(
        {
            "query_fact_type": "included_items",
            "confidence": 0.88,
            "secondary_fact_types": [],
        },
        {
            "query_fact_type": "material",
            "confidence": 0.9,
            "secondary_fact_types": [],
        },
    )

    assert guarded is not None
    assert guarded["query_fact_type"] == "included_items"
    assert guarded["source"] == "semantic_consistency_guard"
    assert guarded["llm_rejected_fact_type"] == "material"


def test_child_safety_rejects_an_off_topic_material_classification():
    guarded = service._semantic_consistency_guard(
        {
            "query_fact_type": "child_safety",
            "confidence": 0.88,
        },
        {
            "query_fact_type": "material",
            "confidence": 0.9,
            "secondary_fact_types": [],
        },
    )

    assert guarded is not None
    assert guarded["query_fact_type"] == "child_safety"
    assert guarded["source"] == "semantic_consistency_guard"
    assert guarded["llm_rejected_fact_type"] == "material"
