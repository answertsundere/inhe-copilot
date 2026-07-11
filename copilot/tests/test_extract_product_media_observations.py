from __future__ import annotations

import os
from types import SimpleNamespace

import pytest


def test_shadow_summary_keeps_formal_mutation_and_sendability_at_zero():
    from scripts.extract_product_media_observations import _summary

    report = _summary([
        {
            "model_success": True,
            "observations": [{"i_id": "IID", "observation_type": "layer_count", "warning_reasons": ["region_missing"]}],
            "rejected_evidence": [{"reason": "out_of_scope_high_risk"}],
            "warnings": [],
        }
    ], guard=SimpleNamespace(enabled=True, write_attempt_count=0), state_unchanged=True)

    assert report["database_query_only"] is True
    assert report["formal_kb_state_unchanged"] is True
    assert report["formal_kb_write_attempt_count"] == 0
    assert report["can_change_can_send_count"] == 0
    assert report["observation_type_counts"] == {"layer_count": 1}
    assert report["out_of_scope_high_risk_count"] == 1
    assert report["missing_region_count"] == 1


def test_diagnose_only_does_not_require_media_role(monkeypatch, tmp_path):
    from scripts import extract_product_media_observations as script

    monkeypatch.setattr(script, "build_media_inventory", lambda: {"database_query_only": True})
    monkeypatch.setattr(
        "sys.argv",
        ["extract_product_media_observations.py", "--diagnose-only", "--json-output", str(tmp_path / "report.json")],
    )

    assert script.main() == 0


def test_dotenv_load_preserves_process_environment(monkeypatch, tmp_path):
    from scripts.extract_product_media_observations import load_project_dotenv

    env_file = tmp_path / ".env"
    env_file.write_text("COPILOT_VLM_MODEL=from-file\nCOPILOT_VLM_ENABLED=true\n", encoding="utf-8")
    monkeypatch.setenv("COPILOT_VLM_MODEL", "from-process")
    monkeypatch.delenv("COPILOT_VLM_ENABLED", raising=False)

    assert load_project_dotenv(env_file) is True
    assert os.environ["COPILOT_VLM_MODEL"] == "from-process"
    assert os.environ["COPILOT_VLM_ENABLED"] == "true"


def test_query_only_guard_rejects_accidental_write(tmp_path):
    from sqlalchemy import create_engine, text
    from sqlalchemy.orm import sessionmaker

    from scripts.extract_product_media_observations import ReadOnlyDatabaseGuard

    engine = create_engine(f"sqlite:///{tmp_path / 'readonly.db'}")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE probe (id INTEGER PRIMARY KEY, value TEXT)"))
    session = sessionmaker(bind=engine)()
    guard = ReadOnlyDatabaseGuard(session)
    try:
        guard.enable()
        with pytest.raises(Exception):
            session.execute(text("INSERT INTO probe (value) VALUES ('blocked')"))
        assert guard.write_attempt_count == 1
    finally:
        guard.close()
        session.close()


def test_enrichment_model_apply_is_blocked_before_any_database_or_vlm_work():
    from scripts.enrich_product_specs import enrich_products

    try:
        enrich_products(dry_run=False, apply=True)
    except RuntimeError as exc:
        assert "Direct VLM writes" in str(exc)
    else:
        raise AssertionError("model-derived product specs must not write directly")


def test_enrichment_dry_run_stays_database_and_vlm_free():
    from scripts.enrich_product_specs import enrich_products

    result = enrich_products(dry_run=True, apply=False)

    assert result["database_accessed"] is False
    assert result["vlm_called"] is False
