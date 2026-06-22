from app import config
from app.services.evidence_rerank_service import _evidence_key, rerank_evidence


def _ev(entry_id, fact_type, text, *, score=1, origin="product_facts", source_type="product_facts"):
    return {
        "entry_id": entry_id,
        "source_type": source_type,
        "evidence_origin": origin,
        "fact_type": fact_type,
        "evidence_fact_type": fact_type,
        "chunk_text": text,
        "score": score,
        "rerank_score": score,
    }


def _asset(entry_id, asset_type, fact_type, *, url="https://example.test/a.mp4"):
    return {
        "asset_id": entry_id,
        "id": entry_id,
        "asset_type": asset_type,
        "asset_title": asset_type,
        "asset_url": url,
        "source_type": "product_media",
        "evidence_origin": "product_media",
        "fact_type": fact_type,
        "evidence_fact_type": fact_type,
        "status": "approved",
        "usable_for_agent": True,
    }


def _mock_context(scores=None, **extra):
    return {
        "enabled": True,
        "provider": "mock",
        "scores": scores or {},
        **extra,
    }


def test_disabled_provider_keeps_deterministic_result(monkeypatch):
    monkeypatch.setattr(config, "EVIDENCE_EMBEDDING_RERANK_ENABLED", False)
    evidence = [
        _ev("load", "load_capacity", "load capacity evidence", score=99),
        _ev("dim", "dimensions", "dimension evidence", score=1),
    ]

    baseline = rerank_evidence(
        retrieved_evidence=evidence,
        query_fact_type="dimensions",
        required_fact_types=["dimensions"],
    )
    disabled = rerank_evidence(
        retrieved_evidence=evidence,
        query_fact_type="dimensions",
        required_fact_types=["dimensions"],
        embedding_context={"enabled": False, "provider": "disabled"},
    )

    assert [_evidence_key(item) for item in disabled["selected_evidence"]] == [
        _evidence_key(item) for item in baseline["selected_evidence"]
    ]
    assert disabled["embedding_rerank_used"] is False
    assert disabled["embedding_provider"] == "disabled"
    assert all(row["embedding_rerank_used"] is False for row in disabled["rerank_trace"])


def test_mock_embedding_only_reorders_direct_evidence_within_same_role(monkeypatch):
    monkeypatch.setattr(config, "EVIDENCE_EMBEDDING_RERANK_ENABLED", True)
    evidence = [
        _ev("dim-low", "dimensions", "size evidence with stronger semantic match", score=1.0),
        _ev("dim-high", "dimensions", "size evidence with weaker semantic match", score=1.1),
    ]
    scores = {
        "entry_id:dim-low": {"embedding_score": 0.99, "embedding_reason": "closer to query"},
        "entry_id:dim-high": {"embedding_score": 0.01, "embedding_reason": "weaker match"},
    }

    result = rerank_evidence(
        retrieved_evidence=evidence,
        query_fact_type="dimensions",
        query_text="what is the size",
        required_fact_types=["dimensions"],
        embedding_context=_mock_context(scores),
    )

    assert result["embedding_rerank_used"] is True
    assert result["selected_evidence"][0]["entry_id"] == "dim-low"
    direct_rows = [row for row in result["rerank_trace"] if row["role"] == "direct_answer"]
    assert [row["entry_id"] for row in direct_rows[:2]] == ["dim-low", "dim-high"]
    assert direct_rows[0]["embedding_score"] > direct_rows[1]["embedding_score"]


def test_embedding_cannot_break_certification_report_boundary(monkeypatch):
    monkeypatch.setattr(config, "EVIDENCE_EMBEDDING_RERANK_ENABLED", True)
    evidence = [
        _ev("material", "material", "material looks very safe", score=99),
        _ev("cert", "certification_report", "certificate report evidence", score=1),
    ]
    scores = {
        "entry_id:material": {"embedding_score": 0.99},
        "entry_id:cert": {"embedding_score": 0.2},
    }

    result = rerank_evidence(
        retrieved_evidence=evidence,
        query_fact_type="certification_report",
        query_text="is there a certificate report",
        required_fact_types=["certification_report"],
        embedding_context=_mock_context(scores),
    )

    assert result["selected_evidence"][0]["entry_id"] == "cert"
    assert result["selected_evidence"][0]["role"] == "direct_answer"
    material = [item for item in result["rejected_evidence"] if item.get("entry_id") == "material"]
    assert material
    assert material[0]["reject_reason"] == "certification_requires_report_evidence"


