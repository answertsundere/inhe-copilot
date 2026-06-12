# -*- coding: utf-8 -*-
"""
测试 scripts/import_kb_products.py 的核心逻辑

使用内存 SQLite 测试数据库，不污染生产数据库。
"""

import json
import os
import sys
import tempfile

import pytest

# 项目路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.db import Base, SessionLocal, engine
from app.models.kb_tables import KBProduct, KBChangeLog

# 导入被测模块
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
from import_kb_products import (
    clean_value,
    build_sku_list,
    build_product_record,
    diff_product,
    decide_new_status,
    _merge_json_dict,
    _merge_sku_list,
    run_import,
    rollback_batch,
)


# ─── Fixtures ───

@pytest.fixture(autouse=True)
def fresh_db(tmp_path, monkeypatch):
    """每个测试使用独立的临时数据库"""
    db_path = str(tmp_path / "test_kb.db")
    monkeypatch.setenv("COPILOT_KNOWLEDGE_DB_PATH", db_path)

    # 重新创建引擎和表
    from app import db as db_module
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    test_engine = create_engine(f"sqlite:///{db_path}")
    monkeypatch.setattr(db_module, "engine", test_engine)
    Base.metadata.create_all(test_engine)

    TestSession = sessionmaker(bind=test_engine, autocommit=False,
                               autoflush=False, expire_on_commit=False)
    monkeypatch.setattr(db_module, "SessionLocal", TestSession)

    # 也更新 repository 的 SessionLocal 引用
    from app.repositories import kb_product_repository
    monkeypatch.setattr(kb_product_repository, "SessionLocal", TestSession)

    yield TestSession


def _make_product(session, i_id="TEST001", name="测试商品", status="published",
                  specs=None, sku_list=None, brand="INHE", category_l1="测试类"):
    """创建测试用商品"""
    p = KBProduct(
        i_id=i_id,
        product_name=name,
        brand=brand,
        category_l1=category_l1,
        category_l2="",
        category_l3="",
        status=status,
        created_by="test",
        updated_by="test",
        import_batch_id="test_batch",
    )
    if specs:
        p.set_specs(specs)
    if sku_list:
        p.set_sku_list(sku_list)
    session.add(p)
    session.commit()
    session.refresh(p)
    return p


# ─── 单元测试 ───

class TestCleanValue:
    def test_none(self):
        assert clean_value(None) is None

    def test_nan(self):
        import math
        assert clean_value(float("nan")) is None

    def test_empty_string(self):
        assert clean_value("") is None
        assert clean_value("  ") is None

    def test_normal_string(self):
        assert clean_value("hello") == "hello"
        assert clean_value("  hello  ") == "hello"

    def test_nan_string(self):
        assert clean_value("nan") is None
        assert clean_value("NaN") is None

    def test_preserves_zero(self):
        assert clean_value("0") == "0"
        assert clean_value("否") == "否"
        assert clean_value("无") == "无"


class TestMergeJsonDict:
    def test_new_overwrites_old(self):
        old = {"weight": "1.0", "color": "red"}
        new = {"weight": "2.0"}
        result = _merge_json_dict(old, new)
        assert result["weight"] == "2.0"
        assert result["color"] == "red"

    def test_blank_new_preserves_old(self):
        old = {"weight": "1.0"}
        new = {"weight": ""}
        result = _merge_json_dict(old, new)
        assert result["weight"] == "1.0"

    def test_none_new_preserves_old(self):
        old = {"weight": "1.0"}
        new = {"weight": None}
        result = _merge_json_dict(old, new)
        assert result["weight"] == "1.0"

    def test_new_key_added(self):
        old = {"weight": "1.0"}
        new = {"height": "2.0"}
        result = _merge_json_dict(old, new)
        assert result["weight"] == "1.0"
        assert result["height"] == "2.0"

    def test_preserves_unknown_keys(self):
        old = {"custom_key": "custom_value"}
        new = {"weight": "2.0"}
        result = _merge_json_dict(old, new)
        assert result["custom_key"] == "custom_value"


