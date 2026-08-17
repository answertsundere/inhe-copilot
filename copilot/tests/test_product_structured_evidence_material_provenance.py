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
        _profile("PP"),
        requested_fact_type="material_composition",
    )
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


def test_product_overview_uses_only_low_risk_verified_profile_fields():
    profile = _profile("PP")
    profile["source_version"] = 3
    profile["source_updated_at"] = "2026-08-17T12:00:00"
    profile["requested_sku"] = "SKU-7"
    profile["specs"].update({
        "size": "60*40*90cm",
        "install_method": "卡扣式组装",
        "accessories": ["层板", "连接件"],
        "load_capacity": "100kg",
        "age_range": "3岁以上",
        "certification": "检测合格",
        "pinch_safety": "防夹手",
    })

    candidates = build_product_spec_evidence_candidates(
        profile,
        requested_fact_type="product_overview",
    )

    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate["fact_type"] == "product_overview"
    assert candidate["requested_fact_type"] == "product_overview"
    assert candidate["sku"] == "SKU-7"
    assert candidate["source_version"] == 3
    assert candidate["source_updated_at"] == "2026-08-17T12:00:00"
    assert candidate["source_field_keys"] == [
        "material",
        "size",
        "install_method",
        "accessories",
    ]
    assert "PP" in candidate["customer_text"]
    assert "60*40*90cm" in candidate["customer_text"]
    assert "卡扣式组装" in candidate["customer_text"]
    assert "层板" in candidate["customer_text"]
    assert "100kg" not in candidate["customer_text"]
    assert "3岁以上" not in candidate["customer_text"]
    assert "检测合格" not in candidate["customer_text"]
    assert "防夹手" not in candidate["customer_text"]
    assert candidate["can_direct_answer"] is True


def test_product_overview_is_unavailable_when_only_restricted_fields_exist():
    profile = {
        "product_id": 8,
        "i_id": "ITEM-8",
        "product_name": "Restricted-only product",
        "status": "published",
        "specs": {
            "load_capacity": "100kg",
            "age_range": "3岁以上",
            "certification": "检测合格",
            "pinch_safety": "防夹手",
        },
    }

    assert build_product_spec_evidence_candidates(
        profile,
        requested_fact_type="product_overview",
    ) == []


def test_product_overview_keeps_direct_facts_but_drops_reference_placeholders():
    profile = _profile("PE PP \u4e0d\u9508\u94a2")
    profile["specs"].update({
        "size": "\u5df2\u6536\u5f55\u5c3a\u5bf8\u56fe\uff0c\u5177\u4f53\u5c3a\u5bf8\u4ee5\u5c3a\u5bf8\u56fe\u6216\u5546\u54c1\u8be6\u60c5\u9875\u6807\u6ce8\u4e3a\u51c6",
        "install_method": "\u5df2\u6536\u5f55\u5b89\u88c5\u89c6\u9891\uff0c\u5efa\u8bae\u6309\u5b89\u88c5\u89c6\u9891\u6216\u8bf4\u660e\u4e66\u6b65\u9aa4\u7ec4\u88c5",
        "detachable": "\u672a\u5728\u73b0\u6709\u7ed3\u6784\u5316\u8d44\u6599\u4e2d\u660e\u786e\u662f\u5426\u53ef\u62c6\u5378\uff0c\u4ee5\u8bf4\u660e\u4e66\u4e3a\u51c6",
        "accessories": "\u5177\u4f53\u914d\u4ef6\u6e05\u5355\u4ee5\u6253\u5305\u6307\u5357\u6216\u5b9e\u7269\u5305\u88c5\u4e3a\u51c6",
    })

    candidates = build_product_spec_evidence_candidates(
        profile,
        requested_fact_type="product_overview",
    )

    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate["source_field_keys"] == ["material"]
    assert candidate["customer_text"] == (
        "\u8fd9\u6b3e\u5546\u54c1\u5df2\u6838\u5b9e\u7684\u4f4e\u98ce\u9669\u8d44\u6599\u5305\u62ec\uff1a"
        "\u6750\u8d28\uff1aPE PP \u4e0d\u9508\u94a2\u3002"
    )


def test_product_overview_is_unavailable_when_all_low_risk_fields_are_placeholders():
    profile = _profile("\u5f85\u786e\u8ba4")
    profile["specs"].update({
        "size": "\u5177\u4f53\u5c3a\u5bf8\u4ee5\u5546\u54c1\u8be6\u60c5\u9875\u4e3a\u51c6",
        "install_method": "\u5df2\u6536\u5f55\u5b89\u88c5\u89c6\u9891",
    })

    assert build_product_spec_evidence_candidates(
        profile,
        requested_fact_type="product_overview",
    ) == []
