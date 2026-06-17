from __future__ import annotations


def test_order_product_resolver_prefers_sidecar_sku_code_without_order_lookup(monkeypatch):
    from app.agent.nodes import order_product_resolver as node

    order_calls = []

    class FakeKnowledgeRepo:
        def get_by_sku_id(self, sku_id):
            assert sku_id == "YH88K01B09S26"
            return {
                "i_id": "YH88K01",
                "product_name": "\u4e00\u53f7\u5582\u517b\u67dc",
                "sku_summary": {"sku_list": [{"sku_id": "YH88K01B09S26"}]},
            }

        def get_by_i_id(self, i_id):
            return None

    monkeypatch.setattr("app.main.get_product_knowledge_repo", lambda: FakeKnowledgeRepo())
    monkeypatch.setattr("app.main.get_product_repo", lambda: None)
    monkeypatch.setattr(
        "app.integrations.jst.live_query.lookup_order_by_identifier",
        lambda identifier, identifier_type: order_calls.append((identifier, identifier_type)) or {"found": False},
    )

    result = node.order_product_resolver({
        "conversation_id": "resolver-direct-sku-code",
        "customer_message": "product followup",
        "normalized_message": "product followup",
        "slots": {},
        "copilot_context": {
            "order_candidates": [{"value": "5116887975001001001", "type": "platform_trade_id_candidate"}],
            "product_candidates": [{"value": "YH88K01B09S26", "type": "sku_id_candidate", "verified": True}],
        },
        "conversation_context": {},
        "trace_steps": [],
    })

    assert order_calls == []
    assert result["matched_product_name"] == "\u4e00\u53f7\u5582\u517b\u67dc"
    assert result["slots"]["sku_code"] == "YH88K01B09S26"
    assert result["order_product_identity"]["source"] == "sidecar_product_code"
    assert result["order_product_identity"]["i_id"] == "YH88K01"


def test_order_product_resolver_can_use_jst_sku_lookup_when_local_missing(monkeypatch):
    from app.agent.nodes import order_product_resolver as node

    class EmptyKnowledgeRepo:
        def get_by_sku_id(self, sku_id):
            return None

        def get_by_i_id(self, i_id):
            return None

    monkeypatch.setattr("app.main.get_product_knowledge_repo", lambda: EmptyKnowledgeRepo())
    monkeypatch.setattr("app.main.get_product_repo", lambda: None)
    monkeypatch.setattr(
        "app.integrations.jst.live_query.lookup_product_by_sku",
        lambda sku_id: {
            "found": True,
            "endpoint": "sku/query",
            "duration_ms": 8,
            "data": {"sku_id": sku_id, "i_id": "YH88K01", "name": "\u4e00\u53f7\u5582\u517b\u67dc"},
        },
    )

    result = node.order_product_resolver({
        "conversation_id": "resolver-direct-jst-sku",
        "customer_message": "product followup",
        "normalized_message": "product followup",
        "slots": {},
        "copilot_context": {
            "product_candidates": [{"value": "YH88K01B09S26", "type": "sku_id_candidate", "verified": True}],
        },
        "conversation_context": {},
        "trace_steps": [],
    })

    assert result["matched_product_name"] == "\u4e00\u53f7\u5582\u517b\u67dc"
    assert result["order_product_identity"]["source"] == "jst_sku_query"
    assert result["order_product_identity"]["lookup_endpoint"] == "sku/query"


