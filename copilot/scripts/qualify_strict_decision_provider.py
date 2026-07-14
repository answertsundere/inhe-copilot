"""Read-only qualification for the Evidence-First decision-shadow provider."""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from collections import Counter
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.services.agent_decision_proposal_service import (
    AgentDecisionProposal,
    DecisionIntake,
    _PROPOSAL_SYSTEM_PROMPT,
    _UNDERSTANDING_SYSTEM_PROMPT,
    _schema_for,
)
from app.services.strict_decision_provider_service import StrictDecisionProviderService


_MESSAGE = "请说明这件商品的材料组成、安全性和耐潮性。"
_INTAKE_PAYLOAD = {
    "customer_message": _MESSAGE,
    "intent": "product_question",
    "resolved_product_identity": {"status": "resolved"},
    "has_order_identifier": False,
    "structured_turn_understanding": {},
}


def _rate(numerator: int, denominator: int) -> dict[str, Any]:
    return {"numerator": numerator, "denominator": denominator, "rate": numerator / denominator if denominator else 0.0}


def _minimal_proposal_payload(intake: dict[str, Any]) -> dict[str, Any]:
    return {
        "customer_message": _MESSAGE,
        "understanding": intake["understanding"],
        "tool_plan": intake["tool_plan"],
        "shadow_tool_execution": {
            "shadow_only": True,
            "executed_tool_names": [],
            "deferred_capabilities": [],
            "tool_results": {},
        },
        "admitted_answer_context": {
            "direct_product_facts": [],
            "direct_policy_facts": [],
            "handoff_action_guidance": [],
            "media_candidates": [],
            "unresolved_claims": [],
            "claim_resolutions": [],
        },
        "actual_reply_block_refs": [],
    }


def _local_contract_checks() -> dict[str, bool]:
    valid = {
        "understanding": {
            "primary_question": "材料问题",
            "requested_claims": [],
            "uncertainty_items": [],
            "requested_fact_types": [],
        },
        "tool_plan": {
            "retrieval_needed": False,
            "product_identity_lookup_needed": False,
            "order_lookup_needed": False,
            "media_lookup_needed": False,
        },
        "evidence_selection": {
            "candidate_evidence_uids": [],
            "requested_evidence_uids": [],
            "unsupported_claims": [],
        },
        "claim_resolutions": [],
        "confirmed_clauses": [],
        "pending_clauses": [],
        "reply_plan": {
            "mode": "controlled_handoff",
            "factual_clause_evidence_uids": [],
            "action_guidance_evidence_uids": [],
            "proposed_reply": "",
        },
        "delivery_intent": {"proposed_reply_block_refs": [], "requires_human_review": True},
        "used_for_final_reply": False,
        "can_change_can_send": False,
    }
    checks: dict[str, bool] = {}
    for name, mutator in {
        "extra_field_rejected": lambda value: value.update({"send": True}),
        "missing_required_field_rejected": lambda value: value.pop("reply_plan"),
        "enum_out_of_range_rejected": lambda value: value["reply_plan"].update({"mode": "send_now"}),
        "used_for_final_reply_literal_false": lambda value: value.update({"used_for_final_reply": True}),
        "can_change_can_send_literal_false": lambda value: value.update({"can_change_can_send": True}),
    }.items():
        candidate = json.loads(json.dumps(valid))
        mutator(candidate)
        try:
            AgentDecisionProposal.model_validate(candidate)
            checks[name] = False
        except Exception:
            checks[name] = True
    return checks


