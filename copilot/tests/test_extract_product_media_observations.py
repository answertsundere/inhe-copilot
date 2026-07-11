from __future__ import annotations


def test_shadow_summary_keeps_formal_mutation_and_sendability_at_zero():
    from scripts.extract_product_media_observations import _summary

    report = _summary([
        {
            "model_success": True,
            "observations": [{"i_id": "IID", "observation_type": "layer_count", "warning_reasons": ["region_missing"]}],
            "rejected_evidence": [{"reason": "out_of_scope_high_risk"}],
            "warnings": [],
        }
    ])

    assert report["formal_kb_mutation_count"] == 0
    assert report["can_change_can_send_count"] == 0
    assert report["observation_type_counts"] == {"layer_count": 1}
    assert report["out_of_scope_high_risk_count"] == 1
    assert report["missing_region_count"] == 1


def test_diagnose_only_does_not_require_media_role(monkeypatch, tmp_path):
    from scripts import extract_product_media_observations as script

    monkeypatch.setattr(script, "build_media_inventory", lambda: {"formal_kb_mutation_count": 0})
    monkeypatch.setattr(
        "sys.argv",
        ["extract_product_media_observations.py", "--diagnose-only", "--json-output", str(tmp_path / "report.json")],
    )

    assert script.main() == 0


def test_enrichment_model_apply_is_blocked_before_any_database_work():
    from scripts.enrich_product_specs import enrich_products

    try:
        enrich_products(limit=1, dry_run=False, apply=True, model="test")
    except RuntimeError as exc:
        assert "Direct VLM writes" in str(exc)
    else:
        raise AssertionError("model-derived product specs must not write directly")