def test_embedding_cannot_select_unsendable_install_video(monkeypatch):
    monkeypatch.setattr(config, "EVIDENCE_EMBEDDING_RERANK_ENABLED", True)
    evidence = [_asset("video-no-url", "install_video", "installation", url="")]

    result = rerank_evidence(
        retrieved_evidence=evidence,
        query_fact_type="installation",
        query_text="installation video",
        required_fact_types=["installation"],
        embedding_context=_mock_context({"asset_id:video-no-url": {"embedding_score": 0.99}}),
    )

    assert not result["selected_assets"]
    assert not result["selected_evidence"]
    assert result["rejected_evidence"][0]["reject_reason"] == "media_not_sendable"


def test_embedding_cannot_turn_load_capacity_into_dimensions_direct(monkeypatch):
    monkeypatch.setattr(config, "EVIDENCE_EMBEDDING_RERANK_ENABLED", True)
    evidence = [
        _ev("load", "load_capacity", "load capacity evidence", score=99),
        _ev("dim", "dimensions", "dimension evidence", score=1),
    ]
    scores = {
        "entry_id:load": {"embedding_score": 0.99},
        "entry_id:dim": {"embedding_score": 0.2},
    }

    result = rerank_evidence(
        retrieved_evidence=evidence,
        query_fact_type="dimensions",
        query_text="what is the size",
        required_fact_types=["dimensions"],
        embedding_context=_mock_context(scores),
    )

    assert result["selected_evidence"][0]["entry_id"] == "dim"
    assert result["selected_evidence"][0]["role"] == "direct_answer"
    assert all(item.get("role") != "direct_answer" for item in result["rejected_evidence"] if item.get("entry_id") == "load")


def test_embedding_cannot_promote_generic_rule_over_direct_product_evidence(monkeypatch):
    monkeypatch.setattr(config, "EVIDENCE_EMBEDDING_RERANK_ENABLED", True)
    evidence = [
        _ev("card", "detachable", "product card says not detachable", score=1, origin="product_card"),
        _ev("generic", "detachable", "generic rule says many items are detachable", score=99, origin="generic_rules", source_type="generic_rules"),
    ]
    scores = {
        "entry_id:card": {"embedding_score": 0.1},
        "entry_id:generic": {"embedding_score": 0.99},
    }

    result = rerank_evidence(
        retrieved_evidence=evidence,
        query_fact_type="detachable",
        query_text="is it detachable",
        required_fact_types=["detachable"],
        embedding_context=_mock_context(scores),
    )

    assert result["selected_evidence"][0]["entry_id"] == "card"
    assert result["selected_evidence"][0]["role"] == "direct_answer"
    generic_rows = [row for row in result["rerank_trace"] if row["entry_id"] == "generic"]
    assert generic_rows[0]["role"] == "fallback"


def test_embedding_failure_falls_back_to_deterministic_result(monkeypatch):
    monkeypatch.setattr(config, "EVIDENCE_EMBEDDING_RERANK_ENABLED", True)
    evidence = [
        _ev("load", "load_capacity", "load capacity evidence", score=99),
        _ev("dim", "dimensions", "dimension evidence", score=1),
    ]
    baseline = rerank_evidence(
        retrieved_evidence=evidence,
        query_fact_type="dimensions",
        required_fact_types=["dimensions"],
    )

    result = rerank_evidence(
        retrieved_evidence=evidence,
        query_fact_type="dimensions",
        query_text="what is the size",
        required_fact_types=["dimensions"],
        embedding_context=_mock_context(**{"raise": True}),
    )

    assert [_evidence_key(item) for item in result["selected_evidence"]] == [
        _evidence_key(item) for item in baseline["selected_evidence"]
    ]
    assert result["embedding_fallback_used"] is True
    assert result["embedding_rerank_used"] is False
    assert result["embedding_error"]


def test_embedding_trace_fields_are_complete(monkeypatch):
    monkeypatch.setattr(config, "EVIDENCE_EMBEDDING_RERANK_ENABLED", True)
    result = rerank_evidence(
        retrieved_evidence=[_ev("dim", "dimensions", "dimension evidence", score=1)],
        query_fact_type="dimensions",
        query_text="what is the size",
        required_fact_types=["dimensions"],
        embedding_context=_mock_context({"entry_id:dim": {"embedding_score": 0.7, "embedding_reason": "mock"}}),
    )

    assert result["embedding_rerank_summary"]["provider"] == "mock"
    assert result["embedding_rerank_summary"]["used"] is True
    for row in result["rerank_trace"]:
        assert "embedding_score" in row
        assert "embedding_reason" in row
        assert "final_rank_score" in row
        assert row["embedding_provider"] == "mock"
