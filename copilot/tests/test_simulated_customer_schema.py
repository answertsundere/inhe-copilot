"""
Tests for simulated customer data schema validation.
"""

import json
import os
import unittest
from collections import Counter

DATA_PATH = os.path.join(os.path.dirname(__file__), "simulated_customers_50.json")


def _load_data():
    with open(DATA_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


class TestSchemaBasic(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = _load_data()
        cls.customers = cls.data.get("customers", [])
        cls.meta = cls.data.get("meta", {})

    def test_has_meta(self):
        self.assertIn("meta", self.data)

    def test_has_customers(self):
        self.assertIn("customers", self.data)
        self.assertIsInstance(self.customers, list)

    def test_total_customers_matches(self):
        self.assertEqual(self.meta["total_customers"], len(self.customers))

    def test_customer_ids_unique(self):
        ids = [c["id"] for c in self.customers]
        self.assertEqual(len(ids), len(set(ids)))

    def test_customer_ids_sequential(self):
        ids = sorted(c["id"] for c in self.customers)
        expected = [f"C{i:03d}" for i in range(1, 51)]
        self.assertEqual(ids, expected)


class TestSchemaPriority(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = _load_data()
        cls.customers = cls.data["customers"]

    def test_priority_distribution_correct(self):
        dist = Counter(c["priority"] for c in self.customers)
        meta_dist = self.data["meta"]["priority_distribution"]
        for k, v in meta_dist.items():
            self.assertEqual(dist.get(k, 0), v, f"Priority {k}: meta says {v}, actual {dist.get(k, 0)}")

    def test_all_priorities_valid(self):
        from tests.simulation.intent_aliases import VALID_PRIORITIES
        for c in self.customers:
            self.assertIn(c["priority"], VALID_PRIORITIES)


class TestSchemaScenario(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = _load_data()
        cls.customers = cls.data["customers"]

    def test_scenario_distribution_matches_meta(self):
        dist = Counter(c["scenario"] for c in self.customers)
        meta_dist = self.data["meta"]["scenario_distribution"]
        for k, v in meta_dist.items():
            self.assertEqual(dist.get(k, 0), v, f"Scenario {k}: meta says {v}, actual {dist.get(k, 0)}")

    def test_all_scenarios_valid(self):
        from tests.simulation.intent_aliases import VALID_SCENARIOS
        for c in self.customers:
            self.assertIn(c["scenario"], VALID_SCENARIOS)


class TestSchemaDialogue(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.customers = _load_data()["customers"]

    def test_dialogue_non_empty(self):
        for c in self.customers:
            self.assertTrue(len(c.get("dialogue", [])) > 0, f"Customer {c['id']} has empty dialogue")

    def test_turn_numbers_sequential(self):
        for c in self.customers:
            turns = [d["turn"] for d in c["dialogue"]]
            expected = list(range(1, len(turns) + 1))
            self.assertEqual(turns, expected, f"Customer {c['id']} turns not sequential")

    def test_all_speakers_customer(self):
        for c in self.customers:
            for d in c["dialogue"]:
                self.assertEqual(d["speaker"], "customer", f"Customer {c['id']} turn {d['turn']} speaker not customer")

    def test_messages_non_empty(self):
        for c in self.customers:
            for d in c["dialogue"]:
                self.assertTrue(d.get("msg", "").strip(), f"Customer {c['id']} turn {d['turn']} has empty msg")


class TestSchemaFields(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.customers = _load_data()["customers"]

    def test_expected_tools_is_list(self):
        for c in self.customers:
            self.assertIsInstance(c.get("expected_tools", []), list)

    def test_traps_is_list(self):
        for c in self.customers:
            self.assertIsInstance(c.get("traps", []), list)

    def test_pass_criteria_non_empty(self):
        for c in self.customers:
            self.assertTrue(c.get("pass_criteria", "").strip(), f"Customer {c['id']} has empty pass_criteria")

    def test_has_expected_intent(self):
        for c in self.customers:
            self.assertTrue(c.get("expected_intent", "").strip(), f"Customer {c['id']} missing expected_intent")

    def test_has_personality(self):
        for c in self.customers:
            self.assertTrue(c.get("personality", "").strip(), f"Customer {c['id']} missing personality")


if __name__ == "__main__":
    unittest.main()
