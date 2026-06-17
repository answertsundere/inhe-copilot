"""
商品知识库完整度计算测试
覆盖：空对象不计入完成、关键子字段缺失、完整字段 100%
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


def _make_session(monkeypatch, tmp_path):
    import app.db as db_module
    from app.repositories import kb_product_repository
    from app.models.kb_tables import KBProduct

    engine = create_engine(
        f"sqlite:///{tmp_path / 'kb_product.db'}",
        connect_args={"check_same_thread": False},
    )
    session_factory = sessionmaker(
        autocommit=False,
        autoflush=False,
        bind=engine,
        expire_on_commit=False,
    )
    monkeypatch.setattr(db_module, "engine", engine)
    monkeypatch.setattr(db_module, "SessionLocal", session_factory)
    monkeypatch.setattr(kb_product_repository, "SessionLocal", session_factory)
    db_module.Base.metadata.create_all(bind=engine)
    return session_factory, KBProduct, kb_product_repository


def _build_full_specs():
    return {
        "material": "PP",
        "size": "60x40x30cm",
        "load_capacity": "20kg",
        "age_range": "3-6岁",
        "accessories": "含说明书、螺丝包",
        "install_method": "免打孔",
        "detachable": "可拆卸",
        "drill_required": "否",
        "pinch_safety": "圆角设计",
        "certification_report": "CCC认证",
    }


def test_empty_specs_not_counted_as_complete(monkeypatch, tmp_path):
    _, KBProduct, kb_product_repository = _make_session(monkeypatch, tmp_path)

    product = KBProduct(
        i_id="TEST001",
        product_name="测试商品",
        brand="INHE",
        category_l1="运动户外",
        category_l2="篮球架",
        category_l3="儿童篮球架",
        sku_list_json='[]',
        specs_json='{"material":"","size":""}',
        logistics_json='{}',
        warranty_json='{}',
    )
    score, missing = kb_product_repository._compute_completeness(product)
    assert score < 1.0
    assert "材质" in missing
    assert "尺寸" in missing
    assert "SKU列表" in missing


def test_partial_completeness(monkeypatch, tmp_path):
    _, KBProduct, kb_product_repository = _make_session(monkeypatch, tmp_path)

    product = KBProduct(
        i_id="TEST002",
        product_name="测试商品2",
        brand="INHE",
        category_l1="运动户外",
        category_l2="篮球架",
        category_l3="儿童篮球架",
        sku_list_json='["SKU001"]',
        specs_json='{"material":"PP","size":"","load_capacity":"","age_range":"","accessories":"","install_method":"","detachable":"","drill_required":"","pinch_safety":"","certification_report":""}',
        logistics_json='{"attribute":"大件"}',
        warranty_json='{"period":"1年"}',
    )
    score, missing = kb_product_repository._compute_completeness(product)
    assert 0.3 < score < 0.8
    assert "材质" not in missing
    assert "尺寸" in missing


def test_full_completeness(monkeypatch, tmp_path):
    _, KBProduct, kb_product_repository = _make_session(monkeypatch, tmp_path)

    product = KBProduct(
        i_id="TEST003",
        product_name="完整商品",
        brand="INHE",
        category_l1="运动户外",
        category_l2="篮球架",
        category_l3="儿童篮球架",
        sku_list_json='["SKU001"]',
        specs_json=str(_build_full_specs()).replace("'", '"'),
        logistics_json='{"attribute":"大件"}',
        warranty_json='{"period":"2年"}',
    )
    score, missing = kb_product_repository._compute_completeness(product)
    assert score == 1.0
    assert missing == []


def test_placeholder_values_are_not_useful(monkeypatch, tmp_path):
    _, KBProduct, kb_product_repository = _make_session(monkeypatch, tmp_path)

    product = KBProduct(
        i_id="TEST004",
        product_name="占位符商品",
        brand="INHE",
        category_l1="运动户外",
        category_l2="篮球架",
        category_l3="儿童篮球架",
        sku_list_json='["SKU001"]',
        specs_json='{"material":"详见商品详情页","size":"-","load_capacity":"","age_range":"","accessories":"","install_method":"","detachable":"","drill_required":"","pinch_safety":"","certification_report":""}',
        logistics_json='{"attribute":"大件"}',
        warranty_json='{"period":"1年"}',
    )
    score, missing = kb_product_repository._compute_completeness(product)
    assert "材质" in missing
    assert "尺寸" in missing
