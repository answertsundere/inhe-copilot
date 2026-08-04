from __future__ import annotations

import json
import subprocess
import sys
import uuid
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool


@pytest.fixture()
def generic_rule_db(monkeypatch):
    import app.db as db_module
    from app.models.kb_tables import KBGenericServiceRule, KBMediaAsset, KBProduct, KBProductActivityRule, KBQA
    from app.models.knowledge_base import KnowledgeChunk, KnowledgeEntry

    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    session_factory = sessionmaker(autocommit=False, autoflush=False, bind=engine, expire_on_commit=False)
    monkeypatch.setattr(db_module, "engine", engine)
    monkeypatch.setattr(db_module, "SessionLocal", session_factory)
    db_module.Base.metadata.create_all(
        bind=engine,
        tables=[
            KBProduct.__table__,
            KBQA.__table__,
            KBMediaAsset.__table__,
            KBProductActivityRule.__table__,
            KnowledgeEntry.__table__,
            KnowledgeChunk.__table__,
            KBGenericServiceRule.__table__,
        ],
    )
    return session_factory


def test_generic_rule_service_uses_semantic_fact_type():
    from app.services.generic_service_rule_service import search_generic_service_rules

    rules = search_generic_service_rules(
        query="有没有味道",
        intent="product_question",
        fact_type="odor",
    )

    assert rules
    assert rules[0]["rule_key"] == "odor_new_product_ventilation_v1"
    assert rules[0]["fact_type"] == "odor"
    assert rules[0]["source_type"] == "generic_rules"


def test_default_generic_rules_are_merged_when_database_has_partial_rules(generic_rule_db):
    from app.models.kb_tables import KBGenericServiceRule
    from app.services.generic_service_rule_service import search_generic_service_rules

    db = generic_rule_db()
    try:
        db.add(KBGenericServiceRule(
            rule_key="custom_invoice_rule",
            title="发票核对",
            fact_type="invoice_policy",
            status="active",
            auto_reply_allowed=True,
            priority=10,
        ))
        db.commit()

        rules = search_generic_service_rules(
            db=db,
            RuleModel=KBGenericServiceRule,
            query="退货取件怎么安排",
            intent="aftersales",
            fact_type="return_pickup",
        )
    finally:
        db.close()

    assert rules
    assert rules[0]["rule_key"] == "return_pickup_aftersales_logistics_check_v1"


def test_after_sales_payment_rule_matches_payment_timing_questions():
    from app.services.generic_service_rule_service import (
        render_generic_service_reply,
        search_generic_service_rules,
    )

    rules = search_generic_service_rules(
        query="\u652f\u4ed8\u5b9d\u6253\u6b3e\u591a\u4e45\u80fd\u5230\u8d26\uff1f\u6dd8\u5b9d\u5c0f\u989d\u6253\u6b3e\u9700\u8981\u591a\u4e45\uff1f",
        intent="aftersales",
        fact_type="aftersales_policy",
    )

    assert rules
    reply = render_generic_service_reply(rules[0])
    assert rules[0]["rule_key"] == "after_sales_payment_timing_v1"
    assert rules[0]["fact_type"] == "aftersales_policy"
    assert "7 \u5929\u5de6\u53f3" in reply
    assert "72 \u5c0f\u65f6\u5de6\u53f3" in reply
    assert "\u652f\u4ed8\u5b9d\u8d26\u53f7" in reply
    assert "\u59d3\u540d" in reply
    assert "\u9a6c\u4e0a\u5230\u8d26" not in reply
    assert "\u4e00\u5b9a\u5f53\u5929\u5230\u8d26" not in reply


