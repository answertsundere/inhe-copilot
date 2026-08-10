import json
import uuid

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.services.reply_style_service import beautify_customer_reply


def test_beautify_customer_reply_splits_into_warm_sections():
    raw = (
        "\u4eb2\u4eb2\uff0c\u810f\u4e86\u600e\u4e48\u6e05\u6d01\u8fd9\u4e2a\u95ee\u9898\u5f88\u5b9e\u7528\uff0c\u6211\u5148\u6309\u4fdd\u5b88\u65b9\u5f0f\u8ddf\u60a8\u8bf4\u54e6\u3002"
        "\u672a\u6838\u5bf9\u5177\u4f53\u6750\u8d28\u548c\u9875\u9762\u6e05\u6d17\u8bf4\u660e\u524d\uff0c\u4e0d\u5efa\u8bae\u76f4\u63a5\u6574\u4f53\u6c34\u6d17\u3002"
        "\u5e73\u65f6\u53ef\u4ee5\u5148\u7528\u5e72\u5e03\u64e6\u62ed\u3002"
    )

    styled = beautify_customer_reply(raw)

    assert styled.startswith("\u4eb2\uff5e")
    assert "\n" in styled
    assert "\n\n" not in styled
    assert "\u6574\u4f53\u6c34\u6d17" in styled
    assert any(icon in styled for icon in ("\U0001f9fc", "\U0001f4cc", "\U0001f4a1", "\U0001f449", "\U0001f64c"))


def test_beautify_does_not_repeat_greeting_after_emoji():
    raw = (
        "\u4eb2\uff5e\u6211\u7406\u89e3\u60a8\u7740\u6025\u60f3\u628a\u9000\u6b3e\u95ee\u9898\u5904\u7406\u597d\uff0c"
        "\u8fd9\u4e2a\u6211\u4f1a\u4f18\u5148\u5e2e\u60a8\u8ddf\u8fdb\u3002"
        "\u6211\u8fd9\u8fb9\u5df2\u7ecf\u770b\u5230\u60a8\u7ed9\u7684\u8ba2\u5355\u4fe1\u606f\u3002"
    )

    styled = beautify_customer_reply(raw, {"query_fact_type": "aftersales_policy"})

    assert styled.startswith("\u4eb2\uff5e\n")
    assert "\U0001f9f6 \u4eb2\uff5e" not in styled
    assert "\U0001faf6 \u4eb2\uff5e" not in styled
    assert styled.count("\u4eb2\uff5e") == 1


@pytest.fixture()
def grounded_material_client(tmp_path, monkeypatch):
    """Provide one published material fact without relying on recovered KB rows."""
    import app.config as config_module
    import app.db as db_module
    import app.main as main_module
    from app.models.kb_tables import KBProduct, KBQA
    from app.models.knowledge_base import KnowledgeChunk, KnowledgeEntry

    db_path = tmp_path / "reply_style_material.db"
    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    session_factory = sessionmaker(autocommit=False, autoflush=False, bind=engine, expire_on_commit=False)
    monkeypatch.setattr(config_module, "KNOWLEDGE_DB_PATH", str(db_path))
    monkeypatch.setattr(main_module, "KNOWLEDGE_DB_PATH", str(db_path))
    monkeypatch.setattr(db_module, "engine", engine)
    monkeypatch.setattr(db_module, "SessionLocal", session_factory)
    for service_name in (
        "_order_repo", "_product_repo", "_knowledge_repo", "_policy_repo",
        "_product_knowledge_repo", "_risk_service", "_context_builder",
        "_output_guard", "_reply_service", "_feedback_service", "_review_queue_service",
        "_reply_template_repo", "_sop_repo", "_data_quality_service", "_quality_check_service",
    ):
        monkeypatch.setattr(main_module, service_name, None)
    db_module.Base.metadata.create_all(bind=engine)

    sku_code = "FIXTURE_REPLY_STYLE_MATERIAL"
    product_name = "Fixture Material Product"
    db = session_factory()
    try:
        product = KBProduct(
            i_id="FIXTURE_REPLY_STYLE_IID",
            product_name=product_name,
            sku_list_json=json.dumps([{"sku_code": sku_code}]),
            specs_json=json.dumps({"material": "\u51b7\u8f67\u94a2\u7ba1\u548c\u73af\u4fddPP"}, ensure_ascii=False),
            status="published",
        )
        db.add(product)
        db.flush()
        db.add(KBQA(
            question="What is the material?",
            answer="The material is cold-rolled steel tubing and PP.",
            product_id=product.id,
            intent="product_question",
            status="published",
            auto_reply=True,
        ))
        entry = KnowledgeEntry(
            source_type="faq",
            title="Fixture material specification",
            content="\u8fd9\u6b3e\u5546\u54c1\u7684\u6750\u8d28\u662f\u51b7\u8f67\u94a2\u7ba1\u548c\u73af\u4fddPP\u3002",
            intent="product_question",
            product_scope_json=json.dumps([product_name]),
            risk_level="low",
            status="published",
            index_status="ready",
            fact_type="material",
            fact_review_status="verified",
        )
        db.add(entry)
        db.flush()
        db.add(KnowledgeChunk(
            entry_id=entry.id,
            chunk_text=entry.content,
            source_type="faq",
            intent="product_question",
            product_scope_json=json.dumps([product_name]),
            metadata_json=json.dumps({"fact_type": "material"}),
            fact_review_status="verified",
            fact_source_type="faq",
        ))
        db.commit()
    finally:
        db.close()

    app = main_module.create_app()
    app.config["TESTING"] = True
    with app.test_client() as client:
        yield client, sku_code


