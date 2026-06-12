"""
输出守卫测试 - 禁止承诺拦截
"""

import sys
import os
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.repositories.file_policy_repository import FilePolicyRepository
from app.services.output_guard import OutputGuard


@pytest.fixture
def guard():
    """创建测试用的输出守卫"""
    policy_repo = FilePolicyRepository()
    policy_repo.load()
    return OutputGuard(policy_repo)


class TestForbiddenClaimsCheck:
    """禁止承诺检测"""

    def test_detect_today_ship(self, guard):
        """检测「今天一定发」"""
        result = guard.check_reply("好的，今天一定发给您")
        assert result["safe"] is False
        assert "今天一定发" in result["matched"]

    def test_detect_guarantee_no_smell(self, guard):
        """检测「绝对没有味道」"""
        result = guard.check_reply("放心，我们的产品绝对没有味道")
        assert result["safe"] is False
        assert "绝对没有味道" in result["matched"]

    def test_detect_100percent_safe(self, guard):
        """检测「百分百安全」"""
        result = guard.check_reply("这个百分百安全的")
        assert result["safe"] is False

    def test_safe_reply_passes(self, guard):
        """安全回复通过检查"""
        result = guard.check_reply("我们会尽快帮您安排发货，请您耐心等待")
        assert result["safe"] is True
        assert result["matched"] == []

    def test_multiple_forbidden_in_one_reply(self, guard):
        """一条回复中多个禁止承诺"""
        reply = "放心，今天一定发，明天一定到，保证没问题"
        result = guard.check_reply(reply)
        assert result["safe"] is False
        assert len(result["matched"]) >= 2

    def test_empty_reply_is_safe(self, guard):
        """空回复通过检查"""
        result = guard.check_reply("")
        assert result["safe"] is True

    def test_no_forbidden_keyword_is_safe(self, guard):
        """不包含禁止承诺的回复通过"""
        reply = "感谢您的咨询，这款书桌的尺寸是120x60cm，材质是橡胶木。"
        result = guard.check_reply(reply)
        assert result["safe"] is True


class TestSanitizeReply:
    """回复清洗测试"""

    def test_sanitize_forbidden_claim(self, guard):
        """清洗禁止承诺"""
        reply = "好的，今天一定发给您"
        sanitized, warnings = guard.sanitize_reply(reply)
        assert "今天一定发" not in sanitized
        assert "会尽快帮您安排发货" in sanitized
        assert len(warnings) > 0

    def test_sanitize_multiple(self, guard):
        """清洗多个禁止承诺"""
        reply = "放心，绝对没有味道，百分百安全，保证没问题"
        sanitized, warnings = guard.sanitize_reply(reply)
        assert "绝对没有味道" not in sanitized
        assert "百分百安全" not in sanitized
        assert "保证没问题" not in sanitized
        assert len(warnings) >= 3

    def test_safe_reply_unchanged(self, guard):
        """安全回复不变"""
        reply = "我们会尽快帮您核实发货进度"
        sanitized, warnings = guard.sanitize_reply(reply)
        assert sanitized == reply
        assert warnings == []


class TestValidateOutput:
    """完整输出校验"""

    def test_auto_fix_human_review_for_high_risk(self, guard):
        """高风险自动标记人工复核"""
        result = {
            "risk_level": "high",
            "requires_human_review": False,
            "suggested_reply": "我们很抱歉给您带来不便",
        }
        validated = guard.validate_output(result)
        assert validated["requires_human_review"] is True
        assert "高风险" in str(validated.get("guard_warnings", ""))

    def test_add_guard_warnings_for_forbidden(self, guard):
        """禁止承诺添加警告"""
        result = {
            "risk_level": "low",
            "suggested_reply": "好的，今天一定发",
        }
        validated = guard.validate_output(result)
        assert "guard_warnings" in validated
        assert "suggested_reply" in validated
        assert "今天一定发" not in validated["suggested_reply"]