def test_order_product_resolver_can_use_jst_i_id_lookup_when_local_missing(monkeypatch):
    from app.agent.nodes import order_product_resolver as node

    node._RESOLUTION_CACHE.clear()

    class EmptyKnowledgeRepo:
        def get_by_sku_id(self, sku_id):
            return None

        def get_by_i_id(self, i_id):
            return None

    monkeypatch.setattr("app.main.get_product_knowledge_repo", lambda: EmptyKnowledgeRepo())
    monkeypatch.setattr("app.main.get_product_repo", lambda: None)
    monkeypatch.setattr(
        "app.db.SessionLocal",
        lambda: (_ for _ in ()).throw(RuntimeError("no kb_product in this unit test")),
    )
    monkeypatch.setattr(
        "app.integrations.jst.live_query.lookup_product_by_i_id",
        lambda i_id: {
            "found": True,
            "endpoint": "mall/item/query",
            "duration_ms": 9,
            "data": {"i_id": i_id, "name": "英禾宝宝围栏"},
        },
    )

    result = node.order_product_resolver({
        "conversation_id": "resolver-direct-jst-i-id",
        "customer_message": "这个有划痕怎么办",
        "normalized_message": "这个有划痕怎么办",
        "slots": {},
        "copilot_context": {
            "product_candidates": [{"value": "YH88K01", "type": "i_id_candidate", "verified": True}],
        },
        "conversation_context": {},
        "trace_steps": [],
    })

    identity = result["order_product_identity"]
    assert result["matched_product_name"] == "英禾宝宝围栏"
    assert identity["source"] == "jst_product_query"
    assert identity["identifier_type"] == "i_id"
    assert identity["i_id"] == "YH88K01"
    assert identity["lookup_endpoint"] == "mall/item/query"


def test_order_product_resolver_does_not_treat_platform_product_id_as_sku(monkeypatch):
    from app.agent.nodes import order_product_resolver as node

    sku_calls = []
    monkeypatch.setattr("app.main.get_product_knowledge_repo", lambda: None)
    monkeypatch.setattr("app.main.get_product_repo", lambda: None)
    monkeypatch.setattr(
        "app.integrations.jst.live_query.lookup_product_by_sku",
        lambda sku_id: sku_calls.append(sku_id) or {"found": False},
    )

    result = node.order_product_resolver({
        "conversation_id": "resolver-platform-product-id",
        "customer_message": "product followup",
        "normalized_message": "product followup",
        "slots": {},
        "copilot_context": {
            "product_candidates": [{"value": "1046558780232", "type": "platform_product_id_candidate"}],
        },
        "conversation_context": {},
        "trace_steps": [],
    })

    assert sku_calls == []
    assert result["trace_steps"][-1]["status"] == "skipped"
    assert "order_product_identity" not in result


def test_order_product_resolver_uses_product_name_to_query_jst(monkeypatch):
    from app.agent.nodes import order_product_resolver as node

    title = "\u82f1\u79be\u5e8a\u56f4\u680f\u5b9d\u5b9d\u9632\u6454\u5a74\u513f\u5e8a\u62a4\u680f\u513f\u7ae5\u5e8a\u8fb9\u6321\u677f\u4e00\u4fa7\u5355\u9762\u9694\u677f\u4fbf\u643a\u5f0f"
    calls = []

    monkeypatch.setattr("app.main.get_product_knowledge_repo", lambda: None)
    monkeypatch.setattr("app.main.get_product_repo", lambda: None)
    monkeypatch.setattr(
        "app.integrations.jst.live_query.lookup_product_by_name",
        lambda product_name: calls.append(product_name) or {
            "found": True,
            "endpoint": "mall/item/query",
            "duration_ms": 15,
            "confidence": 0.92,
            "data": {
                "name": "\u82f1\u79be\u5e8a\u56f4\u680f",
                "i_id": "YH-BED-GUARD",
                "sku_id": "YH-BED-GUARD-S01",
            },
        },
    )

    result = node.order_product_resolver({
        "conversation_id": "resolver-product-name-jst",
        "customer_message": "\u4f1a\u6389\u4e0b\u6765\u4e48",
        "normalized_message": "\u4f1a\u6389\u4e0b\u6765\u4e48",
        "slots": {},
        "copilot_context": {
            "product_candidates": [
                {"value": "985017262291", "type": "platform_product_id_candidate"},
                {"value": title, "type": "product_candidate"},
            ],
        },
        "conversation_context": {},
        "trace_steps": [],
    })

    assert calls == [title]
    assert result["matched_product_name"] == "\u82f1\u79be\u5e8a\u56f4\u680f"
    assert result["slots"]["sku_code"] == "YH-BED-GUARD-S01"
    assert result["order_product_identity"]["source"] == "jst_product_name_query"
    assert result["order_product_identity"]["identifier_type"] == "product_name"


