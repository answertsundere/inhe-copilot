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


def _complete_llm_payload(**overrides):
    payload = {"goals": []}
    payload.update(overrides)
    return payload


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
    assert "classification of one goal must not determine, merge, or erase another" in prompt
    assert "For a canonical goal, omit semantic_key or return it as an empty string" in prompt
    assert "Only an unmapped goal may use" in prompt
    assert "goal_family and allowed_scope directly match" in prompt
    assert "do not substitute a merely related policy" in prompt
    assert "Preserve a specific requested property or performance condition as unmapped" in prompt
    assert "do not collapse it into a broader related action" in prompt
    assert "an explicit buyer request must never be relabeled" in prompt
    assert "not the product, product category, component" in prompt
    assert "Leave it empty when claim_type already identifies" in prompt
    assert "Do not nominate practical_guidance for a direct factual identity" in prompt
    assert "It may be empty only when this is a direct factual identity/value request" in prompt
    assert "as a fallback when media or a service action is unavailable" in prompt
    assert "does not create a practical-guidance intent" in prompt
    assert "changes their precedence, not the number of goals" in prompt
    assert "action, method, handling, care, fit, use, or suitability" in prompt
    assert "whether its claim type is canonical or unmapped" in prompt


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


def _policy_candidate() -> dict[str, str]:
    return {
        "policy_intent_ref": "product_durability_practical_guidance",
        "goal_family": "product_durability",
        "intent_kind": "practical_guidance",
        "allowed_scope": "ordinary_minor_accidental_impact",
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
            semantic_key="free_model_summary",
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
            semantic_key="first_free_model_summary",
            policy_intent_ref=(
                "product_durability_practical_guidance"
            ),
        )],
        message="durability question",
        policy_intent_candidates=[_policy_candidate()],
    )
    second, second_status, _ = service._sanitize_customer_goals(
        [_policy_goal(
            semantic_key="different_free_model_summary",
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
        "cleaning_care_practical_guidance",
        "detachable_storage_practical_guidance",
        "material_daily_use_practical_guidance",
        "moisture_exposure_practical_guidance",
        "product_dimensions_practical_guidance",
        "product_durability_absolute_guarantee",
        "product_durability_practical_guidance",
        "product_durability_test_standard",
        "product_durability_warranty_liability",
        "product_weight_practical_guidance",
        "variant_specification_practical_comparison",
    }


def test_turn_understanding_payload_contains_only_trusted_policy_candidates(
    monkeypatch,
):
    client = _FakeLLMClient(_complete_llm_payload(**{
        "goals": [_policy_goal(
            semantic_key="free_model_summary",
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
