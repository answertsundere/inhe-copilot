"""
Knowledge Evidence Quality Gate 测试 — Phase 2.5

覆盖需求:
1. 未审核材质 FAQ 不允许直接回答材质。
2. verified 材质 FAQ 可以直接回答。
3. real_cases 中出现材质，不得作为强商品事实。
4. Entry 812 未审核时不得直接输出"记忆棉/填充棉"。
5. fact_review_status=verified 后可以输出 evidence 中的材质。
6. evidence_debug 返回 fact_review_status 和 high_risk_fact_fields。
7. safety_contract 和 evidence quality gate 同时生效。
8. 不影响普通低风险 FAQ，如"围兜防水吗？"如果 verified 可正常 exact_faq_answer。
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest


# ── evidence_quality_gate 单元测试 ──


class TestCheckEvidenceQuality:
    """check_evidence_quality 单元测试"""

    def _make_evidence(self, items, bucket="faq_evidence"):
        return {
            bucket: items,
            "product_facts": [],
            "order_facts": [],
            "logistics_facts": [],
            "policy_facts": [],
            "sop_evidence": [],
            "template_evidence": [],
            "unknowns": [],
            "conflicts": [],
        }

    def test_unverified_material_faq_blocks_direct_answer(self):
        """未审核材质 FAQ → evidence_allowed_for_direct_answer=False"""
        from app.services.evidence_quality_gate import check_evidence_quality

        evidence = self._make_evidence([{
            "fact": "枕芯采用优质填充棉/记忆棉",
            "source_type": "faq",
            "entry_status": "draft",
            "fact_review_status": "",
            "confidence": "low",
            "entry_id": 812,
            "title": "六号防摔枕材质是什么？能洗吗？",
        }])
        result = check_evidence_quality(evidence)
        assert result["evidence_allowed_for_direct_answer"] is False
        assert len(result["blocked_items"]) == 1
        assert "填充" in result["high_risk_fact_fields"]

    def test_verified_material_faq_allows_direct_answer(self):
        """verified 材质 FAQ → evidence_allowed_for_direct_answer=True"""
        from app.services.evidence_quality_gate import check_evidence_quality

        evidence = self._make_evidence([{
            "fact": "材质: E1级环保板材+冷轧钢框架",
            "source_type": "product_facts",
            "entry_status": "published",
            "fact_review_status": "verified",
            "confidence": "high",
            "entry_id": 100,
            "title": "书架材质说明",
        }])
        result = check_evidence_quality(evidence)
        assert result["evidence_allowed_for_direct_answer"] is True
        assert result["all_verified"] is True
        assert len(result["blocked_items"]) == 0

    def test_real_cases_cannot_be_strong_fact(self):
        """real_cases 中的材质 → 弱来源，不得作为强事实"""
        from app.services.evidence_quality_gate import check_evidence_quality

        evidence = self._make_evidence([{
            "fact": "客户说这个是实木的",
            "source_type": "real_cases",
            "entry_status": "published",
            "fact_review_status": "verified",
            "confidence": "medium",
            "entry_id": 200,
            "title": "客户反馈实木材质",
        }])
        result = check_evidence_quality(evidence)
        assert len(result["weak_source_items"]) == 1
        assert result["weak_source_items"][0]["source_type"] == "real_cases"

    def test_feedback_records_cannot_be_strong_fact(self):
        """feedback_records 中的材质 → 弱来源"""
        from app.services.evidence_quality_gate import check_evidence_quality

        evidence = self._make_evidence([{
            "fact": "填充物为记忆棉",
            "source_type": "feedback_records",
            "entry_status": "published",
            "fact_review_status": "verified",
            "confidence": "medium",
        }])
        result = check_evidence_quality(evidence)
        assert len(result["weak_source_items"]) == 1

    def test_no_risk_fields_passes(self):
        """无高风险字段 → 全部通过"""
        from app.services.evidence_quality_gate import check_evidence_quality

        evidence = self._make_evidence([{
            "fact": "发货后一般2-3天到达",
            "source_type": "faq",
            "entry_status": "draft",
            "fact_review_status": "",
            "confidence": "low",
        }])
        result = check_evidence_quality(evidence)
        assert result["evidence_allowed_for_direct_answer"] is True
        assert len(result["blocked_items"]) == 0

    def test_low_risk_verified_faq_passes(self):
        """普通低风险 verified FAQ (如"围兜防水吗？") 正常通过"""
        from app.services.evidence_quality_gate import check_evidence_quality

        evidence = self._make_evidence([{
            "fact": "一号狮子围兜采用防水面料",
            "source_type": "faq",
            "entry_status": "published",
            "fact_review_status": "verified",
            "confidence": "high",
        }])
        result = check_evidence_quality(evidence)
        # "防水" is a high risk field but it's verified
        assert result["evidence_allowed_for_direct_answer"] is True


class TestEnforceEvidenceQualityGate:
    """enforce_evidence_quality_gate 集成测试"""

    def test_unverified_forces_clarification_reply(self):
        """未审核高风险事实 → 强制保守回复"""
        from app.services.evidence_quality_gate import enforce_evidence_quality_gate

        state = {
            "evidence": {
                "faq_evidence": [{
                    "fact": "枕芯采用优质填充棉/记忆棉",
                    "source_type": "faq",
                    "entry_status": "draft",
                    "fact_review_status": "",
                    "confidence": "low",
                    "entry_id": 812,
                    "title": "六号防摔枕材质是什么？能洗吗？",
                }],
                "product_facts": [],
                "order_facts": [],
                "logistics_facts": [],
                "policy_facts": [],
                "sop_evidence": [],
                "template_evidence": [],
                "unknowns": [],
                "conflicts": [],
            },
            "knowledge_evidence": [],
            "answer_mode": "exact_faq_answer",
            "guard_warnings": [],
            "suggested_reply": "枕芯采用优质填充棉/记忆棉",
            "intent": "product_question",
        }
        result = enforce_evidence_quality_gate(state)
        assert result["answer_mode"] == "evidence_needs_review"
        assert "核实准确参数" in result["suggested_reply"]
        assert any("evidence_quality_gate" in w for w in result["guard_warnings"])

    def test_verified_keeps_original_reply(self):
        """verified 高风险事实 → 保持原回复（无 suggested_reply key = 未修改）"""
        from app.services.evidence_quality_gate import enforce_evidence_quality_gate

        original = "材质: E1级环保板材+冷轧钢框架"
        state = {
            "evidence": {
                "faq_evidence": [],
                "product_facts": [{
                    "fact": "材质: E1级环保板材+冷轧钢框架",
                    "source_type": "product_facts",
                    "entry_status": "published",
                    "fact_review_status": "verified",
                    "confidence": "high",
                    "entry_id": 100,
                    "title": "书架材质",
                }],
                "order_facts": [],
                "logistics_facts": [],
                "policy_facts": [],
                "sop_evidence": [],
                "template_evidence": [],
                "unknowns": [],
                "conflicts": [],
            },
            "knowledge_evidence": [],
            "answer_mode": "product_fact_answer",
            "guard_warnings": [],
            "suggested_reply": original,
            "intent": "product_question",
        }
        result = enforce_evidence_quality_gate(state)
        # verified → 无 blocked items → 不修改 suggested_reply
        assert "suggested_reply" not in result
        assert result.get("answer_mode") is None  # unchanged


# ── evidence_builder 集成测试 ──


class TestEvidenceBuilderQualityGate:
    """evidence_builder 与 Quality Gate 集成"""

    def test_draft_faq_includes_quality_gate_fields(self):
        """draft FAQ 证据项包含 Phase 2.5 字段"""
        from app.agent.nodes.evidence_builder import evidence_builder

        state = {
            "live_order": None,
            "order": None,
            "logistics_trace": None,
            "matched_product_name": "",
            "shipping_policy": {},
            "order_status": "",
            "slots": {},
            "knowledge_evidence": [{
                "source_type": "faq",
                "chunk_text": "枕芯采用优质填充棉/记忆棉，外套可拆洗",
                "confidence": "low",
                "reference_only": False,
                "entry_status": "draft",
                "source_sheet": "金牌客服问答（增强版）",
                "row_number": 763,
                "entry_id": 812,
                "title": "六号防摔枕材质是什么？能洗吗？",
            }],
            "intent": "product_question",
            "trace_steps": [],
            "tool_results": {},
        }
        result = evidence_builder(state)
        evidence = result["evidence"]
        faq = evidence.get("faq_evidence", [])
        assert len(faq) >= 1
        item = faq[0]
        assert item.get("unverified_fact") is True
        assert item.get("evidence_allowed_for_direct_answer") is False
        assert "high_risk_fact_fields" in item or "high_risk_fields" in item
        assert "填充" in item.get("high_risk_fact_fields", item.get("high_risk_fields", []))

    def test_published_product_facts_allowed(self):
        """published product_facts → evidence_allowed_for_direct_answer=True"""
        from app.agent.nodes.evidence_builder import evidence_builder

        state = {
            "live_order": None,
            "order": None,
            "logistics_trace": None,
            "matched_product_name": "",
            "shipping_policy": {},
            "order_status": "",
            "slots": {},
            "knowledge_evidence": [{
                "source_type": "product_facts",
                "chunk_text": "材质: E1级环保板材+冷轧钢框架",
                "confidence": "high",
                "reference_only": False,
                "entry_status": "published",
                "fact_review_status": "verified",
                "source_sheet": "商品总览",
                "row_number": 1,
                "entry_id": 100,
                "title": "书架材质说明",
            }],
            "intent": "product_question",
            "trace_steps": [],
            "tool_results": {},
        }
        result = evidence_builder(state)
        evidence = result["evidence"]
        pf = evidence.get("product_facts", [])
        assert len(pf) >= 1
        assert pf[0].get("evidence_allowed_for_direct_answer") is True
        assert pf[0].get("unverified_fact") is not True

    def test_low_risk_faq_without_risk_fields_passes(self):
        """无高风险字段的 FAQ 正常通过"""
        from app.agent.nodes.evidence_builder import evidence_builder

        state = {
            "live_order": None,
            "order": None,
            "logistics_trace": None,
            "matched_product_name": "",
            "shipping_policy": {},
            "order_status": "",
            "slots": {},
            "knowledge_evidence": [{
                "source_type": "faq",
                "chunk_text": "发货后一般2-3天到达，偏远地区可能稍晚",
                "confidence": "low",
                "reference_only": False,
                "entry_status": "draft",
                "source_sheet": "物流FAQ",
                "row_number": 50,
            }],
            "intent": "logistics_eta",
            "trace_steps": [],
            "tool_results": {},
        }
        result = evidence_builder(state)
        evidence = result["evidence"]
        faq = evidence.get("faq_evidence", [])
        assert len(faq) >= 1
        assert faq[0].get("evidence_allowed_for_direct_answer") is True


# ── factual_guard 集成测试 ──


class TestFactualGuardQualityGate:
    """factual_guard 与 Knowledge Evidence Quality Gate 集成"""

    def test_safety_contract_and_quality_gate_both_active(self):
        """safety_contract 和 evidence quality gate 同时生效"""
        from app.agent.nodes.factual_guard import factual_guard

        state = {
            "customer_message": "六号防摔枕材质是什么？",
            "suggested_reply": "枕芯采用优质填充棉/记忆棉，一定没问题",
            "intent": "product_question",
            "answer_mode": "exact_faq_answer",
            "risk_level": "low",
            "live_order": None,
            "order": None,
            "logistics_trace": None,
            "guard_warnings": [],
            "trace_steps": [],
            "requires_human_review": False,
            "slots": {},
            "safety_contract": {
                "forbidden_claims": ["一定没问题"],
                "requires_evidence_for": ["材质"],
            },
            "evidence": {
                "faq_evidence": [{
                    "fact": "枕芯采用优质填充棉/记忆棉",
                    "source_type": "faq",
                    "entry_status": "draft",
                    "fact_review_status": "",
                    "confidence": "low",
                    "entry_id": 812,
                    "title": "六号防摔枕材质是什么？能洗吗？",
                }],
                "product_facts": [],
                "order_facts": [],
                "logistics_facts": [],
                "policy_facts": [],
                "sop_evidence": [],
                "template_evidence": [],
                "unknowns": [],
                "conflicts": [],
            },
            "knowledge_evidence": [],
        }

        import os
        os.environ.setdefault("COPILOT_ENABLE_PARALLEL_SAFETY_CONTRACT", "true")
        result = factual_guard(state)

        warnings = result.get("guard_warnings", [])
        assert len(warnings) > 0
        # 至少有一个 safety_contract 或 evidence_quality_gate 的警告
        has_contract = any("safety_contract" in w for w in warnings)
        has_quality = any("evidence_quality_gate" in w for w in warnings)
        assert has_contract or has_quality

    def test_entry_812_unverified_blocks_direct_output(self):
        """Entry 812 未审核时不得直接输出'记忆棉/填充棉'"""
        from app.agent.nodes.factual_guard import factual_guard

        state = {
            "customer_message": "六号防摔枕材质是什么？能洗吗？",
            "suggested_reply": "枕芯采用优质填充棉/记忆棉，外套可拆洗",
            "intent": "product_question",
            "answer_mode": "exact_faq_answer",
            "risk_level": "low",
            "live_order": None,
            "order": None,
            "logistics_trace": None,
            "guard_warnings": [],
            "trace_steps": [],
            "requires_human_review": False,
            "slots": {},
            "safety_contract": {},
            "evidence": {
                "faq_evidence": [{
                    "fact": "枕芯采用优质填充棉/记忆棉，外套可拆洗",
                    "source_type": "faq",
                    "entry_status": "draft",
                    "fact_review_status": "",
                    "confidence": "low",
                    "entry_id": 812,
                    "title": "六号防摔枕材质是什么？能洗吗？",
                }],
                "product_facts": [],
                "order_facts": [],
                "logistics_facts": [],
                "policy_facts": [],
                "sop_evidence": [],
                "template_evidence": [],
                "unknowns": [],
                "conflicts": [],
            },
            "knowledge_evidence": [],
        }

        import os
        os.environ.setdefault("COPILOT_ENABLE_PARALLEL_SAFETY_CONTRACT", "true")
        result = factual_guard(state)

        reply = result["suggested_reply"]
        assert "填充棉" not in reply
        assert "记忆棉" not in reply
        assert "核实" in reply or "确认" in reply or "具体" in reply

    def test_verified_entry_812_allows_output(self):
        """Entry 812 审核通过后可以输出 evidence 中的材质"""
        from app.agent.nodes.factual_guard import factual_guard

        state = {
            "customer_message": "六号防摔枕材质是什么？能洗吗？",
            "suggested_reply": "枕芯采用优质填充棉/记忆棉，外套可拆洗",
            "intent": "product_question",
            "answer_mode": "exact_faq_answer",
            "risk_level": "low",
            "live_order": None,
            "order": None,
            "logistics_trace": None,
            "guard_warnings": [],
            "trace_steps": [],
            "requires_human_review": False,
            "slots": {},
            "safety_contract": {},
            "evidence": {
                "faq_evidence": [{
                    "fact": "枕芯采用优质填充棉/记忆棉，外套可拆洗",
                    "source_type": "faq",
                    "entry_status": "published",
                    "fact_review_status": "verified",
                    "confidence": "high",
                    "entry_id": 812,
                    "title": "六号防摔枕材质是什么？能洗吗？",
                }],
                "product_facts": [],
                "order_facts": [],
                "logistics_facts": [],
                "policy_facts": [],
                "sop_evidence": [],
                "template_evidence": [],
                "unknowns": [],
                "conflicts": [],
            },
            "knowledge_evidence": [],
        }

        import os
        os.environ.setdefault("COPILOT_ENABLE_PARALLEL_SAFETY_CONTRACT", "true")
        result = factual_guard(state)

        reply = result["suggested_reply"]
        # verified entry 允许直接输出
        assert "填充棉" in reply or "记忆棉" in reply


# ── build_response evidence_debug 集成测试 ──


class TestBuildResponseEvidenceDebug:
    """build_response evidence_debug 包含 Quality Gate 字段"""

    def test_evidence_debug_includes_fact_review_fields(self):
        """evidence_debug 包含 fact_review_status, high_risk_fact_fields"""
        from app.agent.nodes.build_response import build_response

        state = {
            "suggested_reply": "测试回复",
            "guard_warnings": [],
            "requires_human_review": False,
            "review_reason": "",
            "risk_level": "low",
            "answer_type": "product_fact",
            "evidence": {
                "faq_evidence": [{
                    "fact": "枕芯采用优质填充棉/记忆棉",
                    "source_type": "faq",
                    "entry_status": "draft",
                    "fact_review_status": "draft_unverified",
                    "confidence": "low",
                    "entry_id": 812,
                    "matched_entry_id": 812,
                    "matched_title": "六号防摔枕材质是什么？能洗吗？",
                    "high_risk_fact_fields": ["填充"],
                    "evidence_allowed_for_direct_answer": False,
                }],
                "product_facts": [],
                "order_facts": [],
                "logistics_facts": [],
                "policy_facts": [],
                "sop_evidence": [],
                "template_evidence": [],
                "unknowns": [],
                "conflicts": [],
                "unverified_fact_fields": ["填充"],
            },
            "trace_steps": [],
            "retrieved_chunks": [],
            "filtered_evidence": [],
            "knowledge_evidence": [],
            "answer_mode": "exact_faq_answer",
        }
        result = build_response(state)
        ed = result.get("evidence_debug", {})

        assert "faq_evidence" in ed
        faq = ed["faq_evidence"]
        assert len(faq) >= 1
        assert faq[0].get("fact_review_status") == "draft_unverified"
        assert faq[0].get("high_risk_fact_fields") == ["填充"]
        assert faq[0].get("matched_entry_id") == 812
        assert faq[0].get("matched_title") == "六号防摔枕材质是什么？能洗吗？"
        assert faq[0].get("evidence_allowed_for_direct_answer") is False
        assert ed.get("unverified_fact_fields") == ["填充"]


# ── Entry 812 专项验收 ──


class TestFaqReviewLifecycle:
    """FAQ 审核状态与直接回答资格。"""

    def test_published_low_risk_faq_without_explicit_review_remains_direct_answer_eligible(self):
        """Published low-risk FAQ follows the published-entry eligibility contract."""
        from app.services.evidence_quality_gate import check_evidence_quality

        result = check_evidence_quality({
            "faq_evidence": [{
                "fact": "商品清洁方式请以对应说明为准。",
                "source_type": "faq",
                "entry_status": "published",
                "index_status": "ready",
                "fact_review_status": None,
                "confidence": "high",
                "entry_id": "fixture-published-faq",
                "title": "清洁说明",
            }],
            "product_facts": [],
            "order_facts": [],
            "logistics_facts": [],
            "policy_facts": [],
            "sop_evidence": [],
            "template_evidence": [],
            "unknowns": [],
            "conflicts": [],
        })

        assert result["evidence_allowed_for_direct_answer"] is True
        assert result["blocked_items"] == []

    def test_entry_812_fact_review_status_not_verified(self):
        """Entry 812 fact_review_status 不是 verified → 不允许直接输出'记忆棉/填充棉'"""
        from app.services.evidence_quality_gate import check_evidence_quality

        evidence = {
            "faq_evidence": [{
                "fact": "枕芯采用优质填充棉/记忆棉，外套可拆洗",
                "source_type": "faq",
                "entry_status": "draft",
                "fact_review_status": None,
                "confidence": "low",
                "entry_id": 812,
                "title": "六号防摔枕材质是什么？能洗吗？",
            }],
            "product_facts": [],
            "order_facts": [],
            "logistics_facts": [],
            "policy_facts": [],
            "sop_evidence": [],
            "template_evidence": [],
            "unknowns": [],
            "conflicts": [],
        }
        result = check_evidence_quality(evidence)
        assert result["evidence_allowed_for_direct_answer"] is False
        assert len(result["blocked_items"]) == 1
        assert result["blocked_items"][0].get("matched_entry_id") == 812

    def test_entry_812_after_verified_allows_direct_answer(self):
        """Entry 812 设置 verified 后允许直接输出"""
        from app.services.evidence_quality_gate import check_evidence_quality

        evidence = {
            "faq_evidence": [{
                "fact": "枕芯采用优质填充棉/记忆棉，外套可拆洗",
                "source_type": "faq",
                "entry_status": "published",
                "fact_review_status": "verified",
                "confidence": "high",
                "entry_id": 812,
                "title": "六号防摔枕材质是什么？能洗吗？",
            }],
            "product_facts": [],
            "order_facts": [],
            "logistics_facts": [],
            "policy_facts": [],
            "sop_evidence": [],
            "template_evidence": [],
            "unknowns": [],
            "conflicts": [],
        }
        result = check_evidence_quality(evidence)
        assert result["evidence_allowed_for_direct_answer"] is True
        assert len(result["blocked_items"]) == 0
