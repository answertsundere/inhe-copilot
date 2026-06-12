"""
DataQualityService 测试
"""

import sys
import os
import json
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from app.services.data_quality_service import DataQualityService


@pytest.fixture
def service_with_data():
    with tempfile.TemporaryDirectory() as tmpdir:
        cards = [
            {
                "i_id": "TEST001",
                "product_name": "北欧书桌",
                "completeness_score": 85,
                "agent_usable_level": "L3",
                "review_status": "高可用待确认",
                "missing_fields": [],
                "data_quality_warnings": [],
                "sku_summary": {"sku_count": 2},
            },
            {
                "i_id": "TEST002",
                "product_name": "简易书架",
                "completeness_score": 35,
                "agent_usable_level": "L0",
                "review_status": "待运营补全",
                "missing_fields": ["material", "weight"],
                "data_quality_warnings": ["价格缺失"],
                "sku_summary": {"sku_count": 1},
            },
        ]
        with open(os.path.join(tmpdir, "product_cards.json"), "w", encoding="utf-8") as f:
            json.dump(cards, f, ensure_ascii=False)

        svc = DataQualityService(data_dir=tmpdir)
        svc.load()
        yield svc


@pytest.fixture
def empty_service():
    with tempfile.TemporaryDirectory() as tmpdir:
        svc = DataQualityService(data_dir=tmpdir)
        svc.load()
        yield svc


class TestDataQualityEmpty:
    def test_quality_summary_empty(self, empty_service):
        s = empty_service.get_quality_summary()
        assert s["product_count"] == 0
        assert "warning" in s

    def test_missing_info_empty(self, empty_service):
        assert empty_service.get_missing_info() == []

    def test_product_quality_not_found(self, empty_service):
        q = empty_service.get_product_quality("NOEXIST")
        assert q["agent_usable_level"] == "L0"
        assert q["review_status"] == "未找到"


class TestDataQualityWithData:
    def test_quality_summary(self, service_with_data):
        s = service_with_data.get_quality_summary()
        assert s["product_count"] == 2
        assert s["sku_count"] == 3
        assert s["avg_completeness_score"] == 60.0
        assert s["level_distribution"]["L3"] == 1
        assert s["level_distribution"]["L0"] == 1

    def test_product_quality_found(self, service_with_data):
        q = service_with_data.get_product_quality("TEST001")
        assert q["product_name"] == "北欧书桌"
        assert q["agent_usable_level"] == "L3"
        assert q["completeness_score"] == 85

    def test_product_quality_l0(self, service_with_data):
        q = service_with_data.get_product_quality("TEST002")
        assert q["agent_usable_level"] == "L0"
        assert "material" in q["missing_fields"]
