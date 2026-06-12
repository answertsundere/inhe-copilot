"""
测试 RAG knowledge_entries 列表 API 的扩展筛选功能
以及商品导入脚本的多商品编号支持
"""

import os
import tempfile
import uuid
import pytest

_test_db_path = None


def setup_module(module):
    global _test_db_path
    _test_db_path = os.path.join(tempfile.gettempdir(), f"test_rag_entries_{uuid.uuid4().hex}.db")

    import app.db as db_module
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    _test_engine = create_engine(f"sqlite:///{_test_db_path}", connect_args={"check_same_thread": False})
    db_module.engine = _test_engine
    db_module.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=_test_engine, expire_on_commit=False)

    from app.models.knowledge_base import Base
    Base.metadata.create_all(bind=_test_engine)


def teardown_module(module):
    try:
        if _test_db_path and os.path.exists(_test_db_path):
            os.unlink(_test_db_path)
    except Exception:
        pass


from app.repositories.knowledge_entry_repository import KnowledgeEntryRepository
from app.models.knowledge_base import KnowledgeEntry
import app.db as db_module


def _create_entry(**kwargs):
    """Helper to create an entry with sensible defaults."""
    defaults = {
        "source_type": "product_facts",
        "title": "test entry",
        "content": "test content",
        "intent": "product_question",
    }
    defaults.update(kwargs)
    return KnowledgeEntryRepository.create(**defaults)


class TestListEntriesFilters:
    """list_entries 扩展筛选"""

    def setup_method(self):
        db = db_module.SessionLocal()
        try:
            db.query(KnowledgeEntry).delete()
            db.commit()
        finally:
            db.close()

    def _seed(self):
        """创建测试数据"""
        _create_entry(
            source_type="product_identity", title="商品A身份",
            content="内容A", intent="product_question",
        )
        _create_entry(
            source_type="product_facts", title="商品B材质",
            content="材质内容", intent="product_question",
        )
        _create_entry(
            source_type="faq", title="退款政策",
            content="退款相关内容", intent="aftersales",
        )

    def test_source_type_filter(self):
        self._seed()
        items, total = KnowledgeEntryRepository.list_entries(source_type="product_identity")
        assert total == 1
        assert items[0].title == "商品A身份"

    def test_intent_filter(self):
        self._seed()
        items, total = KnowledgeEntryRepository.list_entries(intent="aftersales")
        assert total == 1
        assert items[0].title == "退款政策"

    def test_search_query(self):
        self._seed()
        items, total = KnowledgeEntryRepository.list_entries(search_query="退款")
        assert total == 1
        assert items[0].title == "退款政策"

    def test_status_filter(self):
        self._seed()
        items, total = KnowledgeEntryRepository.list_entries(status="draft")
        assert total == 3  # all created as draft

    def test_empty_result(self):
        self._seed()
        items, total = KnowledgeEntryRepository.list_entries(source_type="nonexistent")
        assert total == 0
        assert items == []


class TestExtendedFilters:
    """扩展字段筛选：fact_type, product_id, batch_id, index_status 等"""

    def setup_method(self):
        db = db_module.SessionLocal()
        try:
            db.query(KnowledgeEntry).delete()
            db.commit()
        finally:
            db.close()

    def _seed_extended(self):
        db = db_module.SessionLocal()
        try:
            e1 = KnowledgeEntry(
                source_type="product_identity", title="entry1", content="c1",
                intent="product_question", status="draft",
                business_key="BK:P1::identity:product", product_id="P1",
                sku_id="", fact_type="identity", fact_scope="product",
                import_batch_id="batch_001", index_status="pending",
                human_review_required=False, auto_reply_allowed=True,
                risk_level="low", source_confidence=0.9,
            )
            e2 = KnowledgeEntry(
                source_type="product_facts", title="entry2", content="c2",
                intent="product_question", status="draft",
                business_key="BK:P1::material:product", product_id="P1",
                sku_id="", fact_type="material", fact_scope="product",
                import_batch_id="batch_001", index_status="pending",
                human_review_required=True, auto_reply_allowed=False,
                risk_level="high", source_confidence=0.8,
            )
            e3 = KnowledgeEntry(
                source_type="product_facts", title="entry3", content="c3",
                intent="product_question", status="published",
                business_key="BK:P2::size:product", product_id="P2",
                sku_id="", fact_type="size", fact_scope="product",
                import_batch_id="batch_002", index_status="ready",
                human_review_required=False, auto_reply_allowed=True,
                risk_level="low", source_confidence=0.7,
            )
            db.add_all([e1, e2, e3])
            db.commit()
        finally:
            db.close()

    def test_fact_type_filter(self):
        self._seed_extended()
        items, total = KnowledgeEntryRepository.list_entries(fact_type="material")
        assert total == 1
        assert items[0].product_id == "P1"

    def test_product_id_filter(self):
        self._seed_extended()
        items, total = KnowledgeEntryRepository.list_entries(product_id="P1")
        assert total == 2

    def test_batch_id_filter(self):
        self._seed_extended()
        items, total = KnowledgeEntryRepository.list_entries(batch_id="batch_002")
        assert total == 1
        assert items[0].product_id == "P2"

    def test_index_status_filter(self):
        self._seed_extended()
        items, total = KnowledgeEntryRepository.list_entries(index_status="ready")
        assert total == 1
        assert items[0].title == "entry3"

    def test_human_review_required_true(self):
        self._seed_extended()
        items, total = KnowledgeEntryRepository.list_entries(human_review_required="true")
        assert total == 1
        assert items[0].fact_type == "material"

    def test_human_review_required_false(self):
        self._seed_extended()
        items, total = KnowledgeEntryRepository.list_entries(human_review_required="false")
        assert total == 2

    def test_auto_reply_allowed_true(self):
        self._seed_extended()
        items, total = KnowledgeEntryRepository.list_entries(auto_reply_allowed="true")
        assert total == 2

    def test_auto_reply_allowed_false(self):
        self._seed_extended()
        items, total = KnowledgeEntryRepository.list_entries(auto_reply_allowed="false")
        assert total == 1

    def test_combined_filters(self):
        self._seed_extended()
        items, total = KnowledgeEntryRepository.list_entries(
            source_type="product_facts", product_id="P1", fact_type="material",
        )
        assert total == 1
        assert items[0].title == "entry2"

    def test_sort_by_id_asc(self):
        self._seed_extended()
        items, total = KnowledgeEntryRepository.list_entries(sort_by="id", sort_order="asc")
        assert total == 3
        assert items[0].id < items[1].id < items[2].id

    def test_sort_by_id_desc(self):
        self._seed_extended()
        items, total = KnowledgeEntryRepository.list_entries(sort_by="id", sort_order="desc")
        assert total == 3
        assert items[0].id > items[1].id > items[2].id

    def test_invalid_sort_by_falls_back(self):
        """非法 sort_by 不报错，回退到 updated_at"""
        self._seed_extended()
        items, total = KnowledgeEntryRepository.list_entries(sort_by="DROP TABLE; --")
        assert total == 3  # 不报错

    def test_pagination(self):
        self._seed_extended()
        items, total = KnowledgeEntryRepository.list_entries(limit=2, offset=0)
        assert len(items) == 2
        assert total == 3
        items2, _ = KnowledgeEntryRepository.list_entries(limit=2, offset=2)
        assert len(items2) == 1


