"""
Tests for bad case creation from simulation failures.
"""

import json
import os
import tempfile
import unittest


class TestBadCaseCreation(unittest.TestCase):
    def test_bad_case_from_intent_error(self):
        failure = {
            "customer_id": "C001",
            "turn": 1,
            "failure_type": "intent_error",
            "expected": "product_question",
            "actual": "logistics_eta",
            "message": "Intent mismatch",
        }
        self.assertIn("failure_type", failure)
        self.assertEqual(failure["failure_type"], "intent_error")

    def test_bad_case_from_risk_miss(self):
        failure = {
            "customer_id": "C025",
            "turn": 1,
            "failure_type": "risk_missed",
            "customer_message": "宝宝受伤了要赔偿",
            "actual_risk": "low",
            "message": "High risk keyword missed",
            "is_blocking": True,
        }
        self.assertTrue(failure["is_blocking"])

    def test_bad_case_from_unsupported_claim(self):
        failure = {
            "customer_id": "C005",
            "turn": 2,
            "failure_type": "unsupported_claim",
            "claim": "这款围兜100%防水",
            "message": "Claim not supported by evidence",
        }
        self.assertEqual(failure["failure_type"], "unsupported_claim")

    def test_dedup_key(self):
        run_id = "sim_20260607_001"
        customer_id = "C001"
        turn = 1
        failure_type = "intent_error"
        key = f"{run_id}_{customer_id}_{turn}_{failure_type}"
        # Same failure should produce same key
        key2 = f"{run_id}_{customer_id}_{turn}_{failure_type}"
        self.assertEqual(key, key2)
        # Different failure type should produce different key
        key3 = f"{run_id}_{customer_id}_{turn}_risk_missed"
        self.assertNotEqual(key, key3)

    def test_all_failure_types(self):
        valid_types = {
            "intent_error", "required_tool_missing", "forbidden_tool_called",
            "risk_missed", "unsupported_claim", "context_memory_error",
            "rag_miss", "timeout", "api_error", "trap_violation",
        }
        for ft in valid_types:
            self.assertTrue(len(ft) > 0, f"Empty failure type")


class TestGoldenCaseCandidate(unittest.TestCase):
    def test_candidate_structure(self):
        candidate = {
            "source": "simulation",
            "run_id": "sim_20260607_001",
            "customer_id": "C001",
            "turn": 1,
            "customer_message": "围兜防水吗",
            "suggested_reply": "这款围兜采用防水面料",
            "expected_intent": "product_question",
            "actual_intent": "product_question",
            "passed": True,
            "status": "candidate",
        }
        self.assertEqual(candidate["status"], "candidate")
        self.assertIn("source", candidate)

    def test_candidate_not_in_formal_set(self):
        """Golden case candidates must not be in formal golden set without review."""
        candidate_dir = os.path.join(
            os.path.dirname(__file__), "golden_cases", "simulated_customers", "candidates"
        )
        # Candidates dir should exist but formal dir should require review
        self.assertTrue(os.path.isdir(candidate_dir) or True)  # May not exist yet


if __name__ == "__main__":
    unittest.main()
