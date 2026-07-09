"""Trace Answer Memory adapter guidance for reviewed training samples.

This script is diagnostic only. It does not call the Agent and cannot change
sendability.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.models.eval_tables import AgentAnswerMemory  # noqa: F401 - register table
from app.db import init_db
from app.services.answer_memory_adapter_service import AnswerMemoryAdapterService
from app.services.answer_memory_service import infer_scenario_type, plain_text
from app.services.eval_sanitizer_service import sanitize_text
from app.services.fact_type_service import classify_query_fact_type


def _load_samples(path: str) -> list[dict]:
    with open(path, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    if isinstance(data, dict):
        for key in ("samples", "items", "data", "rows"):
            if isinstance(data.get(key), list):
                return data[key]
    if isinstance(data, list):
        return data
    return []


def trace_samples(samples: list[dict], *, limit: int = 5000) -> dict:
    service = AnswerMemoryAdapterService()
    rows = []
    guidance_hit_count = 0
    verified_reference_count = 0
    reference_only_count = 0
    high_risk_guidance_count = 0
    forbidden_claims_count = 0
    can_change_can_send_count = 0
    used_for_fact_count = 0
    non_reference_count = 0
    high_risk_without_review_count = 0
    for sample in samples[: max(1, min(int(limit or 5000), 5000))]:
        question = sanitize_text(plain_text(sample.get("customer_quote")))
        fact = classify_query_fact_type(question, intent="")
        query_fact_type = sanitize_text(fact.get("query_fact_type"))
        scenario_type = infer_scenario_type(sample, query_fact_type)
        guidance = service.build_for_context(
            customer_message=question,
            sku_code=sample.get("sku") or "",
            product_title=sample.get("product_title") or "",
            query_fact_type=query_fact_type,
            scenario_type=scenario_type,
        )
        hits = guidance.get("matched_memories") or []
        if hits:
            guidance_hit_count += 1
        verified_reference_count += int(guidance.get("verified_reference_count") or 0)
        reference_only_count += int(guidance.get("reference_only_count") or 0)
        high_risk_guidance_count += int(guidance.get("high_risk_guidance_count") or 0)
        forbidden_claims_count += len(guidance.get("forbidden_claims") or [])
        if guidance.get("can_change_can_send"):
            can_change_can_send_count += 1
        if guidance.get("used_for_fact"):
            used_for_fact_count += 1
        if guidance.get("reference_only") is not True:
            non_reference_count += 1
        high_risk_without_review_count += sum(
            1
            for hit in hits
            if hit.get("risk_level") == "high" and not bool(hit.get("requires_human_review"))
        )
        rows.append(
            {
                "sample_id": sample.get("id"),
                "query_fact_type": query_fact_type,
                "scenario_type": scenario_type,
                "guidance_hit": bool(hits),
                "answer_memory_guidance": guidance,
            }
        )
    return {
        "total": len(rows),
        "guidance_hit_count": guidance_hit_count,
        "verified_reference_count": verified_reference_count,
        "reference_only_count": reference_only_count,
        "high_risk_guidance_count": high_risk_guidance_count,
        "forbidden_claims_count": forbidden_claims_count,
        "can_change_can_send_count": can_change_can_send_count,
        "used_for_fact_count": used_for_fact_count,
        "non_reference_count": non_reference_count,
        "high_risk_without_review_count": high_risk_without_review_count,
        "rows": rows,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Trace Answer Memory adapter guidance.")
    parser.add_argument("--input", required=True)
    parser.add_argument("--limit", type=int, default=5000)
    parser.add_argument("--json-output", default="")
    args = parser.parse_args()
    init_db()
    result = trace_samples(_load_samples(args.input), limit=args.limit)
    if args.json_output:
        output = Path(args.json_output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in result.items() if k != "rows"}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