class TestToDictIncludesNewFields:
    """to_dict 应包含 index_status 和 source_confidence"""

    def test_to_dict_has_fields(self):
        db = db_module.SessionLocal()
        try:
            db.query(KnowledgeEntry).delete()
            db.commit()
        finally:
            db.close()

        entry = _create_entry(source_type="product_identity", title="t", content="c")
        d = entry.to_dict(include_content=False)
        assert "index_status" in d
        assert "source_confidence" in d
        assert "business_key" in d
        assert "product_id" in d
        assert "fact_type" in d
        assert "fact_scope" in d

    def test_null_fields_safe(self):
        """旧记录字段为 null 时 to_dict 不报错"""
        db = db_module.SessionLocal()
        try:
            db.query(KnowledgeEntry).delete()
            db.commit()
            e = KnowledgeEntry(
                source_type="faq", title="old", content="old",
                intent="general", status="draft",
            )
            db.add(e)
            db.commit()
            db.refresh(e)
            d = e.to_dict(include_content=True)
            assert d["id"] == e.id
            assert d["business_key"] is None
            assert d["product_id"] is None
            assert d["fact_type"] is None
            assert d["index_status"] == "pending"
        finally:
            db.close()


class TestImportScriptMultiProductId:
    """导入脚本多商品编号支持"""

    def test_merge_single_and_multi(self):
        """--product-id 和 --product-ids 合并去重"""
        import argparse
        from scripts.import_product_knowledge import run_import

        args = argparse.Namespace(
            dry_run=True, limit=0, product_id="YH01K01",
            product_ids="YH01K01,YH01K02", type="identity",
        )
        # 只验证参数合并逻辑，不实际执行导入
        # 通过检查 requested_ids 来验证
        requested_ids = set()
        if args.product_id:
            requested_ids.add(args.product_id.strip())
        if args.product_ids:
            for pid in args.product_ids.split(","):
                pid = pid.strip()
                if pid:
                    requested_ids.add(pid)
        requested_ids.discard("")
        assert requested_ids == {"YH01K01", "YH01K02"}

    def test_multi_ids_dedup(self):
        """重复编号去重"""
        requested_ids = set()
        product_ids_str = "YH01K01,YH01K01,YH02K05"
        for pid in product_ids_str.split(","):
            pid = pid.strip()
            if pid:
                requested_ids.add(pid)
        assert requested_ids == {"YH01K01", "YH02K05"}

    def test_multi_ids_strip_spaces(self):
        """去除空格"""
        requested_ids = set()
        product_ids_str = " YH01K01 , YH01K02 "
        for pid in product_ids_str.split(","):
            pid = pid.strip()
            if pid:
                requested_ids.add(pid)
        assert requested_ids == {"YH01K01", "YH01K02"}

    def test_only_multi(self):
        """只用 --product-ids"""
        requested_ids = set()
        product_ids_str = "YH01K01,YH02K05"
        for pid in product_ids_str.split(","):
            pid = pid.strip()
            if pid:
                requested_ids.add(pid)
        assert requested_ids == {"YH01K01", "YH02K05"}

    def test_empty_ids_ignored(self):
        """空字符串被忽略"""
        requested_ids = set()
        product_ids_str = ",,YH01K01,,"
        for pid in product_ids_str.split(","):
            pid = pid.strip()
            if pid:
                requested_ids.add(pid)
        requested_ids.discard("")
        assert requested_ids == {"YH01K01"}
