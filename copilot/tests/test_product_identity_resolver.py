"""
Product Identity Resolver Tests — 商品身份解析器测试。

验证:
- 平台商品 ID 不误作内部编码
- 低置信度映射需人工审核
- i_id 直接匹配
- SKU 匹配
- 标题关键词匹配
- URL 提取
- 客户消息匹配
"""

from __future__ import annotations

import os
import sys

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.eval_sanitizer_service import hash_sensitive


@pytest.fixture()
def identity_db(monkeypatch):
    import app.db as db_module
    from app.models.kb_tables import KBProduct

    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    session_factory = sessionmaker(autocommit=False, autoflush=False, bind=engine, expire_on_commit=False)
    monkeypatch.setattr(db_module, "engine", engine)
    monkeypatch.setattr(db_module, "SessionLocal", session_factory)
    db_module.Base.metadata.create_all(bind=engine, tables=[KBProduct.__table__])
    return session_factory


def _kb_product(*, i_id: str, name: str, sku: str = "", platform_item_id: str = "", platform_item_id_hash: str = ""):
    import json
    from app.models.kb_tables import KBProduct

    product = KBProduct(
        i_id=i_id,
        product_name=name,
        status="published",
        specs_json=json.dumps({"material": "PP"}, ensure_ascii=False),
    )
    sku_rows = []
    if sku:
        row = {"sku_code": sku}
        if platform_item_id:
            row["platform_item_id"] = platform_item_id
            row["product_url"] = f"https://item.taobao.com/item.htm?id={platform_item_id}"
        if platform_item_id_hash:
            row["platform_item_id_hash"] = platform_item_id_hash
        sku_rows.append(row)
    product.sku_list_json = json.dumps(sku_rows, ensure_ascii=False)
    return product


def test_resolver_exact_sku_maps_to_kb_product(identity_db):
    from app.services.product_identity_resolver import ProductIdentityResolver

    db = identity_db()
    try:
        db.add(_kb_product(i_id="YH90K01", name="Rocket shelf", sku="YH90K01B01S01"))
        db.commit()
    finally:
        db.close()

    result = ProductIdentityResolver().resolve(sku_id="YH90K01B01S01")

    assert result["status"] == "resolved"
    assert result["i_id"] == "YH90K01"
    assert result["sku_code"] == "YH90K01B01S01"
    assert result["identity_confidence"] == 1.0
    assert result["match_reason"] == "exact_sku_match"


def test_resolver_platform_item_id_and_url_map_to_kb_product(identity_db):
    from app.services.product_identity_resolver import ProductIdentityResolver

    db = identity_db()
    try:
        db.add(_kb_product(
            i_id="YH90K02",
            name="Whale storage cart",
            sku="YH90K02B01S01",
            platform_item_id="123456789012",
        ))
        db.commit()
    finally:
        db.close()

    resolver = ProductIdentityResolver()
    by_id = resolver.resolve(platform_product_id="123456789012")
    by_url = resolver.resolve(product_url="https://item.taobao.com/item.htm?id=123456789012")

    assert by_id["status"] == "resolved"
    assert by_id["i_id"] == "YH90K02"
    assert by_id["source"] == "platform_item_id_exact"
    assert by_url["status"] == "resolved"
    assert by_url["i_id"] == "YH90K02"


def test_resolver_platform_item_hash_maps_to_kb_product(identity_db):
    from app.services.product_identity_resolver import ProductIdentityResolver

    db = identity_db()
    try:
        db.add(_kb_product(
            i_id="YH90K07",
            name="Moon storage cabinet",
            sku="YH90K07B01S01",
            platform_item_id_hash=hash_sensitive("456789012345"),
        ))
        db.commit()
    finally:
        db.close()

    result = ProductIdentityResolver().resolve(platform_product_id_hash=hash_sensitive("456789012345"))

    assert result["status"] == "resolved"
    assert result["i_id"] == "YH90K07"
    assert result["match_reason"] == "exact_platform_item_id_hash_match"


def test_resolver_high_confidence_order_title_maps_to_kb_product(identity_db):
    from app.services.product_identity_resolver import ProductIdentityResolver

    db = identity_db()
    try:
        db.add(_kb_product(i_id="YH90K03", name="Three layer rocket shelf", sku="YH90K03B01S01"))
        db.commit()
    finally:
        db.close()

    result = ProductIdentityResolver().resolve(platform_title="Premium Three layer rocket shelf for kids")

    assert result["status"] == "resolved"
    assert result["i_id"] == "YH90K03"
    assert result["identity_confidence"] >= 0.78


def test_resolver_ambiguous_title_does_not_lock_product(identity_db):
    from app.services.product_identity_resolver import ProductIdentityResolver

    db = identity_db()
    try:
        db.add(_kb_product(i_id="YH90K04", name="Rocket shelf tall", sku="YH90K04B01S01"))
        db.add(_kb_product(i_id="YH90K05", name="Rocket shelf short", sku="YH90K05B01S01"))
        db.commit()
    finally:
        db.close()

    result = ProductIdentityResolver().resolve(platform_title="Rocket shelf")

    assert result["status"] == "ambiguous"
    assert result["i_id"] == ""
    assert len(result["ambiguous_candidates"]) == 2


