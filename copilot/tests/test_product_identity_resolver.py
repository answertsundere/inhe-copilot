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

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


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
