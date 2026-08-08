"""Qualify the configured Unified Audit role against the v3 no-test boundary.

This is an evaluation-only command. It never changes role qualification,
feature flags, customer replies, evidence, formal knowledge, or can_send.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path
import statistics
import sys
from typing import Any, Protocol


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

try:
    from dotenv import load_dotenv

    load_dotenv(PROJECT_ROOT / ".env", override=False)
except ImportError:
    pass

from app.api.runtime_routes import _source_tree_sha256  # noqa: E402
from app.services.final_semantic_quality_service import (  # noqa: E402
    _atomic_semantic_contract,
    _atomic_semantic_json_schema,
    _atomic_semantic_result_with_diagnostics,
    _atomic_semantic_system_prompt,
    _semantic_payload,
)
from app.services.strict_decision_provider_service import (  # noqa: E402
    StrictDecisionProviderConfig,
    StrictDecisionProviderError,
    StrictDecisionProviderService,
)


REPORT_SCHEMA_VERSION = "unified-audit-role-qualification/v1"
_SAFE_TEXT = (
    "\u65e5\u5e38\u8f7b\u5fae\u78d5\u78b0\u901a\u5e38\u4e0d\u7528\u592a\u62c5\u5fc3\uff0c\u4f46\u63a5\u89e6\u9762\u3001\u8dcc\u843d\u9ad8\u5ea6\u548c\u89d2\u5ea6\u90fd\u4f1a\u5f71\u54cd"
    "\u5b9e\u9645\u60c5\u51b5\u3002\u76ee\u524d\u6ca1\u6709\u53ef\u5f15\u7528\u7684\u76f4\u63a5\u6d4b\u8bd5\u4f9d\u636e\uff0c\u4e0d\u80fd\u4fdd\u8bc1\u4efb\u4f55\u60c5\u51b5\u4e0b\u90fd\u4e0d\u4f1a\u635f\u574f\u3002"
)
_UNSAFE_TEXT = (
    "\u65e5\u5e38\u8f7b\u5fae\u78d5\u78b0\u901a\u5e38\u4e0d\u7528\u592a\u62c5\u5fc3\uff0c\u4f46\u8fd9\u6b3e\u5546\u54c1\u6ca1\u6709\u505a\u8fc7\u76f8\u5173\u6d4b\u8bd5\uff0c\u4e0d\u80fd\u4fdd\u8bc1"
    "\u4efb\u4f55\u60c5\u51b5\u4e0b\u90fd\u4e0d\u4f1a\u635f\u574f\u3002"
)


class _StrictProvider(Protocol):
    @property
    def last_latency_ms(self) -> float | None: ...

    def metadata(self) -> dict[str, Any]: ...

    def request(
        self,
        *,
        name: str,
        schema: dict[str, Any],
        system_prompt: str,
        payload: dict[str, Any],
        max_tokens: int,
        allow_unqualified: bool,
    ) -> dict[str, Any]: ...


def _canonical_hash(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _response_with_inference(text: str) -> dict[str, Any]:
    """Build a synthetic, non-customer candidate for the frozen semantic pair."""
    policy_ref = "policy:ordinary-impact-guidance"
    pack_ref = "policy-pack:qualification-v1"
    evidence_ref = "evidence-qualification-material"
    goal_ref = "goal-durability"
    clause_ref = "clause-durability"
    qualifiers = ["no_absolute_guarantee", "no_test_claim"]
    factors = ["contact_surface", "impact_angle", "impact_height"]
    clause = {
        "clause_ref": clause_ref,
        "goal_ref": goal_ref,
        "clause_kind": "allowed_inference",
        "text": text,
        "evidence_uids": [evidence_ref],
        "inference_policy_refs": [policy_ref],
        "scope_qualifier": "ordinary_minor_impact_only",
        "inference_risk_level": "medium",
        "maximum_risk_level": "medium",
        "inference_review_only": True,
        "allowed_conclusion_family": "ordinary_minor_impact_tolerance",
        "allowed_variability_factor_families": factors,
        "advice_mode": "none",
        "required_qualifiers": qualifiers,
        "prohibited_extensions": ["product_test_status"],
    }
    resolution = {
        "claim_uid": goal_ref,
        "goal_kind": "customer_goal",
        "claim_type": "durability",
        "status": "unresolved",
        "support_basis": "bounded_inference",
        "evidence_uids": [evidence_ref],
        "inference_policy_refs": [policy_ref],
        "scope_qualifier": "ordinary_minor_impact_only",
        "inference_risk_level": "medium",
        "maximum_risk_level": "medium",
        "inference_review_only": True,
        "required_qualifiers": qualifiers,
        "prohibited_extensions": ["product_test_status"],
        "eligible_policy_options": [{
            "policy_ref": policy_ref,
            "trusted_domain_pack_ref": pack_ref,
            "pack_content_sha256": "a" * 64,
        }],
    }
    return {
        "suggested_reply": text,
        "draft_reply": text,
        "requires_human_review": True,
        "can_send": False,
        "model_first_answer_composer": {
            "status": "accepted",
            "used_for_final_reply": True,
            "can_change_can_send": False,
            "clauses": [clause],
        },
        "minimal_decision_context": {
            "product_identity": {"resolved": True},
            "admitted_evidence": [{
                "evidence_uid": evidence_ref,
                "fact_type": "material",
                "content": "synthetic admitted material premise",
            }],
            "claim_resolutions": [resolution],
            "bounded_inference_policies": [{
                "policy_ref": policy_ref,
                "maximum_risk_level": "medium",
            }],
        },
        "evidence_debug": {
            "admitted_answer_context": {
                "direct_product_facts": [{
                    "evidence_uid": evidence_ref,
                    "source_type": "product_facts",
                    "evidence_role": "product_fact_direct",
                    "claim_types_supported": ["material"],
                }],
                "direct_policy_facts": [],
                "unresolved_claims": [resolution],
            },
        },
    }


def qualification_fixtures() -> list[dict[str, Any]]:
    fixtures: list[dict[str, Any]] = []
    for cohort, text, expected_passed in (
        ("evidence_availability", _SAFE_TEXT, True),
        ("unsupported_test_status", _UNSAFE_TEXT, False),
    ):
        response = _response_with_inference(text)
        contract = _atomic_semantic_contract(response)
        if len(contract) != 1 or contract[0].get("required_qualifiers") != [
            "no_absolute_guarantee",
            "no_test_claim",
        ]:
            raise ValueError("qualification_contract_invalid")
        fixtures.append({
            "cohort": cohort,
            "expected_passed": expected_passed,
            "response": response,
            "contract": contract,
            "payload": {
                **_semantic_payload(response, "synthetic qualification", {}),
                "unified_textual_contract": contract,
            },
        })
    return fixtures


def _result_projection(
    parsed: dict[str, Any],
    *,
    contract: list[dict[str, Any]],
) -> tuple[dict[str, Any] | None, dict[str, Any], dict[str, Any]]:
    result, validation = _atomic_semantic_result_with_diagnostics(
        parsed,
        atomic_contract=contract,
    )
    budget_checks = (
        result.get("semantic_budget_checks")
        if isinstance(result, dict)
        else []
    )
    return result, validation, (
        budget_checks[0] if len(budget_checks) == 1 else {}
    )


def _record(
    *,
    cohort: str,
    attempt: int,
    expected_passed: bool,
    contract: list[dict[str, Any]],
    provider: _StrictProvider,
    parsed: dict[str, Any] | None,
    provider_error: str = "",
) -> dict[str, Any]:
    result: dict[str, Any] | None = None
    validation: dict[str, Any] = {}
    check: dict[str, Any] = {}
    if parsed is not None:
        result, validation, check = _result_projection(
            parsed,
            contract=contract,
        )
    passed = result.get("passed") if isinstance(result, dict) else None
    issues = result.get("issues") if isinstance(result, dict) else []
    qualified = bool(
        not provider_error
        and validation.get("category") == "accepted"
        and passed is expected_passed
        and (
            (expected_passed
             and check.get("qualifier_status") == "satisfied"
             and check.get("prohibited_extension_status") == "absent"
             and issues == [])
            or (
                not expected_passed
                and check.get("prohibited_extension_status") == "present"
                and issues == ["inference_scope_exceeded"]
            )
        )
    )
    return {
        "cohort": cohort,
        "attempt": attempt,
        "expected_passed": expected_passed,
        "qualified": qualified,
        "passed": passed,
        "issues": issues if isinstance(issues, list) else [],
        "semantic_budget_check": check,
        "validation_category": str(validation.get("category") or ""),
        "provider_error": provider_error,
        "provider_call_count": (
            0
            if provider_error in {
                "provider_not_configured",
                "strict_capability_not_supported",
            }
            else 1
        ),
        "provider_latency_ms": provider.last_latency_ms,
    }


def run_qualification(
    *,
    repeat: int = 5,
    provider: _StrictProvider | None = None,
) -> tuple[dict[str, Any], int]:
    if repeat != 5:
        raise ValueError("repeat_must_equal_5")
    fixtures = qualification_fixtures()
    role_provider = provider or StrictDecisionProviderService(
        config=StrictDecisionProviderConfig.from_unified_audit_environment()
    )
    metadata = role_provider.metadata()
    if metadata.get("configured") is not True:
        return {
            "schema_version": REPORT_SCHEMA_VERSION,
            "status": "invalid_run",
            "reason": "provider_not_configured",
            "provider": metadata,
            "real_customer_accuracy": None,
        }, 2

    records: list[dict[str, Any]] = []
    hard_stop_reason = ""
    for fixture in fixtures:
        for attempt in range(1, repeat + 1):
            try:
                parsed = role_provider.request(
                    name="unified_textual_audit_v4",
                    schema=_atomic_semantic_json_schema(fixture["contract"]),
                    system_prompt=_atomic_semantic_system_prompt(),
                    payload=copy.deepcopy(fixture["payload"]),
                    max_tokens=800,
                    allow_unqualified=True,
                )
                record = _record(
                    cohort=fixture["cohort"],
                    attempt=attempt,
                    expected_passed=fixture["expected_passed"],
                    contract=fixture["contract"],
                    provider=role_provider,
                    parsed=parsed,
                )
            except StrictDecisionProviderError as exc:
                record = _record(
                    cohort=fixture["cohort"],
                    attempt=attempt,
                    expected_passed=fixture["expected_passed"],
                    contract=fixture["contract"],
                    provider=role_provider,
                    parsed=None,
                    provider_error=str(exc) or "provider_request_failed",
                )
            records.append(record)
            if not record["qualified"]:
                hard_stop_reason = (
                    f"{fixture['cohort']}_attempt_{attempt}:"
                    f"{record['provider_error'] or record['validation_category'] or ','.join(record['issues']) or 'semantic_expectation_failed'}"
                )
                break
        if hard_stop_reason:
            break

    latencies = [
        item["provider_latency_ms"]
        for item in records
        if isinstance(item["provider_latency_ms"], (int, float))
    ]
    qualified = len(records) == 10 and all(item["qualified"] for item in records)
    qualification_fingerprint = ""
    fingerprint_method = getattr(
        role_provider,
        "qualification_fingerprint",
        None,
    )
    if callable(fingerprint_method):
        qualification_fingerprint = str(fingerprint_method() or "")
    report = {
        "schema_version": REPORT_SCHEMA_VERSION,
        "status": "qualified" if qualified else "not_qualified",
        "source_tree_sha256": _source_tree_sha256(),
        "provider": metadata,
        "qualification_fingerprint": qualification_fingerprint,
        "fixture_sha256": _canonical_hash([
            {
                "cohort": item["cohort"],
                "expected_passed": item["expected_passed"],
                "payload_sha256": _canonical_hash(item["payload"]),
            }
            for item in fixtures
        ]),
        "attempted": len(records),
        "provider_call_count": sum(
            int(item["provider_call_count"]) for item in records
        ),
        "retry_count": 0,
        "repair_count": 0,
        "formal_knowledge_read_count": 0,
        "formal_knowledge_dml": 0,
        "can_change_can_send": False,
        "gold_loaded": False,
        "p50_ms": round(statistics.median(latencies), 2) if latencies else None,
        "p95_ms": max(latencies) if latencies else None,
        "hard_stop_reason": hard_stop_reason,
        "records": records,
        "real_customer_accuracy": None,
    }
    report["report_content_sha256"] = _canonical_hash(report)
    return report, 0 if qualified else 2


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json-output", required=True)
    args = parser.parse_args()
    output = Path(args.json_output)
    if output.exists():
        raise SystemExit("qualification_output_exists")
    try:
        report, exit_code = run_qualification()
    except ValueError as exc:
        report = {
            "schema_version": REPORT_SCHEMA_VERSION,
            "status": "invalid_run",
            "reason": str(exc),
            "real_customer_accuracy": None,
        }
        exit_code = 2
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({
        "status": report["status"],
        "attempted": report.get("attempted", 0),
        "hard_stop_reason": report.get("hard_stop_reason", ""),
    }, ensure_ascii=False))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
