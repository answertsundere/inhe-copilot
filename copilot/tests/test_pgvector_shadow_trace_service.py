from __future__ import annotations


class _PgService:
    def check(self):
        return {"pgvector_available": True, "extension_available": True, "error": ""}

    def retrieve(self, **kwargs):
        if kwargs.get("allowed_source_types") == ["media_asset"]:
            return [{
                "chunk_id": "pgvector:media:1",
                "source_type": "media_asset",
                "evidence_role": "media_reference",
                "media_role": "installation_diagram",
                "fact_type": "installation",
                "chunk_text": "media preview",
            }]
        if kwargs.get("allowed_source_types"):
            return [{
                "chunk_id": "pgvector:service:1",
                "source_type": "generic_rule",
                "evidence_role": "service_action",
                "fact_type": "installation",
                "chunk_text": "service action",
            }]
        return [
            {
                "chunk_id": "pgvector:fact:1",
                "source_type": "product_facts",
                "evidence_role": "product_fact_direct",
                "fact_type": "installation",
                "chunk_text": "direct installation fact",
            },
            {
                "chunk_id": "pgvector:media:strict",
                "source_type": "media_asset",
                "evidence_role": "media_reference",
                "media_role": "installation_diagram",
                "fact_type": "installation",
                "chunk_text": "strict media should stay out of product_fact",
            },
        ]


def test_pgvector_shadow_trace_keeps_direct_service_and_media_separate():
    from app.services.pgvector_shadow_trace_service import build_pgvector_shadow_trace

    shadow = build_pgvector_shadow_trace(
        query_text="installation?",
        query_fact_type="installation",
        sidecar={"i_id": "IID-1", "sku_code": "SKU-1"},
        top_k=5,
        pg_service=_PgService(),
        embedding_provider=lambda texts: [[0.01] * 1024 for _ in texts],
    )

    assert shadow["available"] is True
    assert shadow["product_fact"]["candidate_count"] == 1
    assert shadow["product_fact"]["direct_answerable_count"] == 1
    assert shadow["product_fact"]["top_candidates"][0]["source_type"] == "product_facts"
    assert shadow["service_action"]["candidate_count"] == 1
    assert shadow["service_action"]["hit_count"] == 1
    assert shadow["media_reference"]["candidate_count"] == 1
    assert shadow["safety"]["used_for_generation"] is False
    assert shadow["safety"]["can_send_unchanged"] is True
