from __future__ import annotations

from scripts.plan_product_media_observation_v3_migration import build_report


def test_v3_migration_plan_keeps_v2_rows_read_only(monkeypatch):
    class Query:
        def all(self):
            return [type("Candidate", (), {"status": "pending_review"})()]

    class Session:
        def query(self, _model):
            return Query()

        def close(self):
            pass

    monkeypatch.setattr("scripts.plan_product_media_observation_v3_migration.SessionLocal", lambda: Session())
    report = build_report()
    assert report["v2_candidate_count"] == 1
    assert report["v2_eligible_for_v3_review_gate_count"] == 0
    assert report["action"] == "retain_legacy_read_only"
    assert report["writes_performed"] == 0
