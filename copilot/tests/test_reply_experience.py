"""
回复体验修复测试 - 覆盖 "safe but useless" 问题
目标：回复要有帮助，同时保持安全约束
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from app.agent.nodes.generate_logistics_reply import generate_logistics_reply
from app.agent.nodes.generate_reply import _generate_rule_reply
from app.agent.nodes.factual_guard import factual_guard


# ---------------------------------------------------------------------------
# 1. 物流时效承诺：无订单无商品
# ---------------------------------------------------------------------------

class TestLogisticsTimeCommitmentNoOrderNoProduct:
    """明天能不能一定到？/你们保证今天送到吗？"""

    def test_yiding_dao_no_order_explains_uncertainty(self):
        """无订单时问'明天能不能一定到'，应解释无法保证而非只问订单号"""
        state = {
            "normalized_message": "明天能不能一定到？",
            "answer_mode": "logistics_time_commitment",
            "intent": "logistics_eta",
            "matched_product_name": "",
            "slots": {},
            "trace_steps": [],
        }
        result = generate_logistics_reply(state)
        reply = result["suggested_reply"]
        assert "无法" in reply or "不能" in reply or "受" in reply, f"回复应解释无法保证，实际: {reply}"
        assert "订单号" in reply or "物流单号" in reply, f"回复应引导查询，实际: {reply}"
        assert reply.count("订单号") <= 2, f"回复不应反复只追问订单号，实际: {reply}"

    def test_baozheng_today_delivery_explains_uncertainty(self):
        """无订单时问'你们保证今天送到吗'，应明确说不能保证"""
        state = {
            "normalized_message": "你们保证今天送到吗？",
            "answer_mode": "logistics_time_commitment",
            "intent": "logistics_eta",
            "matched_product_name": "",
            "slots": {},
            "trace_steps": [],
        }
        result = generate_logistics_reply(state)
        reply = result["suggested_reply"]
        assert "无法" in reply or "不能" in reply or "绝对承诺" in reply, f"回复应说明不能保证，实际: {reply}"
        assert "实际" in reply or "物流" in reply, f"回复应提及实际物流，实际: {reply}"

    def test_time_commitment_not_just_ask_order_id(self):
        """时效承诺回复不能只有'提供订单号'一句话"""
        state = {
            "normalized_message": "明天能准时到吗？",
            "answer_mode": "logistics_time_commitment",
            "intent": "logistics_eta",
            "matched_product_name": "",
            "slots": {},
            "trace_steps": [],
        }
        result = generate_logistics_reply(state)
        reply = result["suggested_reply"]
        # 回复长度应大于 30 字（不能只是"麻烦提供订单号"）
        assert len(reply) > 30, f"回复过短，缺乏解释: {reply}"


# ---------------------------------------------------------------------------
# 2. 物流时效承诺：无订单但能匹配商品
# ---------------------------------------------------------------------------

class TestLogisticsTimeCommitmentWithProduct:
    """无订单但有商品匹配时的时效承诺回复"""

    def test_product_matched_time_commitment_explains_first(self):
        """匹配到商品时，先解释无法承诺，再给通用时效"""
        state = {
            "normalized_message": "这个书架明天能保证到吗？",
            "answer_mode": "logistics_time_commitment",
            "intent": "logistics_eta",
            "matched_product_name": "儿童书架",
            "shipping_policy": {"default_courier": "中通", "eta_days_min": 2, "eta_days_max": 4},
            "slots": {},
            "trace_steps": [],
        }
        result = generate_logistics_reply(state)
        reply = result["suggested_reply"]
        assert "无法" in reply or "不能" in reply or "受" in reply, f"回复应先解释无法保证，实际: {reply}"
        assert "2-4" in reply or "中通" in reply, f"回复应包含通用时效信息，实际: {reply}"
        assert "订单号" in reply, f"回复应引导提供订单号查询，实际: {reply}"


# ---------------------------------------------------------------------------
# 3. 产品问题无 product_facts：询问 SKU/链接/截图
# ---------------------------------------------------------------------------

class TestProductQuestionNoFacts:
    """无 product_facts 时的产品咨询回复"""

    def test_solid_wood_asks_for_sku(self):
        """'这个儿童书架是不是实木的？'无 product_facts 时应询问 SKU/链接/截图"""
        reply = _generate_rule_reply(
            msg="这个儿童书架是不是实木的？",
            intent="product_question",
            risk_level="low",
            product_name="",
            policy={},
            knowledge=[],
        )
        assert "链接" in reply or "截图" in reply or "SKU" in reply or "订单号" in reply, f"应询问商品标识，实际: {reply}"
        assert "未指定" not in reply, f"不应说'页面未指定'，实际: {reply}"
        assert "不清楚" not in reply, f"不应说'不清楚'，实际: {reply}"

    def test_product_consult_no_knowledge_asks_identifier(self):
        """product_consult 无知识时也应询问标识"""
        reply = _generate_rule_reply(
            msg="这款椅子承重多少？",
            intent="product_consult",
            risk_level="low",
            product_name="",
            policy={},
            knowledge=[],
        )
        assert "链接" in reply or "截图" in reply or "订单号" in reply, f"应询问商品标识，实际: {reply}"


# ---------------------------------------------------------------------------
# 4. factual_guard：不重写安全的时效承诺解释
# ---------------------------------------------------------------------------

class TestFactualGuardPreservesSafeExplanations:
    """factual_guard 不应把安全的解释降级为无用的追问"""

    def test_safe_explanation_not_rewritten(self):
        """安全的'无法保证'解释不应被 factual_guard 重写"""
        safe_reply = (
            "亲，非常理解您希望包裹准时到达的心情。"
            "\n但由于物流运输受天气、路况、分拣等多种因素影响，我们无法对具体到某一天或某一时刻的送达做出绝对承诺。"
            "\n实际送达时间以快递公司物流更新为准。"
            "\n如果您能提供订单号或物流单号，我可以帮您查询当前最新的物流动态和预计送达时间哦～"
        )
        state = {
            "suggested_reply": safe_reply,
            "evidence": {
                "order_facts": [],
                "logistics_facts": [],
                "product_facts": [],
                "policy_facts": [],
                "sop_evidence": [],
                "unknowns": [],
                "conflicts": [],
            },
            "answer_mode": "logistics_time_commitment",
            "intent": "logistics_eta",
            "slots": {},
            "trace_steps": [],
            "logistics_trace": None,
        }
        result = factual_guard(state)
        reply = result["suggested_reply"]
        # 应保留原回复或至少保留解释部分
        assert "无法" in reply or "不能" in reply, f"factual_guard 不应删除解释，实际: {reply}"
        assert "订单号" in reply, f"应保留引导查询，实际: {reply}"

    def test_safe_explanation_no_guard_warnings(self):
        """安全的解释不应触发 guard_warnings"""
        safe_reply = (
            "亲，但由于物流运输受天气等多种因素影响，我们无法承诺具体到某一天的送达。"
            "\n实际送达时间以快递公司物流更新为准。"
        )
        state = {
            "suggested_reply": safe_reply,
            "evidence": {
                "order_facts": [],
                "logistics_facts": [],
                "product_facts": [],
                "policy_facts": [{}],
                "sop_evidence": [],
                "unknowns": [],
                "conflicts": [],
            },
            "answer_mode": "logistics_time_commitment",
            "intent": "logistics_eta",
            "slots": {},
            "trace_steps": [],
            "logistics_trace": None,
        }
        result = factual_guard(state)
        # logistics_time_commitment 不在 B1 的 answer_mode 列表中，不应触发
        assert len(result["guard_warnings"]) == 0, f"不应有警告，实际: {result['guard_warnings']}"


# ---------------------------------------------------------------------------
# 5. detect_intent + response_strategy_router 集成
# ---------------------------------------------------------------------------

class TestTimeCommitmentIntegration:
    """端到端：时效承诺问题应被正确分类并生成有帮助的回复"""

    def test_detect_intent_flags_time_commitment(self):
        """detect_intent 应正确标记时效承诺问题"""
        from app.agent.nodes.detect_intent import detect_intent
        state = {"customer_message": "明天能不能一定到？", "trace_steps": []}
        result = detect_intent(state)
        assert result.get("is_logistics_time_commitment") is True, "应标记为时效承诺"

    def test_detect_intent_no_time_commitment(self):
        """普通物流问题不应标记为时效承诺"""
        from app.agent.nodes.detect_intent import detect_intent
        state = {"customer_message": "我的快递到哪里了？", "trace_steps": []}
        result = detect_intent(state)
        assert result.get("is_logistics_time_commitment") is not True, "普通查询不应标记为时效承诺"

    def test_strategy_router_sets_answer_mode(self):
        """response_strategy_router 应为时效承诺问题设置正确 answer_mode"""
        from app.agent.nodes.response_strategy_router import response_strategy_router
        state = {
            "intent": "logistics_eta",
            "is_logistics_time_commitment": True,
            "slots": {},
            "trace_steps": [],
        }
        result = response_strategy_router(state)
        assert result.get("answer_mode") == "logistics_time_commitment", f"应设置 answer_mode，实际: {result.get('answer_mode')}"
