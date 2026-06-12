"""
Tests for auto-evaluator — intent, tools, risk, grounding, context memory.
"""

import unittest


class TestIntentMatching(unittest.TestCase):
    def test_exact_match(self):
        from tests.simulation.intent_aliases import intent_matches
        self.assertTrue(intent_matches("product_question", "product_question"))

    def test_alias_match(self):
        from tests.simulation.intent_aliases import intent_matches
        self.assertTrue(intent_matches("product_question", "product_consult"))
        self.assertTrue(intent_matches("product_question", "material_question"))

    def test_no_match(self):
        from tests.simulation.intent_aliases import intent_matches
        self.assertFalse(intent_matches("product_question", "logistics_eta"))
        self.assertFalse(intent_matches("complaint", "product_question"))

    def test_logistics_aliases(self):
        from tests.simulation.intent_aliases import intent_matches
        self.assertTrue(intent_matches("logistics_eta", "shipping"))
        self.assertTrue(intent_matches("logistics_eta", "logistics"))

    def test_complaint_aliases(self):
        from tests.simulation.intent_aliases import intent_matches
        self.assertTrue(intent_matches("complaint", "high_risk"))
        self.assertTrue(intent_matches("complaint", "complaint_high_risk"))


class TestStrategyMatching(unittest.TestCase):
    def test_exact(self):
        from tests.simulation.intent_aliases import strategy_matches
        self.assertTrue(strategy_matches("product_chain", "product_chain"))

    def test_alias(self):
        from tests.simulation.intent_aliases import strategy_matches
        self.assertTrue(strategy_matches("product_chain", "product_question"))
        self.assertTrue(strategy_matches("logistics_with_order", "jst_order"))


class TestToolEvaluation(unittest.TestCase):
    def _make_trace(self, tool_name, status="success"):
        return {"name": tool_name, "status": status, "summary": ""}

    def test_required_tool_executed(self):
        from tests.simulation.evaluator import check_tools
        traces = [self._make_trace("product_resolver_tool"), self._make_trace("rag_search_tool")]
        result = check_tools(["product_resolver_tool", "rag_search_tool"], traces)
        self.assertEqual(result["score"], 1.0)
        self.assertEqual(len(result["missing"]), 0)

    def test_required_tool_missing(self):
        from tests.simulation.evaluator import check_tools
        traces = [self._make_trace("product_resolver_tool")]
        result = check_tools(["product_resolver_tool", "rag_search_tool"], traces)
        self.assertIn("rag_search_tool", result["missing"])

    def test_planned_status_accepted_by_evaluator(self):
        """The evaluator checks tool names; the runner filters by status."""
        from tests.simulation.evaluator import check_tools
        traces = [{"name": "rag_search_tool", "status": "planned", "summary": ""}]
        result = check_tools(["rag_search_tool"], traces)
        # Evaluator counts by name; runner is responsible for filtering planned
        self.assertIn("rag_search_tool", result["found_expected"])


class TestRiskEvaluation(unittest.TestCase):
    HIGH_RISK_MSGS = [
        "宝宝受伤了", "医疗费用", "12315", "平台介入",
        "法律诉讼", "假货", "曝光", "赔偿", "严重安全事故",
    ]

    def test_high_risk_detected(self):
        from tests.simulation.evaluator import check_risk
        for msg in self.HIGH_RISK_MSGS:
            result = check_risk(msg, "high", True)
            self.assertTrue(len(result.get("triggered_high", [])) > 0 or result["detected_risk"] == "high",
                          f"Risk miss for: {msg}")

    def test_high_risk_missed_is_failure(self):
        from tests.simulation.evaluator import check_risk
        result = check_risk("宝宝受伤了", "low", False)
        # Should detect that risk keywords were present but risk level was low
        self.assertTrue(len(result.get("triggered_high", [])) > 0,
                       "Should detect high-risk keyword in message")


class TestContextMemory(unittest.TestCase):
    def test_repeated_question_detected(self):
        from tests.simulation.evaluator import check_context_memory
        history = [
            {"role": "customer", "text": "我的订单号是20260530001", "customer_message": "我的订单号是20260530001"},
            {"role": "agent", "text": "已查到订单20260530001", "suggested_reply": "已查到订单20260530001"},
            {"role": "customer", "text": "什么时候到", "customer_message": "什么时候到"},
        ]
        result = check_context_memory(history, "麻烦提供一下订单号", 3, "什么时候到")
        self.assertTrue(len(result.get("issues", [])) > 0)

    def test_good_context(self):
        from tests.simulation.evaluator import check_context_memory
        history = [
            {"role": "customer", "text": "围兜防水吗", "customer_message": "围兜防水吗"},
            {"role": "agent", "text": "是的采用防水面料", "suggested_reply": "是的采用防水面料"},
        ]
        result = check_context_memory(history, "这款围兜的面料是TPU防水材质", 2, "围兜防水吗")
        self.assertEqual(result["score"], 1.0)


if __name__ == "__main__":
    unittest.main()
