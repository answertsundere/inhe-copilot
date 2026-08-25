import importlib.util
from pathlib import Path

from app.services.strict_decision_provider_service import (
    StrictDecisionProviderError,
)


_SCRIPT_PATH = (
    Path(__file__).resolve().parents[1]
    / "scripts"
    / "qualify_turn_understanding_provider.py"
)
_SPEC = importlib.util.spec_from_file_location(
    "qualify_turn_understanding_provider",
    _SCRIPT_PATH,
)
_MODULE = importlib.util.module_from_spec(_SPEC)
assert _SPEC and _SPEC.loader
_SPEC.loader.exec_module(_MODULE)


class _FakeProvider:
    def __init__(self, responder):
        self._responder = responder
        self.calls = []
        self.last_latency_ms = None

    def metadata(self):
        return {
            "provider_name": "turn-test",
            "host_fingerprint": "a" * 12,
            "model_name": "turn-test-model",
            "configured": True,
            "qualified": False,
        }

    def qualification_fingerprint(self):
        return "f" * 64

    def request(self, **kwargs):
        self.calls.append(kwargs)
        response = self._responder(kwargs, len(self.calls))
        self.last_latency_ms = 10.0 + len(self.calls)
        if isinstance(response, Exception):
            self.last_latency_ms = None
            raise response
        return response


def _span_refs(call, source_text=None):
    message = call["payload"]["customer_message"]
    source_text = message if source_text is None else source_text
    start = message.index(source_text)
    end = start + len(source_text) - 1
    units = call["payload"]["source_units"]
    return {
        "source_start_ref": units[start]["ref"],
        "source_end_ref": units[end]["ref"],
    }


def _canonical_goal(call, *, claim_type="material_composition", source_text=None):
    return {
        "goals": [{
            "goal_kind": "customer_goal",
            "claim_type_status": "canonical",
            "claim_type": claim_type,
            "attribute_key": "",
            "subject_scope": "",
            "semantic_key": "",
            "policy_intent_ref": "",
            **_span_refs(call, source_text),
            "continued_from": "",
        }]
    }


def _case():
    return {
        "alias": "fictional-material",
        "customer_message": "这件虚构商品的主体材质是什么？",
        "current_intent": "product_question",
        "recent_conversation": [],
        "expected_claim_types": ["material_composition"],
        "expected_goal_kinds": ["customer_goal"],
    }


def test_perfect_provider_qualifies_with_current_source_and_stability():
    provider = _FakeProvider(
        lambda call, _index: _canonical_goal(call)
    )

    report = _MODULE.qualify(
        provider=provider,
        cases=[_case()],
        repeats=3,
    )

    assert report["qualification_status"] == "qualified"
    assert report["total_attempt_count"] == 3
    assert report["successful_attempt_count"] == 3
    assert report["schema_success_rate"]["rate"] == 1.0
    assert report["current_source_success_rate"]["rate"] == 1.0
    assert report["semantic_success_rate"]["rate"] == 1.0
    assert report["repeat_stability_rate"]["rate"] == 1.0
    assert report["semantic_repeat_stability_rate"]["rate"] == 1.0
    assert report["source_provenance_repeat_stability_rate"]["rate"] == 1.0
    assert report["qualification_fingerprint"] == "f" * 64
    assert report["formal_kb_write_attempt_count"] == 0
    assert report["can_change_can_send_count"] == 0
    assert all(call["allow_unqualified"] is True for call in provider.calls)


def test_history_source_copy_is_rejected_even_when_schema_is_valid():
    case = {
        **_case(),
        "recent_conversation": [
            {"role": "customer", "content": "上一轮虚构问题"},
            {"role": "agent", "content": "我先核对。"},
        ],
    }
    provider = _FakeProvider(lambda _call, _index: {
        "goals": [{
            "goal_kind": "customer_goal",
            "claim_type_status": "canonical",
            "claim_type": "material_composition",
            "attribute_key": "",
            "subject_scope": "",
            "semantic_key": "",
            "policy_intent_ref": "",
            "source_start_ref": "char-9999",
            "source_end_ref": "char-9999",
            "continued_from": "",
        }],
    })

    report = _MODULE.qualify(
        provider=provider,
        cases=[case],
        repeats=1,
    )

    assert report["qualification_status"] == "not_qualified"
    assert report["current_source_success_rate"]["rate"] == 0.0
    assert report["error_categories"] == {"source_reference_unknown": 1}


def test_attempt_errors_are_counted_per_attempt_without_stale_latency():
    provider = _FakeProvider(
        lambda _call, _index: StrictDecisionProviderError("timeout")
    )

    report = _MODULE.qualify(
        provider=provider,
        cases=[_case()],
        repeats=3,
    )

    assert report["qualification_status"] == "not_qualified"
    assert report["total_attempt_count"] == 3
    assert report["successful_attempt_count"] == 0
    assert report["timeout_attempt_count"] == 3
    assert report["latency_ms"] == {"p50": None, "p95": None}


