"""
质检服务 - 基于规则检查客服最终回复是否违规
不调用 LLM
"""

import logging
import re

logger = logging.getLogger(__name__)

# 违规类型定义
_VIOLATION_TYPES = {
    "forbidden_claim": {"name": "禁止承诺", "weight": 25},
    "missing_empathy": {"name": "缺少安抚", "weight": 10},
    "missing_lookup": {"name": "缺少核实", "weight": 15},
    "offline_trade": {"name": "引导线下交易", "weight": 30},
    "refund_promise": {"name": "退款/赔偿承诺", "weight": 25},
    "rude_tone": {"name": "语气不当", "weight": 20},
    "missing_escalation": {"name": "遗漏升级", "weight": 15},
}

# 绝对禁止表述（来自 forbidden_claims.yaml 的扩展）
_FORBIDDEN_PATTERNS = [
    r"今天一定发", r"明天一定到", r"马上发", r"立刻发", r"立即发",
    r"保证.*到", r"肯定.*到", r"一定.*到", r"绝对.*到",
    r"保证.*发", r"肯定.*发", r"一定.*发",
    r"绝对.*没有", r"绝对.*安全", r"百分百", r"100%", r"百分之百",
    r"不可能.*坏", r"不可能.*塌", r"不可能.*倒", r"不可能.*裂",
    r"绝不会", r"肯定不会", r"绝对不会",
]

# 退款/赔偿承诺模式
_REFUND_PROMISE_PATTERNS = [
    r"一定.*赔", r"一定.*退", r"全额.*退", r"免费.*补", r"必须.*退",
    r"马上.*退", r"立即.*退", r"立刻.*退", r"直接.*退",
    r"赔偿.*\d+", r"退款.*\d+", r"补偿.*\d+",
    r"赔你", r"退你", r"补你",
]

# 线下交易引导
_OFFLINE_TRADE_KEYWORDS = [
    "微信", "支付宝", "私下", "线下", "转账", "扫码", "加QQ", "加V",
    "电话交易", "私下联系", "直接打款", "绕过平台",
]

# 粗鲁用语
_RUDE_KEYWORDS = [
    "傻", "蠢", "笨", "滚", "神经病", "脑子", "有病", "他妈", "去死",
    "垃圾", "骗子", "不要脸", "白痴", "脑残", "混蛋", "操", "他妈的",
    "妈的", "死", "贱", "屌", "滚蛋", "闭嘴", "烦死了", "有完没完",
]

# 安抚用语（缺少时扣分）
_EMPATHY_KEYWORDS = [
    "抱歉", "对不起", "理解", "抱歉", "不好意思", "麻烦", "感谢", "谢谢",
    "请放心", "别担心", "我们会", "帮您", "为您", "不好意思",
]

# 核实动作（缺少时扣分，特定场景）
_LOOKUP_KEYWORDS = [
    "核实", "查询", "查看", "确认", "帮您查", "帮您看", "查一下", "看一下",
    "记录", "反馈", "跟进", "处理", "解决",
]

# 升级动作
_ESCALATION_KEYWORDS = [
    "主管", "经理", "升级", "上报", "转交", "转接", "专人", "领导",
]


