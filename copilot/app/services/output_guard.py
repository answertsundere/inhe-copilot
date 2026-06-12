"""
输出安全检查 - 禁止承诺拦截和安全检查
"""

import logging

from app.repositories.file_policy_repository import FilePolicyRepository

logger = logging.getLogger(__name__)


class OutputGuard:
    """输出安全守卫"""

    def __init__(self, policy_repo: FilePolicyRepository):
        self.policy_repo = policy_repo
        self._forbidden_claims = None

    def _ensure_loaded(self):
        if self._forbidden_claims is None:
            self._forbidden_claims = self.policy_repo.get_forbidden_claims()

    def check_reply(self, suggested_reply: str) -> dict:
        """
        检查建议回复是否包含禁止承诺。
        返回 {"safe": bool, "warnings": [str], "matched": [str]}
        """
        self._ensure_loaded()
        matched = []
        warnings = []

        for claim in self._forbidden_claims:
            if claim and claim in suggested_reply:
                matched.append(claim)
                warnings.append(f'建议回复包含禁止承诺: [{claim}]')

        is_safe = len(matched) == 0

        if not is_safe:
            logger.warning("OutputGuard 拦截到禁止承诺: %s", matched)

        return {
            "safe": is_safe,
            "warnings": warnings,
            "matched": matched,
        }

    def sanitize_reply(self, suggested_reply: str) -> tuple[str, list[str]]:
        """
        清洗回复内容，替换禁止承诺为安全表述。
        返回 (sanitized_reply, warnings)
        """
        self._ensure_loaded()
        warnings = []
        reply = suggested_reply

        # 安全替换映射
        replacements = {
            "今天一定发": "会尽快帮您安排发货",
            "明天一定到": "预计很快就能送到",
            "立刻就发": "会尽快安排发货",
            "马上就好": "会尽快处理",
            "一定免费补发": "核实后会为您处理补发",
            "一定可以退": "核实情况后会为您处理",
            "保证没问题": "我们会认真处理您的问题",
            "肯定能到": "正常情况下很快就能送到",
            "绝对没有味道": "气味会在通风后消散",
            "百分百安全": "产品符合安全标准",
            "不会坏": "产品耐用性经过测试",
            "不会塌": "承重性能经过测试",
        }

        for forbidden, safe_phrase in replacements.items():
            if forbidden in reply:
                reply = reply.replace(forbidden, safe_phrase)
                warnings.append(f'已替换 [{forbidden}] 为安全表述')

        return reply, warnings

    def validate_output(self, result: dict) -> dict:
        """
        完整校验 LLM 输出，包括结构校验和内容安全检查。
        在原始 result 上添加 guard_warnings。
        """
        guard_warnings = []

        # 检查建议回复
        reply = result.get("suggested_reply", "")
        if reply:
            check = self.check_reply(reply)
            guard_warnings.extend(check["warnings"])

            # 如果不安全，尝试清洗
            if not check["safe"]:
                sanitized, sanitize_warnings = self.sanitize_reply(reply)
                result["suggested_reply"] = sanitized
                guard_warnings.extend(sanitize_warnings)

        # 检查 requires_human_review 一致性
        risk = result.get("risk_level", "low")
        human_review = result.get("requires_human_review", False)
        if risk == "high" and not human_review:
            result["requires_human_review"] = True
            guard_warnings.append("高风险消息已自动标记需要人工复核")

        if guard_warnings:
            result["guard_warnings"] = guard_warnings

        return result