def test_service_action_generic_rules_cover_common_policy_gaps():
    from app.services.generic_service_rule_service import (
        render_generic_service_reply,
        search_generic_service_rules,
    )

    cases = [
        {
            "query": "\u9000\u8d27\u53d6\u4ef6\u600e\u4e48\u5b89\u6392\uff0c\u4e3a\u4ec0\u4e48\u6ca1\u6709\u4e0a\u95e8\u53d6\u4ef6",
            "intent": "aftersales",
            "fact_type": "return_pickup",
            "rule_key": "return_pickup_aftersales_logistics_check_v1",
            "must": ["\u8ba2\u5355", "\u552e\u540e", "\u53d6\u4ef6\u65b9\u5f0f", "\u4e0b\u4e00\u6b65"],
            "forbidden": ["\u4e00\u5b9a\u4f1a\u4e0a\u95e8\u53d6\u4ef6", "\u7acb\u5373\u9000\u6b3e", "\u76f4\u63a5\u8865\u53d1"],
        },
        {
            "query": "\u7269\u6d41\u5230\u54ea\u4e86\uff0c\u7b7e\u6536\u540e\u6ca1\u6536\u5230",
            "intent": "logistics",
            "fact_type": "stock_shipping",
            "rule_key": "logistics_order_status_check_v1",
            "must": ["\u8ba2\u5355\u7269\u6d41", "\u53d1\u8d27", "\u7b7e\u6536\u540e\u6ca1\u6536\u5230"],
            "forbidden": ["\u660e\u5929\u4e00\u5b9a\u5230", "\u80af\u5b9a\u5df2\u9001\u8fbe"],
        },
        {
            "query": "\u5c11\u4ef6\u4e86\u600e\u4e48\u8865\u53d1",
            "intent": "aftersales",
            "fact_type": "aftersales_policy",
            "rule_key": "aftersales_issue_collect_and_review_v1",
            "must": ["\u95ee\u9898\u4f4d\u7f6e\u7167\u7247", "\u8ba2\u5355\u4fe1\u606f", "\u5904\u7406\u65b9\u6848"],
            "forbidden": ["\u9a6c\u4e0a\u8865\u53d1", "\u76f4\u63a5\u9000\u6b3e"],
        },
        {
            "query": "\u4e70\u4e24\u4e2a\u80fd\u4e0d\u80fd\u4fbf\u5b9c\u70b9\uff0c\u6709\u6ca1\u6709\u4f18\u60e0\u5238",
            "intent": "promotion",
            "fact_type": "promotion_policy",
            "rule_key": "promotion_current_activity_check_v1",
            "must": ["\u6d3b\u52a8\u548c\u4f18\u60e0", "\u4e0b\u5355\u9875", "\u51c6\u786e\u53e3\u5f84"],
            "forbidden": ["\u4e00\u5b9a\u6709\u4f18\u60e0", "\u80af\u5b9a\u80fd\u4fbf\u5b9c"],
        },
        {
            "query": "\u8fd9\u4e2a\u600e\u4e48\u4e0b\u5355\uff0c\u89c4\u683c\u600e\u4e48\u9009",
            "intent": "order_assistance",
            "fact_type": "order_assistance",
            "rule_key": "purchase_assistance_spec_check_v1",
            "must": ["\u9009\u62e9\u89c4\u683c", "\u5c3a\u5bf8", "\u9875\u9762\u4fe1\u606f"],
            "forbidden": ["\u968f\u4fbf\u62cd", "\u4e00\u5b9a\u9002\u5408"],
        },
    ]

    for case in cases:
        rules = search_generic_service_rules(
            query=case["query"],
            intent=case["intent"],
            fact_type=case["fact_type"],
        )
        assert rules
        assert rules[0]["rule_key"] == case["rule_key"]
        assert rules[0]["source_type"] == "generic_rules"
        assert rules[0]["risk_level"] == "medium"
        reply = render_generic_service_reply(rules[0])
        for term in case["must"]:
            assert term in reply
        for term in case["forbidden"]:
            assert term not in reply


def test_generic_rule_aliases_cover_replay_fact_type_variants():
    from app.services.generic_service_rule_service import search_generic_service_rules

    aftersales_rules = search_generic_service_rules(
        query="这个坏了怎么处理",
        intent="aftersales",
        fact_type="aftersales",
    )
    gift_rules = search_generic_service_rules(
        query="什么赠品呀",
        intent="promotion",
        fact_type="gift_policy",
    )

    assert aftersales_rules
    assert aftersales_rules[0]["fact_type"] in {"aftersales_policy", "return_pickup"}
    assert gift_rules
    assert gift_rules[0]["rule_key"] == "promotion_current_activity_check_v1"