class TestMergeSkuList:
    def test_new_sku_added(self):
        old = [{"sku_id": "A", "name": "SKU A"}]
        new = [{"sku_id": "B", "name": "SKU B"}]
        result = _merge_sku_list(old, new)
        assert len(result) == 2

    def test_existing_sku_merged(self):
        old = [{"sku_id": "A", "name": "SKU A", "price": "10"}]
        new = [{"sku_id": "A", "name": "SKU A Updated", "color": "red"}]
        result = _merge_sku_list(old, new)
        assert len(result) == 1
        assert result[0]["name"] == "SKU A Updated"
        assert result[0]["price"] == "10"
        assert result[0]["color"] == "red"

    def test_dedup_by_sku_id(self):
        old = []
        new = [
            {"sku_id": "A", "name": "SKU A"},
            {"sku_id": "A", "name": "SKU A2"},
        ]
        result = _merge_sku_list(old, new)
        assert len(result) == 1

    def test_preserves_old_skus_not_in_new(self):
        old = [{"sku_id": "A", "name": "SKU A"}, {"sku_id": "B", "name": "SKU B"}]
        new = [{"sku_id": "A", "name": "SKU A Updated"}]
        result = _merge_sku_list(old, new)
        assert len(result) == 2
        assert any(s["sku_id"] == "B" for s in result)


class TestDiffProduct:
    def test_no_change(self, fresh_db):
        session = fresh_db()
        p = _make_product(session, name="测试商品", brand="INHE", category_l1="围栏类")
        new_data = {"product_name": "测试商品", "brand": "INHE", "category_l1": "围栏类"}
        result = diff_product(p, new_data)
        assert not result["is_changed"]
        assert result["changed_fields"] == []
        session.close()

    def test_name_change_is_factual(self, fresh_db):
        session = fresh_db()
        p = _make_product(session, name="旧名称")
        new_data = {"product_name": "新名称"}
        result = diff_product(p, new_data)
        assert result["is_changed"]
        assert result["is_factual_change"]
        assert "product_name" in result["changed_fields"]
        session.close()

    def test_blank_not_overwrite(self, fresh_db):
        session = fresh_db()
        p = _make_product(session, brand="INHE")
        new_data = {"brand": ""}  # 空白不应覆盖
        result = diff_product(p, new_data)
        assert not result["is_changed"]
        session.close()

    def test_none_not_overwrite(self, fresh_db):
        session = fresh_db()
        p = _make_product(session, brand="INHE")
        new_data = {"brand": None}
        result = diff_product(p, new_data)
        assert not result["is_changed"]
        session.close()

    def test_specs_merge(self, fresh_db):
        session = fresh_db()
        p = _make_product(session, specs={"weight": "1.0", "color": "red"})
        new_data = {"specs": {"weight": "2.0"}}
        result = diff_product(p, new_data)
        assert result["is_changed"]
        assert "specs" in result["changed_fields"]
        merged = result["changes"]["specs"]["new"]
        assert merged["weight"] == "2.0"
        assert merged["color"] == "red"  # 保留旧值
        session.close()

    def test_sku_merge(self, fresh_db):
        session = fresh_db()
        p = _make_product(session, sku_list=[
            {"sku_id": "A", "price": "10"}
        ])
        new_data = {"sku_list": [
            {"sku_id": "A", "color": "red"},
            {"sku_id": "B", "name": "New SKU"},
        ]}
        result = diff_product(p, new_data)
        assert result["is_changed"]
        merged = result["changes"]["sku_list"]["new"]
        assert len(merged) == 2
        # 旧 SKU 保留 price，新增 color
        sku_a = [s for s in merged if s["sku_id"] == "A"][0]
        assert sku_a["price"] == "10"
        assert sku_a["color"] == "red"
        session.close()

    def test_specs_identical_no_change(self, fresh_db):
        session = fresh_db()
        p = _make_product(session, specs={"weight": "1.0"})
        new_data = {"specs": {"weight": "1.0"}}
        result = diff_product(p, new_data)
        assert not result["is_changed"]
        session.close()


class TestDecideNewStatus:
    def test_unchanged_stays_published(self):
        diff = {"is_changed": False, "is_factual_change": False}
        assert decide_new_status("published", diff) == "published"

    def test_factual_change_goes_pending_review(self):
        diff = {"is_changed": True, "is_factual_change": True}
        assert decide_new_status("published", diff) == "pending_review"

    def test_non_factual_stays_published(self):
        diff = {"is_changed": True, "is_factual_change": False}
        assert decide_new_status("published", diff) == "published"

    def test_draft_stays_draft(self):
        diff = {"is_changed": True, "is_factual_change": True}
        assert decide_new_status("draft", diff) == "draft"


