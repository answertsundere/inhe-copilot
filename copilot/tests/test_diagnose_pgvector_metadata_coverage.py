from __future__ import annotations


class _FakeQuery:
    def __init__(self, count: int):
        self._count = count

    def filter(self, *args, **kwargs):
        return self

    def count(self):
        return self._count


class _FakeDb:
    def query(self, model):
        name = getattr(model, "__name__", "")
        return _FakeQuery({
            "KBQA": 7,
            "KBGenericServiceRule": 3,
            "KBMediaAsset": 5,
        }.get(name, 0))

    def close(self):
        self.closed = True


class _FakeService:
    dsn = ""
    collection = "kb_chunk_embeddings_pg"


def test_safe_collection_rejects_unsafe_name():
    from scripts.diagnose_pgvector_metadata_coverage import _safe_collection

    assert _safe_collection("kb_chunk_embeddings_pg") == "kb_chunk_embeddings_pg"

    try:
        _safe_collection("kb_chunk_embeddings_pg;drop table x")
    except ValueError as exc:
        assert "unsafe_collection" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("unsafe collection should be rejected")


def test_metadata_coverage_report_includes_shadow_source_counts(monkeypatch):
    import scripts.diagnose_pgvector_metadata_coverage as script

    monkeypatch.setattr(script, "_pgvector_coverage", lambda service: {
        "available": True,
        "total_rows": 10,
        "rows_missing_query_fact_type": 2,
    })

    report = script.run(db_factory=lambda: _FakeDb(), service=_FakeService())

    assert report["pgvector"]["available"] is True
    assert report["pgvector"]["total_rows"] == 10
    assert report["sqlite_shadow_sources"]["sqlite_kbqa_published_count"] == 7
    assert report["sqlite_shadow_sources"]["sqlite_generic_rule_active_count"] == 3
    assert report["sqlite_shadow_sources"]["sqlite_media_asset_count"] == 5
    assert any("media assets" in note for note in report["notes"])