def test_render_generic_service_reply_uses_display_name_without_internal_terms():
    from app.services.generic_service_rule_service import (
        DEFAULT_GENERIC_SERVICE_RULES,
        normalize_rule,
        render_generic_service_reply,
    )

    reply = render_generic_service_reply(
        normalize_rule(DEFAULT_GENERIC_SERVICE_RULES[0]),
        product_name="英禾测试商品",
    )

    assert "英禾测试商品" in reply
    assert "{product_display}" not in reply
    assert "系统" not in reply
    assert "知识库" not in reply
    assert "RAG" not in reply
    assert "fact_type" not in reply


def test_unsafe_promise_terms_detects_customer_forbidden_claims():
    from app.services.generic_service_rule_service import unsafe_promise_terms

    terms = unsafe_promise_terms("这款0甲醛，绝对安全，完全无味，宝宝可以直接用")

    assert "0甲醛" in terms
    assert "绝对安全" in terms
    assert "完全无味" in terms
    assert "宝宝可以直接用" in terms


def test_unsafe_promise_terms_ignore_safe_negation_and_uncertainty():
    from app.services.generic_service_rule_service import unsafe_promise_terms

    assert unsafe_promise_terms("这不代表绝对安全，也不能确认是否0甲醛。") == []
    assert unsafe_promise_terms(
        "是否完全无味，目前没有相关资料可以确认。"
    ) == []
    assert unsafe_promise_terms(
        "是否完全无味，现有资料无法确认。"
    ) == []
    assert unsafe_promise_terms(
        "目前暂无法为您确认是否完全无味。"
    ) == []


def test_unsafe_promise_terms_keep_affirmative_claim_with_unrelated_caveat():
    from app.services.generic_service_rule_service import unsafe_promise_terms

    assert unsafe_promise_terms(
        "这款完全无味，目前没有补充资料。"
    ) == ["完全无味"]


def test_validate_rule_rejects_unsafe_customer_promise():
    from app.services.generic_service_rule_service import validate_rule

    errors = validate_rule({
        "rule_key": "unsafe_rule",
        "title": "不安全承诺",
        "content": "这款0甲醛，绝对安全，宝宝可以直接用。",
        "reply_template": "",
    })

    assert any(item.startswith("unsafe_promise_terms") for item in errors)


def test_generic_rule_to_fact_contract():
    from app.services.generic_service_rule_service import (
        DEFAULT_GENERIC_SERVICE_RULES,
        generic_rule_to_fact,
        normalize_rule,
    )

    fact = generic_rule_to_fact(normalize_rule(DEFAULT_GENERIC_SERVICE_RULES[0]))

    assert fact["source_type"] == "generic_rules"
    assert fact["evidence_allowed_for_direct_answer"] is True
    assert fact["evidence_allowed_for_exact_answer"] is False


def test_seed_generic_service_rules_dry_run_does_not_write_db():
    output_dir = Path(".pytest_tmp_codex") / "generic_seed"
    output_dir.mkdir(parents=True, exist_ok=True)
    output = output_dir / f"generic_rules_seed_report_{uuid.uuid4().hex}.json"
    proc = subprocess.run(
        [
            sys.executable,
            "scripts/seed_generic_service_rules.py",
            "--limit",
            "4",
            "--output",
            str(output),
        ],
        cwd=".",
        text=True,
        capture_output=True,
        check=True,
    )

    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["mode"] == "dry_run"
    assert report["dry_run"] == 4
    assert report["created"] == 0
    assert report["updated"] == 0
    assert "dry_run" in proc.stdout
    output.unlink(missing_ok=True)


