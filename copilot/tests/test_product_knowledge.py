"""
产品知识库仓库测试
"""

import sys
import os
import json
import tempfile
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.repositories.product_knowledge_repository import ProductKnowledgeRepository


@pytest.fixture
def sample_cards():
    """测试用产品知识卡数据"""
    return [
        {
            "i_id": "TEST001",
            "product_name": "北欧实木书桌",
            "category": "家具 - 书桌",
            "brand": "INHE",
            "product_status": "启用",
            "sku_summary": {
                "sku_count": 2,
                "sku_list": [
                    {
                        "sku_id": "SKU001W",
                        "sku_name": "书桌 白色 120cm",
                        "properties_value": "颜色:白色 尺寸:120x60cm",
                        "sale_price": 579.0,
                        "stock_qty": 15,
                        "weight": 25.5,
                    },
                    {
                        "sku_id": "SKU001B",
                        "sku_name": "书桌 黑色 120cm",
                        "properties_value": "颜色:黑色 尺寸:120x60cm",
                        "sale_price": 599.0,
                        "stock_qty": 8,
                        "weight": 25.5,
                    },
                ],
            },
            "customer_service_facts": {
                "material": "橡胶木",
                "weight": 25.5,
                "color": ["白色", "黑色"],
                "selling_points": ["承重好", "北欧设计"],
            },
            "completeness_score": 85,
            "agent_usable_level": "L3",
        },
        {
            "i_id": "TEST002",
            "product_name": "多功能置物架",
            "category": "家具 - 置物架",
            "brand": "INHE",
            "product_status": "启用",
            "sku_summary": {
                "sku_count": 1,
                "sku_list": [
                    {
                        "sku_id": "SKU002",
                        "sku_name": "置物架 黑色 3层",
                        "properties_value": "颜色:黑色 层数:3层",
                        "sale_price": 439.0,
                        "stock_qty": 0,
                        "weight": 12.0,
                    },
                ],
            },
            "customer_service_facts": {
                "material": None,
                "weight": 12.0,
                "color": ["黑色"],
                "selling_points": [],
            },
            "completeness_score": 45,
            "agent_usable_level": "L1",
        },
    ]


@pytest.fixture
def repo_with_data(sample_cards):
    """带样例数据的仓库"""
    with tempfile.TemporaryDirectory() as tmpdir:
        path = os.path.join(tmpdir, "product_cards.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(sample_cards, f, ensure_ascii=False)

        repo = ProductKnowledgeRepository(knowledge_dir=tmpdir)
        repo.load()
        yield repo


@pytest.fixture
def empty_repo():
    """空仓库（文件不存在）"""
    with tempfile.TemporaryDirectory() as tmpdir:
        repo = ProductKnowledgeRepository(knowledge_dir=tmpdir)
        repo.load()
        yield repo


class TestProductKnowledgeRepoEmpty:
    """文件不存在时的优雅降级"""

    def test_count_zero(self, empty_repo):
        assert empty_repo.count() == 0

    def test_search_empty(self, empty_repo):
        assert empty_repo.search("书桌") == []

    def test_get_by_i_id_none(self, empty_repo):
        assert empty_repo.get_by_i_id("TEST001") is None

    def test_get_by_sku_id_none(self, empty_repo):
        assert empty_repo.get_by_sku_id("SKU001W") is None


class TestProductKnowledgeRepoWithData:
    """有数据时的查询测试"""

    def test_count(self, repo_with_data):
        assert repo_with_data.count() == 2

    def test_get_by_i_id(self, repo_with_data):
        card = repo_with_data.get_by_i_id("TEST001")
        assert card is not None
        assert card["product_name"] == "北欧实木书桌"

    def test_get_by_i_id_not_found(self, repo_with_data):
        assert repo_with_data.get_by_i_id("NONEXIST") is None

    def test_get_by_sku_id(self, repo_with_data):
        card = repo_with_data.get_by_sku_id("SKU001W")
        assert card is not None
        assert card["i_id"] == "TEST001"

    def test_get_by_sku_id_second(self, repo_with_data):
        card = repo_with_data.get_by_sku_id("SKU002")
        assert card is not None
        assert card["i_id"] == "TEST002"

    def test_search_by_name(self, repo_with_data):
        results = repo_with_data.search("书桌")
        assert len(results) >= 1
        assert any(r.get("i_id") == "TEST001" for r in results)

    def test_search_by_category(self, repo_with_data):
        results = repo_with_data.search("置物架")
        assert len(results) >= 1
        assert any(r.get("i_id") == "TEST002" for r in results)

    def test_search_no_match(self, repo_with_data):
        results = repo_with_data.search("不存在的商品xxx")
        assert results == []

    def test_search_limit(self, repo_with_data):
        results = repo_with_data.search("INHE", limit=1)
        assert len(results) <= 1

    def test_get_summary(self, repo_with_data, sample_cards):
        card = sample_cards[0]
        summary = repo_with_data.get_summary(card)
        assert summary["i_id"] == "TEST001"
        assert summary["name"] == "北欧实木书桌"
        assert summary["material"] == "橡胶木"
        assert summary["weight"] == 25.5
        assert summary["price_range"] is not None
        assert "¥" in summary["price_range"]
        assert summary["stock_available"] is True
        assert summary["agent_level"] == "L3"