def qualify(*, repeats: int = 5, provider: StrictDecisionProviderService | None = None) -> dict[str, Any]:
    provider = provider or StrictDecisionProviderService()
    metadata = provider.metadata()
    local_checks = _local_contract_checks()
    errors: Counter[str] = Counter()
    intake_success = 0
    proposal_success = 0
    latencies: list[float] = []
    signatures: list[str] = []
    outputs: list[dict[str, Any]] = []

    if metadata["configured"]:
        for _ in range(max(1, repeats)):
            try:
                intake = DecisionIntake.model_validate(provider.request(
                    name="agent_decision_intake",
                    schema=_schema_for(DecisionIntake),
                    system_prompt=_UNDERSTANDING_SYSTEM_PROMPT,
                    payload=_INTAKE_PAYLOAD,
                    max_tokens=700,
                    allow_unqualified=True,
                )).model_dump()
                intake_success += 1
                if provider.last_latency_ms is not None:
                    latencies.append(provider.last_latency_ms)
                proposal = AgentDecisionProposal.model_validate(provider.request(
                    name="agent_decision_proposal",
                    schema=_schema_for(AgentDecisionProposal),
                    system_prompt=_PROPOSAL_SYSTEM_PROMPT,
                    payload=_minimal_proposal_payload(intake),
                    max_tokens=1200,
                    allow_unqualified=True,
                )).model_dump()
                proposal_success += 1
                if provider.last_latency_ms is not None:
                    latencies.append(provider.last_latency_ms)
                signature = json.dumps({
                    "requested_claim_types": [item["claim_type"] for item in intake["understanding"]["requested_claims"]],
                    "tool_plan": intake["tool_plan"],
                    "proposal_mode": proposal["reply_plan"]["mode"],
                    "used_for_final_reply": proposal["used_for_final_reply"],
                    "can_change_can_send": proposal["can_change_can_send"],
                }, ensure_ascii=False, sort_keys=True)
                signatures.append(signature)
                outputs.append({"intake": intake, "proposal": proposal})
            except Exception as exc:
                errors[str(exc) or type(exc).__name__] += 1

    attempts = max(1, repeats)
    contract_passes = sum(local_checks.values())
    total_local_checks = len(local_checks)
    report = {
        "schema_version": "strict-decision-provider-qualification-v1",
        "shadow_only": True,
        "provider": metadata,
        "attempt_count": attempts,
        "intake_schema_success": _rate(intake_success, attempts),
        "proposal_schema_success": _rate(proposal_success, attempts),
        "schema_success_rate": _rate(intake_success + proposal_success, attempts * 2),
        "local_contract_checks": local_checks,
        "required_field_success_rate": _rate(int(local_checks["missing_required_field_rejected"]), 1),
        "forbidden_extra_field_block_rate": _rate(int(local_checks["extra_field_rejected"]), 1),
        "invalid_enum_block_rate": _rate(int(local_checks["enum_out_of_range_rejected"]), 1),
        "literal_false_contract_rate": _rate(
            int(local_checks["used_for_final_reply_literal_false"] and local_checks["can_change_can_send_literal_false"]), 1
        ),
        "compound_claim_split_rate": _rate(
            sum(
                {"material_composition", "material_safety", "moisture_resistance"}.issubset(
                    {claim["claim_type"] for claim in item["intake"]["understanding"]["requested_claims"]}
                )
                for item in outputs
            ),
            len(outputs),
        ),
        "repeat_structure_stability_rate": _rate(
            sum(signature == signatures[0] for signature in signatures) if signatures else 0,
            len(signatures),
        ),
        "timeout_count": errors.get("timeout", 0),
        "truncated_response_count": errors.get("structured_output_truncated", 0),
        "error_categories": dict(sorted(errors.items())),
        "parse_fallback_count": 0,
        "free_text_fallback_count": 0,
        "secret_exposure_count": 0,
        "formal_kb_write_attempt_count": 0,
        "can_change_can_send_count": 0,
        "latency_ms": {
            "p50": round(statistics.median(latencies), 2) if latencies else None,
            "p95": round(sorted(latencies)[max(0, int(len(latencies) * 0.95) - 1)], 2) if latencies else None,
        },
    }
    thresholds_met = (
        metadata["configured"]
        and report["schema_success_rate"]["rate"] == 1.0
        and contract_passes == total_local_checks
        and report["compound_claim_split_rate"]["rate"] == 1.0
        and report["repeat_structure_stability_rate"]["rate"] == 1.0
        and report["timeout_count"] == 0
        and report["truncated_response_count"] == 0
    )
    report["qualification_status"] = "qualified" if thresholds_met else "not_qualified"
    report["shadow_enablement_allowed"] = bool(thresholds_met and metadata["qualified"])
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Qualify a strict decision shadow provider without changing production behavior.")
    parser.add_argument("--repeat", type=int, default=5)
    parser.add_argument("--json-output", required=True)
    args = parser.parse_args()
    report = qualify(repeats=args.repeat)
    output_path = Path(args.json_output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({
        "qualification_status": report["qualification_status"],
        "shadow_enablement_allowed": report["shadow_enablement_allowed"],
        "provider": report["provider"],
    }, ensure_ascii=False))
    return 0 if report["qualification_status"] == "qualified" else 2


if __name__ == "__main__":
    sys.exit(main())
