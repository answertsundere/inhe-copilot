"""
测试 Post-generation Grounding Validation
"""

import pytest
from app.services.grounding_validation_service import (
    validate_reply_grounding,
    _rewrite_fallback_reply,
    INTENT_TO_ALLOWED_FACT_TYPES,
)
from app.agent.nodes.post_generation_grounding_guard import post_generation_grounding_guard


class TestGroundingValidationService:

    def test_passed_when_claims_in_evidence(self):
        state = {
            "suggested_reply": "亲，一号狮子围兜采用TPU防水材质，可以放心使用。",
            "intent": "product_question",
            "evidence": {
                "product_facts": [
                    {"fact": "一号狮子围兜采用TPU防水材质"},
                ],
            },
            "filtered_evidence": [],
            "knowledge_evidence": [],
        }
        result = validate_reply_grounding(state)
        assert result["passed"] is True
        assert result["unsupported_claims"] == []

    def test_fails_when_product_fact_not_in_evidence(self):
        state = {
            "suggested_reply": "亲，一号狮子围兜采用实木材质。",
            "intent": "product_question",
            "evidence": {
                "product_facts": [
                    {"fact": "一号狮子围兜采用TPU防水材质"},
                ],
            },
            "filtered_evidence": [],
            "knowledge_evidence": [],
        }
        result = validate_reply_grounding(state)
        assert result["passed"] is False
        assert any(c["fact_type"] == "product_fact" for c in result["unsupported_claims"])

    def test_fails_when_logistics_status_not_in_evidence(self):
        state = {
            "suggested_reply": "亲，您的包裹已签收。",
            "intent": "logistics_trace",
            "evidence": {
                "logistics_facts": [
                    {"fact": "包裹运输中"},
                ],
            },
            "filtered_evidence": [],
            "knowledge_evidence": [],
        }
        result = validate_reply_grounding(state)
        assert result["passed"] is False
        assert any(c["fact_type"] == "logistics_fact" for c in result["unsupported_claims"])

    def test_customer_attributed_logistics_status_is_context_not_agent_fact(self):
        state = {
            "customer_message": "\u7269\u6d41\u663e\u793a\u5df2\u7b7e\u6536\uff0c\u4f46\u6211\u6ca1\u6536\u5230\u3002",
            "suggested_reply": (
                "\u4eb2\uff0c\u60a8\u53cd\u9988\u7269\u6d41\u663e\u793a\u5df2\u7b7e\u6536\u4f46\u672a\u6536\u5230\uff0c"
                "\u5efa\u8bae\u5148\u6838\u5b9e\u5bb6\u4eba\u3001\u95e8\u536b\u6216\u9a7f\u7ad9\u662f\u5426\u4ee3\u6536\u3002"
            ),
            "intent": "delivery_not_received",
            "evidence": {
                "sop_evidence": [{"fact": "\u7b7e\u6536\u4e89\u8bae\u53ef\u6838\u5b9e\u4ee3\u6536\u60c5\u51b5\u5e76\u8fdb\u884c\u4eba\u5de5\u590d\u6838\u3002"}],
            },
            "filtered_evidence": [],
            "knowledge_evidence": [],
        }

        result = validate_reply_grounding(state)

        assert result["passed"] is True
        assert not any(c["fact_type"] == "logistics_fact" for c in result["unsupported_claims"])

    def test_unattributed_logistics_status_still_requires_evidence(self):
        state = {
            "customer_message": "\u7269\u6d41\u663e\u793a\u5df2\u7b7e\u6536\uff0c\u4f46\u6211\u6ca1\u6536\u5230\u3002",
            "suggested_reply": "\u4eb2\uff0c\u60a8\u7684\u5305\u88f9\u5df2\u7b7e\u6536\uff0c\u8bf7\u7b49\u5f85\u67e5\u8be2\u3002",
            "intent": "delivery_not_received",
            "evidence": {
                "sop_evidence": [{"fact": "\u7b7e\u6536\u4e89\u8bae\u53ef\u6838\u5b9e\u4ee3\u6536\u60c5\u51b5\u5e76\u8fdb\u884c\u4eba\u5de5\u590d\u6838\u3002"}],
            },
            "filtered_evidence": [],
            "knowledge_evidence": [],
        }

        result = validate_reply_grounding(state)

        assert result["passed"] is False
        assert any(c["fact_type"] == "logistics_fact" for c in result["unsupported_claims"])

    def test_conditional_logistics_status_is_not_current_order_fact(self):
        state = {
            "suggested_reply": (
                "\u5982\u679c\u6838\u5bf9\u540e\u53d1\u73b0\u72b6\u6001\u5f02\u5e38\uff0c"
                "\u4f8b\u5982\u663e\u793a\u5df2\u7b7e\u6536\uff0c\u8bf7\u5148\u6838\u5b9e\u662f\u5426\u4ee3\u6536\u3002"
            ),
            "intent": "delivery_not_received",
            "evidence": {
                "sop_evidence": [{"fact": "\u7b7e\u6536\u4e89\u8bae\u53ef\u6838\u5b9e\u4ee3\u6536\u60c5\u51b5\u5e76\u8fdb\u884c\u4eba\u5de5\u590d\u6838\u3002"}],
            },
            "filtered_evidence": [],
            "knowledge_evidence": [],
        }

        result = validate_reply_grounding(state)

        assert result["passed"] is True
        assert not any(c["fact_type"] == "logistics_fact" for c in result["unsupported_claims"])

    def test_passes_when_logistics_status_in_evidence(self):
        state = {
            "suggested_reply": "亲，您的包裹已签收。",
            "intent": "logistics_trace",
            "evidence": {
                "logistics_facts": [
                    {"fact": "包裹已签收"},
                ],
            },
            "filtered_evidence": [],
            "knowledge_evidence": [],
        }
        result = validate_reply_grounding(state)
        assert result["passed"] is True

    def test_fails_when_aftersales_promise_not_allowed(self):
        state = {
            "suggested_reply": "亲，已为您退款。",
            "intent": "product_question",
            "evidence": {
                "product_facts": [
                    {"fact": "一号狮子围兜采用TPU防水材质"},
                ],
            },
            "filtered_evidence": [],
            "knowledge_evidence": [],
        }
        result = validate_reply_grounding(state)
        assert result["passed"] is False
        assert any(c["fact_type"] == "aftersales_promise" for c in result["unsupported_claims"])

    def test_empty_reply_skipped(self):
        state = {"suggested_reply": "", "intent": "product_question"}
        result = validate_reply_grounding(state)
        assert result["passed"] is True
        assert result["checked"] is True
        assert result["evidence_text_length"] == 0

    def test_fallback_mode_resolution(self):
        state = {
            "suggested_reply": "亲，一号狮子围兜采用实木材质。",
            "intent": "product_question",
            "evidence": {
                "product_facts": [
                    {"fact": "一号狮子围兜采用TPU防水材质"},
                ],
            },
            "filtered_evidence": [],
            "knowledge_evidence": [],
        }
        result = validate_reply_grounding(state)
        assert result["fallback_used"] is True
        assert result["fallback_mode"] == "product_fact_answer"

    def test_fallback_rewrite_product(self):
        state = {
            "suggested_reply": "",
            "intent": "product_question",
            "matched_product_name": "一号狮子围兜",
        }
        reply = _rewrite_fallback_reply(state, "product_fact_answer")
        assert "核实" in reply or "确认" in reply

    def test_fallback_rewrite_logistics(self):
        state = {
            "suggested_reply": "",
            "intent": "logistics_eta",
        }
        reply = _rewrite_fallback_reply(state, "no_evidence_clarification")
        assert "物流" in reply or "订单号" in reply

    def test_fallback_rewrite_aftersales(self):
        state = {
            "suggested_reply": "",
            "intent": "aftersales",
        }
        reply = _rewrite_fallback_reply(state, "no_evidence_clarification")
        assert "售后" in reply or "订单号" in reply

    def test_intent_mapping_coverage(self):
        # 关键 intent 必须在映射中
        required = {
            "product_question", "product_consult",
            "logistics_eta", "logistics_trace", "shipping", "logistics",
            "aftersales", "refund", "complaint",
            "installation", "delivery_not_received",
        }
        assert required.issubset(set(INTENT_TO_ALLOWED_FACT_TYPES.keys()))

    def test_intent_mapping_no_empty_sets(self):
        for intent, allowed in INTENT_TO_ALLOWED_FACT_TYPES.items():
            assert len(allowed) > 0, f"intent={intent} has empty allowed set"

    def test_node_skips_when_no_reply(self):
        state = {"suggested_reply": "", "trace_steps": []}
        result = post_generation_grounding_guard(state)
        assert result["trace_steps"][0]["status"] == "skipped"

    def test_node_blocks_and_rewrites(self):
        state = {
            "suggested_reply": "亲，一号狮子围兜采用实木材质。",
            "intent": "product_question",
            "answer_mode": "faq_answer",
            "generation_mode": "llm",
            "guard_warnings": [],
            "trace_steps": [],
            "evidence": {
                "product_facts": [
                    {"fact": "一号狮子围兜采用TPU防水材质"},
                ],
            },
            "filtered_evidence": [],
            "knowledge_evidence": [],
        }
        result = post_generation_grounding_guard(state)
        assert result["post_generation_grounding"]["passed"] is False
        assert result["post_generation_grounding"]["fallback_used"] is True
        # 回复被重写了
        assert result["suggested_reply"] != state["suggested_reply"]
        assert result["generation_mode"] == "grounding_fallback"

    def test_node_passes_and_preserves_reply(self):
        state = {
            "suggested_reply": "亲，一号狮子围兜采用TPU防水材质。",
            "intent": "product_question",
            "answer_mode": "faq_answer",
            "generation_mode": "llm",
            "guard_warnings": [],
            "trace_steps": [],
            "evidence": {
                "product_facts": [
                    {"fact": "一号狮子围兜采用TPU防水材质"},
                ],
            },
            "filtered_evidence": [],
            "knowledge_evidence": [],
        }
        result = post_generation_grounding_guard(state)
        assert result["post_generation_grounding"]["passed"] is True
        assert result["suggested_reply"] == state["suggested_reply"]

    def test_node_appends_guard_warnings(self):
        state = {
            "suggested_reply": "亲，已为您退款。",
            "intent": "product_question",
            "guard_warnings": ["existing_warning"],
            "trace_steps": [],
            "evidence": {
                "product_facts": [
                    {"fact": "一号狮子围兜采用TPU防水材质"},
                ],
            },
            "filtered_evidence": [],
            "knowledge_evidence": [],
        }
        result = post_generation_grounding_guard(state)
        assert len(result["guard_warnings"]) > 1
        assert "existing_warning" in result["guard_warnings"]

    # ========== 反例测试：否定关系、数值一致性、无证据严格拦截 ==========

    def test_blocks_signed_status_without_evidence(self):
        """无证据时，回复中出现'已签收'必须拦截。"""
        state = {
            "suggested_reply": "亲，您的包裹已签收。",
            "intent": "logistics_trace",
            "evidence": {},
            "filtered_evidence": [],
            "knowledge_evidence": [],
        }
        result = validate_reply_grounding(state)
        assert result["passed"] is False
        assert any(c["fact_type"] == "logistics_fact" for c in result["unsupported_claims"])

    def test_blocks_product_fact_without_evidence(self):
        """无证据时，回复中出现商品参数必须拦截。"""
        state = {
            "suggested_reply": "亲，这款围兜是实木材质的。",
            "intent": "product_question",
            "evidence": {},
            "filtered_evidence": [],
            "knowledge_evidence": [],
        }
        result = validate_reply_grounding(state)
        assert result["passed"] is False
        assert any(c["fact_type"] == "product_fact" for c in result["unsupported_claims"])

    def test_blocks_aftersales_promise_without_evidence(self):
        """无证据时，回复中出现售后承诺必须拦截。"""
        state = {
            "suggested_reply": "亲，已为您退款。",
            "intent": "logistics_trace",
            "evidence": {},
            "filtered_evidence": [],
            "knowledge_evidence": [],
        }
        result = validate_reply_grounding(state)
        assert result["passed"] is False
        assert any(c["fact_type"] == "aftersales_promise" for c in result["unsupported_claims"])

    def test_passes_clarification_without_evidence(self):
        """无证据时，纯解释性回复（不含具体事实）应通过。"""
        state = {
            "suggested_reply": "亲，关于物流时效无法精确保证，受多种因素影响。",
            "intent": "logistics_eta",
            "evidence": {},
            "filtered_evidence": [],
            "knowledge_evidence": [],
        }
        result = validate_reply_grounding(state)
        assert result["passed"] is True

    def test_blocks_negation_conflict_not_waterproof_vs_waterproof(self):
        """证据'不防水'，回复'防水' → 矛盾，必须拦截。"""
        state = {
            "suggested_reply": "亲，这款围兜是防水的。",
            "intent": "product_question",
            "evidence": {
                "product_facts": [
                    {"fact": "一号狮子围兜不防水"},
                ],
            },
            "filtered_evidence": [],
            "knowledge_evidence": [],
        }
        result = validate_reply_grounding(state)
        assert result["passed"] is False
        assert any(
            c["fact_type"] == "negation_conflict" and "防水" in c["reason"]
            for c in result["unsupported_claims"]
        )

    def test_blocks_negation_conflict_wood_vs_not_wood(self):
        """证据'实木'，回复'不是实木' → 矛盾，必须拦截。"""
        state = {
            "suggested_reply": "亲，这款围兜不是实木的。",
            "intent": "product_question",
            "evidence": {
                "product_facts": [
                    {"fact": "一号狮子围兜采用实木材质"},
                ],
            },
            "filtered_evidence": [],
            "knowledge_evidence": [],
        }
        result = validate_reply_grounding(state)
        assert result["passed"] is False
        assert any(
            c["fact_type"] == "negation_conflict" and "实木" in c["reason"]
            for c in result["unsupported_claims"]
        )

    def test_stainless_steel_does_not_negate_following_material_label(self):
        state = {
            "suggested_reply": "亲，这款商品的材质信息为：PE、PP、不锈钢。\n材质：PE、PP、不锈钢。",
            "intent": "product_question",
            "evidence": {
                "product_facts": [
                    {"fact": "这款商品的材质为PE、PP、不锈钢。"},
                ],
            },
            "filtered_evidence": [],
            "knowledge_evidence": [],
        }

        result = validate_reply_grounding(state)

        assert not any(c["fact_type"] == "negation_conflict" for c in result["unsupported_claims"])

    def test_blocks_number_conflict_10kg_vs_100kg(self):
        """证据'承重10kg'，回复'承重100kg' → 数值矛盾，必须拦截。"""
        state = {
            "suggested_reply": "亲，这款围兜承重100kg。",
            "intent": "product_question",
            "evidence": {
                "product_facts": [
                    {"fact": "一号狮子围兜承重10kg"},
                ],
            },
            "filtered_evidence": [],
            "knowledge_evidence": [],
        }
        result = validate_reply_grounding(state)
        assert result["passed"] is False
        assert any(
            c["fact_type"] == "number_conflict" and "10" in c["reason"] and "100" in c["reason"]
            for c in result["unsupported_claims"]
        )

    def test_passes_number_within_tolerance(self):
        """证据'承重10kg'，回复'约10kg' → 在±10%容差内，应通过。"""
        state = {
            "suggested_reply": "亲，这款围兜承重约10kg。",
            "intent": "product_question",
            "evidence": {
                "product_facts": [
                    {"fact": "一号狮子围兜承重10kg"},
                ],
            },
            "filtered_evidence": [],
            "knowledge_evidence": [],
        }
        result = validate_reply_grounding(state)
        assert result["passed"] is True

    def test_blocks_number_different_unit_same_value(self):
        """证据'10kg'，回复'10g' → 单位不同，应拦截。"""
        state = {
            "suggested_reply": "亲，这款围兜承重10g。",
            "intent": "product_question",
            "evidence": {
                "product_facts": [
                    {"fact": "一号狮子围兜承重10kg"},
                ],
            },
            "filtered_evidence": [],
            "knowledge_evidence": [],
        }
        result = validate_reply_grounding(state)
        assert result["passed"] is False
        assert any(c["fact_type"] == "number_conflict" for c in result["unsupported_claims"])

    def test_passes_when_number_evidence_matches(self):
        """证据'10kg'，回复'10kg' → 完全一致，应通过。"""
        state = {
            "suggested_reply": "亲，这款围兜承重10kg。",
            "intent": "product_question",
            "evidence": {
                "product_facts": [
                    {"fact": "一号狮子围兜承重10kg"},
                ],
            },
            "filtered_evidence": [],
            "knowledge_evidence": [],
        }
        result = validate_reply_grounding(state)
        assert result["passed"] is True

    def test_accepts_exact_product_hub_attribute_title(self):
        state = {
            "suggested_reply": "亲，这款商品的尺寸为36.5x22cm。",
            "intent": "product_question",
            "evidence": {"product_facts": []},
            "filtered_evidence": [],
            "knowledge_evidence": [{
                "source_type": "product_facts",
                "protocol_source_type": "product_data_hub",
                "title": "尺寸",
                "chunk_text": "36.5x22cm",
                "review_status": "confirmed",
            }],
        }

        result = validate_reply_grounding(state)

        assert result["passed"] is True
        assert result["fallback_used"] is False