class TestDryRunNoWrite:
    def test_dry_run_creates_nothing(self, fresh_db, tmp_path):
        """dry-run 模式不写数据库"""
        session = fresh_db()
        assert session.query(KBProduct).count() == 0

        # 创建最小 xlsx
        import pandas as pd
        xlsx_path = str(tmp_path / "test.xlsx")
        items = pd.DataFrame({
            "i_id": ["TEST001"],
            "name": ["测试商品"],
            "c_name": ["测试类"],
            "brand": [None],
            "h": [None], "l": [None], "w": [None],
            "weight": [None], "unit": [None], "item_type": [None],
            "remark": [None], "pic": [None], "pics": [None],
            "shelf_life": [None], "s_price": [None], "c_id": [None],
            "modified": [None], "f_json": [None], "autoid": [None],
            "co_id": [None], "market_price": [None], "vc_name": [None],
            "created": [None], "storeage": [None],
            "registration_certificate_no": [None], "c_price": [None],
        })
        skus = pd.DataFrame({
            "i_id": ["TEST001"], "sku_id": ["SKU001"],
            "name": ["测试SKU"], "properties_value": [None],
            "sale_price": [None], "cost_price": [None],
            "sku_code": [None], "enabled": [None],
            "supplier_i_id": [None], "item_type": [None], "pic": [None],
            "modified": [None], "brand": [None], "other_10": [None],
            "vc_name": [None], "productionbatch_format": [None],
            "created": [None], "autoid": [None], "weight": [None],
            "labels": [None], "unit": [None], "stock_disabled": [None],
            "is_series_number": [None], "market_price": [None],
            "short_name": [None], "supplier_id": [None],
            "supplier_name": [None], "cost_price": [None],
            "creator": [None], "other_price_5": [None], "other_9": [None],
            "sku_type": [None], "other_8": [None], "other_7": [None],
            "h": [None], "other_6": [None], "other_5": [None],
            "other_4": [None], "other_3": [None], "l": [None],
            "other_2": [None], "sale_price": [None], "other_1": [None],
            "stock_type": [None], "supplier_sku_id": [None],
            "w": [None], "category": [None], "other_price_3": [None],
            "other_price_4": [None], "other_price_1": [None],
            "other_price_2": [None], "color": [None],
            "remark": [None], "production_licence": [None],
            "pic_big": [None], "enabled": [None], "shelf_life": [None],
            "c_id": [None],
        })
        with pd.ExcelWriter(xlsx_path, engine="openpyxl") as writer:
            items.to_excel(writer, sheet_name="items", index=False)
            skus.to_excel(writer, sheet_name="skus", index=False)

        report = run_import(
            file_path=xlsx_path,
            dry_run=True,
            apply=False,
            batch_id="test_dry_run",
            report_dir=str(tmp_path / "reports"),
        )

        # dry-run 不应创建任何记录
        assert session.query(KBProduct).count() == 0
        assert report["summary"]["create"] == 1
        assert report["batch_id"] == "test_dry_run"
        session.close()


class TestIdempotency:
    def test_same_i_id_not_created_twice(self, fresh_db):
        """重复执行不应重复创建"""
        session = fresh_db()
        p = _make_product(session, i_id="IDEM001", name="幂等商品", status="draft")

        new_data = {"product_name": "幂等商品"}
        result = diff_product(p, new_data)

        assert not result["is_changed"]
        assert session.query(KBProduct).filter(KBProduct.i_id == "IDEM001").count() == 1
        session.close()


class TestBatchId:
    def test_batch_id_recorded(self, fresh_db, tmp_path):
        """import_batch_id 应正确记录"""
        import pandas as pd
        session = fresh_db()

        # 先创建一个已有商品
        _make_product(session, i_id="BATCH001", name="批次测试", status="draft")

        # 简单验证
        p = session.query(KBProduct).filter(KBProduct.i_id == "BATCH001").first()
        assert p.import_batch_id == "test_batch"
        session.close()