def test_order_product_resolver_does_not_use_platform_id_for_product_lookup(monkeypatch):
    from app.agent.nodes import order_product_resolver as node

    name_calls = []
    sku_calls = []
    monkeypatch.setattr("app.main.get_product_knowledge_repo", lambda: None)
    monkeypatch.setattr("app.main.get_product_repo", lambda: None)
    monkeypatch.setattr(
        "app.integrations.jst.live_query.lookup_product_by_name",
        lambda product_name: name_calls.append(product_name) or {"found": False},
    )
    monkeypatch.setattr(
        "app.integrations.jst.live_query.lookup_product_by_sku",
        lambda sku_id: sku_calls.append(sku_id) or {"found": False},
    )

    result = node.order_product_resolver({
        "conversation_id": "resolver-platform-id-only-no-query",
        "customer_message": "product followup",
        "normalized_message": "product followup",
        "slots": {},
        "copilot_context": {
            "product_candidates": [{"value": "985017262291", "type": "platform_product_id_candidate"}],
        },
        "conversation_context": {},
        "trace_steps": [],
    })

    assert name_calls == []
    assert sku_calls == []
    assert result["trace_steps"][-1]["status"] == "skipped"
    assert "order_product_identity" not in result


def test_order_product_resolver_maps_sidecar_product_name_to_local_sku(monkeypatch):
    from app.agent.nodes import order_product_resolver as node

    node._RESOLUTION_CACHE.clear()

    class FakeKnowledgeRepo:
        _cards = [
            {
                "i_id": "YH88K01",
                "product_name": "\u4e00\u53f7\u5582\u517b\u67dc",
                "sku_summary": {"sku_list": [{"sku_id": "YH88K01B09S26"}]},
            }
        ]

    monkeypatch.setattr("app.main.get_product_knowledge_repo", lambda: FakeKnowledgeRepo())
    monkeypatch.setattr("app.main.get_product_repo", lambda: None)
    monkeypatch.setattr(
        "app.db.SessionLocal",
        lambda: (_ for _ in ()).throw(RuntimeError("no kb_product in this unit test")),
    )
    monkeypatch.setattr(
        "app.integrations.jst.live_query.lookup_product_by_name",
        lambda product_name: {"found": False, "safe_fallback_reason": "not_found"},
    )

    result = node.order_product_resolver({
        "conversation_id": "resolver-product-name-local",
        "customer_message": "product followup",
        "normalized_message": "product followup",
        "slots": {},
        "copilot_context": {
            "product_candidates": [{"value": "\u82f1\u79be\u5582\u517b\u591a\u529f\u80fd\u6536\u7eb3\u67dc", "type": "product_candidate"}],
        },
        "conversation_context": {},
        "trace_steps": [],
    })

    assert result["matched_product_name"] == "\u4e00\u53f7\u5582\u517b\u67dc"
    assert result["slots"]["sku_code"] == "YH88K01B09S26"
    assert result["order_product_identity"]["source"] == "sidecar_product_name"


def test_order_product_resolver_keeps_ambiguous_sidecar_product_name_unmatched(monkeypatch):
    from app.agent.nodes import order_product_resolver as node

    class FakeKnowledgeRepo:
        _cards = [
            {
                "i_id": "A",
                "product_name": "\u513f\u7ae5\u4e66\u67b6A",
                "sku_summary": {"sku_list": [{"sku_id": "SKU-A"}]},
            },
            {
                "i_id": "B",
                "product_name": "\u513f\u7ae5\u4e66\u67b6B",
                "sku_summary": {"sku_list": [{"sku_id": "SKU-B"}]},
            },
        ]

    monkeypatch.setattr("app.main.get_product_knowledge_repo", lambda: FakeKnowledgeRepo())
    monkeypatch.setattr("app.main.get_product_repo", lambda: None)

    result = node.order_product_resolver({
        "conversation_id": "resolver-product-name-ambiguous",
        "customer_message": "product followup",
        "normalized_message": "product followup",
        "slots": {},
        "copilot_context": {
            "product_candidates": [{"value": "\u513f\u7ae5\u4e66\u67b6", "type": "product_candidate"}],
        },
        "conversation_context": {},
        "trace_steps": [],
    })

    assert result["order_product_identity"]["status"] == "ambiguous"
    assert "matched_product_name" not in result
    assert result["need_clarification"] is True
    assert result["product_candidates"] == []
    assert result["should_query_knowledge"] is False
    assert result["answer_mode"] == "no_evidence_clarification"