def test_api_reply_style_keeps_grounded_material_facts(grounded_material_client):
    client, sku_code = grounded_material_client
    response = client.post("/ask/api/analyze", json={
        "message": "\u8fd9\u4e2a\u4ec0\u4e48\u6750\u8d28\uff1f",
        "conversation_id": f"test_reply_style_material_{uuid.uuid4().hex}",
        "sku_code": sku_code,
        "product_candidates": [
            {"value": sku_code, "type": "sku_id_candidate", "verified": True},
        ],
    })
    assert response.status_code == 200
    result = response.get_json()

    reply = result["suggested_reply"]
    assert "\n" in reply
    assert "\n\n" not in reply
    assert "\u51b7\u8f67\u94a2\u7ba1" in reply
    assert "\u73af\u4fddPP" in reply


def test_logistics_trace_appends_grounded_secondary_safety_answer():
    raw = "\u4eb2\uff0c\u5e2e\u60a8\u67e5\u5230\u5305\u88f9\u5df2\u7ecf\u53d1\u51fa\uff0c\u6b63\u5728\u8fd0\u8f93\u4e2d\u3002"
    state = {
        "intent": "logistics_trace",
        "customer_message": "\u5e2e\u6211\u67e5\u7269\u6d41\uff0c\u8fd9\u4e2a\u4e1c\u897f\u5b89\u5168\u5417",
        "matched_product_name": "\u4e00\u53f7\u5c0f\u718a\u5e8a\u62a4\u680f",
        "evidence": {
            "product_facts": [
                {
                    "source_type": "product_facts",
                    "fact": "\u6750\u8d28\u4ee5\u5546\u54c1\u9875\u9762\u6807\u6ce8\u4e3a\u51c6\uff0c\u4f7f\u7528\u524d\u5efa\u8bae\u6309\u8bf4\u660e\u4e66\u68c0\u67e5\u5b89\u88c5\u72b6\u6001\u3002",
                    "evidence_allowed_for_direct_answer": True,
                }
            ],
        },
    }

    styled = beautify_customer_reply(raw, state)

    assert "\u4e00\u53f7\u5c0f\u718a\u5e8a\u62a4\u680f" in styled
    assert "\u5b89\u5168/\u6750\u8d28\u95ee\u9898" in styled
    assert "\u8bf4\u660e\u4e66" in styled


def test_logistics_trace_appends_safety_next_step_when_product_unknown():
    raw = "\u4eb2\uff0c\u6211\u5df2\u6536\u5230\u60a8\u63d0\u4f9b\u7684\u5355\u53f7\uff0c\u6b63\u5728\u8fdb\u4e00\u6b65\u6838\u5b9e\u4e2d\u3002"
    state = {
        "intent": "logistics_trace",
        "customer_message": "\u5e2e\u6211\u67e5\u8fd9\u4e2a\u8ba2\u5355\u5230\u54ea\u4e86\uff1f\u6574\u4e2a\u4e1c\u897f\u5b89\u5168\u5417",
        "order_product_identity": {"status": "not_found"},
    }

    styled = beautify_customer_reply(raw, state)

    assert "\u8fd9\u4e2a\u4e1c\u897f\u5b89\u5168\u5417" in styled
    assert "\u9700\u8981\u5148\u5bf9\u4e0a\u5177\u4f53\u5546\u54c1" in styled
    assert "\u5546\u54c1\u622a\u56fe\u6216\u94fe\u63a5" in styled


def test_beautify_softens_installation_convenience_promises():
    raw = "\u4eb2\uff0c\u8fd9\u6b3e\u5b89\u88c5\u5f88\u65b9\u4fbf\uff0c\u4e0d\u9700\u8981\u989d\u5916\u5de5\u5177\uff0c\u4e00\u822c15-20\u5206\u949f\u5c31\u80fd\u5b8c\u6210\u5b89\u88c5\u3002"

    styled = beautify_customer_reply(raw)

    assert "\u5b89\u88c5\u5f88\u65b9\u4fbf" not in styled
    assert "\u4e0d\u9700\u8981\u989d\u5916\u5de5\u5177" not in styled
    assert "\u4e00\u822c15-20\u5206\u949f\u5c31\u80fd\u5b8c\u6210\u5b89\u88c5" not in styled
    assert "\u8bf4\u660e\u4e66" in styled
    assert "\u4ee5\u8bf4\u660e\u4e66\u548c\u5b9e\u9645\u914d\u4ef6\u4e3a\u51c6" in styled


def test_absolute_child_safety_request_uses_real_customer_service_tone():
    styled = beautify_customer_reply(
        "亲亲，商品参数、功能或订单信息需要以已验证的商品知识和订单页面为准，我先不凭感觉猜，避免给您误导。",
        {
            "customer_message": "你直接保证我家孩子用了，一定不会出事，我就拍。",
            "matched_product_name": "一号小熊床护栏",
        },
    )

    assert "孩子用的东西您谨慎是应该的" in styled
    assert "百分百一定不会出事" in styled
    assert "说太满反而不负责" in styled
    assert "宝宝多大" in styled
    assert "商品参数、功能或订单信息" not in styled
    assert "系统" not in styled
    assert "避免给您误导" not in styled
    assert styled.count("\n") == 3
    assert "🧡" in styled


def test_beautify_removes_ai_sounding_phrases():
    raw = (
        "亲亲，根据您提供的信息，这类商品参数、功能或订单信息需要以已验证的商品知识和订单页面为准，"
        "我先不凭感觉猜，避免给您误导。如果系统里暂时没有明确证据，就转人工确认后再给您准确答复。"
    )

    styled = beautify_customer_reply(raw)

    assert "根据您提供的信息" not in styled
    assert "商品参数、功能或订单信息需要以已验证" not in styled
    assert "我先不凭感觉猜" not in styled
    assert "避免给您误导" not in styled
    assert "系统里暂时没有明确证据" not in styled
