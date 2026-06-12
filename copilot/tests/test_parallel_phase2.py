from __future__ import annotations

import uuid

import pytest


@pytest.fixture(scope="module")
def client():
    from app.main import create_app

    app = create_app()
    app.config["TESTING"] = True
    return app.test_client()


def _analyze(client, message: str) -> dict:
    resp = client.post(
        "/api/analyze",
        json={
            "message": message,
            "conversation_id": f"phase2-{uuid.uuid4().hex}",
        },
    )
    assert resp.status_code == 200, resp.get_data(as_text=True)
    return resp.get_json()


def _trace_tool_names(data: dict) -> list[str]:
    names: list[str] = []
    for step in data.get("trace_steps", []):
        for key in ("tool_name", "tool", "selected_tool"):
            value = step.get(key)
            if isinstance(value, str) and value:
                names.append(value)
    return names


def _trace_node(data: dict, node_name: str) -> dict:
    for step in data.get("trace_steps", []):
        if step.get("node") == node_name:
            return step
    return {}


def test_safety_contract_blocks_eta_guarantee(client):
    data = _analyze(client, "明天能不能一定到？")
    reply = data["suggested_reply"]

    assert data["evidence_debug"]["safety_contract"]
    assert "一定到" not in reply
    assert "保证到" not in reply
    assert "肯定到" not in reply


def test_material_without_evidence_does_not_assert_solid_wood(client):
    data = _analyze(client, "这个儿童书架是不是实木的？")
    reply = data["suggested_reply"]

    assert data["intent"] in ("product_question", "product_consult", "material_question")
    assert "是实木" not in reply
    assert "不是实木" not in reply
    assert "100%实木" not in reply


def test_identifier_routing_platform_trade_id_calls_outbound_tool(client, monkeypatch):
    from app import config

    monkeypatch.setattr(config, "ENABLE_PARALLEL_IDENTIFIER_ROUTING", True)
    data = _analyze(client, "5118207015382036103 我的快递什么时候到")

    assert "jst_lookup_outbound_tool" in _trace_tool_names(data)
    post_control = _trace_node(data, "parallel_post_strategy_controls")
    assert "identifier_tool=jst_lookup_outbound_tool" in post_control.get("actions", [])


def test_identifier_routing_tracking_no_calls_tracking_tool(client, monkeypatch):
    from app import config

    monkeypatch.setattr(config, "ENABLE_PARALLEL_IDENTIFIER_ROUTING", True)
    data = _analyze(client, "SF0229477422177 到哪里了")

    assert "jst_lookup_tracking_tool" in _trace_tool_names(data)
    post_control = _trace_node(data, "parallel_post_strategy_controls")
    assert "identifier_tool=jst_lookup_tracking_tool" in post_control.get("actions", [])


def test_product_question_does_not_call_jst_tools(client, monkeypatch):
    from app import config

    monkeypatch.setattr(config, "ENABLE_PARALLEL_IDENTIFIER_ROUTING", True)
    data = _analyze(client, "一号狮子围兜防水吗？")
    tools = set(_trace_tool_names(data))

    assert "jst_lookup_order_tool" not in tools
    assert "jst_lookup_outbound_tool" not in tools
    assert "jst_lookup_tracking_tool" not in tools


def test_high_risk_not_downgraded_by_legacy_route(client):
    data = _analyze(client, "再不发货我就投诉平台")

    assert data["risk_level"] == "high"
    assert data["requires_human_review"] is True
    assert "赔偿" not in data["suggested_reply"]


def test_missing_item_uses_manual_followup_or_aftersales_sop(client):
    data = _analyze(client, "收到的货少了一件")

    assert data["risk_level"] in ("medium", "high")
    assert data["requires_human_review"] is True
    assert "直接补发" not in data["suggested_reply"]
    assert "承诺补发" not in data["suggested_reply"]


def test_identifier_routing_switch_off_keeps_observation_mode(client, monkeypatch):
    from app import config

    monkeypatch.setattr(config, "ENABLE_PARALLEL_IDENTIFIER_ROUTING", False)
    data = _analyze(client, "5118207015382036103 我的快递什么时候到")
    post_control = _trace_node(data, "parallel_post_strategy_controls")

    assert post_control.get("actions") == []
    assert "observation/no-op" in post_control.get("summary", "")
