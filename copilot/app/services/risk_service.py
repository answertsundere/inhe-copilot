"""
风险识别服务 - 基于关键词的快速风险检测
"""

from app.repositories.file_policy_repository import FilePolicyRepository


class RiskService:
    """风险识别服务"""

    def __init__(self, policy_repo: FilePolicyRepository):
        self.policy_repo = policy_repo
        self._risk_keywords = None

    def _ensure_loaded(self):
        """确保规则已加载"""
        if self._risk_keywords is None:
            self._risk_keywords = self.policy_repo.get_risk_keywords()

    def detect_risk(self, customer_message: str) -> str:
        """
        快速风险检测，返回 risk_level。
        优先匹配 high -> medium -> low。
        """
        self._ensure_loaded()
        for level in ["high", "medium", "low"]:
            for keyword in self._risk_keywords.get(level, []):
                if keyword in customer_message:
                    return level
        return "low"

    def should_require_human_review(self, customer_message: str, risk_level: str) -> bool:
        """
        判断是否需要人工复核。
        高风险场景必须人工复核。
        """
        if risk_level == "high":
            return True

        # 额外检查：即使 risk_level 不是 high，但包含特定强制复核关键词
        force_review_keywords = [
            "12315", "投诉", "差评", "律师", "起诉", "法院",
            "赔偿", "媒体", "曝光", "工商",
            "有毒", "中毒", "甲醛超标", "宝宝受伤", "孩子受伤",
            "安全隐患", "刺鼻", "异味", "味道很大",
            "破损", "质量问题", "缺件", "错发", "少发", "漏发",
        ]
        for kw in force_review_keywords:
            if kw in customer_message:
                return True

        return False

    def get_matched_keywords(self, customer_message: str) -> dict:
        """获取匹配到的风险关键词，返回 {level: [keywords]}"""
        self._ensure_loaded()
        matched = {}
        for level in ["high", "medium", "low"]:
            for keyword in self._risk_keywords.get(level, []):
                if keyword in customer_message:
                    matched.setdefault(level, []).append(keyword)
        return matched
