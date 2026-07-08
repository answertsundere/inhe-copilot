from __future__ import annotations


class _FakePgService:
    dsn = "configured"
    collection = "kb_chunk_embeddings_pg"

    def check(self):
        return {"pgvector_available": True, "extension_available": True, "error": ""}

    def fetch_rows_for_metadata_normalization(self, *, limit=0):
        return [
            {
                "source_chunk_id": "1",
                "query_fact_type": "accessories",
                "evidence_role": "accessories",
                "source_type": "product_facts",
                "chunk_text": "配件可以单独购买",
                "metadata": {},
            },
            {
                "source_chunk_id": "2",
                "query_fact_type": "",
                "evidence_role": "media_reference",
                "source_type": "media_asset",
                "media_role": "pack_guide_image",
                "chunk_text": "安装指导图",
                "metadata": {},
            },
        ]


def test_diagnose_pgvector_fact_type_metadata_reports_normalization_samples():
    from scripts.diagnose_pgvector_fact_type_metadata import run

    result = run(service=_FakePgService())

    assert result["pgvector_available"] is True
    assert result["total_rows"] == 2
    assert result["recommended_normalization_count"] == 2
    assert result["unknown_or_generic_fact_type_count"] == 1
    assert "recommended_normalization" in result["samples"]
    assert result["samples"]["recommended_normalization"][0]["recommended_query_fact_type"] == "accessory_availability"
