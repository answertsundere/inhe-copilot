from app.services.product_structured_evidence_service import (
    build_product_spec_evidence_candidates,
    material_direct_answer_block_reason,
)


def _profile(material, source=""):
    specs = {"material": material}
    if source:
        specs["_auto_backfill"] = {"batch": {"sources": {"material": source}}}
    return {
        "product_id": 7,
        "i_id": "ITEM-7",
        "product_name": "Test product",
        "status": "published",
        "specs": specs,
        "sku_list": [{"sku_code": "SKU-7"}],
    }


def test_clean_composition_with_structured_or_rag_provenance_is_eligible():
    assert build_product_spec_evidence_candidates(_profile("PP"), requested_fact_type="material")
    assert build_product_spec_evidence_candidates(
        _profile("PP", "rag_fact:knowledge_entry:17"),
        requested_fact_type="material",
    )


def test_placeholder_provenance_blocks_even_when_value_looks_concrete():
    profile = _profile("PP", "conservative_placeholder")
    assert material_direct_answer_block_reason(profile) == "material_source_untrusted"
    assert build_product_spec_evidence_candidates(profile, requested_fact_type="material") == []


def test_strong_claim_mixed_into_material_requires_separate_review():
    profile = _profile("食品级HDPE塑料")
    assert material_direct_answer_block_reason(profile) == "material_strong_claim_mixed"
    assert build_product_spec_evidence_candidates(profile, requested_fact_type="material") == []
