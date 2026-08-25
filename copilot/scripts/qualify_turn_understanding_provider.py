"""Qualify a strict Turn Understanding provider with fictional inputs only."""

from __future__ import annotations

import argparse
import hashlib
import json
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.services.semantic_fact_type_service import (  # noqa: E402
    STRICT_PROVIDER_OUTPUT_SCHEMA,
    SYSTEM_PROMPT,
    _canonical_fact_type_candidates,
    _materialize_strict_source_refs,
    _sanitize_llm_result,
    _strict_source_units,
    _validate_raw_llm_result,
)
from app.services.strict_decision_provider_service import (  # noqa: E402
    StrictDecisionProviderConfig,
    StrictDecisionProviderError,
    StrictDecisionProviderService,
)


SCHEMA_VERSION = "turn-understanding-provider-qualification-v7"
_SIGNATURE_FIELDS = (
    "goal_kind",
    "claim_type_status",
    "claim_type",
    "attribute_key",
    "subject_scope",
    "semantic_key",
    "policy_intent_ref",
    "source_span_start",
    "source_span_end",
    "source_span_sha256",
)
_SOURCE_SIGNATURE_FIELDS = (
    "source_span_start",
    "source_span_end",
    "source_span_sha256",
)
_KNOWN_ERRORS = {
    "authentication_failed",
    "empty_structured_output",
    "provider_not_configured",
    "provider_not_qualified",
    "provider_request_failed",
    "rate_limited",
    "strict_capability_not_supported",
    "strict_schema_rejected",
    "strict_tool_call_missing",
    "structured_output_not_json",
    "structured_output_not_object",
    "structured_output_truncated",
    "timeout",
}