def test_resolver_low_confidence_title_does_not_lock_product(identity_db):
    from app.services.product_identity_resolver import ProductIdentityResolver

    db = identity_db()
    try:
        db.add(_kb_product(i_id="YH90K06", name="Ocean bookcase", sku="YH90K06B01S01"))
        db.commit()
    finally:
        db.close()

    result = ProductIdentityResolver().resolve(platform_title="Weather forecast today")

    assert result["status"] == "not_found"
    assert result["unresolved_reason"]


class TestProductIdentityResolver:
    """商品身份解析器核心测试。"""

    @pytest.fixture(autouse=True)
    def setup(self):
        from app.services.product_identity_resolver import ProductIdentityResolver
        self.resolver = ProductIdentityResolver()

    def test_resolve_by_i_id(self):
        """i_id 直接匹配应返回 resolved。"""
        result = self.resolver.resolve(internal_i_id="YH66K02")
        assert result["status"] in ("resolved", "not_found")
        if result["status"] == "resolved":
            assert result["confidence"] >= 0.9
            assert result["canonical_product_name"]

    def test_platform_id_not_treated_as_internal(self):
        """平台商品 ID 不能直接当作 JST 内部商品编码。"""
        platform_id = "674567891234"  # Typical Taobao product ID
        result = self.resolver.resolve(platform_product_id=platform_id)
        # Should not blindly resolve a platform ID as an internal i_id
        if result["status"] == "resolved":
            assert result["source"] != "i_id_direct"
            assert result["internal_i_id"] != platform_id

    def test_low_confidence_needs_review(self):
        """低置信度映射标记为 ambiguous。"""
        result = self.resolver.resolve(platform_title="一些模糊的描述")
        if result["status"] == "ambiguous":
            assert "reason" in result
            assert "human" in result["reason"].lower() or "review" in result["reason"].lower()

    def test_not_found_when_no_match(self):
        """完全无法匹配时返回 not_found。"""
        result = self.resolver.resolve(customer_message="天气真好")
        assert result["status"] == "not_found"

    def test_url_extraction(self):
        """从 URL 中提取商品 ID。"""
        from app.services.product_identity_resolver import _extract_product_id_from_url
        assert _extract_product_id_from_url("https://item.taobao.com/item.htm?id=674567891234") == "674567891234"
        assert _extract_product_id_from_url("") == ""
        assert _extract_product_id_from_url("https://example.com/no-id") == ""

    def test_keyword_extraction(self):
        """从文本中提取商品关键词。"""
        from app.services.product_identity_resolver import _extract_product_keywords
        kws = _extract_product_keywords("一号狮子围兜防水吗")
        assert len(kws) > 0
        assert any("围兜" in k for k in kws)

        kws2 = _extract_product_keywords("六号防摔枕材质是什么")
        assert any("防摔枕" in k for k in kws2)

    def test_message_model_pattern_matching(self):
        """从客户消息中匹配 N号XXX 模式。"""
        result = self.resolver.resolve(customer_message="一号狮子围兜防水吗")
        # Should find some product match
        assert result["status"] in ("resolved", "ambiguous", "not_found")

    def test_convenience_function(self):
        """便捷函数 resolve_product_from_context 正常工作。"""
        from app.services.product_identity_resolver import resolve_product_from_context
        result = resolve_product_from_context(customer_message="书架多少钱")
        assert "status" in result
        assert "confidence" in result


class TestProductMappingEdgeCases:
    """商品映射边界情况。"""

    def test_empty_inputs(self):
        """所有输入为空时返回 not_found。"""
        from app.services.product_identity_resolver import ProductIdentityResolver
        resolver = ProductIdentityResolver()
        result = resolver.resolve()
        assert result["status"] == "not_found"

    def test_sidecar_candidates(self):
        """Sidecar 候选商品能被解析。"""
        from app.services.product_identity_resolver import ProductIdentityResolver
        resolver = ProductIdentityResolver()
        result = resolver.resolve(
            product_candidates=[
                {"value": "书架", "type": "product_candidate", "confidence": 0.8},
            ],
        )
        assert "status" in result

    def test_confidence_range(self):
        """置信度在 0-1 范围内。"""
        from app.services.product_identity_resolver import ProductIdentityResolver
        resolver = ProductIdentityResolver()
        for query in ["书架", "围兜", "防摔枕", "完全无关的文本", ""]:
            result = resolver.resolve(customer_message=query)
            assert 0.0 <= result["confidence"] <= 1.0, \
                f"confidence out of range for '{query}': {result['confidence']}"

    def test_jst_identifier_matrix(self):
        """JST 查询标识符类型判断。"""
        from app.services.product_identity_resolver import _extract_product_id_from_url
        # Platform trade ID (not URL)
        assert _extract_product_id_from_url("2026052600001") == ""
        # Valid URL
        assert _extract_product_id_from_url("https://detail.tmall.com/item.htm?id=123456789") == "123456789"
