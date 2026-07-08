from __future__ import annotations


def test_normalizes_accessories_to_availability_when_text_is_restock_or_purchase():
    from app.services.fact_type_metadata_normalizer import normalize_pgvector_fact_type_metadata

    result = normalize_pgvector_fact_type_metadata({
        "query_fact_type": "accessories",
        "evidence_role": "accessories",
        "source_type": "product_facts",
        "chunk_text": "这个配件可以单独购买，也支持补配",
    })

    assert result.normalized_query_fact_type == "accessory_availability"
    assert result.normalized_evidence_role == "accessory_availability"
    assert result.changed is True


def test_normalizes_installation_modification_to_structure_function():
    from app.services.fact_type_metadata_normalizer import normalize_pgvector_fact_type_metadata

    result = normalize_pgvector_fact_type_metadata({
        "query_fact_type": "installation",
        "evidence_role": "installation",
        "source_type": "product_facts",
        "chunk_text": "孔位和加装配件适配说明",
    })

    assert result.normalized_query_fact_type == "structure_function"
    assert result.reason == "structure_function_terms"


def test_media_pack_guide_gets_installation_fact_type_but_stays_media_reference():
    from app.services.fact_type_metadata_normalizer import normalize_pgvector_fact_type_metadata

    result = normalize_pgvector_fact_type_metadata({
        "query_fact_type": "",
        "evidence_role": "media_reference",
        "source_type": "media_asset",
        "media_role": "pack_guide_image",
        "chunk_text": "安装指导图",
    })

    assert result.normalized_query_fact_type == "installation"
    assert result.normalized_evidence_role == "media_reference"
    assert result.changed is True


def test_high_risk_original_fact_type_is_not_downgraded():
    from app.services.fact_type_metadata_normalizer import normalize_pgvector_fact_type_metadata

    result = normalize_pgvector_fact_type_metadata({
        "query_fact_type": "load_capacity",
        "evidence_role": "load_capacity",
        "source_type": "product_facts",
        "chunk_text": "这个写的是商品毛重 2.5kg",
    })

    assert result.normalized_query_fact_type == "load_capacity"
    assert result.high_risk_blocked is False


def test_material_safety_text_does_not_become_high_risk_certification_claim():
    from app.services.fact_type_metadata_normalizer import normalize_pgvector_fact_type_metadata

    result = normalize_pgvector_fact_type_metadata({
        "query_fact_type": "material",
        "evidence_role": "material",
        "source_type": "product_facts",
        "chunk_text": "材质安全气味检测说明",
    })

    assert result.normalized_query_fact_type == "material"
    assert result.high_risk_blocked is True
