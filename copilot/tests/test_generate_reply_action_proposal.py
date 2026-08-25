from app.agent.nodes.generate_reply import _action_proposal


def test_free_text_sop_heading_cannot_become_action_proposal():
    default = {"action_type": "无", "reason": ""}
    state = {
        "sop_scenarios": [{
            "scenario": "售后处理",
            "steps": ["客服回复 Agent", "核对订单和问题"],
        }],
    }

    assert _action_proposal(state, default) == default