class QualityCheckService:
    """质检服务"""

    def __init__(self, policy_repo=None):
        self._policy_repo = policy_repo
        self._forbidden_claims = []
        self._qa_checklist = []

    def _ensure_loaded(self):
        if self._policy_repo is None:
            return
        if not self._forbidden_claims:
            self._forbidden_claims = self._policy_repo.get_forbidden_claims()
        if not self._qa_checklist:
            self._qa_checklist = self._policy_repo.get_qa_checklist()

    def check(self, customer_message: str, reply: str, order_id: str = "", scenario: str = "") -> dict:
        """
        检查回复质量。
        返回 dict: score, risk_level, violations, required_actions_missing, requires_human_review
        """
        self._ensure_loaded()
        violations = []
        reply_lower = reply.lower()
        customer_lower = customer_message.lower()

        # 1. 禁止承诺检查
        for pattern in _FORBIDDEN_PATTERNS:
            if re.search(pattern, reply_lower):
                m = re.search(pattern, reply_lower).group(0)
                violations.append({
                    "type": "forbidden_claim",
                    "message": f"检测到禁止承诺: [{m}]",
                    "evidence": m,
                    "suggestion": "将绝对承诺改为缓和表述，如'会尽快帮您安排'",
                })
                break  # 同类只报一次

        # 也检查 policy_repo 的 forbidden_claims
        for claim in self._forbidden_claims:
            if claim and claim in reply_lower:
                violations.append({
                    "type": "forbidden_claim",
                    "message": f"检测到禁止承诺: [{claim}]",
                    "evidence": claim,
                    "suggestion": "替换为安全表述",
                })
                break

        # 2. 退款/赔偿承诺
        for pattern in _REFUND_PROMISE_PATTERNS:
            if re.search(pattern, reply_lower):
                m = re.search(pattern, reply_lower).group(0)
                violations.append({
                    "type": "refund_promise",
                    "message": f"检测到退款/赔偿承诺: [{m}]",
                    "evidence": m,
                    "suggestion": "涉及金额需说明'核实后处理'，不能直接承诺",
                })
                break

        # 3. 线下交易引导
        for kw in _OFFLINE_TRADE_KEYWORDS:
            if kw in reply_lower:
                violations.append({
                    "type": "offline_trade",
                    "message": f"检测到可能引导线下交易: [{kw}]",
                    "evidence": kw,
                    "suggestion": "严禁引导客户线下交易，所有沟通应在平台内完成",
                })
                break

        # 4. 粗鲁用语
        for kw in _RUDE_KEYWORDS:
            if kw in reply_lower:
                violations.append({
                    "type": "rude_tone",
                    "message": f"检测到不当用语: [{kw}]",
                    "evidence": kw,
                    "suggestion": "请使用礼貌、专业的客服用语",
                })
                break

        # 5. 缺少安抚（客户情绪负面时）
        negative_signals = ["投诉", "差评", "失望", "生气", "愤怒", "不满", "质量", "破损", "坏", "差", "骗"]
        customer_negative = any(s in customer_lower for s in negative_signals)
        has_empathy = any(kw in reply_lower for kw in _EMPATHY_KEYWORDS)
        if customer_negative and not has_empathy:
            violations.append({
                "type": "missing_empathy",
                "message": "客户表达不满，回复缺少安抚",
                "evidence": "未检测到抱歉/理解/安抚用语",
                "suggestion": "先表达理解和歉意，再说明处理方案",
            })

        # 6. 缺少核实（特定场景）
        lookup_scenarios = ["发货", "物流", "订单", "退款", "售后", "质量", "破损", "漏发", "错发"]
        needs_lookup = any(s in customer_lower for s in lookup_scenarios)
        has_lookup = any(kw in reply_lower for kw in _LOOKUP_KEYWORDS)
        if needs_lookup and not has_lookup:
            violations.append({
                "type": "missing_lookup",
                "message": "涉及订单/物流/售后问题，回复未体现核实动作",
                "evidence": "未检测到查询/核实/跟进等动作",
                "suggestion": "说明会帮您查询/核实具体情况",
            })

        # 7. 高风险场景遗漏升级
        high_risk_kw = ["投诉", "12315", "工商", "媒体", "曝光", "律师", "起诉", "法院", "举报", "威胁", "差评", "赔偿"]
        is_high_risk = any(kw in customer_lower for kw in high_risk_kw)
        has_escalation = any(kw in reply_lower for kw in _ESCALATION_KEYWORDS)
        if is_high_risk and not has_escalation:
            violations.append({
                "type": "missing_escalation",
                "message": "高风险场景回复未提及升级/上报/主管",
                "evidence": "未检测到升级动作",
                "suggestion": "高风险问题应说明会升级处理或转交主管",
            })

        # 计算分数
        total_weight = sum(_VIOLATION_TYPES.get(v["type"], {}).get("weight", 10) for v in violations)
        score = max(0, 100 - total_weight)

        # risk_level
        if any(v["type"] in ("offline_trade", "forbidden_claim", "refund_promise") for v in violations):
            risk_level = "high"
        elif total_weight >= 20:
            risk_level = "medium"
        else:
            risk_level = "low"

        requires_human = risk_level == "high" or any(
            v["type"] in ("offline_trade", "forbidden_claim", "refund_promise") for v in violations
        )

        return {
            "score": score,
            "risk_level": risk_level,
            "violations": violations,
            "required_actions_missing": [v["type"] for v in violations],
            "requires_human_review": requires_human,
        }