def test_report_contains_no_raw_messages_or_provider_secrets():
    provider = _FakeProvider(
        lambda call, _index: _canonical_goal(call)
    )
    case = _case()

    report = _MODULE.qualify(
        provider=provider,
        cases=[case],
        repeats=1,
    )
    serialized = str(report)

    assert case["customer_message"] not in serialized
    assert "api_base" not in serialized
    assert "api_key" not in serialized
    assert report["case_results"][0]["alias"] == "fictional-material"
    assert len(report["fixture_sha256"]) == 64


def test_repeat_instability_reports_safe_case_and_changed_field_diagnostics():
    case = {
        "alias": "fictional-dimension-attributes",
        "customer_message": "这件虚构商品的宽度和高度是多少？",
        "current_intent": "product_question",
        "recent_conversation": [],
        "expected_claim_types": ["dimensions"],
        "expected_goal_kinds": ["customer_goal"],
    }

    def responder(call, index):
        return {
            "goals": [{
                "goal_kind": "customer_goal",
                "claim_type_status": "canonical",
                "claim_type": "dimensions",
                "attribute_key": "width" if index != 2 else "height",
                "subject_scope": "product_overall",
                "semantic_key": "",
                "policy_intent_ref": "",
            **_span_refs(call),
                "continued_from": "",
            }]
        }

    report = _MODULE.qualify(
        provider=_FakeProvider(responder),
        cases=[case],
        repeats=3,
    )

    result = report["case_results"][0]
    assert report["schema_version"] == (
        "turn-understanding-provider-qualification-v7"
    )
    assert report["qualification_status"] == "not_qualified"
    assert result["signature_variant_count"] == 2
    assert result["stable_attempt_count"] == 2
    assert result["changed_field_names"] == ["attribute_key"]
    assert report["semantic_repeat_stability_rate"]["rate"] == (2 / 3)
    assert report["source_provenance_repeat_stability_rate"]["rate"] == 1.0
    serialized = str(report)
    assert case["customer_message"] not in serialized
    assert "width" not in serialized
    assert "height" not in serialized


def test_equivalent_source_substrings_in_one_clause_are_repeat_stable():
    case = {
        **_case(),
        "customer_message": "fictional product body material?",
    }

    def responder(call, index):
        message = call["payload"]["customer_message"]
        result = _canonical_goal(
            call,
            source_text=(
                message if index != 2 else "body material"
            ),
        )
        return result

    report = _MODULE.qualify(
        provider=_FakeProvider(responder),
        cases=[case],
        repeats=3,
    )

    assert report["qualification_status"] == "qualified"
    assert report["repeat_stability_rate"]["rate"] == 1.0
    assert report["case_results"][0]["signature_variant_count"] == 1


def test_service_action_semantic_key_is_not_authoritative_for_stability():
    case = {
        "alias": "fictional-service-action",
        "customer_message": "please contact the fictional carrier",
        "current_intent": "logistics",
        "recent_conversation": [],
        "expected_claim_types": [],
        "expected_goal_kinds": ["service_action"],
    }

    def responder(call, index):
        return {
            "goals": [{
                "goal_kind": "service_action",
                "claim_type_status": "unmapped",
                "claim_type": "",
                "attribute_key": "",
                "subject_scope": "",
                "semantic_key": (
                    "contact_carrier" if index != 2 else "verify_carrier"
                ),
                "policy_intent_ref": "",
            **_span_refs(call),
                "continued_from": "",
            }]
        }

    report = _MODULE.qualify(
        provider=_FakeProvider(responder),
        cases=[case],
        repeats=3,
    )

    assert report["qualification_status"] == "qualified"
    assert report["repeat_stability_rate"]["rate"] == 1.0
    assert report["case_results"][0]["changed_field_names"] == []


def test_unbound_unmapped_goal_semantic_key_wording_is_not_authoritative():
    case = {
        "alias": "fictional-unmapped-goal",
        "customer_message": "fictional durability question",
        "current_intent": "product_question",
        "recent_conversation": [],
        "expected_claim_types": [],
        "expected_goal_kinds": ["customer_goal"],
    }

    def responder(call, index):
        return {
            "goals": [{
                "goal_kind": "customer_goal",
                "claim_type_status": "unmapped",
                "claim_type": "",
                "attribute_key": "durability",
                "subject_scope": "",
                "semantic_key": (
                    "drop_durability" if index != 2 else "impact_durability"
                ),
                "policy_intent_ref": "",
            **_span_refs(call),
                "continued_from": "",
            }]
        }

    report = _MODULE.qualify(
        provider=_FakeProvider(responder),
        cases=[case],
        repeats=3,
    )

    assert report["qualification_status"] == "qualified"
    assert report["repeat_stability_rate"]["rate"] == 1.0
    assert report["case_results"][0]["changed_field_names"] == []


