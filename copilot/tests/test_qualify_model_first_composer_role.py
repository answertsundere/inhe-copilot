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
                "text": "synthetic qualification reply",
                "selected_option_refs": (
                    [] if not options or self.invalid else [options[0]["option_ref"]]
                ),
            })
        return SimpleNamespace(choices=[SimpleNamespace(
            finish_reason="stop",
            message=SimpleNamespace(content=json.dumps({"clauses": clauses})),
        )])


def test_qualification_fixture_has_one_direct_fact_and_one_required_option():
    response = qualification.qualification_response()
    minimal = response["minimal_decision_context"]

    assert len(minimal["requested_claims"]) == 2
    assert len(minimal["admitted_evidence"]) == 1
    assert len(minimal["claim_resolutions"][1]["eligible_policy_options"]) == 1


def test_role_qualification_accepts_five_single_call_attempts():
    client = _FakeClient()

    report, exit_code = qualification.run_qualification(client=client)

    assert exit_code == 0
    assert report["status"] == "qualified"
    assert report["attempted"] == 5
    assert report["provider_call_count"] == 5
    assert len(client.calls) == 5
    assert all(record["qualified"] for record in report["records"])
    assert report["can_change_can_send"] is False


def test_role_qualification_stops_on_first_required_option_omission():
    client = _FakeClient(invalid=True)

    report, exit_code = qualification.run_qualification(client=client)

    assert exit_code == 2
    assert report["status"] == "not_qualified"
    assert report["attempted"] == 1
    assert report["provider_call_count"] == 1
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