def test_product_facts_keep_priority_over_generic_rules(generic_rule_db):
    from app.models.kb_tables import KBProduct
    from app.services.product_context_pack_service import build_product_context_pack

    db = generic_rule_db()
    try:
        db.add(KBProduct(
            i_id="TEST_GENERIC_PRIORITY_001",
            product_name="测试收纳柜",
            sku_list_json=json.dumps([{"sku_code": "TEST_GENERIC_PRIORITY_001B01S01"}], ensure_ascii=False),
            specs_json=json.dumps({
                "odor_note": "新品打开后可能有轻微包装气味，通风后会逐步散去。"
            }, ensure_ascii=False),
            status="published",
        ))
        db.commit()
    finally:
        db.close()

    pack = build_product_context_pack(
        {
            "intent": "product_question",
            "slots": {"sku_code": "TEST_GENERIC_PRIORITY_001B01S01"},
            "matched_product_name": "测试收纳柜",
        },
        query="这个有味道吗",
        allowed_source_types=["product_facts", "faq"],
        query_fact_type="odor",
    )

    assert pack["facts"]
    assert pack["facts"][0]["source_type"] == "product_facts"
    assert pack["evidence_pack"]["answerability"] == "direct_answer"
    assert pack["generic_rules"]


def test_odor_generic_fallback_when_product_card_missing_field(generic_rule_db):
    from app.models.kb_tables import KBProduct
    from app.services.product_context_pack_service import build_product_context_pack

    db = generic_rule_db()
    try:
        db.add(KBProduct(
            i_id="TEST_GENERIC_ODOR_001",
            product_name="测试床护栏",
            sku_list_json=json.dumps([{"sku_code": "TEST_GENERIC_ODOR_001B01S01"}], ensure_ascii=False),
            specs_json=json.dumps({"material": "PP"}, ensure_ascii=False),
            status="published",
        ))
        db.commit()
    finally:
        db.close()

    pack = build_product_context_pack(
        {
            "intent": "product_question",
            "slots": {"sku_code": "TEST_GENERIC_ODOR_001B01S01"},
            "matched_product_name": "测试床护栏",
        },
        query="这个有味儿吗，宝宝用",
        allowed_source_types=["product_facts", "faq"],
        query_fact_type="odor",
    )

    assert pack["facts"] == []
    assert pack["generic_rules"][0]["fact_type"] == "odor"
    assert pack["recommended_assets"] == []
    assert pack["evidence_pack"]["answerability"] == "generic_rule_fallback"
    assert pack["evidence_pack"]["matched_generic_rules"][0]["rule_key"] == "odor_new_product_ventilation_v1"


def test_generate_reply_uses_generic_rule_without_llm():
    from app.agent.nodes.generate_reply import generate_reply

    result = generate_reply({
        "intent": "product_question",
        "answer_mode": "policy_grounded_answer",
        "customer_message": "这个有味儿吗",
        "normalized_message": "这个有味儿吗",
        "query_fact_type": "odor",
        "matched_product_name": "测试床护栏",
        "product_context_pack": {
            "generic_rules": [
                {
                    "rule_key": "odor_new_product_ventilation_v1",
                    "title": "新品气味保守说明",
                    "fact_type": "odor",
                    "score": 12,
                    "reply_template": "亲～您担心{product_display}的气味问题很正常，建议先通风。明显刺鼻时先暂停使用并联系处理。",
                    "content": "新品气味保守说明。",
                }
            ],
            "evidence_pack": {
                "answerability": "generic_rule_fallback",
                "query_fact_type": "odor",
                "matched_generic_rules": [{"rule_key": "odor_new_product_ventilation_v1"}],
            },
        },
        "trace_steps": [],
    })

    assert result["llm_used"] is False
    assert result["generic_service_rule_used"]["rule_key"] == "odor_new_product_ventilation_v1"
    assert "测试床护栏" in result["suggested_reply"]
    assert "通风" in result["suggested_reply"]
    assert result["trace_steps"][-1]["generic_service_rule_used"]["rule_key"] == "odor_new_product_ventilation_v1"