DEFAULT_CASES: list[dict[str, Any]] = [
    {
        "alias": "fictional-material",
        "customer_message": "这件虚构商品的主体材质是什么？",
        "current_intent": "product_question",
        "recent_conversation": [],
        "expected_claim_types": ["material_composition"],
        "expected_goal_kinds": ["customer_goal"],
        "expected_goal_count": 1,
    },
    {
        "alias": "fictional-dimensions-promotion",
        "customer_message": "请问商品整体尺寸是多少，今天还有优惠吗？",
        "current_intent": "product_question",
        "recent_conversation": [],
        "expected_claim_types": ["dimensions", "promotion_policy"],
        "expected_goal_kinds": ["customer_goal"],
        "expected_goal_count": 2,
    },
    {
        "alias": "fictional-confirmation-followup",
        "customer_message": "好的",
        "current_intent": "general",
        "recent_conversation": [
            {"role": "agent", "content": "需要我继续核对虚构订单吗？"},
        ],
        "expected_claim_types": [],
        "expected_goal_kinds": ["contextual_constraint"],
        "expected_goal_count": 1,
    },
    {
        "alias": "fictional-closure-followup",
        "customer_message": "其他没有问题了",
        "current_intent": "general",
        "recent_conversation": [
            {"role": "agent", "content": "还需要了解其他信息吗？"},
        ],
        "expected_claim_types": [],
        "expected_goal_kinds": ["contextual_constraint"],
        "expected_goal_count": 1,
    },
    {
        "alias": "fictional-installation-media",
        "customer_message": "请提供这件虚构商品的安装视频",
        "current_intent": "installation",
        "recent_conversation": [],
        "expected_claim_types": [],
        "expected_goal_kinds": ["media_request"],
        "expected_goal_count": 1,
    },
    {
        "alias": "fictional-carrier-action",
        "customer_message": "请帮我联系承运方核实这个虚构包裹的进度",
        "current_intent": "logistics",
        "recent_conversation": [],
        "expected_claim_types": [],
        "expected_goal_kinds": ["service_action"],
        "expected_goal_count": 1,
    },
    {
        "alias": "fictional-absolute-guarantee",
        "customer_message": "能绝对保证这件虚构商品永远不会损坏吗？",
        "current_intent": "product_question",
        "recent_conversation": [],
        "expected_claim_types": [],
        "expected_goal_kinds": ["customer_goal"],
        "expected_goal_count": 1,
    },
    {
        "alias": "fictional-current-source-boundary",
        "customer_message": "这件虚构商品应该怎么安装？",
        "current_intent": "installation",
        "recent_conversation": [
            {"role": "customer", "content": "上一件虚构商品是什么材质？"},
            {"role": "agent", "content": "我只处理当前问题。"},
        ],
        "expected_claim_types": ["installation"],
        "expected_goal_kinds": ["customer_goal"],
        "expected_goal_count": 1,
    },
    {
        "alias": "fictional-scoped-overall-dimensions",
        "customer_message": (
            "这件虚构商品的外包装整体尺寸是多少，"
            "完整商品展开后的整体尺寸是多少？"
        ),
        "current_intent": "product_question",
        "recent_conversation": [],
        "expected_claim_types": ["dimensions"],
        "expected_goal_kinds": ["customer_goal"],
        "expected_goal_count": 2,
        "expected_goal_signatures": [
            {
                "goal_kind": "customer_goal",
                "claim_type_status": "canonical",
                "claim_type": "dimensions",
                "attribute_key": "overall_dimensions",
                "subject_scope": "packaging",
            },
            {
                "goal_kind": "customer_goal",
                "claim_type_status": "canonical",
                "claim_type": "dimensions",
                "attribute_key": "overall_dimensions",
                "subject_scope": "product",
            },
        ],
    },
    {
        "alias": "fictional-colloquial-scoped-dimensions",
        "customer_message": (
            "虚构商品的发货包装多大？完整产品展开后的整体尺寸也分别告诉我，"
            "不要把两类尺寸混为一谈。"
        ),
        "current_intent": "product_question",
        "recent_conversation": [],
        "expected_claim_types": ["dimensions"],
        "expected_goal_kinds": [
            "customer_goal",
            "contextual_constraint",
        ],
        "expected_goal_count": 3,
        "expected_goal_signatures": [
            {
                "goal_kind": "customer_goal",
                "claim_type_status": "canonical",
                "claim_type": "dimensions",
                "attribute_key": "overall_dimensions",
                "subject_scope": "packaging",
            },
            {
                "goal_kind": "customer_goal",
                "claim_type_status": "canonical",
                "claim_type": "dimensions",
                "attribute_key": "overall_dimensions",
                "subject_scope": "product",
            },
            {
                "goal_kind": "contextual_constraint",
                "claim_type_status": "unmapped",
                "claim_type": "",
                "attribute_key": "",
                "subject_scope": "",
                "semantic_key": "rejection",
            },
        ],
    },
    {
        "alias": "fictional-installation-media-boundary",
        "customer_message": (
            "安装时先装哪一边？有视频的话也发我，"
            "没有就不要说已经发了。"
        ),
        "current_intent": "installation",
        "recent_conversation": [],
        "expected_claim_types": ["installation"],
        "expected_goal_kinds": [
            "customer_goal",
            "media_request",
            "contextual_constraint",
        ],
        "expected_goal_count": 3,
    },
    {
        "alias": "fictional-followup-detachable-reassembly",
        "customer_message": (
            "前面材质已经说清楚了，我现在追问的是能不能拆洗，"
            "以及拆下来的部件怎么装回去。"
        ),
        "current_intent": "installation",
        "recent_conversation": [
            {"role": "customer", "content": "这个商品是什么材质？"},
            {"role": "agent", "content": "材质信息已经说明。"},
        ],
        "expected_claim_types": ["detachable", "installation"],
        "expected_goal_kinds": ["customer_goal"],
        "expected_goal_count": 2,
    },
]


def _rate(numerator: int, denominator: int) -> dict[str, Any]:
    return {
        "numerator": numerator,
        "denominator": denominator,
        "rate": numerator / denominator if denominator else None,
    }


def _percentile(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, int(len(ordered) * percentile) - 1))
    return round(ordered[index], 2)


