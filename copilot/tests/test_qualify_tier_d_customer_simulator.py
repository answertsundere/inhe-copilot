from __future__ import annotations

from scripts import qualify_tier_d_customer_simulator as qualification


class _Simulator:
    def metadata(self):
        return {
            "provider_name": "simulator",
            "model_name": "simulator-model",
            "identity": "simulator-host:simulator-model",
            "configured": True,
        }

    def next_turn(self, scenario, _transcript, _observed_actions):
        domain = (scenario.get("scenario_domains") or [""])[0]
        if domain == "installation_accessory":
            state = "handoff_accepted"
            reason = "handoff_accepted"
        elif domain == "order_logistics_service_action":
            state = "satisfied"
            reason = "resolved"
        else:
            state = "continue"
            reason = "continue"
        return {
            "next_message": "请继续核对。" if state == "continue" else "",
            "observed_action_ids": [],
            "buyer_state": state,
            "stop": state != "continue",
            "stop_reason": reason,
        }


def test_customer_simulator_qualification_requires_serial_and_concurrent_long_load(monkeypatch):
    monkeypatch.setattr(
        qualification,
        "_simulator_from_environment",
        lambda **_kwargs: _Simulator(),
    )

    report = qualification.qualify(repeats=2, workers=2)

    assert report["qualification_status"] == "qualified"
    assert report["serial"]["status"] == "qualified"
    assert report["concurrent"]["status"] == "qualified"
    assert report["serial"]["total_attempt_count"] == 6
    assert report["concurrent"]["semantic_pass_rate"]["rate"] == 1.0


def test_customer_simulator_qualification_fails_on_semantic_instability(monkeypatch):
    calls = {"count": 0}

    class _UnstableSimulator(_Simulator):
        def next_turn(self, scenario, transcript, observed_actions):
            calls["count"] += 1
            value = super().next_turn(scenario, transcript, observed_actions)
            if calls["count"] % 2 == 0:
                value.update({
                    "buyer_state": "blocked",
                    "stop": True,
                    "stop_reason": "cannot_continue",
                    "next_message": "",
                })
            return value

    monkeypatch.setattr(
        qualification,
        "_simulator_from_environment",
        lambda **_kwargs: _UnstableSimulator(),
    )

    report = qualification.qualify(repeats=2, workers=2)

    assert report["qualification_status"] == "not_qualified"
    assert (
        report["serial"]["semantic_pass_rate"]["rate"] < 1.0
        or report["serial"]["repeat_stability_rate"]["rate"] < 1.0
    )