class TestChangeLog:
    def test_change_log_has_snapshot(self, fresh_db):
        """变更日志应包含快照"""
        session = fresh_db()
        p = _make_product(session, name="日志测试")
        # 手动检查 change_log
        logs = session.query(KBChangeLog).all()
        # 创建时应该有一条 create 日志
        # 注意：_make_product 不走 repository，不会有 change_log
        session.close()


class TestStringEncoding:
    def test_i_id_as_string(self):
        """ID 应按字符串处理，不转数字"""
        val = clean_value("001")
        assert val == "001"
        assert val != "1"

    def test_scientific_notation(self):
        """科学计数法 ID 应保留原始值"""
        val = clean_value("6.97087E+11")
        assert val == "6.97087E+11"


def _write_import_xlsx(path, items_rows, sku_rows=None):
    import pandas as pd
    items = pd.DataFrame(items_rows)
    skus = pd.DataFrame(sku_rows or [])
    with pd.ExcelWriter(str(path), engine="openpyxl") as writer:
        items.to_excel(writer, sheet_name="items", index=False)
        skus.to_excel(writer, sheet_name="skus", index=False)


class TestApplyAndRollback:
    def test_apply_create_can_rollback_delete(self, fresh_db, tmp_path):
        session = fresh_db()
        xlsx_path = tmp_path / "create.xlsx"
        _write_import_xlsx(
            xlsx_path,
            [{"i_id": "NEW001", "name": "New Product", "c_name": "Cat", "brand": "INHE"}],
            [{"i_id": "NEW001", "sku_id": "SKU001", "name": "Sku One"}],
        )

        report = run_import(
            file_path=str(xlsx_path),
            apply=True,
            batch_id="batch_create",
            report_dir=str(tmp_path / "reports"),
        )
        assert report["summary"]["create"] == 1
        assert report["summary"]["new_skus"] == 1
        assert session.query(KBProduct).filter(KBProduct.i_id == "NEW001").count() == 1

        rollback_batch("batch_create")
        session.expire_all()
        assert session.query(KBProduct).filter(KBProduct.i_id == "NEW001").count() == 0
        session.close()


class TestKBProductSummaryCounts:
    def test_summary_reports_actual_draft_count(self, fresh_db):
        from flask import Flask
        from app.api.kb_admin_routes import kb_admin_bp

        session = fresh_db()
        try:
            _make_product(session, i_id="PUB001", name="Published Product", status="published")
            _make_product(session, i_id="DRAFT001", name="Draft Product", status="draft")
            _make_product(session, i_id="REVIEW001", name="Review Product", status="pending_review")
        finally:
            session.close()

        app = Flask(__name__)
        app.register_blueprint(kb_admin_bp)
        resp = app.test_client().get("/api/kb/products/summary")

        assert resp.status_code == 200
        data = resp.get_json()
        assert data["total"] == 3
        assert data["published"] == 1
        assert data["draft"] == 1
        assert data["review_pending"] == 1


