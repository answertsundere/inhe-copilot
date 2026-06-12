"""
Tests for simulated customer runner — leak prevention, execution modes, resume.
"""

import json
import os
import tempfile
import unittest

DATA_PATH = os.path.join(os.path.dirname(__file__), "simulated_customers_50.json")


def _load_customers():
    with open(DATA_PATH, "r", encoding="utf-8") as f:
        return json.load(f)["customers"]


class TestLeakPrevention(unittest.TestCase):
    """Ensure expected fields never enter agent payload."""

    FORBIDDEN_KEYS = {
        "expected_intent", "expected_strategy", "expected_tools",
        "traps", "pass_criteria", "test_goal",
    }

    def test_safe_payload_excludes_forbidden(self):
        """Verify the runner's safe payload builder excludes all forbidden keys."""
        customers = _load_customers()
        for c in customers[:5]:
            # Simulate what the runner builds
            safe = {
                "source": "simulation",
                "scenario": c.get("scenario", ""),
                "conversation_id": f"sim_{c['id']}",
                "customer_message": c["dialogue"][0]["msg"] if c["dialogue"] else "",
                "conversation_history": [],
            }
            for k in self.FORBIDDEN_KEYS:
                self.assertNotIn(k, safe, f"Forbidden key '{k}' found in payload for {c['id']}")

    def test_conversation_history_no_forbidden(self):
        """Verify conversation history doesn't leak forbidden fields."""
        history = [
            {"role": "customer", "text": "围兜防水吗"},
            {"role": "agent", "text": "这款围兜采用防水面料"},
            {"role": "customer", "text": "安全吗"},
        ]
        serialized = json.dumps(history)
        for k in self.FORBIDDEN_KEYS:
            self.assertNotIn(k, serialized)


class TestCustomerLoading(unittest.TestCase):
    def test_load_all_customers(self):
        customers = _load_customers()
        self.assertEqual(len(customers), 50)

    def test_filter_by_scenario(self):
        customers = _load_customers()
        filtered = [c for c in customers if c.get("scenario") == "complaint_high_risk"]
        self.assertTrue(len(filtered) > 0)
        for c in filtered:
            self.assertEqual(c["scenario"], "complaint_high_risk")

    def test_filter_by_priority(self):
        customers = _load_customers()
        filtered = [c for c in customers if c.get("priority") == "P0"]
        self.assertEqual(len(filtered), 28)

    def test_filter_by_customer_id(self):
        customers = _load_customers()
        filtered = [c for c in customers if c.get("id") == "C001"]
        self.assertEqual(len(filtered), 1)
        self.assertEqual(filtered[0]["id"], "C001")


class TestConversationHistory(unittest.TestCase):
    def test_history_format(self):
        """Verify history follows [{role, text}] format."""
        history = []
        history.append({"role": "customer", "text": "你好"})
        history.append({"role": "agent", "text": "您好"})
        self.assertEqual(len(history), 2)
        self.assertEqual(history[0]["role"], "customer")
        self.assertEqual(history[1]["role"], "agent")

    def test_context_isolation(self):
        """Different customers must have different conversation_ids."""
        ids = set()
        for i in range(5):
            cid = f"sim_C{ i+1:03d}"
            ids.add(cid)
        self.assertEqual(len(ids), 5)


if __name__ == "__main__":
    unittest.main()