def test_order_product_resolver_uses_sidecar_order_to_resolve_internal_product(monkeypatch):
    from app.agent.nodes import order_product_resolver as node

    calls = []

    def fake_lookup(identifier, identifier_type):
        calls.append((identifier, identifier_type))
        return {
            "found": True,
            "endpoint": "orders/out/simple/query",
            "duration_ms": 12,
            "data": {
                "o_id": "1636367",
                "so_id": "5118207015382036103",
                "items": [
                    {
                        "name": "一号喂养柜",
                        "sku_id": "SKU-YG-001",
                        "i_id": "I-YG-001",
                        "qty": 1,
                    }
                ],
            },
        }

    monkeypatch.setattr(
        "app.integrations.jst.live_query.lookup_order_by_identifier",
        fake_lookup,
    )

    state = {
        "conversation_id": "resolver-1",
        "customer_message": "这个怎么自动感应",
        "normalized_message": "这个怎么自动感应",
        "slots": {},
        "copilot_context": {
            "order_candidates": [
                {"value": "5118207015382036103", "type": "platform_trade_id_candidate"}
            ],
            "product_candidates": [
                {"value": "平台标题 英禾喂养多功能收纳柜"}
            ],
        },
        "conversation_context": {},
        "trace_steps": [],
    }

    result = node.order_product_resolver(state)

    assert calls == [("5118207015382036103", "platform_trade_id")]
    assert result["matched_product_name"] == "一号喂养柜"
    assert result["slots"]["product_name"] == "一号喂养柜"
    assert result["slots"]["sku_code"] == "SKU-YG-001"
    assert result["order_product_identity"]["i_id"] == "I-YG-001"
    assert result["product_identity_source"] == "jst_order_items"


def test_order_product_resolver_uses_conversation_cache_without_requery(monkeypatch):
    from app.agent.nodes import order_product_resolver as node

    calls = []

    def fake_lookup(identifier, identifier_type):
        calls.append((identifier, identifier_type))
        return {"found": False, "safe_fallback_reason": "should_not_call"}

    monkeypatch.setattr(
        "app.integrations.jst.live_query.lookup_order_by_identifier",
        fake_lookup,
    )

    state = {
        "conversation_id": "resolver-cache",
        "customer_message": "这个能洗吗",
        "normalized_message": "这个能洗吗",
        "slots": {},
        "copilot_context": {
            "order_candidates": [
                {"value": "5118207015382036103", "type": "platform_trade_id_candidate"}
            ]
        },
        "conversation_context": {
            "order_product_identity_key": "platform_trade_id:5118207015382036103",
            "order_product_identity": {
                "status": "resolved",
                "source": "jst_order_items",
                "identifier": "5118207015382036103",
                "identifier_type": "platform_trade_id",
                "matched_product_name": "一号喂养柜",
                "sku_id": "SKU-YG-001",
                "i_id": "I-YG-001",
                "candidates": ["一号喂养柜", "SKU-YG-001", "I-YG-001"],
            },
        },
        "trace_steps": [],
    }

    result = node.order_product_resolver(state)

    assert calls == []
    assert result["matched_product_name"] == "一号喂养柜"
    assert result["trace_steps"][-1]["cache_hit"] is True


def test_order_product_resolver_keeps_ambiguous_multi_item_order_unmatched(monkeypatch):
    from app.agent.nodes import order_product_resolver as node

    def fake_lookup(identifier, identifier_type):
        return {
            "found": True,
            "data": {
                "o_id": "1",
                "items": [
                    {"name": "一号喂养柜", "sku_id": "A", "i_id": "IA"},
                    {"name": "六号防摔枕", "sku_id": "B", "i_id": "IB"},
                ],
            },
        }

    monkeypatch.setattr(
        "app.integrations.jst.live_query.lookup_order_by_identifier",
        fake_lookup,
    )

    result = node.order_product_resolver({
        "conversation_id": "resolver-ambiguous",
        "customer_message": "这个材质是什么",
        "normalized_message": "这个材质是什么",
        "slots": {},
        "copilot_context": {
            "order_candidates": [{"value": "1", "type": "platform_trade_id_candidate"}]
        },
        "conversation_context": {},
        "trace_steps": [],
    })

    assert result["order_product_identity"]["status"] == "ambiguous"
    assert "matched_product_name" not in result
    assert result["need_clarification"] is True


