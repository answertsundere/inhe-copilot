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


def _canonical_goal(message, *, claim_type="material_composition"):
    return {
        "goals": [{
            "goal_kind": "customer_goal",
            "claim_type_status": "canonical",
            "claim_type": claim_type,
            "attribute_key": "",
            "subject_scope": "",
            "semantic_key": "",
            "policy_intent_ref": "",
            "source_text": message,
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
        lambda call, _index: _canonical_goal(
            call["payload"]["customer_message"]
        )
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
    provider = _FakeProvider(
        lambda _call, _index: _canonical_goal("上一轮虚构问题")
    )

    report = _MODULE.qualify(
        provider=provider,
        cases=[case],
        repeats=1,
    )

    assert report["qualification_status"] == "not_qualified"
    assert report["current_source_success_rate"]["rate"] == 0.0
    assert report["error_categories"] == {
        "source_text_from_wrong_turn": 1
    }


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
        lambda call, _index: _canonical_goal(
            call["payload"]["customer_message"]
        )
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
                "source_text": call["payload"]["customer_message"],
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
        "turn-understanding-provider-qualification-v3"
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
        result = _canonical_goal(message)
        result["goals"][0]["source_text"] = (
            message if index != 2 else "body material"
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
                "source_text": call["payload"]["customer_message"],
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
                "source_text": call["payload"]["customer_message"],
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
                "source_text": call["payload"]["customer_message"],
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
        lambda call, _index: _canonical_goal(
            call["payload"]["customer_message"]
        )
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
