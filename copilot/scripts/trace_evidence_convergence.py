"""Create a read-only evidence convergence report from one analysis response."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.services.admitted_answer_context_service import AdmittedAnswerContextService
from app.services.product_context_pack_service import build_product_context_pack


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _response_from_payload(payload: dict[str, Any]) -> dict[str, Any]:
    for key in ("response", "result", "data"):
        nested = payload.get(key)
        if isinstance(nested, dict) and (
            "product_context_pack" in nested or "selected_evidence" in nested or "evidence_debug" in nested
        ):
            return nested
    return payload


def _requested_claims(payload: dict[str, Any], claim_types: list[str]) -> list[dict[str, str]]:
    if claim_types:
        return [
            {"claim_type": claim_type, "question": "", "risk_level": "medium"}
            for claim_type in claim_types
            if claim_type
        ]
    proposal = _as_dict(_as_dict(payload.get("evidence_debug")).get("llm_decision_proposal"))
    understanding = _as_dict(proposal.get("understanding"))
    requested = understanding.get("requested_claims")
    return requested if isinstance(requested, list) else []


def _identity_from_response(response: dict[str, Any]) -> dict[str, str]:
    context = _as_dict(response.get("context_used"))
    pack = _as_dict(context.get("product_context_pack"))
    identity = _as_dict(pack.get("identity"))
    return {
        "sku_code": str(identity.get("sku") or identity.get("sku_code") or "").strip(),
        "i_id": str(identity.get("i_id") or "").strip(),
        "product_name": str(identity.get("product_name") or response.get("display_product_name") or "").strip(),
    }


def _compact_candidate_count(response: dict[str, Any]) -> int:
    pack = _as_dict(_as_dict(response.get("context_used")).get("product_context_pack"))
    return sum(
        1
        for item in pack.get("facts") or []
        if isinstance(item, dict) and not any(item.get(key) for key in ("content", "chunk_text", "value", "metadata"))
    )


def trace_response(
    payload: dict[str, Any],
    *,
    claim_types: list[str] | None = None,
    rebuild_product_context: bool = False,
    customer_message: str = "",
    query_fact_type: str = "",
) -> dict[str, Any]:
    response = dict(_response_from_payload(payload))
    identity = _as_dict(payload.get("product_identity"))
    identity = identity or _identity_from_response(response)
    compact_candidate_count = _compact_candidate_count(response)
    context_source = "response_snapshot"
    if rebuild_product_context:
        if not customer_message or not query_fact_type:
            raise ValueError("--rebuild-product-context requires --message and --query-fact-type")
        response["product_context_pack"] = build_product_context_pack(
            {"copilot_context": identity},
            query=customer_message,
            query_fact_type=query_fact_type,
            top_k=8,
        )
        context_source = "rebuilt_current_product_context"
    requested_claims = _requested_claims(response, claim_types or [])
    context = AdmittedAnswerContextService().build_for_response(
        response,
        product_identity=identity,
        understanding={"requested_claims": requested_claims},
    )
    return {
        "schema_version": "evidence-convergence-report-v1",
        "product_identity": context.get("product_identity") or {},
        "requested_claims": context.get("requested_claims") or [],
        "context_source": context_source,
        "input_compact_candidate_count": compact_candidate_count,
        "evidence_convergence": context.get("evidence_convergence") or {},
        "direct_product_facts": context.get("direct_product_facts") or [],
        "rejected_evidence": context.get("rejected_evidence") or [],
        "read_only": True,
        "used_for_final_reply": False,
        "can_change_can_send": False,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Trace evidence convergence without calling an Agent or provider.")
    parser.add_argument("--input", required=True, help="Analysis-response JSON path")
    parser.add_argument("--claim-type", action="append", default=[], help="Optional requested claim type; repeatable")
    parser.add_argument("--rebuild-product-context", action="store_true", help="Read current scoped Product Context Pack")
    parser.add_argument("--message", default="", help="Customer message when rebuilding product context")
    parser.add_argument("--query-fact-type", default="", help="Current formal query fact type when rebuilding product context")
    parser.add_argument("--json-output", required=True, help="Output report path")
    args = parser.parse_args(argv)

    payload = json.loads(Path(args.input).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("input JSON must be an object")
    report = trace_response(
        payload,
        claim_types=args.claim_type,
        rebuild_product_context=args.rebuild_product_context,
        customer_message=args.message,
        query_fact_type=args.query_fact_type,
    )
    output = Path(args.json_output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"output": str(output), "summary": report["evidence_convergence"].get("summary", {})}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