def test_order_product_resolver_selects_single_paid_item_when_order_has_gift(monkeypatch):
    from app.agent.nodes import order_product_resolver as node

    def fake_lookup(identifier, identifier_type):
        return {
            "found": True,
            "data": {
                "o_id": "1647110",
                "items": [
                    {"name": "一号喂养柜", "sku_id": "YH88K01B09S26", "i_id": "YH88K01", "price": 775.52},
                    {"name": "【赠品】折叠衣架两只装", "sku_id": "YH45K03B05S17", "i_id": "YH45K03B05S17", "price": 0},
                ],
            },
        }

    monkeypatch.setattr(
        "app.integrations.jst.live_query.lookup_order_by_identifier",
        fake_lookup,
    )

    result = node.order_product_resolver({
        "conversation_id": "resolver-primary-plus-gift",
        "customer_message": "这是可拆卸的吗",
        "normalized_message": "这是可拆卸的吗",
        "slots": {},
        "copilot_context": {
            "order_candidates": [{"value": "3307902168539007857", "type": "platform_trade_id_candidate"}]
        },
        "conversation_context": {},
        "trace_steps": [],
    })

    identity = result["order_product_identity"]
    assert identity["status"] == "resolved"
    assert identity["matched_product_name"] == "一号喂养柜"
    assert identity["sku_id"] == "YH88K01B09S26"
    assert identity["reason"] == "single_primary_item_with_gifts"


def test_order_product_resolver_falls_back_to_unknown_identifier_when_typed_lookup_misses(monkeypatch):
    from app.agent.nodes import order_product_resolver as node

    calls = []

    def fake_lookup(identifier, identifier_type):
        calls.append((identifier, identifier_type))
        if identifier_type == "platform_trade_id":
            return {"found": False, "safe_fallback_reason": "not_found"}
        return {
            "found": True,
            "data": {
                "o_id": "1636367",
                "items": [{"name": "一号喂养柜", "sku_id": "SKU-YG-001", "i_id": "I-YG-001"}],
            },
        }

    monkeypatch.setattr(
        "app.integrations.jst.live_query.lookup_order_by_identifier",
        fake_lookup,
    )

    result = node.order_product_resolver({
        "conversation_id": "resolver-fallback",
        "customer_message": "这个怎么用",
        "normalized_message": "这个怎么用",
        "slots": {},
        "copilot_context": {
            "order_candidates": [
                {"value": "5116887975001001001", "type": "platform_trade_id_candidate"}
            ]
        },
        "conversation_context": {},
        "trace_steps": [],
    })

    assert calls == [
        ("5116887975001001001", "platform_trade_id"),
        ("5116887975001001001", "unknown_identifier"),
    ]
    assert result["matched_product_name"] == "一号喂养柜"
    assert result["order_product_identity"]["identifier_type"] == "unknown_identifier"


def test_order_product_resolver_maps_i_id_from_kb_product(monkeypatch, tmp_path):
    import json
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    import app.db as db_module
    from app.agent.nodes import order_product_resolver as node
    from app.models.kb_tables import KBProduct

    node._RESOLUTION_CACHE.clear()
    engine = create_engine(f"sqlite:///{tmp_path / 'kb_product.db'}", connect_args={"check_same_thread": False})
    session_factory = sessionmaker(autocommit=False, autoflush=False, bind=engine, expire_on_commit=False)
    monkeypatch.setattr(db_module, "engine", engine)
    monkeypatch.setattr(db_module, "SessionLocal", session_factory)
    db_module.Base.metadata.create_all(bind=engine)

    db = session_factory()
    try:
        db.add(KBProduct(
            i_id="YH64K01",
            product_name="一号小熊床护栏",
            sku_list_json=json.dumps([{"sku_code": "YH64K01B03S26"}]),
            status="published",
        ))
        db.commit()
    finally:
        db.close()

    class EmptyKnowledgeRepo:
        def get_by_sku_id(self, sku_id):
            return None

        def get_by_i_id(self, i_id):
            return None

    monkeypatch.setattr("app.main.get_product_knowledge_repo", lambda: EmptyKnowledgeRepo())
    monkeypatch.setattr("app.main.get_product_repo", lambda: None)

    result = node.order_product_resolver({
        "conversation_id": "resolver-kb-product-iid",
        "customer_message": "这个如何安装方便吗",
        "normalized_message": "这个如何安装方便吗",
        "slots": {},
        "copilot_context": {
            "product_candidates": [{"value": "YH64K01", "type": "i_id_candidate", "verified": True}],
        },
        "conversation_context": {},
        "trace_steps": [],
    })

    assert result["matched_product_name"] == "一号小熊床护栏"
    assert result["order_product_identity"]["source"] == "sidecar_product_code"
    assert result["order_product_identity"]["i_id"] == "YH64K01"


