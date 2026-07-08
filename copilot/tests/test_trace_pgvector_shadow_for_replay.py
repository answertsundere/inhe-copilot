from __future__ import annotations


class _Trace:
    def __init__(self, *, buyer_message="hello", query_fact_type="installation", sidecar=None):
        self.case_uid = "case-1"
        self.turn_uid = "turn-1"
        self.buyer_message = buyer_message
        self.query_fact_type = query_fact_type
        self._sidecar = sidecar if sidecar is not None else {
            "product_title": "product",
            "sku_code": "SKU-1",
            "i_id": "IID-1",
        }

    def get_turn_understanding(self):
        return {"query_fact_type": self.query_fact_type}

    def get_answer_trace(self):
        return {}

    def get_raw_response(self):
        return {"copilot_context": {"sidecar_context": self._sidecar}}


class _Db:
    def close(self):
        pass


class _PgService:
    dsn = "configured"

    def __init__(self, available=True, rows_by_mode=None):
        self.available = available
        self.rows_by_mode = rows_by_mode or {}

    def check(self):
        return {
            "pgvector_available": self.available,
            "extension_available": self.available,
            "error": "" if self.available else "pgvector_unavailable",
        }

    def retrieve(self, **kwargs):
        if not self.available:
            return []
        if not kwargs.get("i_id") and not kwargs.get("sku_code"):
            mode = "no_product"
        elif not kwargs.get("query_fact_type"):
            mode = "no_fact_type"
        else:
            mode = "strict"
        return [dict(row) for row in self.rows_by_mode.get(mode, [])]


def _embedding_provider(texts):
    return [[0.01] * 1024 for _ in texts]


def test_trace_pgvector_shadow_reports_fact_type_filter_help(monkeypatch):
    import scripts.trace_pgvector_shadow_for_replay as script

    monkeypatch.setattr(script, "_load_traces", lambda db, run_uid, limit: [_Trace()])
    pg_service = _PgService(rows_by_mode={
        "no_fact_type": [{
            "chunk_id": "pgvector:generic_rule:1",
            "source_type": "generic_rule",
            "evidence_role": "service_action",
            "chunk_text": "service action",
        }]
    })

    result = script.trace_pgvector_shadow(
        run_uid="run-1",
        pg_service=pg_service,
        embedding_provider=_embedding_provider,
        db_factory=lambda: _Db(),
    )

    summary = result["summary"]
    assert summary["searchable_trace_count"] == 1
    assert summary["strict_hit_count"] == 0
    assert summary["no_fact_type_helped_count"] == 1
    assert summary["filter_exclusion_reason_counts"] == {"fact_type_filter_empty": 1}
    assert summary["pgvector_direct_answerable_count"] == 0
    assert result["rows"][0]["pgvector_shadow"]["filter_mode_results"]["no_fact_type"]["service_action_count"] == 1


def test_trace_pgvector_shadow_counts_unknown_media_reference(monkeypatch):
    import scripts.trace_pgvector_shadow_for_replay as script

    monkeypatch.setattr(script, "_load_traces", lambda db, run_uid, limit: [_Trace()])
    pg_service = _PgService(rows_by_mode={
        "strict": [{
            "chunk_id": "pgvector:media_asset:1",
            "source_type": "media_asset",
            "evidence_role": "media_reference",
            "media_role": "",
            "chunk_text": "media reference",
        }]
    })

    result = script.trace_pgvector_shadow(
        run_uid="run-1",
        pg_service=pg_service,
        embedding_provider=_embedding_provider,
        db_factory=lambda: _Db(),
    )

    summary = result["summary"]
    assert summary["strict_hit_count"] == 1
    assert summary["pgvector_media_reference_count"] == 1
    assert summary["media_reference_with_unknown_role_count"] == 1
    assert summary["pgvector_direct_answerable_count"] == 0


def test_trace_pgvector_shadow_handles_unavailable_pgvector(monkeypatch):
    import scripts.trace_pgvector_shadow_for_replay as script

    monkeypatch.setattr(script, "_load_traces", lambda db, run_uid, limit: [_Trace()])

    result = script.trace_pgvector_shadow(
        run_uid="run-1",
        pg_service=_PgService(available=False),
        embedding_provider=_embedding_provider,
        db_factory=lambda: _Db(),
    )

    summary = result["summary"]
    assert summary["pgvector_available"] is False
    assert summary["pgvector_error_count"] == 1
    assert summary["filter_exclusion_reason_counts"] == {"pgvector_unavailable": 1}
    assert result["rows"][0]["pgvector_shadow"]["available"] is False
