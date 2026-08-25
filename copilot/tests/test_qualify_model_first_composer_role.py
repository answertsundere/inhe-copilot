from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

import pytest

from app import config
from scripts import qualify_model_first_composer_role as qualification


class _FakeClient:
    api_key = "configured"
    api_base = "https://provider.invalid/v1"
    model = "fake-composer"
    provider_name = "fake"

    def __init__(self, *, invalid: bool = False):
        self.invalid = invalid
        self.calls: list[dict[str, Any]] = []

    def create_chat_completion(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        material = json.loads(kwargs["messages"][1]["content"])
        goals_by_ref = {
            goal["goal_ref"]: goal
            for goal in material["renderable_customer_goals"]
        }
        clauses = []
        for goal_ref in material["presentation_order"]:
            goal = goals_by_ref[goal_ref]
            options = goal.get("eligible_policy_options") or []
            clauses.append({
                "goal_ref": goal["goal_ref"],
                "text": "这是合成资格回复。",
                "selected_option_refs": (
                    [] if not options or self.invalid else [options[0]["option_ref"]]
                ),
            })
        return SimpleNamespace(choices=[SimpleNamespace(
            finish_reason="stop",
            message=SimpleNamespace(content=json.dumps({"clauses": clauses})),
        )])


class _MixedLanguageClient(_FakeClient):
    def create_chat_completion(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        material = json.loads(kwargs["messages"][1]["content"])
        goals_by_ref = {
            goal["goal_ref"]: goal
            for goal in material["renderable_customer_goals"]
        }
        clauses = []
        for goal_ref in material["presentation_order"]:
            goal = goals_by_ref[goal_ref]
            options = goal.get("eligible_policy_options") or []
            clauses.append({
                "goal_ref": goal["goal_ref"],
                "text": "当前可以说明 this synthetic qualification result.",
                "selected_option_refs": (
                    [options[0]["option_ref"]] if options else []
                ),
            })
        return SimpleNamespace(choices=[SimpleNamespace(
            finish_reason="stop",
            message=SimpleNamespace(content=json.dumps({"clauses": clauses})),
        )])


class _UnresolvedOnlyMixedLanguageClient(_FakeClient):
    def create_chat_completion(self, **kwargs: Any) -> Any:
        material = json.loads(kwargs["messages"][1]["content"])
        if material["admitted_evidence"]:
            return super().create_chat_completion(**kwargs)
        self.calls.append(kwargs)
        clauses = [{
            "goal_ref": goal_ref,
            "text": "目前无法确认 the specific limit for routine use.",
            "selected_option_refs": [],
        } for goal_ref in material["presentation_order"]]
        return SimpleNamespace(choices=[SimpleNamespace(
            finish_reason="stop",
            message=SimpleNamespace(content=json.dumps({"clauses": clauses})),
        )])


class _HistoryFactRepeatingClient(_FakeClient):
    def create_chat_completion(self, **kwargs: Any) -> Any:
        material = json.loads(kwargs["messages"][1]["content"])
        if material.get("current_customer_question") != (
            qualification._HISTORY_FACT_CUSTOMER_MESSAGE
        ):
            return super().create_chat_completion(**kwargs)
        self.calls.append(kwargs)
        clauses = [{
            "goal_ref": goal_ref,
            "text": "商品可以确认为合成材质甲。",
            "selected_option_refs": [],
        } for goal_ref in material["presentation_order"]]
        return SimpleNamespace(choices=[SimpleNamespace(
            finish_reason="stop",
            message=SimpleNamespace(content=json.dumps({"clauses": clauses})),
        )])


def test_qualification_fixture_covers_fact_option_and_unresolved_boundary():
    response = qualification.qualification_response()
    minimal = response["minimal_decision_context"]

    assert len(minimal["requested_claims"]) == 3
    assert len(minimal["admitted_evidence"]) == 1
    assert len(minimal["claim_resolutions"][1]["eligible_policy_options"]) == 1
    unresolved = minimal["claim_resolutions"][2]
    assert unresolved["status"] == "unresolved"
    assert unresolved["evidence_uids"] == []
    assert unresolved["eligible_policy_options"] == []


def test_qualification_profiles_include_a_standalone_unresolved_only_case():
    profiles = qualification.qualification_profiles()

    assert [profile["name"] for profile in profiles] == [
        "unresolved_only",
        "unadmitted_history_fact",
        "fact_bounded_and_unresolved",
    ]
    unresolved = profiles[0]["response"]["minimal_decision_context"]
    assert unresolved["admitted_evidence"] == []
    assert len(unresolved["requested_claims"]) == 2
    assert all(
        item["status"] == "unresolved"
        and item["evidence_uids"] == []
        and item["eligible_policy_options"] == []
        for item in unresolved["claim_resolutions"]
    )
    history_response = profiles[1]["response"]
    service = qualification.ModelFirstAnswerComposerService()
    decision_input, decision_error = service.build_composer_decision_input(
        history_response,
        customer_message=qualification._HISTORY_FACT_CUSTOMER_MESSAGE,
    )
    material, material_error = (
        service.build_provider_material_from_decision_input(decision_input)
    )
    assert decision_error == material_error == ""
    assert material["prompt_payload"][
        "non_authoritative_recent_conversation_turns"
    ] == []


def test_role_qualification_accepts_five_single_call_attempts_per_profile():
    client = _FakeClient()

    report, exit_code = qualification.run_qualification(client=client)

    assert exit_code == 0
    assert report["status"] == "qualified"
    assert report["attempted"] == 15
    assert report["provider_call_count"] == 15
    assert len(report["qualification_fingerprint"]) == 64
    assert len(client.calls) == 15
    assert report["profile_count"] == 3
    assert report["attempts_per_profile"] == 5
    assert all(record["qualified"] for record in report["records"])
    assert all(
        record["checks"]["unresolved_boundary_preserved"]
        for record in report["records"]
    )
    assert report["can_change_can_send"] is False


def test_role_qualification_rejects_unadmitted_history_product_fact():
    client = _HistoryFactRepeatingClient()

    report, exit_code = qualification.run_qualification(client=client)

    assert exit_code == 2
    assert report["status"] == "not_qualified"
    assert report["attempted"] == 6
    assert report["records"][-1]["profile"] == (
        "unadmitted_history_fact"
    )
    assert report["hard_stop_reason"] == (
        "unadmitted_history_fact_excluded"
    )


def test_role_qualification_rejects_mixed_english_prose_for_chinese_fixture():
    client = _MixedLanguageClient()

    report, exit_code = qualification.run_qualification(client=client)

    assert exit_code == 2
    assert report["status"] == "not_qualified"
    assert report["attempted"] == 1
    assert report["hard_stop_reason"] == (
        "composer_customer_language_mismatch"
    )


def test_role_qualification_rejects_unresolved_only_language_instability():
    client = _UnresolvedOnlyMixedLanguageClient()

    report, exit_code = qualification.run_qualification(client=client)

    assert exit_code == 2
    assert report["status"] == "not_qualified"
    assert report["attempted"] == 1
    assert report["records"][-1]["profile"] == "unresolved_only"
    assert report["hard_stop_reason"] == (
        "composer_customer_language_mismatch"
    )


def test_role_qualification_stops_on_first_required_option_omission():
    client = _FakeClient(invalid=True)

    report, exit_code = qualification.run_qualification(client=client)

    assert exit_code == 2
    assert report["status"] == "not_qualified"
    assert report["attempted"] == 11
    assert report["provider_call_count"] == 11
    assert report["hard_stop_reason"] == "composer_required_option_not_selected"


def test_role_qualification_rejects_any_repeat_count_other_than_five():
    with pytest.raises(ValueError, match="repeat_must_equal_5"):
        qualification.run_qualification(repeat=4, client=_FakeClient())


def test_role_qualification_never_uses_the_formal_client_without_override(
    monkeypatch: pytest.MonkeyPatch,
):
    for field in (
        "COPILOT_COMPOSER_LLM_API_BASE",
        "COPILOT_COMPOSER_LLM_API_KEY",
        "COPILOT_COMPOSER_LLM_MODEL",
    ):
        monkeypatch.setattr(config, field, "")
    monkeypatch.setattr(
        qualification,
        "get_composer_llm_client",
        lambda **_: (_ for _ in ()).throw(AssertionError("formal_client_used")),
    )

    report, exit_code = qualification.run_qualification()

    assert exit_code == 2
    assert report["reason"] == "provider_not_configured"
    assert report["provider"] == {"configured": False}
