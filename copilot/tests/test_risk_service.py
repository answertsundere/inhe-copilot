"""
风险识别服务测试
"""

import sys
import os
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.repositories.file_policy_repository import FilePolicyRepository
from app.services.risk_service import RiskService


@pytest.fixture
def risk_service():
    """创建测试用的风险服务"""
    policy_repo = FilePolicyRepository()
    policy_repo.load()
    return RiskService(policy_repo)


class TestRiskDetection:
    """风险等级检测测试"""

    def test_high_risk_complaint(self, risk_service):
        """投诉 -> high"""
        assert risk_service.detect_risk("我要投诉你们！") == "high"

    def test_high_risk_12315(self, risk_service):
        """12315 -> high"""
        assert risk_service.detect_risk("再不处理我就打12315") == "high"

    def test_high_risk_lawyer(self, risk_service):
        """律师 -> high"""
        assert risk_service.detect_risk("我要找律师起诉你们") == "high"

    def test_high_risk_media(self, risk_service):
        """媒体曝光 -> high"""
        assert risk_service.detect_risk("我要找媒体曝光你们") == "high"

    def test_high_risk_compensation(self, risk_service):
        """赔偿 -> high"""
        assert risk_service.detect_risk("你们必须赔偿我损失") == "high"

    def test_high_risk_bad_review(self, risk_service):
        """差评 -> high"""
        assert risk_service.detect_risk("不给解决就差评") == "high"

    def test_medium_risk_urge_shipping(self, risk_service):
        """催发货 -> medium"""
        assert risk_service.detect_risk("催发货，怎么还没发") == "medium"

    def test_medium_risk_not_received(self, risk_service):
        """没收到 -> medium"""
        assert risk_service.detect_risk("显示签收了但我没收到") == "medium"

    def test_medium_risk_quality(self, risk_service):
        """质量问题 -> medium"""
        assert risk_service.detect_risk("这个有质量问题") == "medium"

    def test_medium_risk_broken(self, risk_service):
        """破损 -> medium"""
        assert risk_service.detect_risk("收到的东西破损了") == "medium"

    def test_low_risk_when_ship(self, risk_service):
        """什么时候发货 -> low"""
        assert risk_service.detect_risk("请问什么时候发货") == "low"

    def test_low_risk_size(self, risk_service):
        """尺寸 -> low"""
        assert risk_service.detect_risk("请问这个尺寸是多少") == "low"

    def test_low_risk_material(self, risk_service):
        """材质 -> low"""
        assert risk_service.detect_risk("请问材质是什么") == "low"

    def test_no_match_returns_low(self, risk_service):
        """无匹配返回 low"""
        assert risk_service.detect_risk("你好，在吗") == "low"

    def test_high_takes_priority(self, risk_service):
        """high 优先于 medium/low"""
        msg = "质量问题，不给解决就投诉你们"
        assert risk_service.detect_risk(msg) == "high"


class TestHumanReviewRequired:
    """人工复核判断测试"""

    def test_high_risk_requires_review(self, risk_service):
        """高风险必须人工复核"""
        assert risk_service.should_require_human_review("我要投诉", "high") is True

    def test_12315_requires_review(self, risk_service):
        """12315 即使不标 high 也需复核"""
        assert risk_service.should_require_human_review("打12315", "medium") is True

    def test_low_risk_no_review(self, risk_service):
        """低风险不需要人工复核"""
        assert risk_service.should_require_human_review("什么时候发货", "low") is False

    def test_medium_no_special_keyword_no_review(self, risk_service):
        """中风险无特殊关键词不需要复核"""
        assert risk_service.should_require_human_review("催发货", "medium") is False

    def test_baby_safety_issue_requires_review(self, risk_service):
        """母婴安全/异味问题需要人工复核"""
        msg = "这个爬爬垫有刺鼻异味，还能给宝宝用吗"
        assert risk_service.detect_risk(msg) == "high"
        assert risk_service.should_require_human_review(msg, "high") is True

    def test_quality_after_sales_issue_requires_review(self, risk_service):
        """错发/缺件/质量类售后问题需要人工复核"""
        msg = "围栏缺件还有划痕，孩子用着不放心"
        assert risk_service.detect_risk(msg) == "medium"
        assert risk_service.should_require_human_review(msg, "medium") is True


class TestMatchedKeywords:
    """关键词匹配测试"""

    def test_get_matched_keywords(self, risk_service):
        """获取匹配到的关键词"""
        msg = "质量问题，不给解决就投诉到12315"
        matched = risk_service.get_matched_keywords(msg)
        assert "high" in matched
        assert "投诉" in matched["high"]
        assert "12315" in matched["high"]
        assert "medium" in matched
        assert "质量问题" in matched["medium"]

    def test_no_match_empty(self, risk_service):
        """无匹配返回空"""
        matched = risk_service.get_matched_keywords("你好")
        assert matched == {}