def test_unbound_unmapped_goal_semantic_key_presence_remains_authoritative():
    case = {
        "alias": "fictional-unmapped-goal",
        "customer_message": "fictional durability question",
        "current_intent": "product_question",
        "recent_conversation": [],
        "expected_claim_types": [],
        "expected_goal_kinds": ["customer_goal"],
    }

    def responder(call, index):
        return {
            "goals": [{
                "goal_kind": "customer_goal",
                "claim_type_status": "unmapped",
                "claim_type": "",
                "attribute_key": "durability",
                "subject_scope": "",
                "semantic_key": "drop_durability" if index != 2 else "",
                "policy_intent_ref": "",
            **_span_refs(call),
                "continued_from": "",
            }]
        }

    report = _MODULE.qualify(
        provider=_FakeProvider(responder),
        cases=[case],
        repeats=3,
    )

    assert report["qualification_status"] == "not_qualified"
    assert report["repeat_stability_rate"]["rate"] == (2 / 3)
    assert report["case_results"][0]["changed_field_names"] == [
        "semantic_key"
    ]


def test_default_provider_uses_turn_understanding_role_config(monkeypatch):
    sentinel = object()
    captured = []
    provider = _FakeProvider(
        lambda call, _index: _canonical_goal(call)
    )
    monkeypatch.setattr(
        _MODULE.StrictDecisionProviderConfig,
        "from_turn_understanding_environment",
        classmethod(lambda cls: sentinel),
    )
    monkeypatch.setattr(
        _MODULE,
        "StrictDecisionProviderService",
        lambda config: captured.append(config) or provider,
    )

    report = _MODULE.qualify(cases=[_case()], repeats=1)

    assert report["qualification_status"] == "qualified"
    assert captured == [sentinel]


def test_default_matrix_covers_compound_goal_boundaries():
    cases = {
        case["alias"]: case
        for case in _MODULE.DEFAULT_CASES
    }

    assert cases["fictional-installation-media-boundary"][
        "expected_goal_count"
    ] == 3
    assert cases["fictional-followup-detachable-reassembly"][
        "expected_goal_count"
    ] == 2


def test_semantic_expectation_rejects_extra_unique_goal():
    case = {
        **_case(),
        "expected_goal_count": 1,
    }

    def responder(call, _index):
        message = call["payload"]["customer_message"]
        first = _canonical_goal(call, source_text=message[:5])["goals"][0]
        second = {
            **_canonical_goal(
                call,
                claim_type="dimensions",
                source_text=message[5:],
            )["goals"][0],
            "subject_scope": "product_overall",
        }
        return {"goals": [first, second]}

    report = _MODULE.qualify(
        provider=_FakeProvider(responder),
        cases=[case],
        repeats=1,
    )

    assert report["qualification_status"] == "not_qualified"
    assert report["error_categories"] == {
        "semantic_expectation_failed": 1,
    }


def test_semantic_expectation_rejects_wrong_scope_or_attribute():
    case = {
        "alias": "fictional-scoped-dimensions",
        "customer_message": "包装整体尺寸和商品整体尺寸分别是多少？",
        "current_intent": "product_question",
        "recent_conversation": [],
        "expected_claim_types": ["dimensions"],
        "expected_goal_kinds": ["customer_goal"],
        "expected_goal_count": 2,
        "expected_goal_signatures": [
            {
                "goal_kind": "customer_goal",
                "claim_type_status": "canonical",
                "claim_type": "dimensions",
                "attribute_key": "overall_dimensions",
                "subject_scope": "packaging",
            },
            {
                "goal_kind": "customer_goal",
                "claim_type_status": "canonical",
                "claim_type": "dimensions",
                "attribute_key": "overall_dimensions",
                "subject_scope": "product",
            },
        ],
    }

    def responder(call, _index):
        message = call["payload"]["customer_message"]
        first = {
            **_canonical_goal(
                call,
                claim_type="dimensions",
                source_text=message[:6],
            )["goals"][0],
            "attribute_key": "",
            "subject_scope": "packaging",
        }
        second = {
            **_canonical_goal(
                call,
                claim_type="dimensions",
                source_text=message[6:],
            )["goals"][0],
            "attribute_key": "",
            "subject_scope": "product",
        }
        return {"goals": [first, second]}

    report = _MODULE.qualify(
        provider=_FakeProvider(responder),
        cases=[case],
        repeats=1,
    )

    assert report["qualification_status"] == "not_qualified"
    assert report["error_categories"] == {
        "semantic_expectation_failed": 1,
    }


def test_default_matrix_covers_scoped_overall_dimensions():
    case = next(
        item
        for item in _MODULE.DEFAULT_CASES
        if item["alias"] == "fictional-scoped-overall-dimensions"
    )

    assert case["expected_goal_count"] == 2
    assert {
        (item["attribute_key"], item["subject_scope"])
        for item in case["expected_goal_signatures"]
    } == {
        ("overall_dimensions", "packaging"),
        ("overall_dimensions", "product"),
    }


def test_default_matrix_covers_colloquial_scoped_dimensions_with_boundary():
    case = next(
        item
        for item in _MODULE.DEFAULT_CASES
        if item["alias"] == "fictional-colloquial-scoped-dimensions"
    )

    assert case["expected_goal_count"] == 3
    assert set(case["expected_goal_kinds"]) == {
        "customer_goal",
        "contextual_constraint",
    }
