from copy import deepcopy

import pytest

from app.agent.nodes import order_product_resolver as node


@pytest.mark.parametrize("context", [
    {},
    {"slots": {"sku_code": "variable-sku"}},
    {"order_id": "order-ref", "intent": "logistics_trace"},
    {"copilot_context": {"product_candidates": [{"type": "product_title", "value": "ambiguous title"}]}},
    {"conversation_context": {"order_product_identity": {"status": "resolved", "sku_id": "stale-sku"}}},
])
def test_hub_only_defers_legacy_identity_without_promoting_input(monkeypatch, context):
    monkeypatch.setenv("COPILOT_KNOWLEDGE_SOURCE_MODE", "product_hub_review_only")
    state = {"conversation_id": "variable-conversation", "trace_steps": [{"node": "upstream"}], **context}
    before = deepcopy(state)

    def forbidden(*args, **kwargs):
        raise AssertionError("Legacy identity/cache lookup must not run in Hub-only mode")

    monkeypatch.setattr(node, "_resolve_direct_product_code", forbidden)
    monkeypatch.setattr(node, "_cache_get", forbidden)
    monkeypatch.setattr(node, "_resolve_product_name_via_jst", forbidden)
    updates = node.order_product_resolver(state)

    assert state == before
    assert set(updates) == {"trace_steps"}
    assert updates["trace_steps"][:-1] == before["trace_steps"]
    trace = updates["trace_steps"][-1]
    assert trace["status"] == "skipped"
    assert trace["reason"] == "product_hub_identity_owned_by_context_pack"
    assert trace["cache_hit"] is False


@pytest.mark.parametrize("mode", [None, "local", "product_hub_review_only_typo"])
def test_default_identity_path_is_unchanged(monkeypatch, mode):
    if mode is None:
        monkeypatch.delenv("COPILOT_KNOWLEDGE_SOURCE_MODE", raising=False)
    else:
        monkeypatch.setenv("COPILOT_KNOWLEDGE_SOURCE_MODE", mode)
    calls = []
    identity = {"status": "resolved", "source": "existing-owner"}
    monkeypatch.setattr(node, "_resolve_direct_product_code", lambda state: calls.append(state) or identity)
    monkeypatch.setattr(node, "_build_updates_from_identity", lambda state, actual, *args, **kwargs: {"existing_result": actual})
    state = {"trace_steps": []}

    updates = node.order_product_resolver(state)

    assert calls == [state]
    assert updates == {"existing_result": identity}
