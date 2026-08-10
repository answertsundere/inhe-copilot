"""Build and run the Phase 1.10 answer-eligibility qualification matrix.

This evaluator never invokes the composer and never changes formal response
fields. Expected labels are kept outside the request payload passed to the
shared admission and eligibility service.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import re
import secrets
import subprocess
import sys
import tempfile
from collections import Counter
from copy import deepcopy
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.repositories.file_policy_repository import FilePolicyRepository
from app.services.canonical_conversation_turn_service import (
    canonical_current_customer_turn_uid,
)
from app.services.admitted_answer_context_service import AdmittedAnswerContextService
from app.services.formal_knowledge_database_guard_service import (
    fingerprint_formal_knowledge_tables,
)
from app.services.real_derived_evidence_fixture_service import (
    validate_real_derived_fixture,
)
from app.services.semantic_fact_type_service import (
    GOAL_IDENTITY_SCHEMA_VERSION,
    _goal_ref,
)


DATASET_ID = "risk-tier-fast-path-qualification"
DATASET_VERSION = "1.0.0"
SCHEMA_VERSION = "risk-tier-fast-path-qualification/v1"
EVALUATOR_SCHEMA_VERSION = "risk-tier-fast-path-evaluator/v1"
SHUFFLE_SEED = 1101
BASELINE_COMMIT = "2ceac9c204a5a878e3d2bac1db0b7091ca7256da"
FROZEN_DATASET_SHA256 = (
    "59583cf0806435a9f74559f0af4b5daadb731132335bf79b622c01d14b3021bf"
)
DOMAIN_POLICY_ID = "maternal_child_home"
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_PHONE_RE = re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)")
_URL_RE = re.compile(r"https?://", re.I)
_SECRET_RE = re.compile(r"(?:sk-|api[_-]?key|password|token|dsn)\s*[:=]", re.I)


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha256(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _runtime_identity() -> dict[str, Any]:
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=PROJECT_ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    source_files = (
        PROJECT_ROOT / "app" / "services" / "admitted_answer_context_service.py",
        Path(__file__).resolve(),
    )
    source_contract = [
        {
            "name": path.name,
            "sha256": _file_sha256(path),
        }
        for path in source_files
    ]
    return {
        "runtime_commit": commit,
        "source_contract_sha256": _sha256(source_contract),
        "source_file_count": len(source_contract),
    }


def _question_variants(fact_type: str) -> tuple[str, str]:
    questions = {
        "material": ("这款商品是什么材质？", "请直接说明当前商品的材质。"),
        "dimensions": ("这款商品的尺寸是多少？", "请直接说明当前商品的尺寸。"),
        "gross_weight": ("这款商品的毛重是多少？", "请直接说明当前商品的毛重。"),
    }
    if fact_type not in questions:
        raise ValueError(f"unsupported_positive_fact_type:{fact_type}")
    return questions[fact_type]


def _claim_for_message(
    *,
    message: str,
    claim_type: str,
    attribute_key: str,
    risk_level: str = "low",
) -> dict[str, Any]:
    """Build the same canonical goal projection consumed by eligibility."""
    source_digest = hashlib.sha256(message.encode("utf-8")).hexdigest()
    claim = {
        "schema_version": GOAL_IDENTITY_SCHEMA_VERSION,
        "goal_kind": "customer_goal",
        "claim_type_status": "canonical",
        "claim_type": claim_type,
        "claim_type_exact_match": True,
        "attribute_key": attribute_key,
        "semantic_key": "",
        "policy_intent_ref": "",
        "policy_goal_family": "",
        "policy_intent_kind": "",
        "goal_summary": message,
        "source": "current_customer_message",
        "source_span_start": 0,
        "source_span_end": len(message),
        "source_span_sha256": source_digest,
        "source_text_sha256": source_digest,
        "source_turn_uid": canonical_current_customer_turn_uid(message),
        "owner": "turn_understanding_owner",
        "source_stage": "query_fact_type_classifier",
        "question": message,
        "risk_level": risk_level,
    }
    claim["goal_ref"] = _goal_ref(claim)
    return claim


def _candidate_from_fact(
    fact: dict[str, Any],
    identity: dict[str, Any],
) -> dict[str, Any]:
    return {
        "evidence_uid": str(fact["evidence_uid"]),
        "origin_evidence_key": f"real-derived:{fact['evidence_uid']}",
        "source_type": "product_facts",
        "evidence_role": "product_fact_direct",
        "fact_type": str(fact["fact_type"]),
        "attribute_key": str(fact.get("attribute_key") or ""),
        "content": str(fact["content"]),
        "sku_code": str(identity.get("sku_code") or ""),
        "i_id": str(identity.get("i_id") or ""),
        "fact_review_status": str(fact["review_status"]),
        "gate_status": "allowed",
        "direct_answer_allowed": True,
        "material_provenance": "structured_product_record",
        "provenance_hash": str(fact["provenance_hash"]),
    }


def _positive_request(
    *,
    index: int,
    identity: dict[str, Any],
    fact: dict[str, Any],
    message: str,
) -> dict[str, Any]:
    return {
        "customer_message": message,
        "product_identity": dict(identity),
        "understanding": {
            "schema_version": "turn-understanding/v2",
            "owner": "turn_understanding_owner",
            "source_stage": "query_fact_type_classifier",
            "goal_understanding_status": "valid",
            "goal_understanding_diagnostics": [],
            "requested_claims": [
                _claim_for_message(
                    message=message,
                    claim_type=str(fact["fact_type"]),
                    attribute_key=str(fact.get("attribute_key") or ""),
                )
            ],
        },
        "response": {
            "formal_evidence_candidates": [
                _candidate_from_fact(fact, identity)
            ],
            "can_send": False,
            "requires_human_review": True,
            "sendable_reply": "",
        },
        "owner_context": {
            "conversation_reference_status": {
                "status": "not_required",
                "source_stage": "canonical_context_resolution",
                "reason_codes": [],
            },
            "tool_requirement_status": {
                "status": "not_required",
                "required_tool_refs": [],
                "completed_tool_refs": [],
                "source_stage": "tool_router_and_executor",
                "reason_codes": [],
            },
        },
        "domain_policy_variant": "loaded",
    }


def _set_claim_type(
    request: dict[str, Any],
    claim_type: str,
    *,
    risk_level: str,
    attribute_key: str = "",
) -> None:
    claim = request["understanding"]["requested_claims"][0]
    claim.update({
        "claim_type": claim_type,
        "attribute_key": attribute_key,
        "risk_level": risk_level,
    })


def _candidate(request: dict[str, Any]) -> dict[str, Any]:
    return request["response"]["formal_evidence_candidates"][0]


def _mutation_request(base: dict[str, Any], kind: str) -> dict[str, Any]:
    request = deepcopy(base)
    claim = request["understanding"]["requested_claims"][0]
    candidate = _candidate(request)

    if kind == "goal_missing":
        request["understanding"]["requested_claims"] = []
    elif kind == "goal_multiple":
        second = deepcopy(claim)
        second["goal_ref"] = f"{claim['goal_ref']}-second"
        request["understanding"]["requested_claims"].append(second)
    elif kind == "understanding_degraded":
        request["understanding"]["goal_understanding_status"] = "degraded"
        request["understanding"]["goal_understanding_diagnostics"] = ["owner_degraded"]
    elif kind == "understanding_invalid":
        request["understanding"]["goal_understanding_status"] = "invalid"
        request["understanding"]["goal_understanding_diagnostics"] = ["owner_invalid"]
    elif kind == "goal_owner_invalid":
        claim["owner"] = "public_request"
    elif kind == "goal_stage_invalid":
        claim["source_stage"] = "public_context"
    elif kind == "goal_source_invalid":
        claim["source"] = "conversation_history"
    elif kind == "goal_span_hash_invalid":
        claim["source_span_sha256"] = "0" * 64
    elif kind == "goal_span_range_invalid":
        claim["source_span_end"] = len(request["customer_message"]) + 10
    elif kind == "reference_unknown":
        request["owner_context"]["conversation_reference_status"]["status"] = "unknown"
    elif kind == "reference_ambiguous":
        request["owner_context"]["conversation_reference_status"]["status"] = "ambiguous"
    elif kind in {
        "live_tool_required",
        "live_tool_completed",
        "live_tool_failed",
        "action_tool_required",
    }:
        request["owner_context"]["tool_requirement_status"]["status"] = kind
        request["owner_context"]["tool_requirement_status"]["required_tool_refs"] = ["tool-ref"]
    elif kind == "bounded_inference_required":
        _set_claim_type(request, "placement_scene", risk_level="medium")
    elif kind == "unresolved_claim":
        request["response"]["formal_evidence_candidates"] = []
    elif kind == "conflicting_numeric_facts":
        _set_claim_type(request, "gross_weight", risk_level="low", attribute_key="gross_weight")
        candidate.update({
            "fact_type": "gross_weight",
            "attribute_key": "gross_weight",
            "content": "10kg",
        })
        second = deepcopy(candidate)
        second.update({
            "evidence_uid": f"{candidate['evidence_uid']}-conflict",
            "origin_evidence_key": f"{candidate['origin_evidence_key']}-conflict",
            "content": "12kg",
        })
        request["response"]["formal_evidence_candidates"].append(second)
    elif kind == "prohibited_claim":
        claim.update({
            "prohibited": True,
            "direct_handling_prohibited": True,
            "prohibition_reason": "evaluation_prohibited_claim",
        })
    elif kind == "evidence_dependency":
        dependency = {
            "goal_kind": "evidence_dependency",
            "claim_type": claim["claim_type"],
            "attribute_key": claim.get("attribute_key") or "",
            "question": request["customer_message"],
            "risk_level": "low",
            "supporting_only": True,
        }
        request["understanding"]["requested_claims"].append(dependency)
    elif kind == "service_action":
        request["response"]["product_context_pack"] = {
            "generic_rules": [{
                "evidence_uid": "nonfact-service-action",
                "source_type": "generic_rule",
                "evidence_role": "service_action",
                "content": "人工处理动作",
            }]
        }
    elif kind == "media_candidate":
        request["response"]["recommended_assets"] = [{
            "evidence_uid": "nonfact-media-reference",
            "source_type": "media_reference",
            "evidence_role": "media_reference",
            "asset_type": "image",
        }]
    elif kind == "identity_mismatch":
        candidate["sku_code"] = "fixture-sku-mismatch"
        candidate["i_id"] = "fixture-iid-mismatch"
    elif kind == "identity_namespace_missing":
        candidate.pop("sku_code", None)
        candidate.pop("i_id", None)
        candidate["product_id"] = "fixture-product-other-namespace"
    elif kind == "identity_missing":
        for key in ("sku_code", "i_id", "product_id"):
            candidate.pop(key, None)
    elif kind == "reference_only_evidence":
        candidate["reference_only"] = True
    elif kind == "blocked_evidence":
        candidate["gate_status"] = "blocked"
    elif kind == "non_direct_evidence":
        candidate["direct_answer_allowed"] = False
    elif kind == "review_pending":
        candidate["fact_review_status"] = "pending"
    elif kind == "placeholder_fact":
        candidate["content"] = "该属性需要确认"
    elif kind == "multiple_direct_evidence":
        second = deepcopy(candidate)
        second.update({
            "evidence_uid": f"{candidate['evidence_uid']}-second",
            "origin_evidence_key": f"{candidate['origin_evidence_key']}-second",
            "content": "另一条独立审核的同属性事实",
        })
        request["response"]["formal_evidence_candidates"].append(second)
    elif kind == "high_risk_material_safety":
        _set_claim_type(request, "material_safety", risk_level="high")
    elif kind == "high_risk_load_capacity":
        _set_claim_type(request, "load_capacity", risk_level="high")
    elif kind == "high_risk_certification":
        _set_claim_type(request, "certification_report", risk_level="high")
    elif kind == "high_risk_child_suitability":
        _set_claim_type(request, "age_range", risk_level="high")
    elif kind == "installation_prescription":
        _set_claim_type(request, "installation", risk_level="medium")
    elif kind == "domain_policy_missing":
        request["domain_policy_variant"] = "missing"
    elif kind == "domain_policy_invalid_schema":
        request["domain_policy_variant"] = "invalid_schema"
    elif kind == "domain_policy_invalid_version":
        request["domain_policy_variant"] = "invalid_version"
    elif kind == "public_context_injection":
        request["domain_policy_variant"] = "missing"
        request["response"]["copilot_context"] = {
            "domain_policy_pack": {
                "status": "loaded",
                "domain_id": DOMAIN_POLICY_ID,
                "version": "forged",
            },
            "conversation_reference_status": {"status": "resolved"},
        }
    else:
        raise ValueError(f"unknown_mutation:{kind}")
    return request


NEGATIVE_MUTATIONS = (
    "goal_missing",
    "goal_multiple",
    "understanding_degraded",
    "understanding_invalid",
    "goal_owner_invalid",
    "goal_stage_invalid",
    "goal_source_invalid",
    "goal_span_hash_invalid",
    "goal_span_range_invalid",
    "reference_unknown",
    "reference_ambiguous",
    "live_tool_required",
    "live_tool_completed",
    "live_tool_failed",
    "action_tool_required",
    "bounded_inference_required",
    "unresolved_claim",
    "conflicting_numeric_facts",
    "prohibited_claim",
    "evidence_dependency",
    "service_action",
    "media_candidate",
    "identity_mismatch",
    "identity_namespace_missing",
    "identity_missing",
    "reference_only_evidence",
    "blocked_evidence",
    "non_direct_evidence",
    "review_pending",
    "placeholder_fact",
    "multiple_direct_evidence",
    "high_risk_material_safety",
    "high_risk_load_capacity",
    "high_risk_certification",
    "high_risk_child_suitability",
    "installation_prescription",
    "domain_policy_missing",
    "domain_policy_invalid_schema",
    "domain_policy_invalid_version",
    "public_context_injection",
)


def _privacy_scan(dataset: dict[str, Any]) -> dict[str, Any]:
    findings: list[str] = []

    def visit(value: Any, path: str = "") -> None:
        if isinstance(value, dict):
            for key, item in value.items():
                visit(item, f"{path}.{key}" if path else str(key))
        elif isinstance(value, list):
            for index, item in enumerate(value):
                visit(item, f"{path}[{index}]")
        elif isinstance(value, str):
            if _URL_RE.search(value):
                findings.append(f"url:{path}")
            if _PHONE_RE.search(value):
                findings.append(f"phone:{path}")
            if _SECRET_RE.search(value):
                findings.append(f"credential:{path}")

    visit(dataset)
    return {"passed": not findings, "finding_count": len(findings), "findings": findings}


def build_qualification_dataset(
    source_fixture: dict[str, Any],
    source_manifest: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    validate_real_derived_fixture(source_fixture, source_manifest)
    facts = [
        (product["identity"], fact)
        for product in source_fixture["products"]
        for fact in product["facts"]
        if fact.get("fact_type") in {"material", "dimensions", "gross_weight"}
    ]
    fact_types = Counter(str(fact["fact_type"]) for _identity, fact in facts)
    product_uids = {
        str(identity.get("i_id") or identity.get("sku_code"))
        for identity, _fact in facts
    }
    if len(facts) < 15 or len(fact_types) < 3 or len(product_uids) < 10:
        raise ValueError("source_fixture_coverage_insufficient")

    positives: list[dict[str, Any]] = []
    for fact_index, (identity, fact) in enumerate(facts[:15]):
        for variant_index, question in enumerate(_question_variants(str(fact["fact_type"]))):
            index = fact_index * 2 + variant_index
            case_seed = f"{index}|{fact['evidence_uid']}"
            positives.append({
                "case_uid": f"positive-{hashlib.sha256(case_seed.encode()).hexdigest()[:20]}",
                "kind": "positive",
                "request": _positive_request(
                    index=index,
                    identity=identity,
                    fact=fact,
                    message=question,
                ),
                "expected": {
                    "eligible": True,
                    "admitted_evidence_count": 1,
                    "supported_resolution_count": 1,
                },
            })
    if len(positives) != 30:
        raise ValueError("positive_case_count_invalid")

    material_base = next(
        item for item in positives
        if item["request"]["understanding"]["requested_claims"][0]["claim_type"] == "material"
    )
    negatives: list[dict[str, Any]] = []
    for index, mutation in enumerate(NEGATIVE_MUTATIONS):
        negatives.append({
            "case_uid": f"negative-{hashlib.sha256(mutation.encode()).hexdigest()[:20]}",
            "kind": "negative",
            "mutation": mutation,
            "request": _mutation_request(material_base["request"], mutation),
            "expected": {"eligible": False, "category": mutation},
        })

    dataset = {
        "dataset_id": DATASET_ID,
        "dataset_version": DATASET_VERSION,
        "schema_version": SCHEMA_VERSION,
        "source_kind": "real_derived_formal_product_facts",
        "source_dataset_id": source_fixture["dataset_id"],
        "source_dataset_version": source_fixture["dataset_version"],
        "source_snapshot_sha256": source_fixture["source_snapshot_hash"],
        "source_fixture_sha256": source_manifest["fixture_sha256"],
        "baseline_commit": BASELINE_COMMIT,
        "privacy_status": "passed",
        "labels_are_evaluator_only": True,
        "cases": [*positives, *negatives],
    }
    privacy = _privacy_scan(dataset)
    if not privacy["passed"]:
        raise ValueError("qualification_fixture_privacy_failed")
    manifest = {
        "dataset_id": DATASET_ID,
        "dataset_version": DATASET_VERSION,
        "schema_version": SCHEMA_VERSION,
        "dataset_sha256": _sha256(dataset),
        "positive_count": len(positives),
        "negative_count": len(negatives),
        "fact_type_counts": dict(sorted(Counter(
            case["request"]["understanding"]["requested_claims"][0]["claim_type"]
            for case in positives
        ).items())),
        "anonymous_product_count": len({
            case["request"]["product_identity"].get("i_id")
            or case["request"]["product_identity"].get("sku_code")
            for case in positives
        }),
        "source_snapshot_sha256": source_fixture["source_snapshot_hash"],
        "source_fixture_sha256": source_manifest["fixture_sha256"],
        "baseline_commit": BASELINE_COMMIT,
        "evaluator_source_sha256": _file_sha256(Path(__file__)),
        "privacy_scan": privacy,
    }
    return dataset, manifest


def validate_dataset(dataset: dict[str, Any], manifest: dict[str, Any]) -> None:
    if dataset.get("dataset_id") != DATASET_ID:
        raise ValueError("dataset_id_invalid")
    if dataset.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("dataset_schema_invalid")
    if manifest.get("dataset_sha256") != _sha256(dataset):
        raise ValueError("dataset_hash_mismatch")
    cases = dataset.get("cases")
    if not isinstance(cases, list):
        raise ValueError("dataset_cases_invalid")
    if len({case.get("case_uid") for case in cases}) != len(cases):
        raise ValueError("duplicate_case_uid")
    positive_count = sum(case.get("kind") == "positive" for case in cases)
    negative_count = sum(case.get("kind") == "negative" for case in cases)
    if positive_count == 0:
        raise ValueError("positive_denominator_empty")
    if negative_count == 0:
        raise ValueError("negative_denominator_empty")
    if positive_count != 30 or negative_count != 40:
        raise ValueError("dataset_case_count_changed")
    if manifest.get("dataset_sha256") != FROZEN_DATASET_SHA256:
        raise ValueError("frozen_dataset_hash_mismatch")
    if manifest.get("positive_count") != positive_count:
        raise ValueError("manifest_positive_count_mismatch")
    if manifest.get("negative_count") != negative_count:
        raise ValueError("manifest_negative_count_mismatch")
    if dataset.get("labels_are_evaluator_only") is not True:
        raise ValueError("evaluator_label_boundary_missing")
    if not _privacy_scan(dataset)["passed"]:
        raise ValueError("dataset_privacy_failed")
    for field in ("dataset_sha256", "source_snapshot_sha256", "source_fixture_sha256"):
        if not _SHA256_RE.fullmatch(str(manifest.get(field) or "")):
            raise ValueError(f"{field}_invalid")


def _domain_policy(
    variant: str,
    repository: FilePolicyRepository,
) -> dict[str, Any]:
    if variant == "loaded":
        return repository.resolve_domain_policy_pack(
            {"catalog_metadata": {"domain_policy_id": DOMAIN_POLICY_ID}}
        )
    if variant == "missing":
        return {
            "schema_version": "domain-policy-pack/v1",
            "domain_id": "",
            "version": "",
            "status": "missing",
            "reason_codes": ["domain_policy_pack_not_provided"],
            "claim_policies": {},
        }
    reason = (
        "domain_policy_schema_invalid"
        if variant == "invalid_schema"
        else "domain_policy_version_invalid"
    )
    return {
        "schema_version": "domain-policy-pack/v1",
        "domain_id": DOMAIN_POLICY_ID,
        "version": "",
        "status": "invalid",
        "reason_codes": [reason],
        "claim_policies": {},
    }


def _ordered_candidates(response: dict[str, Any], order_mode: str) -> dict[str, Any]:
    prepared = deepcopy(response)
    candidates = list(prepared.get("formal_evidence_candidates") or [])
    if order_mode == "reverse":
        candidates.reverse()
    elif order_mode == "fixed_seed_shuffle":
        random.Random(SHUFFLE_SEED).shuffle(candidates)
    prepared["formal_evidence_candidates"] = candidates
    return prepared


def _evaluate_case(
    case: dict[str, Any],
    *,
    repository: FilePolicyRepository,
    order_mode: str,
) -> dict[str, Any]:
    request = case["request"]
    context = AdmittedAnswerContextService().build_for_response(
        _ordered_candidates(request["response"], order_mode),
        product_identity=request["product_identity"],
        understanding=request["understanding"],
        current_customer_message=request["customer_message"],
        answer_eligibility_inputs={
            "domain_policy_pack": _domain_policy(
                request["domain_policy_variant"],
                repository,
            ),
            **request["owner_context"],
        },
    )
    eligibility = context["answer_eligibility_context"]
    resolutions = context["claim_resolutions"]
    return {
        "case_uid": case["case_uid"],
        "kind": case["kind"],
        "mutation": case.get("mutation", ""),
        "eligible": eligibility["fast_path_preconditions_complete"] is True,
        "block_reasons": sorted(eligibility["fast_path_block_reasons"]),
        "admitted_evidence_count": len(context["direct_product_facts"])
        + len(context["direct_policy_facts"]),
        "supported_resolution_count": sum(
            item.get("status") == "supported" for item in resolutions
        ),
        "supporting_resolution_count": sum(
            item.get("supporting_only") is True for item in resolutions
        ),
        "resolution_statuses": sorted(
            str(item.get("status") or "") for item in resolutions
        ),
        "rejected_reasons": sorted({
            str(item.get("reason") or "")
            for item in context["rejected_evidence"]
            if item.get("reason")
        }),
        "used_for_final_reply": eligibility["used_for_final_reply"],
        "can_change_can_send": eligibility["can_change_can_send"],
    }


def _knowledge_summary(fingerprint: dict[str, Any]) -> dict[str, Any]:
    return {
        "query_only": fingerprint.get("query_only") is True,
        "formal_content_sha256": fingerprint.get("formal_content_sha256"),
        "tables": [
            {
                "table": item.get("table"),
                "row_count": item.get("row_count"),
                "schema_sha256": item.get("schema_sha256"),
                "content_sha256": item.get("content_sha256"),
            }
            for item in fingerprint.get("formal_tables") or []
        ],
    }


def run_eligibility_matrix(
    dataset: dict[str, Any],
    manifest: dict[str, Any],
    *,
    formal_database: str = "",
    rules_dir: str = "",
    max_rounds: int = 3,
) -> tuple[dict[str, Any], int]:
    validate_dataset(dataset, manifest)
    if max_rounds not in {1, 3}:
        raise ValueError("max_rounds_invalid")
    repository = FilePolicyRepository(rules_dir=rules_dir or None)
    before: dict[str, Any] | None = None
    knowledge_hmac_key = secrets.token_hex(32)
    if formal_database:
        before = fingerprint_formal_knowledge_tables(
            formal_database,
            hmac_key=knowledge_hmac_key,
        )

    rounds: list[dict[str, Any]] = []
    negative_leaks: list[dict[str, Any]] = []
    baseline_by_case: dict[str, tuple[Any, ...]] = {}
    order_modes = ("original", "reverse", "fixed_seed_shuffle")[:max_rounds]
    for round_index, order_mode in enumerate(
        order_modes,
        start=1,
    ):
        case_order = list(dataset["cases"])
        if order_mode == "reverse":
            case_order.reverse()
        elif order_mode == "fixed_seed_shuffle":
            random.Random(SHUFFLE_SEED).shuffle(case_order)
        results = [
            _evaluate_case(case, repository=repository, order_mode=order_mode)
            for case in case_order
        ]
        result_by_case = {item["case_uid"]: item for item in results}
        if round_index == 1:
            baseline_by_case = {
                uid: (
                    item["eligible"],
                    tuple(item["block_reasons"]),
                    item["admitted_evidence_count"],
                    item["supported_resolution_count"],
                    item["supporting_resolution_count"],
                    tuple(item["resolution_statuses"]),
                    tuple(item["rejected_reasons"]),
                )
                for uid, item in result_by_case.items()
            }
        stable = all(
            baseline_by_case[uid] == (
                item["eligible"],
                tuple(item["block_reasons"]),
                item["admitted_evidence_count"],
                item["supported_resolution_count"],
                item["supporting_resolution_count"],
                tuple(item["resolution_statuses"]),
                tuple(item["rejected_reasons"]),
            )
            for uid, item in result_by_case.items()
        )
        positive = [item for item in results if item["kind"] == "positive"]
        negative = [item for item in results if item["kind"] == "negative"]
        leaks = [item for item in negative if item["eligible"]]
        rounds.append({
            "round": round_index,
            "order_mode": order_mode,
            "positive_count": len(positive),
            "positive_eligible_count": sum(item["eligible"] for item in positive),
            "negative_count": len(negative),
            "negative_blocked_count": sum(not item["eligible"] for item in negative),
            "stable_against_round_one": stable,
            "negative_eligible_cases": [
                {
                    "case_uid": item["case_uid"],
                    "mutation": item["mutation"],
                    "admitted_evidence_count": item["admitted_evidence_count"],
                    "supported_resolution_count": item["supported_resolution_count"],
                    "supporting_resolution_count": item["supporting_resolution_count"],
                }
                for item in leaks
            ],
            "results": results,
        })
        if leaks:
            negative_leaks = leaks
            break

    after: dict[str, Any] | None = None
    knowledge_diff = {
        "changed": False,
        "changed_row_count": 0,
        "changed_table_count": 0,
        "table_diffs": [],
    }
    if formal_database and before is not None:
        # Reuse the same HMAC key is required for row identities. The evaluator
        # intentionally reports only table-level hashes, so compare the stable
        # composite and table hashes directly instead of exposing row material.
        after = fingerprint_formal_knowledge_tables(
            formal_database,
            hmac_key=knowledge_hmac_key,
        )
        before_summary = _knowledge_summary(before)
        after_summary = _knowledge_summary(after)
        changed = before_summary != after_summary
        knowledge_diff = {
            "changed": changed,
            "changed_row_count": None if changed else 0,
            "changed_table_count": None if changed else 0,
            "table_diffs": [],
        }
    else:
        before_summary = None
        after_summary = None

    first_round = rounds[0]
    first_round_positive_failures = [
        item
        for item in first_round["results"]
        if item["kind"] == "positive" and not item["eligible"]
    ]
    qualification_passed = bool(
        len(rounds) == 3
        and all(
            item["positive_eligible_count"] == item["positive_count"]
            and item["negative_blocked_count"] == item["negative_count"]
            and item["stable_against_round_one"]
            for item in rounds
        )
        and not negative_leaks
        and not knowledge_diff["changed"]
    )
    report_status = (
        "qualified"
        if qualification_passed
        else "blocked"
        if negative_leaks or len(rounds) == 3
        else "attempted"
    )
    report = {
        "schema_version": EVALUATOR_SCHEMA_VERSION,
        "attempted": True,
        "runtime_identity": _runtime_identity(),
        "dataset": {
            "dataset_id": dataset["dataset_id"],
            "dataset_version": dataset["dataset_version"],
            "dataset_sha256": manifest["dataset_sha256"],
            "source_snapshot_sha256": manifest["source_snapshot_sha256"],
            "source_fixture_sha256": manifest["source_fixture_sha256"],
            "positive_count": manifest["positive_count"],
            "negative_count": manifest["negative_count"],
            "anonymous_product_count": manifest["anonymous_product_count"],
            "fact_type_counts": manifest["fact_type_counts"],
            "privacy_scan": manifest["privacy_scan"],
        },
        "status": report_status,
        "stop_reason": (
            ""
            if qualification_passed
            else "negative_case_eligible"
            if negative_leaks
            else "qualification_incomplete"
            if len(rounds) < 3
            else "eligibility_matrix_not_qualified"
        ),
        "earliest_breakpoint": "eligibility_matrix",
        "rounds_completed": len(rounds),
        "required_rounds": 3,
        "positive_eligible_count": first_round["positive_eligible_count"],
        "positive_count": first_round["positive_count"],
        "positive_failed_count": len(first_round_positive_failures),
        "positive_failure_reasons": dict(sorted(Counter(
            reason
            for item in first_round_positive_failures
            for reason in item["block_reasons"]
        ).items())),
        "negative_blocked_count": first_round["negative_blocked_count"],
        "negative_count": first_round["negative_count"],
        "negative_eligible_count": len(negative_leaks),
        "negative_eligible_mutations": sorted({
            item["mutation"] for item in negative_leaks
        }),
        "shuffle_seed": SHUFFLE_SEED,
        "rounds": rounds,
        "composer_call_count": 0,
        "fast_path_shadow_implemented": False,
        "used_for_final_reply": False,
        "can_change_can_send": False,
        "formal_reply_change_count": 0,
        "can_send_true_count": 0,
        "formal_knowledge_dml_count": 0,
        "formal_knowledge_before": before_summary,
        "formal_knowledge_after": after_summary,
        "formal_knowledge_diff": knowledge_diff,
        "stopped_before_full_path_baseline": not qualification_passed,
        "stopped_before_shadow_fast_path": not qualification_passed,
        "stopped_before_mutation_tests": not qualification_passed,
        "stopped_before_latency_comparison": not qualification_passed,
        "stopped_before_cross_domain_pack": not qualification_passed,
    }
    return report, 0 if qualification_passed else 2


def _load_json(path: str) -> dict[str, Any]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("json_object_required")
    return value


def _write_json(path: str, payload: dict[str, Any]) -> None:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    content = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        indent=2,
    ) + "\n"
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{destination.name}.",
        suffix=".tmp",
        dir=destination.parent,
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, destination)
    except Exception:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass
        raise


def main() -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)

    build_parser = subparsers.add_parser("build")
    build_parser.add_argument("--source-fixture", required=True)
    build_parser.add_argument("--source-manifest", required=True)
    build_parser.add_argument("--fixture-output", required=True)
    build_parser.add_argument("--manifest-output", required=True)

    run_parser = subparsers.add_parser("run")
    run_parser.add_argument("--fixture", required=True)
    run_parser.add_argument("--manifest", required=True)
    run_parser.add_argument("--json-output", required=True)
    run_parser.add_argument("--formal-db", default="")
    run_parser.add_argument("--rules-dir", default="")
    run_parser.add_argument("--max-rounds", type=int, choices=(1, 3), default=3)

    args = parser.parse_args()
    try:
        if args.command == "build":
            dataset, manifest = build_qualification_dataset(
                _load_json(args.source_fixture),
                _load_json(args.source_manifest),
            )
            _write_json(args.fixture_output, dataset)
            _write_json(args.manifest_output, manifest)
            print(json.dumps({
                "status": "built",
                "dataset_sha256": manifest["dataset_sha256"],
                "positive_count": manifest["positive_count"],
                "negative_count": manifest["negative_count"],
            }, ensure_ascii=False))
            return 0

        report, exit_code = run_eligibility_matrix(
            _load_json(args.fixture),
            _load_json(args.manifest),
            formal_database=args.formal_db,
            rules_dir=args.rules_dir,
            max_rounds=args.max_rounds,
        )
        _write_json(args.json_output, report)
        print(json.dumps({
            "status": report["status"],
            "stop_reason": report["stop_reason"],
            "rounds_completed": report["rounds_completed"],
            "positive_eligible": f"{report['positive_eligible_count']}/{report['positive_count']}",
            "negative_blocked": f"{report['negative_blocked_count']}/{report['negative_count']}",
            "negative_eligible_mutations": report["negative_eligible_mutations"],
            "composer_call_count": report["composer_call_count"],
        }, ensure_ascii=False))
        return exit_code
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(json.dumps({"status": "blocked", "reason": str(exc)}, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