def _fixture_sha256(cases: list[dict[str, Any]]) -> str:
    payload = json.dumps(
        cases,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _history_texts(case: dict[str, Any]) -> list[str]:
    return [
        str(turn.get("content") or "")
        for turn in case.get("recent_conversation", [])
        if isinstance(turn, dict)
        and str(turn.get("role") or "").lower() in {"customer", "buyer", "user"}
        and str(turn.get("content") or "")
    ]


def _payload(case: dict[str, Any]) -> dict[str, Any]:
    message = str(case["customer_message"])
    payload: dict[str, Any] = {
        "customer_message": message,
        "current_intent": str(case.get("current_intent") or "general"),
        "canonical_fact_type_candidates": _canonical_fact_type_candidates(),
        "policy_intent_candidates": [],
        "source_units": _strict_source_units(message),
    }
    recent = case.get("recent_conversation")
    if isinstance(recent, list) and recent:
        payload["recent_conversation"] = recent
    return payload


def _safe_error(exc: Exception) -> str:
    if isinstance(exc, StrictDecisionProviderError):
        reason = str(exc).strip()
        return reason if reason in _KNOWN_ERRORS else "provider_request_failed"
    return "provider_request_failed"


def _semantic_matches(result: dict[str, Any], case: dict[str, Any]) -> bool:
    goals = result.get("customer_goals")
    if not isinstance(goals, list) or not goals:
        return False
    actual_claim_types = {
        str(goal.get("claim_type") or "")
        for goal in goals
        if isinstance(goal, dict) and goal.get("claim_type")
    }
    actual_goal_kinds = {
        str(goal.get("goal_kind") or "")
        for goal in goals
        if isinstance(goal, dict) and goal.get("goal_kind")
    }
    expected_claim_types = set(case.get("expected_claim_types") or [])
    expected_goal_kinds = set(case.get("expected_goal_kinds") or [])
    expected_goal_count = case.get("expected_goal_count")
    expected_goal_signatures = case.get("expected_goal_signatures") or []
    remaining_goals = [goal for goal in goals if isinstance(goal, dict)]
    signatures_match = True
    for expected in expected_goal_signatures:
        if not isinstance(expected, dict):
            signatures_match = False
            break
        matched_index = next(
            (
                index
                for index, goal in enumerate(remaining_goals)
                if all(goal.get(key) == value for key, value in expected.items())
            ),
            None,
        )
        if matched_index is None:
            signatures_match = False
            break
        remaining_goals.pop(matched_index)
    return (
        expected_claim_types.issubset(actual_claim_types)
        and expected_goal_kinds.issubset(actual_goal_kinds)
        and (
            expected_goal_count is None
            or len(goals) == int(expected_goal_count)
        )
        and signatures_match
    )


def _signature_field_value(goal: dict[str, Any], key: str) -> Any:
    if key != "semantic_key":
        return goal.get(key)
    semantic_key = str(goal.get("semantic_key") or "").strip()
    if goal.get("goal_kind") == "contextual_constraint":
        return semantic_key
    if (
        goal.get("goal_kind") == "customer_goal"
        and goal.get("claim_type_status") == "unmapped"
    ):
        if str(goal.get("policy_intent_ref") or "").strip():
            return semantic_key
        return "present" if semantic_key else ""
    return ""


def _signature_projection(result: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            key: _signature_field_value(goal, key)
            for key in _SIGNATURE_FIELDS
        }
        for goal in result.get("customer_goals", [])
        if isinstance(goal, dict)
    ]