def test_order_product_resolver_maps_long_title_from_kb_product(monkeypatch, tmp_path):
    import json
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    import app.db as db_module
    from app.agent.nodes import order_product_resolver as node
    from app.models.kb_tables import KBProduct

    node._RESOLUTION_CACHE.clear()
    engine = create_engine(f"sqlite:///{tmp_path / 'kb_product_name.db'}", connect_args={"check_same_thread": False})
    session_factory = sessionmaker(autocommit=False, autoflush=False, bind=engine, expire_on_commit=False)
    monkeypatch.setattr(db_module, "engine", engine)
    monkeypatch.setattr(db_module, "SessionLocal", session_factory)
    db_module.Base.metadata.create_all(bind=engine)

    db = session_factory()
    try:
        db.add(KBProduct(
            i_id="YH06K53",
            product_name="九号防夹滑门收纳柜",
            sku_list_json=json.dumps([{"sku_code": "YH06K53"}]),
            status="published",
        ))
        db.commit()
    finally:
        db.close()

    monkeypatch.setattr("app.main.get_product_knowledge_repo", lambda: None)
    monkeypatch.setattr("app.main.get_product_repo", lambda: None)
    monkeypatch.setattr(
        "app.integrations.jst.live_query.lookup_product_by_name",
        lambda product_name: {"found": False, "safe_fallback_reason": "not_found"},
    )

    result = node.order_product_resolver({
        "conversation_id": "resolver-kb-product-title",
        "customer_message": "这个材质安全吗",
        "normalized_message": "这个材质安全吗",
        "slots": {},
        "copilot_context": {
            "product_candidates": [{
                "value": "英禾防夹滑门收纳架整理客厅零食桌面儿童玩具卧室可拼搭储物抽屉",
                "type": "product_candidate",
            }],
        },
        "conversation_context": {},
        "trace_steps": [],
    })

    assert result["matched_product_name"] == "九号防夹滑门收纳柜"
    assert result["order_product_identity"]["i_id"] == "YH06K53"


# ---------------------------------------------------------------------------
# Strategy regression: local-first, JST as low-confidence second confirmation.
# These tests exercise the resolver's DECISION logic by injecting controlled
# local + JST results (generic placeholder names, no hardcoded real title/SKU).
# ---------------------------------------------------------------------------


def _stub_local_identity(name: str, sku: str, *, low_confidence: bool, confidence: float) -> dict:
    """Build a controlled local-resolution identity (confident or low_confidence)."""
    identity = {
        "status": "resolved",
        "source": "sidecar_product_name",
        "identifier": name,
        "identifier_type": "product_name",
        "internal_product_name": name,
        "matched_product_name": name,
        "sku_id": sku,
        "i_id": sku,
        "confidence": confidence,
        "reason": "low_confidence_single_match" if low_confidence else "matched_by_sidecar_product_name",
        "item_count": 1,
        "candidates": [{"name": name, "sku_id": sku, "i_id": sku}],
    }
    if low_confidence:
        identity["low_confidence"] = True
    return identity


def _stub_jst_lookup(*, found: bool, name: str = "", sku: str = "", confidence: float = 0.9) -> dict:
    if not found:
        return {"found": False, "safe_fallback_reason": "not_found"}
    return {
        "found": True,
        "endpoint": "mall/item/query",
        "duration_ms": 10,
        "confidence": confidence,
        "data": {"name": name, "i_id": sku, "sku_id": sku},
    }