def test_generate_reply_prefers_product_fact_over_same_fact_type_generic_rule():
    from app.agent.nodes.generate_reply import generate_reply

    result = generate_reply({
        "intent": "product_question",
        "customer_message": "这个有味道吗",
        "normalized_message": "这个有味道吗",
        "query_fact_type": "odor",
        "matched_product_name": "测试床护栏",
        "evidence": {
            "product_facts": [
                {
                    "source_type": "product_facts",
                    "fact_type": "odor",
                    "evidence_fact_type": "odor",
                    "chunk_text": "气味说明：这款商品出厂前已做通风处理，收到后短暂晾放即可。",
                    "evidence_allowed_for_direct_answer": True,
                    "direct_answer_allowed": True,
                }
            ],
        },
        "product_context_pack": {
            "generic_rules": [
                {
                    "rule_key": "odor_new_product_ventilation_v1",
                    "title": "新品气味保守说明",
                    "fact_type": "odor",
                    "score": 12,
                    "reply_template": "亲～这是通用气味话术，{product_display}先通风。",
                    "content": "通用气味话术。",
                }
            ],
        },
        "trace_steps": [],
    })

    assert "出厂前已做通风处理" in result["suggested_reply"]
    assert "通用气味话术" not in result["suggested_reply"]
    assert result.get("generic_service_rule_used") is None


def test_installation_query_can_recommend_media_when_material_exists(generic_rule_db):
    from app.models.kb_tables import KBMediaAsset, KBProduct
    from app.services.product_context_pack_service import build_product_context_pack

    db = generic_rule_db()
    try:
        product = KBProduct(
            i_id="TEST_GENERIC_MEDIA_001",
            product_name="测试收纳架",
            sku_list_json=json.dumps([{"sku_code": "TEST_GENERIC_MEDIA_001B01S01"}], ensure_ascii=False),
            specs_json=json.dumps({"material": "PP"}, ensure_ascii=False),
            status="published",
        )
        db.add(product)
        db.flush()
        asset = KBMediaAsset(
            product_id=product.id,
            i_id="TEST_GENERIC_MEDIA_001",
            sku_code="TEST_GENERIC_MEDIA_001B01S01",
            product_name="测试收纳架",
            asset_type="install_video",
            asset_title="安装教程视频",
            asset_url="https://example.com/install.mp4",
            status="approved",
            usable_for_agent=1,
            refresh_status="ok",
            match_confidence=0.9,
        )
        asset.set_source_raw({"auto_send_level": "auto", "answer_scenarios": ["installation"]})
        db.add(asset)
        db.commit()
    finally:
        db.close()

    pack = build_product_context_pack(
        {
            "intent": "product_question",
            "slots": {"sku_code": "TEST_GENERIC_MEDIA_001B01S01"},
            "matched_product_name": "测试收纳架",
        },
        query="这个有安装视频吗",
        allowed_source_types=["product_facts", "faq"],
        query_fact_type="installation",
    )

    assert pack["recommended_assets"]
    assert pack["recommended_assets"][0]["asset_type"] == "install_video"
    assert pack["evidence_pack"]["answerability"] in {"media_supported", "direct_answer"}


def test_platform_product_id_is_not_used_as_internal_iid(generic_rule_db):
    from app.models.kb_tables import KBProduct
    from app.services.product_context_pack_service import build_product_context_pack

    db = generic_rule_db()
    try:
        db.add(KBProduct(
            i_id="1046558780232",
            product_name="不应被平台ID命中的商品",
            specs_json=json.dumps({"material": "错误材质"}, ensure_ascii=False),
            status="published",
        ))
        db.commit()
    finally:
        db.close()

    pack = build_product_context_pack(
        {
            "intent": "product_question",
            "product_candidates": [{"type": "platform_product_id_candidate", "value": "1046558780232"}],
        },
        query="这个是什么材质",
        allowed_source_types=["product_facts", "faq"],
        query_fact_type="material",
    )

    assert pack["identity"]["i_id"] == ""
    assert pack["structured_profile"] == {}
    assert pack["facts"] == []


def test_final_answer_auditor_blocks_unsafe_product_promise():
    from app.services.final_answer_auditor import audit_final_answer

    audited = audit_final_answer(
        {
            "intent": "material_safety",
            "suggested_reply": "亲亲，这款0甲醛，宝宝可以直接用，绝对安全。",
            "requires_human_review": False,
            "evidence_debug": {"query_fact_type": "material"},
        },
        customer_message="这个宝宝用安全吗",
    )

    assert audited["requires_human_review"] is True
    assert any(issue.startswith("unsafe_customer_promise") for issue in audited["final_answer_audit"]["issues"])
    assert "0甲醛" not in audited["suggested_reply"]
    assert "宝宝可以直接用" not in audited["suggested_reply"]