def _subset_signature(
    projection: list[dict[str, Any]],
    fields: tuple[str, ...],
) -> str:
    subset = [
        {field: row.get(field) for field in fields}
        for row in projection
    ]
    return hashlib.sha256(
        json.dumps(
            subset,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _signature(result: dict[str, Any]) -> str:
    goals = _signature_projection(result)
    return hashlib.sha256(
        json.dumps(
            goals,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _changed_field_names(
    projections: list[list[dict[str, Any]]],
) -> list[str]:
    if len(projections) < 2:
        return []
    changed: set[str] = set()
    goal_counts = {len(projection) for projection in projections}
    if len(goal_counts) > 1:
        changed.add("customer_goals")
    comparable_count = min(goal_counts)
    for index in range(comparable_count):
        for field in _SIGNATURE_FIELDS:
            if len({
                json.dumps(
                    projection[index].get(field),
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                )
                for projection in projections
            }) > 1:
                changed.add(field)
    return sorted(changed)


def _stability_diagnostics(
    signatures: list[str],
    projections: list[list[dict[str, Any]]],
) -> dict[str, Any]:
    return {
        "signature_variant_count": len(set(signatures)),
        "stable_attempt_count": (
            sum(value == signatures[0] for value in signatures)
            if signatures
            else 0
        ),
        "changed_field_names": _changed_field_names(projections),
    }


def qualify(
    *,
    provider: StrictDecisionProviderService | None = None,
    cases: list[dict[str, Any]] | None = None,
    repeats: int = 3,
) -> dict[str, Any]:
    provider = provider or StrictDecisionProviderService(
        StrictDecisionProviderConfig.from_turn_understanding_environment()
    )
    selected_cases = list(cases or DEFAULT_CASES)
    repeat_count = max(1, int(repeats))
    metadata = provider.metadata()
    errors: Counter[str] = Counter()
    signatures: dict[str, list[str]] = defaultdict(list)
    semantic_signatures: dict[str, list[str]] = defaultdict(list)
    source_signatures: dict[str, list[str]] = defaultdict(list)
    signature_projections: dict[
        str,
        list[list[dict[str, Any]]],
    ] = defaultdict(list)
    successful_latencies: list[float] = []
    case_counts: dict[str, Counter[str]] = defaultdict(Counter)
    total_attempts = len(selected_cases) * repeat_count
    execution_success = 0
    schema_success = 0
    current_source_success = 0
    semantic_success = 0

    if metadata.get("configured"):
        for case in selected_cases:
            alias = str(case.get("alias") or "unnamed")
            message = str(case.get("customer_message") or "")
            history_texts = _history_texts(case)
            for _ in range(repeat_count):
                try:
                    raw = provider.request(
                        name="turn_understanding",
                        schema=STRICT_PROVIDER_OUTPUT_SCHEMA,
                        system_prompt=SYSTEM_PROMPT,
                        payload=_payload(case),
                        max_tokens=1200,
                        allow_unqualified=True,
                    )
                    execution_success += 1
                    case_counts[alias]["execution"] += 1
                    raw, source_ref_violations = (
                        _materialize_strict_source_refs(
                            raw,
                            message=message,
                        )
                    )
                    if source_ref_violations:
                        reason = str(
                            source_ref_violations[0].get("reason_code")
                            or "source_reference_invalid"
                        )
                        errors[reason] += 1
                        continue
                    if raw is None:
                        errors["source_reference_invalid"] += 1
                        continue
                    schema_violations, provenance_violations = (
                        _validate_raw_llm_result(
                            raw,
                            message=message,
                            history_texts=history_texts,
                        )
                    )
                    if schema_violations:
                        reason = str(
                            schema_violations[0].get("reason_code")
                            or "schema_validation_failed"
                        )
                        errors[reason] += 1
                        continue
                    schema_success += 1
                    case_counts[alias]["schema"] += 1
                    if provenance_violations:
                        reason = str(
                            provenance_violations[0].get("reason_code")
                            or "source_provenance_failed"
                        )
                        errors[reason] += 1
                        continue
                    current_source_success += 1
                    case_counts[alias]["current_source"] += 1
                    normalized = _sanitize_llm_result(
                        raw,
                        message=message,
                        history_texts=history_texts,
                        canonicalize_source_clauses=True,
                    )
                    if not normalized or normalized.get(
                        "goal_understanding_status"
                    ) != "valid":
                        errors["canonical_normalization_failed"] += 1
                        continue
                    if not _semantic_matches(normalized, case):
                        errors["semantic_expectation_failed"] += 1
                        continue
                    semantic_success += 1
                    case_counts[alias]["semantic"] += 1
                    projection = _signature_projection(normalized)
                    signatures[alias].append(_signature(normalized))
                    semantic_signatures[alias].append(_subset_signature(
                        projection,
                        tuple(
                            field
                            for field in _SIGNATURE_FIELDS
                            if field not in _SOURCE_SIGNATURE_FIELDS
                        ),
                    ))
                    source_signatures[alias].append(_subset_signature(
                        projection,
                        _SOURCE_SIGNATURE_FIELDS,
                    ))
                    signature_projections[alias].append(projection)
                    latency = provider.last_latency_ms
                    if isinstance(latency, (int, float)):
                        successful_latencies.append(float(latency))
                except Exception as exc:
                    errors[_safe_error(exc)] += 1

    stable_attempts = 0
    semantic_stable_attempts = 0
    source_stable_attempts = 0
    stable_denominator = 0
    for case in selected_cases:
        alias = str(case.get("alias") or "unnamed")
        values = signatures.get(alias, [])
        stable_denominator += repeat_count
        if len(values) == repeat_count and values:
            stable_attempts += sum(value == values[0] for value in values)
        semantic_values = semantic_signatures.get(alias, [])
        if len(semantic_values) == repeat_count and semantic_values:
            semantic_stable_attempts += sum(
                value == semantic_values[0] for value in semantic_values
            )
        source_values = source_signatures.get(alias, [])
        if len(source_values) == repeat_count and source_values:
            source_stable_attempts += sum(
                value == source_values[0] for value in source_values
            )

    case_results = [
        {
            "alias": str(case.get("alias") or "unnamed"),
            "case_sha256": hashlib.sha256(
                json.dumps(
                    case,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            ).hexdigest(),
            "execution_success_count": case_counts[
                str(case.get("alias") or "unnamed")
            ]["execution"],
            "schema_success_count": case_counts[
                str(case.get("alias") or "unnamed")
            ]["schema"],
            "current_source_success_count": case_counts[
                str(case.get("alias") or "unnamed")
            ]["current_source"],
            "semantic_success_count": case_counts[
                str(case.get("alias") or "unnamed")
            ]["semantic"],
            **_stability_diagnostics(
                signatures.get(
                    str(case.get("alias") or "unnamed"),
                    [],
                ),
                signature_projections.get(
                    str(case.get("alias") or "unnamed"),
                    [],
                ),
            ),
        }
        for case in selected_cases
    ]
    report = {
        "schema_version": SCHEMA_VERSION,
        "shadow_only": True,
        "provider": metadata,
        "qualification_fingerprint": provider.qualification_fingerprint(),
        "fixture_sha256": _fixture_sha256(selected_cases),
        "case_count": len(selected_cases),
        "repeat_count": repeat_count,
        "total_attempt_count": total_attempts,
        "successful_attempt_count": semantic_success,
        "execution_success_rate": _rate(execution_success, total_attempts),
        "schema_success_rate": _rate(schema_success, total_attempts),
        "current_source_success_rate": _rate(
            current_source_success,
            total_attempts,
        ),
        "semantic_success_rate": _rate(semantic_success, total_attempts),
        "repeat_stability_rate": _rate(
            stable_attempts,
            stable_denominator,
        ),
        "semantic_repeat_stability_rate": _rate(
            semantic_stable_attempts,
            stable_denominator,
        ),
        "source_provenance_repeat_stability_rate": _rate(
            source_stable_attempts,
            stable_denominator,
        ),
        "timeout_attempt_count": errors.get("timeout", 0),
        "truncated_attempt_count": errors.get(
            "structured_output_truncated",
            0,
        ),
        "schema_error_attempt_count": sum(
            count
            for reason, count in errors.items()
            if "schema" in reason or "field" in reason
        ),
        "free_text_fallback_attempt_count": 0,
        "error_categories": dict(sorted(errors.items())),
        "latency_ms": {
            "p50": (
                round(statistics.median(successful_latencies), 2)
                if successful_latencies
                else None
            ),
            "p95": _percentile(successful_latencies, 0.95),
        },
        "case_results": case_results,
        "formal_kb_write_attempt_count": 0,
        "can_change_can_send_count": 0,
    }
    qualified = (
        bool(metadata.get("configured"))
        and total_attempts > 0
        and execution_success == total_attempts
        and schema_success == total_attempts
        and current_source_success == total_attempts
        and semantic_success == total_attempts
        and stable_attempts == stable_denominator
        and not errors
    )
    report["qualification_status"] = (
        "qualified" if qualified else "not_qualified"
    )
    report["strict_enablement_allowed"] = False
    report["strict_enablement_requires_configuration_pin"] = bool(qualified)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Qualify a strict Turn Understanding provider without changing "
            "production behavior."
        )
    )
    parser.add_argument("--repeat", type=int, default=3)
    parser.add_argument("--json-output", required=True)
    args = parser.parse_args()
    report = qualify(repeats=args.repeat)
    output = Path(args.json_output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps({
        "qualification_status": report["qualification_status"],
        "case_count": report["case_count"],
        "total_attempt_count": report["total_attempt_count"],
        "provider": report["provider"],
    }, ensure_ascii=False))
    return 0 if report["qualification_status"] == "qualified" else 2


if __name__ == "__main__":
    raise SystemExit(main())
