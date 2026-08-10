"""
factual_guard 承诺词精确匹配测试
区分危险承诺与安全业务表达
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from app.agent.nodes.factual_guard import factual_guard


def _run_guard(reply: str, answer_mode: str = "policy", policy_facts: bool = True) -> dict:
    """构造 state 调用 factual_guard"""
    state = {
        "suggested_reply": reply,
        "logistics_trace": None,
        "order": None,
        "evidence": {
            "order_facts": [],
            "logistics_facts": [],
            "product_facts": [],
            "policy_facts": [{}] if policy_facts else [],
            "sop_evidence": [],
            "unknowns": [],
            "conflicts": [],
        },
        "answer_mode": answer_mode,
        "intent": "logistics_eta",
        "slots": {},
        "trace_steps": [],
    }
    return factual_guard(state)


class TestDangerousPromisesBlocked:
    """危险承诺必须被拦截"""

    def test_yiding_dao_blocked(self):
        """明天一定到 → 拦截"""
        result = _run_guard("亲，明天一定到，请您放心。")
        assert len(result["guard_warnings"]) > 0
        assert any("绝对承诺" in w for w in result["guard_warnings"])

    def test_baozheng_songda_blocked(self):
        """保证明天送达 → 拦截"""
        result = _run_guard("亲，保证明天送达。")
        assert len(result["guard_warnings"]) > 0
        assert any("绝对承诺" in w for w in result["guard_warnings"])

    def test_yiding_peichang_blocked(self):
        """一定赔偿 → 拦截"""
        result = _run_guard("亲，我们一定赔偿您的损失。")
        assert len(result["guard_warnings"]) > 0
        assert any("绝对承诺" in w for w in result["guard_warnings"])

    def test_yiding_48h_fahuo_blocked(self):
        """一定48小时内发货 → 拦截"""
        result = _run_guard("亲，一定48小时内发货。")
        assert len(result["guard_warnings"]) > 0
        assert any("绝对承诺" in w for w in result["guard_warnings"])

    def test_juedui_mei_wenti_blocked(self):
        """绝对没问题 → 拦截"""
        result = _run_guard("亲，绝对没问题。")
        assert len(result["guard_warnings"]) > 0

    def test_ensure_arrival_blocked(self):
        """确保明天到 → 拦截"""
        result = _run_guard("亲，确保明天到。")
        assert len(result["guard_warnings"]) > 0


class TestSafePhrasesNotBlocked:
    """安全业务表达不应被误伤"""

    def test_page_promise_time_safe(self):
        """以页面承诺时效为准 → 不拦截"""
        result = _run_guard("亲，以页面承诺时效为准。")
        assert len(result["guard_warnings"]) == 0

    def test_detail_page_promise_safe(self):
        """详情页承诺时效 → 不拦截"""
        result = _run_guard("亲，详情页承诺时效为48小时。")
        assert len(result["guard_warnings"]) == 0

    def test_shop_page_arrange_safe(self):
        """按店铺页面承诺时效安排发货，发出后以实际物流为准 → 不拦截"""
        reply = "亲，按店铺页面承诺时效安排发货，发出后以实际物流为准。"
        result = _run_guard(reply)
        assert len(result["guard_warnings"]) == 0

    def test_actual_logistics_safe(self):
        """以实际物流为准 → 不拦截"""
        result = _run_guard("亲，具体时效以实际物流为准。")
        assert len(result["guard_warnings"]) == 0

    def test_ensure_quality_safe(self):
        """确保安全（安全语境）→ 不拦截"""
        result = _run_guard("亲，我们已确保质量合格。")
        assert len(result["guard_warnings"]) == 0

    def test_delivery_not_received_rewrite_never_invents_signed_status_from_order_presence(self):
        state = {
            "suggested_reply": "\u4eb2\uff0c\u60a8\u7684\u5305\u88f9\u5df2\u7b7e\u6536\u3002",
            "intent": "delivery_not_received",
            "order": {"items": [{"name": "\u5546\u54c1A"}]},
            "live_order": None,
            "logistics_trace": None,
            "evidence": {
                "order_facts": [],
                "logistics_facts": [],
                "product_facts": [],
                "policy_facts": [],
                "sop_evidence": [],
                "unknowns": [],
                "conflicts": [],
            },
            "answer_mode": "human_review",
            "slots": {"order_id": "order-ref"},
            "trace_steps": [],
        }

        result = factual_guard(state)

        assert "\u5df2\u7b7e\u6536" not in result["suggested_reply"]

    def test_normal_arrange_safe(self):
        """一般会按店铺规则安排 → 不拦截"""
        result = _run_guard("亲，一般会按店铺规则安排发货。")
        assert len(result["guard_warnings"]) == 0
