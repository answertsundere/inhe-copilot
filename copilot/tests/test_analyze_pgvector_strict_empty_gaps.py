from __future__ import annotations

import json


def _row(
    *,
    requested: str,
    product_candidates: list[dict],
    no_product_candidates: list[dict] | None = None,
    buyer_message: str = "buyer question",
) -> dict:
    def result(candidates: list[dict]) -> dict:
        return {
            "candidate_count": len(candidates),
            "direct_answerable_count": sum(
                1
                for item in candidates
                if item.get("evidence_role") in {"product_fact_direct", "faq_direct"}
                or item.get("source_type") in {"product_facts", "kbqa"}
            ),
            "top_candidates": candidates,
        }

    return {
        "case_uid": "case-1",
        "turn_uid": "turn-1",
        "query_fact_type": requested,
        "buyer_message_preview": buyer_message,
        "pgvector_shadow": {
            "filter_mode_results": {
                "strict": {"candidate_count": 0, "top_candidates": []},
                "product_only": result(product_candidates),
                "no_product": result(no_product_candidates or []),
            }
        },
    }


def test_analyze_strict_empty_keeps_high_risk_strict():
    from scripts.analyze_pgvector_strict_empty_gaps import analyze_trace

    report = analyze_trace({
        "summary": {"run_uid": "run-1", "trace_count": 1, "strict_hit_count": 0},
        "rows": [
            _row(
                requested="load_capacity",
                product_candidates=[
                    {
                        "query_fact_type": "dimensions",
                        "source_type": "product_facts",
                        "evidence_role": "product_fact_direct",
                        "preview": "product dimensions",
                    }
                ],
            )
        ],
    })

    assert report["strict_empty_product_only_hit_count"] == 1
    assert report["keep_strict_count"] == 1
    assert report["groups"][0]["risk_level"] == "high"
    assert report["groups"][0]["reason"] == "high_risk_requested_fact_type_requires_exact_evidence"


def test_analyze_strict_empty_classifies_service_source_coverage():
    from scripts.analyze_pgvector_strict_empty_gaps import analyze_trace

    report = analyze_trace({
        "summary": {"run_uid": "run-1", "trace_count": 1, "strict_hit_count": 0},
        "rows": [
            _row(
                requested="invoice_policy",
                buyer_message="发票还没开好吗",
                product_candidates=[
                    {
                        "query_fact_type": "installation",
                        "source_type": "product_facts",
                        "evidence_role": "product_fact_direct",
                        "preview": "installation guide",
                    }
                ],
                no_product_candidates=[
                    {
                        "query_fact_type": "invoice_policy",
                        "source_type": "generic_rule",
                        "evidence_role": "service_action",
                        "preview": "发票申请兜底口径",
                    }
                ],
            )
        ],
    })

    assert report["add_source_coverage_count"] == 1
    assert report["groups"][0]["recommendation"] == "add_source_coverage"
    assert report["groups"][0]["samples"][0]["why_strict_excluded_it"]


def test_analyze_strict_empty_detects_split_fact_type_family():
    from scripts.analyze_pgvector_strict_empty_gaps import analyze_trace

    report = analyze_trace({
        "summary": {"run_uid": "run-1", "trace_count": 1, "strict_hit_count": 0},
        "rows": [
            _row(
                requested="structure_function",
                product_candidates=[
                    {
                        "query_fact_type": "installation",
                        "source_type": "product_facts",
                        "evidence_role": "product_fact_direct",
                        "preview": "孔位和安装步骤说明",
                    }
                ],
            )
        ],
    })

    assert report["split_fact_type_count"] == 1
    assert report["groups"][0]["product_only_top_candidate_fact_types"] == {"installation": 1}


def test_analyze_strict_empty_script_writes_json(tmp_path):
    from scripts.analyze_pgvector_strict_empty_gaps import run

    trace_path = tmp_path / "trace.json"
    out_path = tmp_path / "report.json"
    trace_path.write_text(
        json.dumps({
            "summary": {"run_uid": "run-1", "trace_count": 1, "strict_hit_count": 0},
            "rows": [
                _row(
                    requested="gift_policy",
                    product_candidates=[
                        {
                            "query_fact_type": "promotion_policy",
                            "source_type": "product_facts",
                            "evidence_role": "product_fact_direct",
                            "preview": "赠品活动说明",
                        }
                    ],
                )
            ],
        }, ensure_ascii=False),
        encoding="utf-8",
    )

    report = run(trace_json=str(trace_path), json_output=str(out_path))

    assert report["strict_empty_product_only_hit_count"] == 1
    assert out_path.exists()
    loaded = json.loads(out_path.read_text(encoding="utf-8"))
    assert loaded["run_uid"] == "run-1"
