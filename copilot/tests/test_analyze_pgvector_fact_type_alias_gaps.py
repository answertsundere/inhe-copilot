from __future__ import annotations

import json


def _trace_payload(row):
    return {"summary": {"run_uid": "run-1"}, "rows": [row]}


def test_alias_gap_analysis_recommends_safe_low_risk_alias(tmp_path):
    from scripts.analyze_pgvector_fact_type_alias_gaps import analyze_alias_gaps

    source = tmp_path / "trace.json"
    source.write_text(json.dumps(_trace_payload({
        "case_uid": "case-1",
        "turn_uid": "turn-1",
        "query_fact_type": "promotion_policy",
        "buyer_message_preview": "promotion question",
        "pgvector_shadow": {
            "filter_mode_results": {
                "strict": {"candidate_count": 0},
                "no_fact_type": {
                    "candidate_count": 1,
                    "top_candidates": [{
                        "query_fact_type": "price_negotiation",
                        "source_type": "product_facts",
                        "evidence_role": "product_fact_direct",
                        "preview": "promotion policy",
                    }],
                },
            }
        },
    }), ensure_ascii=False), encoding="utf-8")

    result = analyze_alias_gaps(str(source))

    assert result["summary"]["inspected_gap_count"] == 1
    assert result["rows"][0]["requested_fact_type"] == "promotion_policy"
    assert result["rows"][0]["alias_recommendation"] == "add_alias"
    assert result["rows"][0]["risk_level"] == "low"


def test_alias_gap_analysis_keeps_high_risk_strict(tmp_path):
    from scripts.analyze_pgvector_fact_type_alias_gaps import analyze_alias_gaps

    source = tmp_path / "trace.json"
    source.write_text(json.dumps(_trace_payload({
        "case_uid": "case-1",
        "turn_uid": "turn-1",
        "query_fact_type": "load_capacity",
        "buyer_message_preview": "load question",
        "pgvector_shadow": {
            "filter_mode_results": {
                "strict": {"candidate_count": 0},
                "no_fact_type": {
                    "candidate_count": 1,
                    "top_candidates": [{
                        "query_fact_type": "gross_weight",
                        "source_type": "product_facts",
                        "evidence_role": "product_fact_direct",
                        "preview": "weight",
                    }],
                },
            }
        },
    }), ensure_ascii=False), encoding="utf-8")

    result = analyze_alias_gaps(str(source))

    assert result["rows"][0]["alias_recommendation"] == "keep_strict"
    assert result["rows"][0]["risk_level"] == "high"


def test_alias_gap_analysis_ignores_service_and_media_only_candidates(tmp_path):
    from scripts.analyze_pgvector_fact_type_alias_gaps import analyze_alias_gaps

    source = tmp_path / "trace.json"
    source.write_text(json.dumps(_trace_payload({
        "case_uid": "case-1",
        "turn_uid": "turn-1",
        "query_fact_type": "installation",
        "buyer_message_preview": "install question",
        "pgvector_shadow": {
            "filter_mode_results": {
                "strict": {"candidate_count": 0},
                "no_fact_type": {
                    "candidate_count": 2,
                    "top_candidates": [
                        {
                            "query_fact_type": "installation",
                            "source_type": "generic_rule",
                            "evidence_role": "service_action",
                            "preview": "handoff",
                        },
                        {
                            "query_fact_type": "installation",
                            "source_type": "media_asset",
                            "evidence_role": "media_reference",
                            "preview": "asset",
                        },
                    ],
                },
            }
        },
    }), ensure_ascii=False), encoding="utf-8")

    result = analyze_alias_gaps(str(source))

    assert result["rows"][0]["alias_recommendation"] == "ignore_noise"
    assert result["rows"][0]["reason"] == "only service/media/reference candidates were found"

