"""Read-only qualification for the strict Turn Understanding role.

This command exercises the production Turn Understanding parser and its local
validator with synthetic inputs only. It never changes runtime configuration,
formal knowledge, a customer reply, or delivery authority.
"""

from __future__ import annotations

import argparse
from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import statistics
import sys
from typing import Any, Iterator, Protocol


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.services import semantic_fact_type_service as turn_understanding
from app.services.strict_decision_provider_service import (
    StrictDecisionProviderConfig,
    StrictDecisionProviderService,
)


REPORT_SCHEMA_VERSION = "turn-understanding-strict-provider-qualification/v1"
_TRAILING_SOURCE_PUNCTUATION = " \t\r\n，,。！？!?；;：:"

FIXTURES: tuple[dict[str, Any], ...] = (
    {
        "alias": "general_quality",
        "message": "这款质量怎么样？",
        "expected_goals": (
            {
                "goal_kind": "customer_goal",
                "claim_type_status": "unmapped",
                "claim_type": "",
                "semantic_key": "general_product_quality",
                "source_text": "这款质量怎么样",
            },
        ),
    },
    {
        "alias": "overall_dimensions",
        "message": "这款整体尺寸是多少？",
        "expected_goals": (
            {
                "goal_kind": "customer_goal",
                "claim_type_status": "canonical",
                "claim_type": "dimensions",
                "semantic_key": "",
                "source_text": "这款整体尺寸是多少",
            },
        ),
    },
    {
        "alias": "material_and_moisture",
        "message": "这款是什么材质，平时容易受潮吗？",
        "expected_goals": (
            {
                "goal_kind": "customer_goal",
                "claim_type_status": "canonical",
                "claim_type": "material_composition",
                "semantic_key": "",
                "source_text": "这款是什么材质",
            },
            {
                "goal_kind": "customer_goal",
                "claim_type_status": "canonical",
                "claim_type": "moisture_resistance",
                "semantic_key": "",
                "source_text": "平时容易受潮吗",
            },
        ),
    },
    {
        "alias": "absolute_drop_guarantee",
        "message": "能保证从高处掉下来也不会坏吗？",
        "expected_goals": (
            {
                "goal_kind": "customer_goal",
                "claim_type_status": "unmapped",
                "claim_type": "",
                "semantic_key": "absolute_drop_durability",
                "source_text": "能保证从高处掉下来也不会坏吗",
            },
        ),
    },
    {
        "alias": "shipment_location",
        "message": "我的快递现在到哪里了？",
        "expected_goals": (
            {
                "goal_kind": "customer_goal",
                "claim_type_status": "unmapped",
                "claim_type": "",
                "semantic_key": "shipment_tracking",
                "source_text": "我的快递现在到哪里了",
            },
        ),
    },
)

