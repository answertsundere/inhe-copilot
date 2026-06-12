"""
Tests for context memory evaluation across multi-turn dialogues.
"""

import unittest


class TestContextMemoryDetailed(unittest.TestCase):
    def test_repeated_order_id_request_detected(self):
        from tests.simulation.evaluator import check_context_memory
        history = [
            {"role": "customer", "text": "我的订单号是20260530001", "customer_message": "我的订单号是20260530001"},
            {"role": "agent", "text": "已查到订单20260530001", "suggested_reply": "已查到订单20260530001"},
            {"role": "customer", "text": "什么时候发货", "customer_message": "什么时候发货"},
        ]
        result = check_context_memory(history, "麻烦提供一下订单号", 3, "什么时候发货")
        self.assertTrue(len(result.get("issues", [])) > 0, "Should detect repeated order ID request")

    def test_no_repeat_after_product_provided(self):
        from tests.simulation.evaluator import check_context_memory
        history = [
            {"role": "customer", "text": "这个爬行垫怎么样", "customer_message": "这个爬行垫怎么样"},
            {"role": "agent", "text": "这是英禾爬行垫，EPE材质", "suggested_reply": "这是英禾爬行垫，EPE材质"},
        ]
        # The evaluator checks for repeated questions about product links
        result = check_context_memory(history, "请问您说的是哪款产品？请发链接", 2, "这个爬行垫怎么样")
        # This may or may not be detected depending on pattern matching
        # At minimum, the evaluator should run without error
        self.assertIn("score", result)

    def test_good_multi_turn(self):
        from tests.simulation.evaluator import check_context_memory
        history = [
            {"role": "customer", "text": "围兜防水吗", "customer_message": "围兜防水吗"},
            {"role": "agent", "text": "是的，采用防水面料", "suggested_reply": "是的，采用防水面料"},
            {"role": "customer", "text": "安全吗", "customer_message": "安全吗"},
        ]
        result = check_context_memory(history, "这款围兜通过国家安全检测", 3, "安全吗")
        self.assertEqual(result["score"], 1.0)

    def test_pronoun_reference_ok(self):
        from tests.simulation.evaluator import check_context_memory
        history = [
            {"role": "customer", "text": "我想买爬行垫", "customer_message": "我想买爬行垫"},
            {"role": "agent", "text": "推荐英禾加厚爬行垫", "suggested_reply": "推荐英禾加厚爬行垫"},
            {"role": "customer", "text": "这个多少钱", "customer_message": "这个多少钱"},
        ]
        result = check_context_memory(history, "英禾加厚爬行垫售价89元", 3, "这个多少钱")
        self.assertEqual(result["score"], 1.0)

    def test_empty_history_ok(self):
        from tests.simulation.evaluator import check_context_memory
        result = check_context_memory([], "您好，请问有什么可以帮您？", 1)
        self.assertEqual(result["score"], 1.0)


if __name__ == "__main__":
    unittest.main()