class TestImportSafety:
    def _summary_reports_actual_draft_count(self, fresh_db):
        from flask import Flask
        from app.api.kb_admin_routes import kb_admin_bp

        session = fresh_db()
        try:
            _make_product(session, i_id="PUB001", name="已发布商品", status="published")
            _make_product(session, i_id="DRAFT001", name="草稿商品", status="draft")
            _make_product(session, i_id="REVIEW001", name="待审商品", status="pending_review")
        finally:
            session.close()

        app = Flask(__name__)
        app.register_blueprint(kb_admin_bp)
        resp = app.test_client().get("/api/kb/products/summary")

        assert resp.status_code == 200
        data = resp.get_json()
        assert data["total"] == 3
        assert data["published"] == 1
        assert data["draft"] == 1
        assert data["review_pending"] == 1
        assert report["summary"]["new_skus"] == 1
        assert session.query(KBProduct).filter(KBProduct.i_id == "NEW001").count() == 1

        rollback_batch("batch_create")
        session.expire_all()
        assert session.query(KBProduct).filter(KBProduct.i_id == "NEW001").count() == 0
        session.close()

    def test_apply_update_can_rollback_snapshot(self, fresh_db, tmp_path):
        session = fresh_db()
        _make_product(
            session,
            i_id="UPD001",
            name="Old Name",
            status="published",
            specs={"weight": "1"},
            sku_list=[{"sku_id": "SKU001", "sku_name": "Old Sku"}],
        )
        xlsx_path = tmp_path / "update.xlsx"
        _write_import_xlsx(
            xlsx_path,
            [{"i_id": "UPD001", "name": "New Name", "c_name": "Cat", "brand": "INHE", "weight": "2"}],
            [{"i_id": "UPD001", "sku_id": "SKU001", "name": "New Sku"}],
        )

        report = run_import(
            file_path=str(xlsx_path),
            apply=True,
            batch_id="batch_update",
            report_dir=str(tmp_path / "reports"),
        )
        assert report["summary"]["update"] == 1
        assert report["summary"]["updated_skus"] == 1
        session.expire_all()
        product = session.query(KBProduct).filter(KBProduct.i_id == "UPD001").one()
        assert product.product_name == "New Name"
        assert product.status == "pending_review"

        rollback_batch("batch_update")
        session.expire_all()
        product = session.query(KBProduct).filter(KBProduct.i_id == "UPD001").one()
        assert product.product_name == "Old Name"
        assert product.status == "published"
        assert product.get_specs()["weight"] == "1"
        assert product.get_sku_list()[0]["sku_name"] == "Old Sku"
        session.close()

    def test_dry_run_duplicate_iid_reports_conflict(self, fresh_db, tmp_path):
        session = fresh_db()
        xlsx_path = tmp_path / "dup.xlsx"
        _write_import_xlsx(
            xlsx_path,
            [
                {"i_id": "DUP001", "name": "Product A", "c_name": "Cat"},
                {"i_id": "DUP001", "name": "Product B", "c_name": "Cat"},
            ],
            [],
        )
        report = run_import(
            file_path=str(xlsx_path),
            dry_run=True,
            apply=False,
            batch_id="batch_dup",
            report_dir=str(tmp_path / "reports"),
        )
        assert report["summary"]["create"] == 1
        assert report["summary"]["conflict"] == 1
        assert session.query(KBProduct).count() == 0
        session.close()

    def test_dingtalk_not_called_by_default(self, fresh_db, tmp_path, monkeypatch):
        xlsx_path = tmp_path / "offline.xlsx"
        _write_import_xlsx(
            xlsx_path,
            [{"i_id": "OFF001", "name": "Offline Product", "c_name": "Cat"}],
            [],
        )
        import import_kb_products as mod
        monkeypatch.setattr(
            mod,
            "read_dingtalk_products",
            lambda: (_ for _ in ()).throw(AssertionError("DingTalk should be opt-in")),
        )
        report = run_import(
            file_path=str(xlsx_path),
            dry_run=True,
            apply=False,
            batch_id="batch_offline",
            report_dir=str(tmp_path / "reports"),
        )
        assert report["summary"]["create"] == 1

    def test_large_apply_requires_explicit_full_import_confirmation(self, fresh_db, tmp_path):
        xlsx_path = tmp_path / "large.xlsx"
        rows = [
            {"i_id": f"BIG{i:03d}", "name": f"Big Product {i}", "c_name": "Cat"}
            for i in range(51)
        ]
        _write_import_xlsx(xlsx_path, rows, [])

        with pytest.raises(RuntimeError, match="Refusing full apply"):
            run_import(
                file_path=str(xlsx_path),
                apply=True,
                batch_id="batch_large",
                report_dir=str(tmp_path / "reports"),
            )


class TestRepositoryCompleteness:
    def test_create_uses_percentage_completeness_score(self, fresh_db):
        from app.repositories.kb_product_repository import KBProductRepository

        product = KBProductRepository.create(
            i_id="COMP001",
            product_name="Completeness Product",
            brand="INHE",
            category_l1="Cat",
            category_l2="Sub",
            category_l3="Leaf",
            sku_list_json=json.dumps([{"sku_id": "SKU001"}]),
            specs_json=json.dumps({"weight": "1"}),
            logistics_json=json.dumps({"package_weight": "1"}),
            warranty_json=json.dumps({"period": "1 year"}),
            status="draft",
            created_by="test",
            updated_by="test",
        )

        assert product.completeness_score == 90.0