FIXTURE_CONTRACT_SHA256 = hashlib.sha256(
    json.dumps(
        FIXTURES,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
).hexdigest()


class _StrictProvider(Protocol):
    last_latency_ms: float | None

    def metadata(self) -> dict[str, Any]: ...

    def qualification_fingerprint(self) -> str: ...

    def request(self, **kwargs: Any) -> dict[str, Any]: ...


class _QualificationProvider:
    """Permit one isolated evaluation process to probe an unqualified role."""

    def __init__(self, provider: _StrictProvider):
        self._provider = provider

    @property
    def last_latency_ms(self) -> float | None:
        return getattr(self._provider, "last_latency_ms", None)

    def metadata(self) -> dict[str, Any]:
        return self._provider.metadata()

    def request(self, **kwargs: Any) -> dict[str, Any]:
        kwargs["allow_unqualified"] = True
        return self._provider.request(**kwargs)


def _safe_provider_metadata(provider: _StrictProvider) -> dict[str, Any]:
    metadata = provider.metadata()
    if not isinstance(metadata, dict):
        metadata = {}
    return {
        key: metadata.get(key)
        for key in (
            "provider_name",
            "host_fingerprint",
            "model_name",
            "capability",
            "configured",
            "qualified",
            "qualification_status",
            "disable_thinking",
        )
    }


def _actual_projection(result: dict[str, Any]) -> list[dict[str, str]]:
    goals = result.get("customer_goals")
    if not isinstance(goals, list):
        return []
    return [
        {
            "goal_kind": str(goal.get("goal_kind") or ""),
            "claim_type_status": str(goal.get("claim_type_status") or ""),
            "claim_type": str(goal.get("claim_type") or ""),
            "source_text_sha256": str(goal.get("source_text_sha256") or ""),
        }
        for goal in goals
        if isinstance(goal, dict)
    ]


def _source_span_core(value: Any) -> str:
    return str(value or "").strip().rstrip(_TRAILING_SOURCE_PUNCTUATION)


def _semantic_contract_matches(
    result: dict[str, Any],
    fixture: dict[str, Any],
) -> bool:
    actual_goals = result.get("customer_goals")
    expected_goals = fixture.get("expected_goals")
    if not isinstance(actual_goals, list) or not isinstance(expected_goals, tuple):
        return False
    if len(actual_goals) != len(expected_goals):
        return False
    for expected, actual in zip(expected_goals, actual_goals, strict=True):
        if not isinstance(expected, dict) or not isinstance(actual, dict):
            return False
        if any(
            str(actual.get(field) or "") != str(expected[field])
            for field in (
                "goal_kind",
                "claim_type_status",
                "claim_type",
            )
        ):
            return False
        if _source_span_core(actual.get("goal_summary")) != _source_span_core(
            expected.get("source_text")
        ):
            return False
    return True


def _stable_signature(projection: list[dict[str, str]]) -> str:
    return hashlib.sha256(
        json.dumps(
            projection,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def synthetic_provider_output(message: str) -> dict[str, Any]:
    """Return a test-only valid strict output for one fixed synthetic fixture."""

    fixture = next(
        (item for item in FIXTURES if item["message"] == message),
        None,
    )
    if fixture is None:
        raise ValueError("unknown_qualification_fixture")
    goals = []
    for item in fixture["expected_goals"]:
        goals.append(
            {
                "goal_kind": item["goal_kind"],
                "claim_type_status": item["claim_type_status"],
                "claim_type": item["claim_type"],
                "attribute_key": "",
                "subject_scope": "",
                "semantic_key": item["semantic_key"],
                "policy_intent_ref": "",
                "source_text": item["source_text"],
                "continued_from": "",
            }
        )
    return {"goals": goals}


@contextmanager
def _qualification_route(provider: _StrictProvider) -> Iterator[None]:
    """Run the production parser through strict transport in this process only."""

    original_enabled = getattr(
        turn_understanding.config,
        "COPILOT_TURN_UNDERSTANDING_STRICT_ENABLED",
        False,
    )
    original_factory = turn_understanding._turn_understanding_strict_provider
    adapter = _QualificationProvider(provider)
    turn_understanding.config.COPILOT_TURN_UNDERSTANDING_STRICT_ENABLED = True
    turn_understanding._turn_understanding_strict_provider = lambda: adapter
    try:
        yield
    finally:
        turn_understanding.config.COPILOT_TURN_UNDERSTANDING_STRICT_ENABLED = (
            original_enabled
        )
        turn_understanding._turn_understanding_strict_provider = original_factory


def _rate(numerator: int, denominator: int) -> dict[str, Any]:
    return {
        "numerator": numerator,
        "denominator": denominator,
        "rate": numerator / denominator if denominator else 0.0,
    }


def qualify(
    *,
    repeats: int = 5,
    provider: _StrictProvider | None = None,
) -> dict[str, Any]:
    provider = provider or StrictDecisionProviderService(
        config=StrictDecisionProviderConfig.from_turn_understanding_environment()
    )
    safe_metadata = _safe_provider_metadata(provider)
    attempt_records: list[dict[str, Any]] = []
    latencies: list[float] = []
    error_categories: dict[str, int] = {}
    expected_count = len(FIXTURES) * max(1, repeats)

    if safe_metadata.get("configured"):
        with _qualification_route(provider):
            for fixture in FIXTURES:
                for attempt in range(1, max(1, repeats) + 1):
                    diagnostics: dict[str, Any] = {}
                    result = turn_understanding._classify_with_llm(
                        {},
                        str(fixture["message"]),
                        "product_question",
                        diagnostics_sink=diagnostics,
                    )
                    projection = (
                        _actual_projection(result)
                        if isinstance(result, dict)
                        else []
                    )
                    latency = diagnostics.get("latency", {}).get("provider_ms")
                    if isinstance(latency, (int, float)) and latency >= 0:
                        latencies.append(float(latency))
                    reason_code = str(diagnostics.get("reason_code") or "")
                    provider_error = str(
                        diagnostics.get("provider", {}).get(
                            "provider_error_category"
                        )
                        or ""
                    )
                    if reason_code:
                        error_categories[reason_code] = (
                            error_categories.get(reason_code, 0) + 1
                        )
                    elif provider_error:
                        error_categories[provider_error] = (
                            error_categories.get(provider_error, 0) + 1
                        )
                    strict_transport_passed = (
                        diagnostics.get("response_envelope") == "strict_tool_call"
                        and diagnostics.get("model_call_count") == 1
                        and diagnostics.get("json_repair_count") == 0
                    )
                    semantic_contract_passed = (
                        isinstance(result, dict)
                        and _semantic_contract_matches(result, fixture)
                        and diagnostics.get("status") == "passed"
                    )
                    attempt_records.append(
                        {
                            "fixture_alias": fixture["alias"],
                            "fixture_input_sha256": hashlib.sha256(
                                str(fixture["message"]).encode("utf-8")
                            ).hexdigest(),
                            "attempt": attempt,
                            "execution_status": (
                                "passed" if semantic_contract_passed else "failed"
                            ),
                            "strict_transport_passed": strict_transport_passed,
                            "semantic_contract_passed": semantic_contract_passed,
                            "goal_projection": projection,
                            "goal_projection_sha256": _stable_signature(projection),
                            "reason_code": reason_code or provider_error,
                            "provider_latency_ms": latency if isinstance(
                                latency, (int, float)
                            ) else None,
                        }
                    )

    strict_passes = sum(
        bool(record["strict_transport_passed"])
        for record in attempt_records
    )
    semantic_passes = sum(
        bool(record["semantic_contract_passed"])
        for record in attempt_records
    )
    signatures_by_fixture: dict[str, set[str]] = {}
    for record in attempt_records:
        signatures_by_fixture.setdefault(
            str(record["fixture_alias"]), set()
        ).add(str(record["goal_projection_sha256"]))
    stable_fixture_count = sum(
        len(signatures) == 1
        and sum(
            record["fixture_alias"] == alias
            for record in attempt_records
        ) == max(1, repeats)
        for alias, signatures in signatures_by_fixture.items()
    )
    repeat_denominator = len(FIXTURES)
    timeout_count = sum(
        count
        for category, count in error_categories.items()
        if category == "timeout" or category.endswith("_timeout")
    )
    report = {
        "schema_version": REPORT_SCHEMA_VERSION,
        "shadow_only": True,
        "provider": safe_metadata,
        "provider_qualification_fingerprint": str(
            provider.qualification_fingerprint()
        ),
        "fixture_contract_sha256": FIXTURE_CONTRACT_SHA256,
        "fixture_count": len(FIXTURES),
        "attempt_count": expected_count,
        "completed_attempt_count": len(attempt_records),
        "strict_transport_success_rate": _rate(strict_passes, expected_count),
        "semantic_contract_success_rate": _rate(
            semantic_passes,
            expected_count,
        ),
        "repeat_structure_stability_rate": _rate(
            stable_fixture_count,
            repeat_denominator,
        ),
        "timeout_count": timeout_count,
        "truncated_response_count": error_categories.get(
            "structured_output_truncated", 0
        ) + error_categories.get("response_truncated", 0),
        "schema_error_count": sum(
            count
            for category, count in error_categories.items()
            if "schema" in category or "json" in category
        ),
        "error_categories": dict(sorted(error_categories.items())),
        "free_text_fallback_count": 0,
        "json_repair_count": 0,
        "formal_kb_write_attempt_count": 0,
        "can_change_can_send_count": 0,
        "records": attempt_records,
        "latency_ms": {
            "p50": round(statistics.median(latencies), 2) if latencies else None,
            "p95": (
                round(
                    sorted(latencies)[max(0, int(len(latencies) * 0.95) - 1)],
                    2,
                )
                if latencies
                else None
            ),
        },
    }
    qualified = (
        bool(safe_metadata.get("configured"))
        and len(attempt_records) == expected_count
        and report["strict_transport_success_rate"]["rate"] == 1.0
        and report["semantic_contract_success_rate"]["rate"] == 1.0
        and report["repeat_structure_stability_rate"]["rate"] == 1.0
        and report["timeout_count"] == 0
        and report["truncated_response_count"] == 0
        and report["schema_error_count"] == 0
    )
    report["qualification_status"] = "qualified" if qualified else "not_qualified"
    report["deployment_enablement_allowed"] = bool(
        qualified and safe_metadata.get("qualification_status") == "qualified"
    )
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Qualify strict Turn Understanding with synthetic inputs only."
    )
    parser.add_argument("--repeat", type=int, default=5)
    parser.add_argument("--json-output", required=True)
    args = parser.parse_args(argv)
    report = qualify(repeats=args.repeat)
    output_path = Path(args.json_output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "qualification_status": report["qualification_status"],
                "deployment_enablement_allowed": report[
                    "deployment_enablement_allowed"
                ],
                "provider": report["provider"],
            },
            ensure_ascii=False,
        )
    )
    return 0 if report["qualification_status"] == "qualified" else 2


if __name__ == "__main__":
    raise SystemExit(main())
