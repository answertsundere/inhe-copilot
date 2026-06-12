"""
Skill Router - 根据客户消息和上下文判断应使用的 skill/scenario
基于规则关键词匹配，初期不使用 ML
"""

import logging

logger = logging.getLogger(__name__)

# 关键词映射表
_SKILL_KEYWORDS = {
    "shipping": ["发货", "物流", "快递", "运输", "签收", "派送", "揽收", "配送", "什么时候发", "几天到", "没到", "未收到", "丢件", "停发", "延迟", "催发", "催快递", "查物流", "跟踪", "单号", "快递站", "驿站", "自提"],
    "refund": ["退", "换", "售后", "保修", "维修", "补偿", "赔偿", "退款", "退货", "拒收", "七天无理由", "不想要", "不满意", "补发", "漏发", "少发", "错发", "发错"],
    "product_consult": ["材质", "尺寸", "规格", "颜色", "安装", "使用", "功能", "重量", "气味", "味道", "甲醛", "承重", "容量", "升降", "调节", "多高", "多宽", "多长", "多大", "怎么装", "怎么用", "好用吗", "结实", "稳", "晃", "摇", "掉漆", "生锈"],
    "complaint": ["投诉", "12315", "差评", "曝光", "媒体", "工商", "律师", "起诉", "法院", "举报", "威胁", "欺骗", "骗子", "虚假宣传", "欺诈", "坑人", "黑心", "无良", "骗", "假的", "仿冒", "山寨"],
    "quality_issue": ["质量", "瑕疵", "划痕", "开裂", "变形", "掉漆", "生锈", "坏", "次品", "不合格", "有毛病", "有问题", " defective", "破", "烂", "歪", "松", "散", "塌", "裂", "缺", "断", "毛刺", "不平", "不稳"],
    "price_promotion": ["价格", "优惠", "活动", "券", "满减", "折扣", "降价", "保价", "差价", "赠品", "红包", "秒杀", "促销", "便宜", "贵", "降价", "涨价", "多少钱", "怎么买", "能优惠", "有活动", "送什么"],
    "logistics": ["物流", "快递", "运输", "签收", "派送", "揽收", "配送", "中转", "分拣", "网点", "站点", "驿站", "自提", "送货上门", "放门口", "放驿站", "没收到", "显示签收", "已签收", "未签收"],
}

# 风险等级对 skill 的映射（用于兜底）
_RISK_SKILL_PRIORITY = {
    "high": ["complaint", "quality_issue", "refund"],
    "medium": ["refund", "shipping", "quality_issue"],
    "low": ["product_consult", "shipping", "price_promotion"],
}


class SkillRouter:
    """技能路由器"""

    def route(self, customer_message: str, risk_level: str = "low", context: dict = None) -> dict:
        """
        判断应使用的 skill。
        返回 {"skill": str, "intent": str, "matched_keywords": list}
        """
        msg_lower = customer_message.lower()
        scores = {}
        matched_keywords = []

        for skill, keywords in _SKILL_KEYWORDS.items():
            score = 0
            for kw in keywords:
                if kw in msg_lower:
                    score += len(kw)  # 长关键词权重更高
                    matched_keywords.append(kw)
            if score > 0:
                scores[skill] = score

        if scores:
            best_skill = max(scores, key=scores.get)
        else:
            # 兜底：按风险等级选默认 skill
            defaults = _RISK_SKILL_PRIORITY.get(risk_level, ["general"])
            best_skill = defaults[0]

        # 去重 matched_keywords
        matched_keywords = list(dict.fromkeys(matched_keywords))[:10]

        return {
            "skill": best_skill,
            "intent": best_skill,
            "matched_keywords": matched_keywords,
        }
