"""
Skill Router 测试
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.skill_router import SkillRouter


class TestSkillRouter:
    def setup_method(self):
        self.router = SkillRouter()

    def test_shipping_urge(self):
        r = self.router.route("怎么还没发货？都好几天了")
        assert r["skill"] == "shipping"
        assert "发货" in r["matched_keywords"]

    def test_refund(self):
        r = self.router.route("我要退货退款")
        assert r["skill"] == "refund"
        assert "退货" in r["matched_keywords"]

    def test_product_consult(self):
        r = self.router.route("这款书桌尺寸是多少？")
        assert r["skill"] == "product_consult"
        assert "尺寸" in r["matched_keywords"]

    def test_complaint(self):
        r = self.router.route("我要投诉你们，打12315")
        assert r["skill"] == "complaint"
        assert "投诉" in r["matched_keywords"]

    def test_logistics(self):
        r = self.router.route("显示签收了但我没收到")
        assert r["skill"] == "logistics"
        assert "签收" in r["matched_keywords"]

    def test_quality_issue(self):
        r = self.router.route("收到的东西有划痕，质量太差")
        assert r["skill"] == "quality_issue"
        assert "质量" in r["matched_keywords"]

    def test_general_fallback(self):
        r = self.router.route("你好")
        # 无匹配时 low 风险兜底为 product_consult（通用咨询）
        assert r["skill"] in ("product_consult", "shipping", "price_promotion")

    def test_risk_priority(self):
        # 无关键词时按风险等级兜底
        r = self.router.route("xxx", risk_level="high")
        assert r["skill"] == "complaint"
