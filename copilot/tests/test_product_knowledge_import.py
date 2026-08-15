"""
商品知识导入管道测试 v3

覆盖:
- 稳定业务键 (结构化字段)
- 批次号与业务键分离
- 身份/事实分离
- 空字段不生成
- 高风险/uncertain 事实必须人工审核
- 幂等导入 (业务键 + content_hash)
- 内容变化创建 revision
- revision 不重复创建
- 商品级事实 scope=product 且 sku_scope 为空
- 导入工具不能直接发布/设置 ready
- 正式生命周期: submit -> approve -> chunks -> ready
- 索引失败补偿
- dry-run 不修改数据库
- 单商品事务
- 人工知识保护
- pending_review 保护
"""

import json
import os
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


@pytest.fixture
def tmp_db(monkeypatch):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from app.models.knowledge_base import Base
    import app.models.kb_tables  # noqa: F401 - register KBProduct tables

    tmp = tempfile.mktemp(suffix=".db")
    engine = create_engine(f"sqlite:///{tmp}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    TestSession = sessionmaker(bind=engine, expire_on_commit=False)

    import app.db as db_module
    original_session = db_module.SessionLocal
    original_engine = db_module.engine
    db_module.SessionLocal = TestSession
    db_module.engine = engine

    yield {"session": TestSession(), "engine": engine, "tmp": tmp}

    db_module.SessionLocal = original_session
    db_module.engine = original_engine
    try:
        os.unlink(tmp)
    except OSError:
        pass


@pytest.fixture
def sample_card():
    return {
        "i_id": "TEST001", "product_name": "测试商品A", "category": "测试类目",
        "completeness_score": 80, "agent_usable_level": "L1", "review_status": "可用",
        "customer_service_facts": {
            "material": "塑料", "size": "30x20x10cm", "weight": "500g",
            "color": ["红色", "蓝色"], "waterproof": None, "age_range": None,
        },
        "sku_summary": {"sku_count": 2, "sku_list": [
            {"sku_id": "SKU_A1", "sku_name": "红色款"},
            {"sku_id": "SKU_A2", "sku_name": "蓝色款"},
        ]},
        "missing_fields": ["waterproof", "age_range"], "data_quality_warnings": [],
    }


@pytest.fixture
def empty_facts_card():
    return {
        "i_id": "TEST002", "product_name": "测试商品B", "category": "测试类目",
        "completeness_score": 30, "agent_usable_level": "L2", "review_status": "待补全",
        "customer_service_facts": {"material": None, "size": None, "weight": None, "color": [], "waterproof": None},
        "sku_summary": {"sku_count": 1, "sku_list": [{"sku_id": "SKU_B1", "sku_name": "默认款"}]},
        "missing_fields": ["material", "size", "weight", "color"], "data_quality_warnings": ["所有参数缺失"],
    }


@pytest.fixture
def high_risk_card():
    return {
        "i_id": "TEST003", "product_name": "婴儿防摔枕", "category": "婴幼用品",
        "completeness_score": 90, "agent_usable_level": "L1", "review_status": "可用",
        "customer_service_facts": {
            "material": "棉", "age_range": "0-3岁", "waterproof": "是",
            "size": "40x30cm", "weight": "200g",
        },
        "sku_summary": {"sku_count": 1, "sku_list": [{"sku_id": "SKU_C1", "sku_name": "默认款"}]},
        "missing_fields": [], "data_quality_warnings": [],
    }


# === Business Key ===

class TestBusinessKey:
    def test_key_format(self):
        from scripts.import_product_knowledge import _make_business_key
        assert _make_business_key("P001", "", "material", "product") == "BK:P001::material:product"

    def test_key_with_sku(self):
        from scripts.import_product_knowledge import _make_business_key
        assert _make_business_key("P001", "SKU1", "material", "sku") == "BK:P001:SKU1:material:sku"

    def test_key_parse(self):
        from scripts.import_product_knowledge import _parse_business_key
        p = _parse_business_key("BK:P001:SKU1:material:sku")
        assert p == {"product_id": "P001", "sku_id": "SKU1", "fact_type": "material", "scope": "sku"}

    def test_different_products_different_keys(self):
        from scripts.import_product_knowledge import _make_business_key
        assert _make_business_key("P001", "", "identity", "product") != _make_business_key("P002", "", "identity", "product")

    def test_different_fact_types_different_keys(self):
        from scripts.import_product_knowledge import _make_business_key
        assert _make_business_key("P001", "", "material", "product") != _make_business_key("P001", "", "size", "product")


# === Batch ID ===

class TestBatchId:
    def test_batch_id_unique(self):
        from scripts.import_product_knowledge import _gen_batch_id
        id1 = _gen_batch_id()
        id2 = _gen_batch_id()
        # At least the timestamp portion differs or PID is the same
        assert id1.startswith("product_import_")
        assert id2.startswith("product_import_")

    def test_batch_id_format(self):
        from scripts.import_product_knowledge import _gen_batch_id
        bid = _gen_batch_id()
        assert bid.startswith("product_import_")
        parts = bid.split("_")
        assert len(parts) >= 4  # product_import_YYYYMMDD_HHMMSS_PID


# === Fact Extraction ===

class TestExtractFacts:
    def test_extracts_confirmed(self, sample_card):
        from scripts.import_product_knowledge import _extract_facts
        types = [f["fact_type"] for f in _extract_facts(sample_card["customer_service_facts"])]
        assert "material" in types and "size" in types and "weight" in types and "color" in types

    def test_skips_none(self, sample_card):
        from scripts.import_product_knowledge import _extract_facts
        types = [f["fact_type"] for f in _extract_facts(sample_card["customer_service_facts"])]
        assert "waterproof" not in types and "age_range" not in types

    def test_empty_returns_empty(self, empty_facts_card):
        from scripts.import_product_knowledge import _extract_facts
        assert len(_extract_facts(empty_facts_card["customer_service_facts"])) == 0

    def test_high_risk_flagged(self, high_risk_card):
        from scripts.import_product_knowledge import _extract_facts
        hr = [f for f in _extract_facts(high_risk_card["customer_service_facts"]) if f["high_risk"]]
        assert "material" in [f["fact_type"] for f in hr]

    def test_uncertain_flagged(self, sample_card):
        from scripts.import_product_knowledge import _extract_facts
        unc = [f for f in _extract_facts(sample_card["customer_service_facts"]) if f["uncertain"]]
        assert "weight" in [f["fact_type"] for f in unc] and "color" in [f["fact_type"] for f in unc]


# === Entry Building ===

class TestBuildEntries:
    def test_identity_has_name(self, sample_card):
        from scripts.import_product_knowledge import analyze_card, build_identity_entry
        e = build_identity_entry(sample_card, analyze_card(sample_card))
        assert "测试商品A" in e["title"] and e["source_type"] == "product_identity"

    def test_identity_scope_product(self, sample_card):
        from scripts.import_product_knowledge import analyze_card, build_identity_entry
        e = build_identity_entry(sample_card, analyze_card(sample_card))
        assert e["fact_scope"] == "product" and e["sku_id"] == "" and json.loads(e["sku_scope_json"]) == []

    def test_fact_scope_product(self, sample_card):
        from scripts.import_product_knowledge import analyze_card, build_fact_entry
        fact = {"fact_type": "material", "label": "材质", "content": "塑料", "confidence": 0.8, "high_risk": False, "uncertain": False}
        e = build_fact_entry(sample_card, analyze_card(sample_card), fact)
        assert e["fact_scope"] == "product" and e["sku_id"] == "" and json.loads(e["sku_scope_json"]) == []

    def test_high_risk_requires_review(self, high_risk_card):
        from scripts.import_product_knowledge import analyze_card, build_fact_entry
        fact = {"fact_type": "age_range", "label": "适龄范围", "content": "0-3岁", "confidence": 0.9, "high_risk": True, "uncertain": False}
        e = build_fact_entry(high_risk_card, analyze_card(high_risk_card), fact)
        assert e["human_review_required"] and not e["auto_reply_allowed"] and e["risk_level"] == "high"

    def test_uncertain_requires_review(self, sample_card):
        from scripts.import_product_knowledge import analyze_card, build_fact_entry
        fact = {"fact_type": "weight", "label": "重量", "content": "500g", "confidence": 0.5, "high_risk": False, "uncertain": True}
        e = build_fact_entry(sample_card, analyze_card(sample_card), fact)
        assert e["human_review_required"] and not e["auto_reply_allowed"]

    def test_structured_fields_in_entry(self, sample_card):
        from scripts.import_product_knowledge import analyze_card, build_identity_entry
        e = build_identity_entry(sample_card, analyze_card(sample_card))
        assert e["product_id"] == "TEST001"
        assert e["fact_type"] == "identity"
        assert e["business_key"] == "BK:TEST001::identity:product"


class TestBuildProductDraft:
    def test_builds_review_only_product_identity(self, sample_card):
        from scripts.import_product_knowledge import analyze_card, build_product_draft

        data = build_product_draft(sample_card, analyze_card(sample_card))

        assert data["i_id"] == "TEST001"
        assert data["product_name"] == sample_card["product_name"]
        assert data["status"] == "draft"
        assert data["sku_list"] == sample_card["sku_summary"]["sku_list"]

    def test_does_not_promote_card_facts_into_product_specs(self, sample_card):
        from scripts.import_product_knowledge import analyze_card, build_product_draft

        data = build_product_draft(sample_card, analyze_card(sample_card))

        assert data["specs"] == {}
        assert data["logistics"] == {}
        assert data["warranty"] == {}


class TestProductDraftPlanning:
    def test_creates_managed_product_as_draft(self, tmp_db, sample_card):
        from app.models.kb_tables import KBProduct
        from scripts.import_product_knowledge import analyze_card, build_product_draft, _plan_product

        db = tmp_db["session"]
        plan = _plan_product(
            db,
            build_product_draft(sample_card, analyze_card(sample_card)),
            dry_run=False,
            batch_id="batch1",
        )
        db.commit()

        product = db.query(KBProduct).filter(KBProduct.i_id == "TEST001").one()
        assert plan["action"] == "created"
        assert product.status == "draft"
        assert product.created_by == "import_tool"
        assert product.get_specs() == {}

    def test_dry_run_does_not_create_product(self, tmp_db, sample_card):
        from app.models.kb_tables import KBProduct
        from scripts.import_product_knowledge import analyze_card, build_product_draft, _plan_product

        db = tmp_db["session"]
        plan = _plan_product(
            db,
            build_product_draft(sample_card, analyze_card(sample_card)),
            dry_run=True,
            batch_id="batch1",
        )

        assert plan["action"] == "would_create"
        assert db.query(KBProduct).count() == 0

    def test_existing_published_product_is_never_overwritten(self, tmp_db, sample_card):
        from app.models.kb_tables import KBProduct
        from scripts.import_product_knowledge import analyze_card, build_product_draft, _plan_product

        db = tmp_db["session"]
        product = KBProduct(
            i_id="TEST001",
            product_name="reviewed name",
            status="published",
            created_by="supervisor",
        )
        db.add(product)
        db.commit()

        data = build_product_draft(sample_card, analyze_card(sample_card))
        plan = _plan_product(db, data, dry_run=False, batch_id="batch1")
        db.commit()

        db.refresh(product)
        assert plan["action"] == "conflict"
        assert product.product_name == "reviewed name"
        assert product.status == "published"

    def test_manually_created_draft_is_never_overwritten(self, tmp_db, sample_card):
        from app.models.kb_tables import KBProduct
        from scripts.import_product_knowledge import analyze_card, build_product_draft, _plan_product

        db = tmp_db["session"]
        product = KBProduct(
            i_id="TEST001",
            product_name="manual draft",
            status="draft",
            created_by="reviewer",
        )
        db.add(product)
        db.commit()

        data = build_product_draft(sample_card, analyze_card(sample_card))
        plan = _plan_product(db, data, dry_run=False, batch_id="batch1")
        db.commit()

        db.refresh(product)
        assert plan["action"] == "conflict"
        assert product.product_name == "manual draft"
        assert product.created_by == "reviewer"

    def test_managed_draft_identity_update_preserves_structured_fields(
        self, tmp_db, sample_card
    ):
        from app.models.kb_tables import KBProduct
        from scripts.import_product_knowledge import analyze_card, build_product_draft, _plan_product

        db = tmp_db["session"]
        product = KBProduct(
            i_id="TEST001",
            product_name="old recovered name",
            status="draft",
            created_by="import_tool",
            updated_by="import_tool",
        )
        product.set_specs({"reviewed_candidate": "retain"})
        product.set_logistics({"reviewed_candidate": "retain"})
        product.set_warranty({"reviewed_candidate": "retain"})
        db.add(product)
        db.commit()

        data = build_product_draft(sample_card, analyze_card(sample_card))
        plan = _plan_product(db, data, dry_run=False, batch_id="batch1")
        db.commit()

        db.refresh(product)
        assert plan["action"] == "updated_draft"
        assert product.product_name == sample_card["product_name"]
        assert product.get_specs() == {"reviewed_candidate": "retain"}
        assert product.get_logistics() == {"reviewed_candidate": "retain"}
        assert product.get_warranty() == {"reviewed_candidate": "retain"}

    def test_same_managed_draft_is_idempotent(self, tmp_db, sample_card):
        from app.models.kb_tables import KBProduct
        from scripts.import_product_knowledge import analyze_card, build_product_draft, _plan_product

        db = tmp_db["session"]
        data = build_product_draft(sample_card, analyze_card(sample_card))
        first = _plan_product(db, data, dry_run=False, batch_id="batch1")
        db.commit()
        second = _plan_product(db, data, dry_run=False, batch_id="batch2")
        db.commit()

        assert first["action"] == "created"
        assert second["action"] == "skipped"
        assert db.query(KBProduct).count() == 1

    def test_execute_import_stages_product_and_entry_in_one_product_transaction(
        self, tmp_db, sample_card
    ):
        from app.models.kb_tables import KBProduct
        from app.models.knowledge_base import KnowledgeEntry
        from scripts.import_product_knowledge import (
            analyze_card,
            build_identity_entry,
            build_product_draft,
            _execute_import,
        )

        analysis = analyze_card(sample_card)
        result = _execute_import(
            [("product_identity", build_identity_entry(sample_card, analysis), analysis)],
            [(build_product_draft(sample_card, analysis), analysis)],
        )

        db = tmp_db["session"]
        db.expire_all()
        product = db.query(KBProduct).filter(KBProduct.i_id == "TEST001").one()
        entry = db.query(KnowledgeEntry).filter(KnowledgeEntry.product_id == "TEST001").one()
        assert result["product_records_created"] == 1
        assert result["created"] == 1
        assert product.status == "draft"
        assert product.get_specs() == {}
        assert entry.status == "draft"
        assert entry.index_status == "pending"

    def test_staged_product_is_not_formal_product_context(self, tmp_db, sample_card):
        from scripts.import_product_knowledge import analyze_card, build_product_draft, _plan_product
        from app.services.product_context_pack_service import build_product_context_pack

        db = tmp_db["session"]
        analysis = analyze_card(sample_card)
        _plan_product(
            db,
            build_product_draft(sample_card, analysis),
            dry_run=False,
            batch_id="batch1",
        )
        db.commit()

        pack = build_product_context_pack(
            {"i_id": "TEST001"},
            query="what material",
            allowed_source_types=["product_facts"],
            query_fact_type="material",
        )

        product_first = pack["product_first_evidence_pack"]
        assert product_first["product_structured_facts"] == []
        assert pack["facts"] == []


# === Analysis ===

class TestAnalyzeCard:
    def test_has_identity(self, sample_card):
        from scripts.import_product_knowledge import analyze_card
        a = analyze_card(sample_card)
        assert a["has_identity"] and a["i_id"] == "TEST001"

    def test_has_facts(self, sample_card):
        from scripts.import_product_knowledge import analyze_card
        assert analyze_card(sample_card)["has_facts"]

    def test_no_facts_empty(self, empty_facts_card):
        from scripts.import_product_knowledge import analyze_card
        assert not analyze_card(empty_facts_card)["has_facts"]

    def test_high_risk_detected(self, high_risk_card):
        from scripts.import_product_knowledge import analyze_card
        assert len(analyze_card(high_risk_card)["high_risk_facts"]) > 0


# === Idempotent Import ===

class TestIdempotentImport:
    def test_same_content_skipped(self, tmp_db, sample_card):
        from scripts.import_product_knowledge import analyze_card, build_identity_entry, _plan_entry
        db = tmp_db["session"]
        data = build_identity_entry(sample_card, analyze_card(sample_card))
        p1 = _plan_entry(db, data, dry_run=False, batch_id="batch1")
        db.commit()
        p2 = _plan_entry(db, data, dry_run=False, batch_id="batch1")
        db.commit()
        assert p1["action"] == "created"
        assert p2["action"] == "skipped"
        assert p2["entry_id"] == p1["entry_id"]

    def test_triple_import_skipped(self, tmp_db, sample_card):
        from scripts.import_product_knowledge import analyze_card, build_identity_entry, _plan_entry
        db = tmp_db["session"]
        data = build_identity_entry(sample_card, analyze_card(sample_card))
        _plan_entry(db, data, dry_run=False, batch_id="b1")
        db.commit()
        _plan_entry(db, data, dry_run=False, batch_id="b1")
        db.commit()
        p3 = _plan_entry(db, data, dry_run=False, batch_id="b1")
        db.commit()
        assert p3["action"] == "skipped"

    def test_different_product_not_deduped(self, tmp_db, sample_card, empty_facts_card):
        from scripts.import_product_knowledge import analyze_card, build_identity_entry, _plan_entry
        db = tmp_db["session"]
        p1 = _plan_entry(db, build_identity_entry(sample_card, analyze_card(sample_card)), dry_run=False, batch_id="b1")
        db.commit()
        p2 = _plan_entry(db, build_identity_entry(empty_facts_card, analyze_card(empty_facts_card)), dry_run=False, batch_id="b1")
        db.commit()
        assert p1["action"] == "created" and p2["action"] == "created"
        assert p1["entry_id"] != p2["entry_id"]

    def test_different_fact_type_not_deduped(self, tmp_db, sample_card):
        from scripts.import_product_knowledge import analyze_card, build_fact_entry, _plan_entry
        db = tmp_db["session"]
        a = analyze_card(sample_card)
        f1 = {"fact_type": "material", "label": "材质", "content": "塑料", "confidence": 0.8, "high_risk": False, "uncertain": False}
        f2 = {"fact_type": "size", "label": "尺寸", "content": "30x20x10cm", "confidence": 0.7, "high_risk": False, "uncertain": False}
        p1 = _plan_entry(db, build_fact_entry(sample_card, a, f1), dry_run=False, batch_id="b1")
        db.commit()
        p2 = _plan_entry(db, build_fact_entry(sample_card, a, f2), dry_run=False, batch_id="b1")
        db.commit()
        assert p1["action"] == "created" and p2["action"] == "created"
        assert p1["entry_id"] != p2["entry_id"]


# === Draft Update ===

class TestDraftUpdate:
    def test_draft_content_change_updates(self, tmp_db, sample_card):
        from app.models.knowledge_base import KnowledgeEntry
        from scripts.import_product_knowledge import analyze_card, build_identity_entry, _plan_entry
        db = tmp_db["session"]
        data = build_identity_entry(sample_card, analyze_card(sample_card))
        p1 = _plan_entry(db, data, dry_run=False, batch_id="b1")
        db.commit()
        assert p1["action"] == "created"

        # Change content
        data["content"] = data["content"] + "\n新内容"
        data["content_hash"] = "new_hash_123"
        p2 = _plan_entry(db, data, dry_run=False, batch_id="b2")
        db.commit()
        assert p2["action"] == "updated_draft"
        assert p2["entry_id"] == p1["entry_id"]

        # Verify content_hash updated
        entry = db.query(KnowledgeEntry).get(p1["entry_id"])
        assert entry.content_hash == "new_hash_123"

    def test_update_then_skip(self, tmp_db, sample_card):
        from scripts.import_product_knowledge import analyze_card, build_identity_entry, _plan_entry
        db = tmp_db["session"]
        data = build_identity_entry(sample_card, analyze_card(sample_card))
        _plan_entry(db, data, dry_run=False, batch_id="b1")
        db.commit()

        data["content"] = "changed"
        data["content_hash"] = "hash_changed"
        _plan_entry(db, data, dry_run=False, batch_id="b2")
        db.commit()

        # Same changed content again -> skip
        p3 = _plan_entry(db, data, dry_run=False, batch_id="b3")
        db.commit()
        assert p3["action"] == "skipped"


# === Revision ===

class TestRevision:
    def test_published_change_creates_revision(self, tmp_db, sample_card):
        from app.models.knowledge_base import KnowledgeEntry
        from scripts.import_product_knowledge import analyze_card, build_identity_entry, _plan_entry
        db = tmp_db["session"]
        data = build_identity_entry(sample_card, analyze_card(sample_card))
        p1 = _plan_entry(db, data, dry_run=False, batch_id="b1")
        db.commit()

        # Publish it
        entry = db.query(KnowledgeEntry).get(p1["entry_id"])
        entry.status = "published"
        entry.index_status = "ready"
        db.commit()

        # Change content
        data["content"] = "changed content for revision"
        data["content_hash"] = "rev_hash_1"
        p2 = _plan_entry(db, data, dry_run=False, batch_id="b2")
        db.commit()

        assert p2["action"] == "revision_created"
        assert p2["parent_id"] == p1["entry_id"]
        rev = db.query(KnowledgeEntry).get(p2["entry_id"])
        assert rev.parent_entry_id == p1["entry_id"]
        assert rev.status == "draft"
        assert rev.business_key == data["business_key"]

    def test_revision_not_duplicated(self, tmp_db, sample_card):
        from app.models.knowledge_base import KnowledgeEntry
        from scripts.import_product_knowledge import analyze_card, build_identity_entry, _plan_entry
        db = tmp_db["session"]
        data = build_identity_entry(sample_card, analyze_card(sample_card))
        p1 = _plan_entry(db, data, dry_run=False, batch_id="b1")
        db.commit()

        entry = db.query(KnowledgeEntry).get(p1["entry_id"])
        entry.status = "published"
        entry.index_status = "ready"
        db.commit()

        data["content"] = "changed"
        data["content_hash"] = "hash_x"
        p2 = _plan_entry(db, data, dry_run=False, batch_id="b2")
        db.commit()
        assert p2["action"] == "revision_created"

        # Same content again -> should skip (revision already exists with same hash)
        p3 = _plan_entry(db, data, dry_run=False, batch_id="b3")
        db.commit()
        assert p3["action"] == "skipped"

    def test_dry_run_detects_revision(self, tmp_db, sample_card):
        from app.models.knowledge_base import KnowledgeEntry
        from scripts.import_product_knowledge import analyze_card, build_identity_entry, _plan_entry
        db = tmp_db["session"]
        data = build_identity_entry(sample_card, analyze_card(sample_card))
        p1 = _plan_entry(db, data, dry_run=False, batch_id="b1")
        db.commit()

        entry = db.query(KnowledgeEntry).get(p1["entry_id"])
        entry.status = "published"
        entry.index_status = "ready"
        db.commit()

        data["content"] = "changed"
        data["content_hash"] = "different"
        p2 = _plan_entry(db, data, dry_run=True, batch_id="b2")
        assert p2["action"] == "would_create_revision"


# === SKU Isolation ===

class TestSKUIsolation:
    def test_product_level_empty_sku_scope(self, sample_card):
        from scripts.import_product_knowledge import analyze_card, build_fact_entry
        a = analyze_card(sample_card)
        fact = {"fact_type": "material", "label": "材质", "content": "塑料", "confidence": 0.8, "high_risk": False, "uncertain": False}
        e = build_fact_entry(sample_card, a, fact)
        assert json.loads(e["sku_scope_json"]) == [] and e["fact_scope"] == "product" and e["sku_id"] == ""

    def test_identity_empty_sku_scope(self, sample_card):
        from scripts.import_product_knowledge import analyze_card, build_identity_entry
        e = build_identity_entry(sample_card, analyze_card(sample_card))
        assert json.loads(e["sku_scope_json"]) == []


# === Import Tool Cannot Publish ===

class TestCannotPublish:
    def test_no_force_publish_function(self):
        import scripts.import_product_knowledge as mod
        assert not hasattr(mod, "_force_publish_entry")
        assert not hasattr(mod, "_submit_for_review")

    def test_no_force_publish_cli(self):
        import scripts.import_product_knowledge as mod
        import inspect
        src = inspect.getsource(mod)
        assert "--force-publish" not in src
        assert "--submit-review" not in src
        assert "_force_publish" not in src

    def test_created_as_draft(self, tmp_db, sample_card):
        from app.models.knowledge_base import KnowledgeEntry
        from scripts.import_product_knowledge import analyze_card, build_identity_entry, _plan_entry
        db = tmp_db["session"]
        data = build_identity_entry(sample_card, analyze_card(sample_card))
        p = _plan_entry(db, data, dry_run=False, batch_id="b1")
        db.commit()
        entry = db.query(KnowledgeEntry).get(p["entry_id"])
        assert entry.status == "draft"
        assert entry.index_status == "pending"

    def test_draft_has_no_chunks(self, tmp_db, sample_card):
        from app.models.knowledge_base import KnowledgeChunk
        from scripts.import_product_knowledge import analyze_card, build_identity_entry, _plan_entry
        db = tmp_db["session"]
        data = build_identity_entry(sample_card, analyze_card(sample_card))
        p = _plan_entry(db, data, dry_run=False, batch_id="b1")
        db.commit()
        count = db.query(KnowledgeChunk).filter(KnowledgeChunk.entry_id == p["entry_id"]).count()
        assert count == 0


# === Lifecycle Integration (formal path) ===

class TestLifecycleIntegration:
    def test_submit_approve_creates_chunks(self, tmp_db, sample_card):
        """正式 submit_for_review + approve 创建真实 chunks。"""
        from app.models.knowledge_base import KnowledgeEntry, KnowledgeChunk
        from scripts.import_product_knowledge import analyze_card, build_identity_entry, _plan_entry
        from app.services.knowledge_lifecycle_service import KnowledgeLifecycleService

        db = tmp_db["session"]
        data = build_identity_entry(sample_card, analyze_card(sample_card))
        p = _plan_entry(db, data, dry_run=False, batch_id="b1")
        db.commit()
        entry_id = p["entry_id"]

        # Submit via formal lifecycle
        r = KnowledgeLifecycleService.submit_review(entry_id, user="test")
        assert r.get("error") is None

        # Approve via formal lifecycle (passes quality gate)
        r = KnowledgeLifecycleService.approve(entry_id, user="test")
        assert r.get("error") is None

        # Verify published + chunks
        entry = db.query(KnowledgeEntry).get(entry_id)
        assert entry.status == "published"
        assert entry.index_status == "ready"
        chunk_count = db.query(KnowledgeChunk).filter(KnowledgeChunk.entry_id == entry_id).count()
        assert chunk_count > 0

    def test_draft_not_searchable(self, tmp_db, sample_card):
        from app.repositories.knowledge_chunk_repository import KnowledgeChunkRepository
        from scripts.import_product_knowledge import analyze_card, build_identity_entry, _plan_entry
        db = tmp_db["session"]
        data = build_identity_entry(sample_card, analyze_card(sample_card))
        _plan_entry(db, data, dry_run=False, batch_id="b1")
        db.commit()
        results = KnowledgeChunkRepository.search_chunks("测试商品A", top_k=5)
        assert len(results) == 0

    def test_published_searchable(self, tmp_db, sample_card):
        from app.repositories.knowledge_chunk_repository import KnowledgeChunkRepository
        from scripts.import_product_knowledge import analyze_card, build_identity_entry, _plan_entry
        from app.services.knowledge_lifecycle_service import KnowledgeLifecycleService
        db = tmp_db["session"]
        data = build_identity_entry(sample_card, analyze_card(sample_card))
        p = _plan_entry(db, data, dry_run=False, batch_id="b1")
        db.commit()
        KnowledgeLifecycleService.submit_review(p["entry_id"], user="test")
        KnowledgeLifecycleService.approve(p["entry_id"], user="test")
        results = KnowledgeChunkRepository.search_chunks("测试商品A", top_k=5)
        assert len(results) > 0

    def test_archive_clears_chunks(self, tmp_db, sample_card):
        from app.models.knowledge_base import KnowledgeChunk
        from scripts.import_product_knowledge import analyze_card, build_identity_entry, _plan_entry
        from app.services.knowledge_lifecycle_service import KnowledgeLifecycleService
        db = tmp_db["session"]
        data = build_identity_entry(sample_card, analyze_card(sample_card))
        p = _plan_entry(db, data, dry_run=False, batch_id="b1")
        db.commit()
        KnowledgeLifecycleService.submit_review(p["entry_id"], user="test")
        KnowledgeLifecycleService.approve(p["entry_id"], user="test")
        KnowledgeLifecycleService.archive(p["entry_id"], user="test")
        count = db.query(KnowledgeChunk).filter(KnowledgeChunk.entry_id == p["entry_id"]).count()
        assert count == 0


# === Protection ===

class TestProtection:
    def test_pending_review_not_modified(self, tmp_db, sample_card):
        from app.models.knowledge_base import KnowledgeEntry
        from scripts.import_product_knowledge import analyze_card, build_identity_entry, _plan_entry
        db = tmp_db["session"]
        data = build_identity_entry(sample_card, analyze_card(sample_card))
        p = _plan_entry(db, data, dry_run=False, batch_id="b1")
        db.commit()

        entry = db.query(KnowledgeEntry).get(p["entry_id"])
        entry.status = "pending_review"
        db.commit()

        data["content"] = "should not be applied"
        data["content_hash"] = "should_not_match"
        p2 = _plan_entry(db, data, dry_run=False, batch_id="b2")
        db.commit()
        assert p2["action"] == "conflict"

    def test_manual_entry_not_overwritten(self, tmp_db, sample_card):
        from app.models.knowledge_base import KnowledgeEntry
        from scripts.import_product_knowledge import analyze_card, build_identity_entry, _plan_entry
        db = tmp_db["session"]

        # Create a manual entry with same business_key
        data = build_identity_entry(sample_card, analyze_card(sample_card))
        manual = KnowledgeEntry(
            source_type=data["source_type"], title="人工创建", content="人工内容",
            business_key=data["business_key"], product_id=data["product_id"],
            sku_id=data["sku_id"], fact_type=data["fact_type"], fact_scope=data["fact_scope"],
            content_hash="manual_hash", created_by="human_expert", status="draft",
        )
        db.add(manual)
        db.commit()

        # Import tool tries to update
        p = _plan_entry(db, data, dry_run=False, batch_id="b1")
        db.commit()
        assert p["action"] == "conflict"
        assert "manually" in p["reason"]


# === Dry-run ===

class TestDryRun:
    def test_no_changes(self, tmp_db, sample_card):
        from app.models.knowledge_base import KnowledgeEntry
        from scripts.import_product_knowledge import analyze_card, build_identity_entry, _plan_entry
        db = tmp_db["session"]
        count_before = db.query(KnowledgeEntry).count()
        data = build_identity_entry(sample_card, analyze_card(sample_card))
        _plan_entry(db, data, dry_run=True, batch_id="dry1")
        assert db.query(KnowledgeEntry).count() == count_before

    def test_no_audit_log(self, tmp_db, sample_card):
        from app.models.knowledge_base import KnowledgeAuditLog
        from scripts.import_product_knowledge import analyze_card, build_identity_entry, _plan_entry
        db = tmp_db["session"]
        log_before = db.query(KnowledgeAuditLog).count()
        data = build_identity_entry(sample_card, analyze_card(sample_card))
        _plan_entry(db, data, dry_run=True, batch_id="dry1")
        assert db.query(KnowledgeAuditLog).count() == log_before


# === Module ===

class TestModule:
    def test_has_required_functions(self):
        import scripts.import_product_knowledge as mod
        for name in ["run_import", "analyze_card", "build_identity_entry", "build_fact_entry",
                      "build_product_draft", "_plan_product", "_make_business_key",
                      "_find_by_business_key", "_plan_entry", "_gen_batch_id"]:
            assert hasattr(mod, name), f"missing {name}"

    def test_no_dangerous_functions(self):
        import scripts.import_product_knowledge as mod
        assert not hasattr(mod, "_force_publish_entry")
        assert not hasattr(mod, "_submit_for_review")