def _name_only_state(conv_id: str, candidate: str) -> dict:
    return {
        "conversation_id": conv_id,
        "customer_message": "follow up",
        "normalized_message": "follow up",
        "slots": {},
        "copilot_context": {"product_candidates": [{"value": candidate, "type": "product_candidate"}]},
        "conversation_context": {},
        "trace_steps": [],
    }


def test_local_confident_match_skips_jst_name_query(monkeypatch):
    from app.agent.nodes import order_product_resolver as node

    node._RESOLUTION_CACHE.clear()
    jst_calls = []
    monkeypatch.setattr(
        node,
        "_resolve_product_name_from_local",
        lambda state: _stub_local_identity("demo-local-A", "SKU-LOCAL-A", low_confidence=False, confidence=0.9),
    )
    monkeypatch.setattr(
        "app.integrations.jst.live_query.lookup_product_by_name",
        lambda product_name: jst_calls.append(product_name) or _stub_jst_lookup(found=False),
    )

    result = node.order_product_resolver(_name_only_state("strategy-confident", "demo-candidate-A"))

    assert jst_calls == []  # confident local match -> JST not queried
    assert result["matched_product_name"] == "demo-local-A"
    assert result["order_product_identity"]["source"] == "sidecar_product_name"
    assert result["order_product_identity"].get("low_confidence") is not True


def test_local_low_confidence_match_triggers_jst_name_query(monkeypatch):
    from app.agent.nodes import order_product_resolver as node

    node._RESOLUTION_CACHE.clear()
    jst_calls = []
    monkeypatch.setattr(
        node,
        "_resolve_product_name_from_local",
        lambda state: _stub_local_identity("demo-local-B", "SKU-LOCAL-B", low_confidence=True, confidence=0.4),
    )
    monkeypatch.setattr(
        "app.integrations.jst.live_query.lookup_product_by_name",
        lambda product_name: jst_calls.append(product_name) or _stub_jst_lookup(found=False),
    )

    node.order_product_resolver(_name_only_state("strategy-low-triggers-jst", "demo-candidate-B"))

    assert len(jst_calls) == 1  # low-confidence local match -> JST queried for confirmation


def test_jst_resolved_overrides_local_low_confidence(monkeypatch):
    from app.agent.nodes import order_product_resolver as node

    node._RESOLUTION_CACHE.clear()
    monkeypatch.setattr(
        node,
        "_resolve_product_name_from_local",
        lambda state: _stub_local_identity("demo-local-C", "SKU-LOCAL-C", low_confidence=True, confidence=0.4),
    )
    monkeypatch.setattr(
        "app.integrations.jst.live_query.lookup_product_by_name",
        lambda product_name: _stub_jst_lookup(found=True, name="demo-jst-C", sku="SKU-JST-C", confidence=0.92),
    )

    result = node.order_product_resolver(_name_only_state("strategy-jst-wins", "demo-candidate-C"))

    assert result["matched_product_name"] == "demo-jst-C"
    assert result["slots"]["sku_code"] == "SKU-JST-C"
    assert result["order_product_identity"]["source"] == "jst_product_name_query"
    assert result["order_product_identity"].get("low_confidence") is not True


def test_jst_miss_keeps_local_low_confidence_result(monkeypatch):
    from app.agent.nodes import order_product_resolver as node

    node._RESOLUTION_CACHE.clear()
    monkeypatch.setattr(
        node,
        "_resolve_product_name_from_local",
        lambda state: _stub_local_identity("demo-local-D", "SKU-LOCAL-D", low_confidence=True, confidence=0.4),
    )
    monkeypatch.setattr(
        "app.integrations.jst.live_query.lookup_product_by_name",
        lambda product_name: _stub_jst_lookup(found=False),
    )

    result = node.order_product_resolver(_name_only_state("strategy-jst-miss", "demo-candidate-D"))

    assert result["matched_product_name"] == "demo-local-D"
    assert result["slots"]["sku_code"] == "SKU-LOCAL-D"
    assert result["order_product_identity"]["source"] == "sidecar_product_name"
    assert result["order_product_identity"].get("low_confidence") is True
