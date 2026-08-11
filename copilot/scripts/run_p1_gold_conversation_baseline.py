"""Run one split, privacy-safe P1 long-conversation development baseline."""

from __future__ import annotations

import argparse
from collections import Counter
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import secrets
import sqlite3
import subprocess
import sys
from typing import Any

from dotenv import load_dotenv


_PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from app.services.fact_type_alias_service import (
    canonical_attribute_slot,
    canonical_dimension_subject_scope,
    canonical_material_composition_claim_type,
)
from app.services.claim_resolution_service import _requested_subject_scope
from app.services.product_media_annotation_schema_service import (
    canonical_dimension_attribute,
)

SCHEMA_VERSION = "p1-gold-conversation-baseline/v2"
EXPECTED_DATASET_ID = "hq-long-conversation-real-derived-v4"
EXPECTED_DATASET_VERSION = "1.3.2-draft"
EXPECTED_CASE_COUNT = 26
EXPECTED_HISTORY_TURN_COUNT = 208
EXPECTED_DATASET_SHA256 = (
    "610c6078ae14118451bee8852ab669208cf824ff809a2c506260bbe80e10f1cf"
)
EXPECTED_MANIFEST_FILE_SHA256 = (
    "af78ec3e75831d154faea34b5d2650cf6cc9234ab7d216d25e6afba1759a8aa3"
)


@dataclass(frozen=True)
class DatasetContract:
    contract_name: str
    dataset_id: str
    dataset_version: str
    case_count: int
    history_turn_count: int
    dataset_sha256: str
    manifest_file_sha256: str
    source_class: str
    real_customer_accuracy: None = None
    original_fixed8_restored: bool = False


_DATASET_CONTRACTS = {
    "legacy-real-derived-v4": DatasetContract(
        contract_name="legacy-real-derived-v4",
        dataset_id=EXPECTED_DATASET_ID,
        dataset_version=EXPECTED_DATASET_VERSION,
        case_count=EXPECTED_CASE_COUNT,
        history_turn_count=EXPECTED_HISTORY_TURN_COUNT,
        dataset_sha256=EXPECTED_DATASET_SHA256,
        manifest_file_sha256=EXPECTED_MANIFEST_FILE_SHA256,
        source_class="real_derived_draft",
    ),
    "conversation-reconstructed-v1": DatasetContract(
        contract_name="conversation-reconstructed-v1",
        dataset_id="p1-conversation-reconstructed-v1",
        dataset_version="1.2.0",
        case_count=8,
        history_turn_count=40,
        dataset_sha256=(
            "babd57bb8572633d0b8c38b52841ce310395efb242851afaacc2d708672babf1"
        ),
        manifest_file_sha256=(
            "0b2c57d035aa48eb57983f6db8633235ca497d3ab26504159de8501945e0040d"
        ),
        source_class="conversation_reconstructed",
    ),
}


def _resolve_dataset_contract(name: str) -> DatasetContract:
    contract = _DATASET_CONTRACTS.get(str(name or "").strip())
    if contract is None:
        raise P1BaselineIntegrityError("dataset_contract_unknown")
    return contract


def _legacy_dataset_contract() -> DatasetContract:
    """Preserve legacy tests that intentionally narrow the case count."""
    return DatasetContract(
        contract_name="legacy-real-derived-v4",
        dataset_id=EXPECTED_DATASET_ID,
        dataset_version=EXPECTED_DATASET_VERSION,
        case_count=EXPECTED_CASE_COUNT,
        history_turn_count=EXPECTED_HISTORY_TURN_COUNT,
        dataset_sha256=EXPECTED_DATASET_SHA256,
        manifest_file_sha256=EXPECTED_MANIFEST_FILE_SHA256,
        source_class="real_derived_draft",
    )


def _contract_report_fields(
    contract: DatasetContract,
) -> dict[str, Any]:
    return {
        "dataset_contract": contract.contract_name,
        "source_class": contract.source_class,
        "real_customer_accuracy": contract.real_customer_accuracy,
        "optimization_unverified": True,
        "original_fixed8_restored": contract.original_fixed8_restored,
    }
_PROHIBITED_REPORT_KEYS = {
    "api_key",
    "authorization",
    "chain_of_thought",
    "prompt",
    "reasoning",
    "reasoning_content",
    "reasoning_details",
    "secret",
    "token",
}
_CONTROLLED_FINGERPRINT_PATTERNS = {
    "content_sha256": re.compile(r"^[0-9a-f]{64}$"),
    "dataset_hash": re.compile(r"^[0-9a-f]{64}$"),
    "dataset_sha256": re.compile(r"^[0-9a-f]{64}$"),
    "end_runner_source_sha256": re.compile(r"^[0-9a-f]{64}$"),
    "evaluator_source_sha256": re.compile(r"^[0-9a-f]{64}$"),
    "file_sha256": re.compile(r"^[0-9a-f]{64}$"),
    "field_name_sha256": re.compile(r"^[0-9a-f]{64}$"),
    "formal_content_sha256": re.compile(r"^[0-9a-f]{64}$"),
    "head": re.compile(r"^[0-9a-f]{40}$"),
    "host_fingerprint": re.compile(r"^[0-9a-f]{12}$"),
    "manifest_content_sha256": re.compile(r"^[0-9a-f]{64}$"),
    "manifest_file_sha256": re.compile(r"^[0-9a-f]{64}$"),
    "post_run_manifest_sha256": re.compile(r"^[0-9a-f]{64}$"),
    "pre_run_manifest_sha256": re.compile(r"^[0-9a-f]{64}$"),
    "row_identity_hmac": re.compile(r"^[0-9a-f]{64}$"),
    "row_sha256": re.compile(r"^[0-9a-f]{64}$"),
    "response_body_sha256": re.compile(r"^[0-9a-f]{64}$"),
    "runner_source_sha256": re.compile(r"^[0-9a-f]{64}$"),
    "runtime_commit": re.compile(r"^[0-9a-f]{40}$"),
    "schema_sha256": re.compile(r"^[0-9a-f]{64}$"),
    "sha256": re.compile(r"^[0-9a-f]{64}$"),
    "snapshot_file_sha256": re.compile(r"^[0-9a-f]{64}$"),
    "source_manifest_file_sha256": re.compile(r"^[0-9a-f]{64}$"),
    "source_span_sha256": re.compile(r"^[0-9a-f]{64}$"),
    "source_tree_sha256": re.compile(r"^[0-9a-f]{64}$"),
    "value_sha256": re.compile(r"^[0-9a-f]{64}$"),
}
_RAW_INTERNAL_REF_RE = re.compile(
    r"\b(?:goal|claim)-[A-Za-z0-9][A-Za-z0-9._:-]{3,}\b"
)
_SUMMARY_METRIC_FIELDS = {
    "absolute_guarantee_supported_count",
    "bounded_inference_attribution",
    "bounded_inference_premise_coverage",
    "bounded_inference_scope_coverage",
    "can_send_true_count",
    "composer_accepted_count",
    "composer_latency_ms",
    "composer_rejected_reasons",
    "customer_goal_clause_coverage",
    "dataset_required_point_coverage",
    "dataset_unresolved_point_coverage",
    "dependency_evidence_link_coverage",
    "duplicate_goal_ref_clause_count",
    "duplicate_reply_count",
    "eligible_policy_option_total_count",
    "eligible_policy_options_coverage",
    "execution_success_count",
    "fallback_count",
    "final_audit_model_call_count",
    "final_audit_pass_count",
    "latency_ms",
    "non_customer_goal_clause_count",
    "nonempty_reply_count",
    "partial_answer_success",
    "policy_intent_kind_counts",
    "policy_intent_precision",
    "policy_intent_recall",
    "policy_selection_coverage",
    "policy_intent_ref_total_count",
    "renderable_customer_goal_count",
    "repeated_known_information_request_count",
    "requires_human_review_count",
    "runtime_supported_claim_attribution",
    "runtime_unresolved_claim_declaration",
    "scenario_count",
    "selected_evidence_scenario_count",
    "selected_evidence_total_count",
    "selected_policy_premise_coverage",
    "selected_policy_scope_validity",
    "selected_policy_validity",
    "semantic_audit_pass_count",
    "shadow_candidate_formal_use_count",
    "supported_goal_coverage",
    "supporting_dependency_count",
    "system_tone_count",
    "unified_audit_latency_ms",
    "unified_audit_model_call_count",
    "unified_audit_repair_count",
    "unified_audit_retry_count",
    "unknown_evidence_ref_count",
    "unknown_goal_kind_count",
    "unknown_goal_ref_count",
    "unnecessary_handoff_count",
    "unresolved_goal_coverage",
    "unsupported_evidence_ref_count",
    "unsupported_high_risk_claim_count",
    "unsupported_media_promise_count",
    "unsupported_service_action_count",
    "wrong_clause_kind_count",
}
_CAPSULE_TOP_LEVEL_FIELDS = {
    "analysis_pipeline",
    "answer_trace",
    "can_send",
    "context_used",
    "draft_reply",
    "evidence_debug",
    "final_answer_audit",
    "final_semantic_fit_audit",
    "minimal_decision_context",
    "model_first_answer_composer",
    "reason_for_review",
    "reply_blocks",
    "reply_status",
    "requires_human_review",
    "selected_evidence",
    "sendable_reply",
    "service_actions",
    "suggested_reply",
    "tool_calls",
    "tool_results",
    "turn_understanding",
}
_CAPSULE_GOAL_KINDS = {
    "customer_goal",
    "evidence_dependency",
    "service_action",
    "media_request",
    "media_candidate",
    "contextual_constraint",
    "compatibility_claim",
}
_CAPSULE_CLAUSE_KINDS = {
    "supported_fact",
    "unresolved",
    "allowed_inference",
    "service_action",
    "empathy_or_transition",
}
_CAPSULE_STATUS_VALUES = {
    "supported",
    "unresolved",
    "conflicting",
    "prohibited",
}
_CAPSULE_SAFE_FIELD_VALUES = {
    "owner": {"turn_understanding_owner"},
    "schema_version": {
        "turn-understanding/v2",
        "turn-understanding-goal-identity/v2",
    },
    "source": {
        "current_customer_message",
        "conversation_history",
    },
    "source_stage": {
        "query_fact_type_classifier",
        "semantic_fact_type_service",
    },
}
_GOAL_REF_RE = re.compile(r"^goal-[A-Za-z0-9._:-]{1,128}$")
_CLAIM_REF_RE = re.compile(r"^claim-[A-Za-z0-9._:-]{1,128}$")


class P1BaselineIntegrityError(RuntimeError):
    pass


def _validate_reconstructed_dataset_contract(
    dataset: dict[str, Any],
    manifest: dict[str, Any],
) -> None:
    """Keep reconstructed evidence distinct from real or recovered Gold data."""
    findings: list[str] = []
    scenarios = dataset.get("scenarios")
    rows = scenarios if isinstance(scenarios, list) else []
    expected_aliases = [f"rc-{index:02d}" for index in range(1, 9)]
    aliases = [
        str(row.get("reconstruction_alias") or "")
        for row in rows
        if isinstance(row, dict)
    ]

    if (
        dataset.get("source_class") != "conversation_reconstructed"
        or manifest.get("source_class") != "conversation_reconstructed"
    ):
        findings.append("reconstructed_source_class_mismatch")
    if len(rows) != 8 or int(manifest.get("scenario_count") or 0) != 8:
        findings.append("reconstructed_scenario_count_mismatch")
    if aliases != expected_aliases:
        findings.append("reconstructed_alias_sequence_mismatch")
    if manifest.get("real_customer_accuracy") is not None:
        findings.append("reconstructed_accuracy_claim_forbidden")
    if manifest.get("original_fixed8_restored") is not False:
        findings.append("reconstructed_original_equivalence_forbidden")
    if manifest.get("optimization_unverified") is not True:
        findings.append("reconstructed_optimization_claim_forbidden")

    privacy = manifest.get("privacy_declaration")
    privacy = privacy if isinstance(privacy, dict) else {}
    if (
        privacy.get("classification") != "synthetic_anonymous"
        or privacy.get("contains_real_customer_pii") is not False
        or privacy.get("contains_real_order_or_sku") is not False
        or privacy.get("scan_passed") is not True
    ):
        findings.append("reconstructed_privacy_declaration_invalid")

    if (
        manifest.get("dataset_id") != dataset.get("dataset_id")
        or manifest.get("dataset_version") != dataset.get("dataset_version")
        or manifest.get("content_sha256")
        != _dict(dataset.get("manifest")).get("content_sha256")
    ):
        findings.append("reconstructed_manifest_identity_mismatch")

    scenario_hashes = manifest.get("scenario_hashes")
    scenario_hashes = (
        scenario_hashes if isinstance(scenario_hashes, dict) else {}
    )
    expected_hashes = {
        str(row.get("reconstruction_alias") or ""): str(
            row.get("content_sha256") or ""
        )
        for row in rows
        if isinstance(row, dict)
    }
    if scenario_hashes != expected_hashes:
        findings.append("reconstructed_scenario_hash_manifest_mismatch")

    for row in rows:
        if not isinstance(row, dict):
            continue
        history = row.get("conversation_history")
        request_template = row.get("api_request_template")
        request_template = (
            request_template if isinstance(request_template, dict) else {}
        )
        if (
            not isinstance(history, list)
            or history != request_template.get("conversation_history")
            or row.get("current_buyer_message")
            != request_template.get("message")
        ):
            findings.append("reconstructed_conversation_projection_mismatch")
            break
        if any(
            not isinstance(turn, dict)
            or turn.get("role") not in {"customer", "assistant"}
            or not str(turn.get("content") or "").strip()
            for turn in history
        ):
            findings.append("reconstructed_conversation_turn_invalid")
            break
        message = str(request_template.get("message") or "")
        for claim in _dicts(row.get("expected_claims")):
            expectation = _goal_expectation(claim)
            if expectation is None:
                continue
            source_hash = expectation["source_span_sha256"]
            source = message[
                expectation["source_span_start"]:
                expectation["source_span_end"]
            ]
            if not source_hash or source_hash != hashlib.sha256(
                source.encode("utf-8")
            ).hexdigest():
                findings.append("reconstructed_goal_span_hash_invalid")
                break
        if findings:
            break

    if findings:
        raise P1BaselineIntegrityError(
            "reconstructed_dataset_contract_blocked:"
            + ",".join(sorted(set(findings)))
        )


def _validate_reconstructed_delivery_boundary(
    observations: list[dict[str, Any]],
    *,
    contract: DatasetContract,
) -> None:
    if contract.source_class != "conversation_reconstructed":
        return
    deliveries = [
        _dict(item.get("delivery"))
        for item in observations
        if isinstance(item, dict)
    ]
    if any(delivery.get("can_send") is True for delivery in deliveries):
        raise P1BaselineIntegrityError(
            "reconstructed_can_send_forbidden"
        )
    if any(
        delivery.get("requires_human_review") is not True
        for delivery in deliveries
    ):
        raise P1BaselineIntegrityError(
            "reconstructed_human_review_required"
        )


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _dicts(value: Any) -> list[dict[str, Any]]:
    return [item for item in value or [] if isinstance(item, dict)]


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _canonical_hash(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _runner_source_sha256() -> str:
    relative_paths = (
        "app/services/high_quality_long_conversation_review_service.py",
        "app/services/real_accuracy_privacy_service.py",
        "scripts/compare_model_first_answer_composer.py",
        "scripts/run_p1_gold_conversation_baseline.py",
    )
    digest = hashlib.sha256()
    for relative in relative_paths:
        path = _PROJECT_ROOT / relative
        if not path.is_file():
            raise P1BaselineIntegrityError(
                "runner_source_file_missing"
            )
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def _evaluator_source_sha256() -> str:
    relative_paths = (
        "app/services/high_quality_long_conversation_review_service.py",
        "app/services/real_accuracy_privacy_service.py",
        "scripts/compare_model_first_answer_composer.py",
    )
    digest = hashlib.sha256()
    for relative in relative_paths:
        path = _PROJECT_ROOT / relative
        if not path.is_file():
            raise P1BaselineIntegrityError(
                "evaluator_source_file_missing"
            )
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def _runtime_source_tree_sha256() -> str:
    from app.api.runtime_routes import _source_tree_sha256

    value = _source_tree_sha256()
    if not re.fullmatch(r"[0-9a-f]{64}", value):
        raise P1BaselineIntegrityError(
            "runtime_source_identity_unavailable"
        )
    return value


def _git_identity() -> dict[str, Any]:
    try:
        head = subprocess.check_output(
            ["git", "-C", str(_PROJECT_ROOT), "rev-parse", "HEAD"],
            text=True,
            encoding="utf-8",
            stderr=subprocess.DEVNULL,
        ).strip()
        status = subprocess.check_output(
            ["git", "-C", str(_PROJECT_ROOT), "status", "--porcelain"],
            text=True,
            encoding="utf-8",
            stderr=subprocess.DEVNULL,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise P1BaselineIntegrityError(
            "git_identity_unavailable"
        ) from exc
    if not re.fullmatch(r"[0-9a-f]{40}", head):
        raise P1BaselineIntegrityError("git_head_invalid")
    return {"head": head, "worktree_dirty": bool(status.strip())}


def _load_json(path: Path, *, reason: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise P1BaselineIntegrityError(reason) from exc
    if not isinstance(value, dict):
        raise P1BaselineIntegrityError(reason)
    return value


def assess_offline_reconstruction(
    baseline_dir: Path | str,
) -> dict[str, Any]:
    """Assess old split artifacts without making Agent or Provider calls."""
    root = Path(baseline_dir).expanduser().resolve()
    checkpoint = _load_json(
        root / "checkpoint.json",
        reason="offline_checkpoint_invalid",
    )
    completed_files = _dicts(
        checkpoint.get("completed_case_files")
    )
    hashes_valid = True
    projection_source_count = 0
    for metadata in completed_files:
        relative = str(metadata.get("path") or "")
        path = (root / relative).resolve()
        if root not in path.parents or not path.is_file():
            hashes_valid = False
            continue
        if _sha256_file(path) != str(metadata.get("sha256") or ""):
            hashes_valid = False
            continue
        payload = _load_json(
            path,
            reason="offline_case_json_invalid",
        )
        if isinstance(payload.get("raw_projection_source"), dict):
            projection_source_count += 1
    missing = []
    if projection_source_count != len(completed_files):
        missing.append("raw_projection_source")
    for field in (
        "runner_source_sha256",
        "formal_knowledge_before",
        "dml_start_offset",
    ):
        if field not in checkpoint:
            missing.append(field)
    status = (
        "reconstructable_diagnostic_only"
        if hashes_valid and not missing
        else "diagnostic_only_projection_source_missing"
    )
    result = {
        "schema_version": "p1-offline-reconstruction/v1",
        "offline_reconstruction_status": status,
        "completed_case_count": len(completed_files),
        "case_hashes_valid": hashes_valid,
        "projection_recalculation_attempted_count": len(
            completed_files
        ),
        "projection_recalculation_completed_count": (
            projection_source_count
        ),
        "missing_required_fields": sorted(missing),
        "agent_call_count": 0,
        "provider_call_count": 0,
        "authoritative_baseline_allowed": False,
        "reason_code": (
            "pre_run_knowledge_snapshot_not_persisted"
            if hashes_valid else "case_hash_validation_failed"
        ),
    }
    _assert_report_safe(result)
    return result


def _safe_text(value: Any) -> str:
    from app.services.eval_sanitizer_service import sanitize_text
    from app.services.real_accuracy_privacy_service import (
        scan_privacy_output,
    )

    text = str(value or "").strip()
    findings = scan_privacy_output({"text": text})
    if findings:
        reason_codes = sorted({
            str(item.get("reason_code") or "")
            for item in findings
        })
        raise P1BaselineIntegrityError(
            "report_source_privacy_validation_failed:"
            + ",".join(reason_codes)
        )
    return sanitize_text(text).strip()


def _case_alias(
    scenario_uid: str,
    alias_secret: bytes,
) -> str:
    from app.services.high_quality_long_conversation_review_service import (
        stable_evaluation_alias,
    )

    return stable_evaluation_alias(
        "case",
        scenario_uid,
        alias_secret=alias_secret,
    )


def _run_alias(
    *,
    dataset_sha256: str,
    pre_run_manifest_sha256: str,
    runner_source_sha256: str,
    alias_secret: bytes,
) -> str:
    from app.services.high_quality_long_conversation_review_service import (
        stable_evaluation_alias,
    )

    return stable_evaluation_alias(
        "run",
        ":".join((
            dataset_sha256,
            pre_run_manifest_sha256,
            runner_source_sha256,
        )),
        alias_secret=alias_secret,
    )


def _canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _value_fingerprint(value: Any) -> dict[str, Any]:
    encoded = _canonical_json_bytes(value)
    return {
        "value_type": type(value).__name__,
        "value_length": len(encoded),
        "value_sha256": hashlib.sha256(encoded).hexdigest(),
    }


def _enum_shape(
    value: Any,
    *,
    allowed_values: set[str],
) -> dict[str, Any]:
    result = {
        "present": value is not None,
        "value_type": type(value).__name__,
        "allowlisted": False,
    }
    if isinstance(value, str) and value in allowed_values:
        result.update(
            allowlisted=True,
            canonical_value=value,
        )
    elif value is not None:
        result.update(_value_fingerprint(value))
    return result


def _field_shape(
    item: dict[str, Any],
    field: str,
) -> dict[str, Any]:
    if field not in item:
        return {
            "present": False,
            "value_type": "missing",
            "allowlisted": False,
        }
    result = _enum_shape(
        item.get(field),
        allowed_values=_CAPSULE_SAFE_FIELD_VALUES[field],
    )
    if (
        field == "schema_version"
        and isinstance(result.get("canonical_value"), str)
    ):
        result["canonical_value"] = (
            str(result["canonical_value"])
            .replace("-", "_")
            .replace("/", "_")
        )
    return result


def _reference_shape(
    value: Any,
    *,
    namespace: str,
    alias_secret: bytes,
    pattern: re.Pattern[str],
) -> dict[str, Any]:
    result = {
        "present": value is not None and value != "",
        "value_type": type(value).__name__,
        "canonical_format": False,
    }
    if not result["present"]:
        return result
    if isinstance(value, str) and pattern.fullmatch(value):
        from app.services.high_quality_long_conversation_review_service import (
            stable_evaluation_alias,
        )

        result.update(
            canonical_format=True,
            alias=stable_evaluation_alias(
                namespace,
                value,
                alias_secret=alias_secret,
            ),
        )
    else:
        result.update(_value_fingerprint(value))
    return result


def _top_level_shape(response: dict[str, Any]) -> list[dict[str, Any]]:
    result = []
    for field, value in sorted(
        response.items(),
        key=lambda pair: str(pair[0]),
    ):
        field_name = str(field)
        item = {
            "field_name_allowlisted": (
                field_name in _CAPSULE_TOP_LEVEL_FIELDS
            ),
            "value_type": type(value).__name__,
            "item_count": (
                len(value)
                if isinstance(value, (dict, list, str))
                else None
            ),
        }
        if field_name in _CAPSULE_TOP_LEVEL_FIELDS:
            item["field_path"] = f"$.{field_name}"
        else:
            item["field_name_length"] = len(
                field_name.encode("utf-8")
            )
            item["field_name_sha256"] = hashlib.sha256(
                field_name.encode("utf-8")
            ).hexdigest()
        result.append(item)
    return result


def _capsule_turn_understanding(
    response: dict[str, Any],
) -> tuple[dict[str, Any], str]:
    candidates = (
        (response, "$.turn_understanding"),
        (_dict(response.get("evidence_debug")), "$.evidence_debug"),
        (_dict(response.get("answer_trace")), "$.answer_trace"),
        (_dict(response.get("context_used")), "$.context_used"),
    )
    for container, base_path in candidates:
        understanding = container.get("turn_understanding")
        if isinstance(understanding, dict):
            return understanding, f"{base_path}.turn_understanding"
    return {}, "missing"


def _contract_field_shapes(item: dict[str, Any]) -> dict[str, Any]:
    return {
        field: _field_shape(item, field)
        for field in (
            "owner",
            "schema_version",
            "source",
            "source_stage",
        )
    }


def _build_projection_failure_capsule(
    *,
    run_uid_alias: str,
    case_uid_alias: str,
    case_index: int,
    status_code: int,
    response: dict[str, Any],
    alias_secret: bytes,
) -> dict[str, Any]:
    from app.services.real_accuracy_privacy_service import (
        scan_privacy_output,
    )

    response_bytes = _canonical_json_bytes(response)
    understanding, understanding_path = _capsule_turn_understanding(
        response
    )
    goals = _dicts(understanding.get("customer_goals"))
    minimal = _dict(response.get("minimal_decision_context"))
    resolutions = _dicts(minimal.get("claim_resolutions"))
    composer = _dict(response.get("model_first_answer_composer"))
    clauses = _dicts(composer.get("clauses"))

    goal_rows = []
    trusted_goal_aliases: set[str] = set()
    for index, goal in enumerate(goals):
        goal_ref = _reference_shape(
            goal.get("goal_ref"),
            namespace="goal",
            alias_secret=alias_secret,
            pattern=_GOAL_REF_RE,
        )
        if goal_ref.get("alias"):
            trusted_goal_aliases.add(str(goal_ref["alias"]))
        goal_rows.append({
            "array_index": index,
            "goal_kind": _enum_shape(
                goal.get("goal_kind"),
                allowed_values=_CAPSULE_GOAL_KINDS,
            ),
            "contract_fields": _contract_field_shapes(goal),
            "goal_ref": goal_ref,
            "supporting_for_goal_ref": _reference_shape(
                goal.get("supporting_for_goal_ref"),
                namespace="goal",
                alias_secret=alias_secret,
                pattern=_GOAL_REF_RE,
            ),
        })
    for row in goal_rows:
        goal_ref = _dict(row.get("goal_ref"))
        supporting_ref = _dict(row.get("supporting_for_goal_ref"))
        row["goal_ref_matches_trusted_goal"] = (
            bool(goal_ref.get("alias"))
            and goal_ref.get("alias") in trusted_goal_aliases
        )
        row["supporting_ref_matches_trusted_goal"] = (
            bool(supporting_ref.get("alias"))
            and supporting_ref.get("alias") in trusted_goal_aliases
        )
        row["goal_ref_equals_supporting_ref"] = (
            bool(goal_ref.get("alias"))
            and goal_ref.get("alias") == supporting_ref.get("alias")
        )

    resolution_rows = []
    resolution_claim_aliases: set[str] = set()
    for index, resolution in enumerate(resolutions):
        goal_ref = _reference_shape(
            resolution.get("goal_ref"),
            namespace="goal",
            alias_secret=alias_secret,
            pattern=_GOAL_REF_RE,
        )
        supporting_ref = _reference_shape(
            resolution.get("supporting_for_goal_ref"),
            namespace="goal",
            alias_secret=alias_secret,
            pattern=_GOAL_REF_RE,
        )
        claim_ref = _reference_shape(
            resolution.get("claim_uid"),
            namespace="claim",
            alias_secret=alias_secret,
            pattern=_CLAIM_REF_RE,
        )
        if claim_ref.get("alias"):
            resolution_claim_aliases.add(str(claim_ref["alias"]))
        resolution_rows.append({
            "array_index": index,
            "goal_kind": _enum_shape(
                resolution.get("goal_kind"),
                allowed_values=_CAPSULE_GOAL_KINDS,
            ),
            "resolution_status": _enum_shape(
                resolution.get("status"),
                allowed_values=_CAPSULE_STATUS_VALUES,
            ),
            "contract_fields": _contract_field_shapes(resolution),
            "goal_ref": goal_ref,
            "supporting_for_goal_ref": supporting_ref,
            "claim_uid": claim_ref,
            "goal_ref_matches_trusted_goal": (
                bool(goal_ref.get("alias"))
                and goal_ref.get("alias") in trusted_goal_aliases
            ),
            "supporting_ref_matches_trusted_goal": (
                bool(supporting_ref.get("alias"))
                and supporting_ref.get("alias")
                in trusted_goal_aliases
            ),
            "goal_ref_equals_supporting_ref": (
                bool(goal_ref.get("alias"))
                and goal_ref.get("alias")
                == supporting_ref.get("alias")
            ),
        })

    clause_rows = []
    for index, clause in enumerate(clauses):
        clause_goal_ref = _reference_shape(
            clause.get("goal_ref"),
            namespace="claim",
            alias_secret=alias_secret,
            pattern=_CLAIM_REF_RE,
        )
        clause_rows.append({
            "array_index": index,
            "clause_kind": _enum_shape(
                clause.get("clause_kind"),
                allowed_values=_CAPSULE_CLAUSE_KINDS,
            ),
            "goal_ref": clause_goal_ref,
            "goal_ref_matches_resolution_claim": (
                bool(clause_goal_ref.get("alias"))
                and clause_goal_ref.get("alias")
                in resolution_claim_aliases
            ),
        })

    reply = response.get("suggested_reply")
    reply_text = reply if isinstance(reply, str) else ""
    reply_bytes = reply_text.encode("utf-8")
    privacy_findings = scan_privacy_output(
        {"customer_visible_reply": reply_text}
    )
    capsule = {
        "schema_version": "projection-failure-capsule/v1",
        "run_uid_alias": run_uid_alias,
        "case_uid_alias": case_uid_alias,
        "case_index": int(case_index),
        "api_http_status": int(status_code),
        "response_body_sha256": hashlib.sha256(
            response_bytes
        ).hexdigest(),
        "response_body_byte_count": len(response_bytes),
        "top_level_fields": _top_level_shape(response),
        "turn_understanding_path": understanding_path,
        "turn_understanding_contract": _contract_field_shapes(
            understanding
        ),
        "runtime_customer_goal_count": len(goals),
        "resolution_count": len(resolutions),
        "clause_count": len(clauses),
        "goals": goal_rows,
        "resolutions": resolution_rows,
        "clauses": clause_rows,
        "customer_visible_reply": {
            "value_type": type(reply).__name__,
            "character_count": len(reply_text),
            "byte_count": len(reply_bytes),
            "value_sha256": hashlib.sha256(
                reply_bytes
            ).hexdigest(),
            "privacy_finding_count": sum(
                int(item.get("count") or 0)
                for item in privacy_findings
            ),
            "privacy_reason_codes": sorted({
                str(item.get("reason_code") or "")
                for item in privacy_findings
            }),
        },
        "projection_stage": "received_pre_projection",
        "projection_status": "pending",
        "exception": {"present": False},
        "used_for_scoring": False,
        "used_for_agent_input": False,
        "can_change_can_send": False,
        "authoritative_business_result": False,
    }
    _assert_report_safe(capsule)
    return capsule


def _capsule_exception(exc: Exception) -> dict[str, Any]:
    class_name = type(exc).__name__
    reason = str(exc).strip()
    if not re.fullmatch(r"[A-Za-z0-9_:,.-]{1,200}", reason):
        reason_shape = _value_fingerprint(reason)
        reason = ""
    else:
        reason_shape = {}
    result = {
        "present": True,
        "exception_class": (
            class_name
            if class_name in {
                "P1BaselineIntegrityError",
                "HighQualityReviewProjectionError",
            }
            else "unallowlisted_exception"
        ),
        "reason_code": reason,
    }
    result.update(reason_shape)
    return result


def _write_projection_capsule(
    path: Path,
    payload: dict[str, Any],
) -> dict[str, Any]:
    temporary = path.with_suffix(path.suffix + ".tmp")
    try:
        return _write_json(path, payload)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def _build_case_observation_with_capsule(
    *,
    output_dir: Path,
    capsule_path: Path,
    capsule_records: list[dict[str, Any]],
    run_uid_alias: str,
    case_uid_alias: str,
    case_index: int,
    status_code: int,
    scenario: dict[str, Any],
    response: dict[str, Any],
    scored: dict[str, Any],
    alias_secret: bytes,
) -> dict[str, Any]:
    capsule = _build_projection_failure_capsule(
        run_uid_alias=run_uid_alias,
        case_uid_alias=case_uid_alias,
        case_index=case_index,
        status_code=status_code,
        response=response,
        alias_secret=alias_secret,
    )
    _write_projection_capsule(capsule_path, capsule)
    try:
        observation = build_case_observation(
            scenario,
            response,
            scored,
            alias_secret=alias_secret,
        )
    except Exception as exc:
        failed = deepcopy(capsule)
        failed["projection_stage"] = "projection_failed"
        failed["projection_status"] = "projection_failed"
        failed["exception"] = _capsule_exception(exc)
        metadata = _write_projection_capsule(
            capsule_path,
            failed,
        )
        metadata["path"] = capsule_path.relative_to(
            output_dir
        ).as_posix()
        capsule_records.append(metadata)
        raise
    completed = deepcopy(capsule)
    completed["projection_stage"] = "completed"
    completed["projection_status"] = "completed"
    metadata = _write_projection_capsule(
        capsule_path,
        completed,
    )
    metadata["path"] = capsule_path.relative_to(
        output_dir
    ).as_posix()
    capsule_records.append(metadata)
    return observation


def _evidence_projection(
    response: dict[str, Any],
    *,
    alias_secret: bytes,
) -> list[dict[str, Any]]:
    from app.services.high_quality_long_conversation_review_service import (
        stable_evaluation_alias,
    )

    selected = _dicts(response.get("selected_evidence"))
    if not selected:
        selected = _dicts(
            _dict(response.get("minimal_decision_context")).get(
                "admitted_evidence"
            )
        )
    projected = []
    for item in selected:
        raw_uid = str(item.get("evidence_uid") or "").strip()
        if not raw_uid:
            continue
        identity_scope = _dict(item.get("identity_scope"))
        projected.append({
            "evidence_alias": stable_evaluation_alias(
                "evidence",
                raw_uid,
                alias_secret=alias_secret,
            ),
            "source": _safe_text(item.get("source")),
            "evidence_role": str(
                item.get("evidence_role") or item.get("role") or ""
            ),
            "fact_type": str(item.get("fact_type") or ""),
            "attribute_key": str(item.get("attribute_key") or ""),
            "review_status": str(item.get("review_status") or ""),
            "identity_namespaces": sorted(str(key) for key in identity_scope),
            "fact_summary": _safe_text(
                item.get("content")
                or item.get("answer")
                or item.get("value")
                or item.get("normalized_value")
            ),
        })
    return sorted(
        projected,
        key=lambda item: (
            item["evidence_alias"],
            item["fact_type"],
            item["attribute_key"],
        ),
    )


def _tool_projection(response: dict[str, Any]) -> dict[str, Any]:
    minimal = _dict(response.get("minimal_decision_context"))
    eligibility = _dict(minimal.get("answer_eligibility_context"))
    status = _dict(eligibility.get("tool_requirement_status"))
    calls = _dicts(response.get("tool_calls"))
    results = _dicts(response.get("tool_results"))
    return {
        "requirement_status": str(status.get("status") or ""),
        "reason_code": str(status.get("reason") or ""),
        "tool_call_count": len(calls),
        "tool_result_count": len(results),
        "tool_names": sorted({
            str(item.get("tool_name") or item.get("name") or "")
            for item in [*calls, *results]
            if str(item.get("tool_name") or item.get("name") or "")
        }),
        "completed_result_count": sum(
            str(item.get("status") or "").lower()
            in {"completed", "success", "succeeded"}
            for item in results
        ),
    }


def _service_projection(response: dict[str, Any]) -> list[dict[str, Any]]:
    values = _dicts(
        _dict(response.get("minimal_decision_context")).get("service_actions")
    )
    return [
        {
            "action_type": str(item.get("action_type") or ""),
            "status": str(item.get("status") or ""),
            "requires_human": bool(item.get("requires_human")),
        }
        for item in values
    ]


def _pipeline_projection(response: dict[str, Any]) -> dict[str, Any]:
    pipeline = _dict(response.get("analysis_pipeline"))
    return {
        "version": str(pipeline.get("version") or ""),
        "stage_statuses": [
            {
                "stage": str(item.get("stage") or ""),
                "status": str(item.get("status") or ""),
                "reason_code": str(item.get("reason") or ""),
            }
            for item in _dicts(pipeline.get("stages"))
        ],
    }


def _provider_projection(value: Any) -> dict[str, Any]:
    identity = _dict(value)
    host_fingerprint = str(identity.get("host_fingerprint") or "")
    if not _CONTROLLED_FINGERPRINT_PATTERNS[
        "host_fingerprint"
    ].fullmatch(host_fingerprint):
        raise P1BaselineIntegrityError(
            "formal_provider_fingerprint_invalid"
        )
    return {
        "provider_name": _safe_text(identity.get("provider_name")),
        "host_fingerprint": host_fingerprint,
        "model_name": _safe_text(identity.get("model_name")),
        "configured": identity.get("configured") is True,
    }


def build_case_observation(
    scenario: dict[str, Any],
    response: dict[str, Any],
    scored: dict[str, Any],
    *,
    alias_secret: bytes,
) -> dict[str, Any]:
    from app.services.high_quality_long_conversation_review_service import (
        HighQualityReviewProjectionError,
        project_trusted_goal_references,
    )

    request_template = _dict(scenario.get("api_request_template"))
    customer_message = str(
        request_template.get("message")
        or scenario.get("current_buyer_message")
        or ""
    )
    conversation_history = [
        item
        for item in request_template.get("conversation_history") or []
        if isinstance(item, dict)
    ]
    if str(scored.get("error_type") or ""):
        reference_projection = {
            "schema_version": "trusted-control-reference-projection/v1",
            "status": "execution_unavailable",
            "reason_code": "agent_execution_failed",
            "goal_count": 0,
            "resolution_count": 0,
            "clause_count": 0,
            "goals": [],
            "resolutions": [],
            "composer_clauses": [],
        }
    else:
        try:
            reference_projection = project_trusted_goal_references(
                response,
                customer_message=customer_message,
                conversation_history=conversation_history,
                alias_secret=alias_secret,
            )
        except HighQualityReviewProjectionError as exc:
            projection_reason = str(exc).strip()
            if not re.fullmatch(
                r"[a-z0-9_:,.-]{1,200}",
                projection_reason,
            ):
                projection_reason = "unallowlisted_projection_error"
            raise P1BaselineIntegrityError(
                "trusted_reference_projection_failed:"
                + projection_reason
            ) from exc
    composer = _dict(response.get("model_first_answer_composer"))
    final_audit = _dict(response.get("final_answer_audit"))
    semantic_audit = _dict(response.get("final_semantic_fit_audit"))
    blocks = _dicts(response.get("reply_blocks"))
    observation = {
        "schema_version": "p1-gold-conversation-case/v2",
        "case_alias": _case_alias(
            str(scenario.get("scenario_uid") or ""),
            alias_secret,
        ),
        "business_domain": _safe_text(scenario.get("business_domain")),
        "risk_level": str(scenario.get("risk_level") or ""),
        "conversation_turn_count": len(
            request_template.get("conversation_history") or []
        ) + 1,
        "must_handoff": bool(scenario.get("must_handoff")),
        "review_context": {
            "limited_history": _limited_history(scenario),
            "current_customer_message": _safe_text(
                request_template.get("message")
                or scenario.get("current_buyer_message")
            ),
        },
        "trusted_goal_projection": reference_projection,
        "selected_evidence": _evidence_projection(
            response,
            alias_secret=alias_secret,
        ),
        "tool": _tool_projection(response),
        "service_actions": _service_projection(response),
        "candidate_reply": _safe_text(composer.get("candidate_reply")),
        "final_customer_visible_reply": _safe_text(
            response.get("suggested_reply")
        ),
        "composer": {
            "status": str(composer.get("status") or ""),
            "rejection_reason": str(
                composer.get("rejection_reason") or ""
            ),
            "used_for_final_reply": bool(
                composer.get("used_for_final_reply")
            ),
            "model_call_count": int(
                scored.get("composer_model_call_count") or 0
            ),
            "latency_ms": scored.get("composer_latency_ms"),
        },
        "deterministic_final": {
            "passed": final_audit.get("passed") is True,
            "issues": sorted(
                str(item) for item in final_audit.get("issues") or []
            ),
            "model_call_count": int(
                scored.get("final_audit_model_call_count") or 0
            ),
        },
        "unified_audit": {
            "passed": semantic_audit.get("passed") is True,
            "issues": sorted(
                str(item) for item in semantic_audit.get("issues") or []
            ),
            "model_call_count": int(
                scored.get("unified_audit_model_call_count") or 0
            ),
            "latency_ms": scored.get("unified_audit_latency_ms"),
        },
        "delivery": {
            "can_send": bool(response.get("can_send")),
            "requires_human_review": bool(
                response.get("requires_human_review")
            ),
            "reply_status": str(response.get("reply_status") or ""),
            "handoff_reason": _safe_text(
                response.get("reason_for_review")
                or response.get("handoff_reason")
            ),
            "media_block_types": sorted(
                str(item.get("type") or "")
                for item in blocks
                if item.get("type") in {"image", "video"}
            ),
        },
        "pipeline": _pipeline_projection(response),
        "latency_ms": scored.get("latency_ms"),
        "error_type": str(scored.get("error_type") or ""),
        "deterministic_score": {
            key: deepcopy(scored.get(key))
            for key in (
                "nonempty_reply",
                "supported_complete",
                "unresolved_complete",
                "partial_answer_success",
                "partial_answer_expected",
                "runtime_supported_claim_numerator",
                "runtime_supported_claim_denominator",
                "runtime_unresolved_handling_numerator",
                "runtime_unresolved_handling_denominator",
                "bounded_inference_attribution_numerator",
                "bounded_inference_attribution_denominator",
                "eligible_policy_options_numerator",
                "eligible_policy_options_denominator",
                "eligible_policy_option_total_count",
                "policy_selection_numerator",
                "policy_selection_denominator",
                "selected_policy_validity_numerator",
                "selected_policy_validity_denominator",
                "selected_policy_premise_numerator",
                "selected_policy_premise_denominator",
                "selected_policy_scope_numerator",
                "selected_policy_scope_denominator",
                "inference_opportunity_missed_count",
                "unsupported_high_risk_claim",
                "unsupported_media_promise",
                "unsupported_service_action",
                "unnecessary_handoff",
                "repeated_known_information_request",
                "system_tone_terms",
                "forbidden_claim_hits",
                "unknown_goal_ref_count",
                "duplicate_goal_ref_clause_count",
                "wrong_clause_kind_count",
                "unsupported_evidence_ref_count",
                "non_customer_goal_clause_count",
                "fallback_used",
            )
        },
        "goal_recall_diagnostic": _goal_recall_diagnostic(
            scenario,
            reference_projection,
        ),
    }
    _assert_report_safe(observation)
    return observation


def _canonical_goal_identity(item: dict[str, Any]) -> tuple[str, str]:
    """Reuse production-owned aliases when scoring an isolated evaluation goal."""
    claim_type = canonical_material_composition_claim_type(
        item.get("claim_type") or item.get("fact_type")
    )
    raw_attribute = str(item.get("attribute_key") or "")
    normalized_attribute = (
        canonical_dimension_attribute(raw_attribute)
        if claim_type in {"dimensions", "size", "space_fit"}
        else raw_attribute
    )
    return (
        claim_type,
        canonical_attribute_slot(normalized_attribute, fact_type=claim_type),
    )


def _goal_expectation(item: dict[str, Any]) -> dict[str, Any] | None:
    """Normalize an evaluation-only atomic goal label without widening runtime facts."""
    raw = item.get("understanding_expectation")
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise P1BaselineIntegrityError("understanding_expectation_invalid")

    required = {
        "goal_kind",
        "claim_type_status",
        "claim_type",
        "attribute_key",
        "semantic_key",
        "subject_scope",
        "source_span_start",
        "source_span_end",
    }
    optional = {"source_span_sha256", "policy_intent_ref"}
    if not required <= set(raw) or set(raw) - required - optional:
        raise P1BaselineIntegrityError("understanding_expectation_fields_invalid")

    goal_kind = str(raw.get("goal_kind") or "").strip()
    status = str(raw.get("claim_type_status") or "").strip().lower()
    source_start = raw.get("source_span_start")
    source_end = raw.get("source_span_end")
    source_hash = str(raw.get("source_span_sha256") or "").strip().lower()
    policy_intent_ref = str(raw.get("policy_intent_ref") or "").strip().lower()
    if goal_kind not in {
        "customer_goal",
        "evidence_dependency",
        "media_request",
        "service_action",
        "contextual_constraint",
    }:
        raise P1BaselineIntegrityError("understanding_expectation_goal_kind_invalid")
    if status not in {"canonical", "unmapped"}:
        raise P1BaselineIntegrityError("understanding_expectation_status_invalid")
    if (
        not isinstance(source_start, int)
        or isinstance(source_start, bool)
        or not isinstance(source_end, int)
        or isinstance(source_end, bool)
        or source_start < 0
        or source_end <= source_start
        or (source_hash and not re.fullmatch(r"[0-9a-f]{64}", source_hash))
        or (
            policy_intent_ref
            and not re.fullmatch(r"[a-z][a-z0-9_]{2,95}", policy_intent_ref)
        )
    ):
        raise P1BaselineIntegrityError("understanding_expectation_span_invalid")

    claim_type, attribute_key = _canonical_goal_identity(raw)
    semantic_key = str(raw.get("semantic_key") or "").strip().lower()
    if status == "canonical":
        if not claim_type or semantic_key:
            raise P1BaselineIntegrityError("understanding_expectation_canonical_invalid")
    elif claim_type or attribute_key or not semantic_key:
        raise P1BaselineIntegrityError("understanding_expectation_unmapped_invalid")

    subject_scope = canonical_dimension_subject_scope(raw.get("subject_scope"))
    if str(raw.get("subject_scope") or "").strip() and not subject_scope:
        raise P1BaselineIntegrityError("understanding_expectation_scope_invalid")
    if subject_scope and claim_type not in {"dimensions", "size", "space_fit"}:
        raise P1BaselineIntegrityError("understanding_expectation_scope_type_invalid")
    return {
        "goal_kind": goal_kind,
        "claim_type_status": status,
        "claim_type": claim_type,
        "attribute_key": attribute_key,
        "semantic_key": semantic_key,
        "policy_intent_ref": policy_intent_ref,
        "subject_scope": subject_scope,
        "source_span_start": source_start,
        "source_span_end": source_end,
        "source_span_sha256": source_hash,
    }


def _runtime_goal_contract(item: dict[str, Any]) -> dict[str, Any]:
    claim_type, attribute_key = _canonical_goal_identity(item)
    status = str(item.get("claim_type_status") or "").strip().lower()
    if status not in {"canonical", "unmapped"}:
        status = "canonical" if claim_type else "unmapped"
    raw_claim_type = str(item.get("claim_type") or "").strip().lower()
    raw_attribute_key = str(item.get("attribute_key") or "").strip().lower()
    raw_subject_scope = canonical_dimension_subject_scope(
        item.get("subject_scope")
    )
    effective_subject_scope = _requested_subject_scope({
        "claim_type": raw_claim_type,
        "attribute_key": raw_attribute_key,
        "original_attribute_key": raw_attribute_key,
        "subject_scope": raw_subject_scope,
    })
    return {
        "goal_kind": str(item.get("goal_kind") or "customer_goal").strip(),
        "claim_type_status": status,
        "claim_type": claim_type,
        "attribute_key": attribute_key,
        "semantic_key": str(item.get("semantic_key") or "").strip().lower(),
        "policy_intent_ref": str(
            item.get("policy_intent_ref") or ""
        ).strip().lower(),
        "subject_scope": raw_subject_scope,
        "effective_subject_scope": str(effective_subject_scope or ""),
        "source_span_start": item.get("source_span_start"),
        "source_span_end": item.get("source_span_end"),
        "source_span_sha256": str(item.get("source_span_sha256") or "").strip().lower(),
    }


def _goal_source_matches(
    expected: dict[str, Any],
    observed: dict[str, Any],
) -> bool:
    return (
        expected["goal_kind"] == observed["goal_kind"]
        and expected["source_span_start"] == observed["source_span_start"]
        and expected["source_span_end"] == observed["source_span_end"]
        and (
            not expected["source_span_sha256"]
            or expected["source_span_sha256"] == observed["source_span_sha256"]
        )
    )


def _goal_identity_matches(
    expected: dict[str, Any],
    observed: dict[str, Any],
) -> bool:
    if not _goal_source_matches(expected, observed):
        return False
    if expected["claim_type_status"] != observed["claim_type_status"]:
        return False
    if expected["claim_type_status"] == "canonical":
        return (
            expected["claim_type"] == observed["claim_type"]
            and expected["attribute_key"] == observed["attribute_key"]
            and not observed["semantic_key"]
        )
    if observed["claim_type"] or observed["attribute_key"]:
        return False
    if expected["policy_intent_ref"]:
        return expected["policy_intent_ref"] == observed["policy_intent_ref"]
    return expected["semantic_key"] == observed["semantic_key"]


def _goal_recall_diagnostic(
    scenario: dict[str, Any],
    projection: dict[str, Any],
) -> dict[str, Any]:
    expectations = [
        expectation
        for item in _dicts(scenario.get("expected_claims"))
        if (expectation := _goal_expectation(item)) is not None
    ]
    if expectations:
        expected_customer_goals = [
            item for item in expectations if item["goal_kind"] == "customer_goal"
        ]
        expected_explicit_requests = [
            item
            for item in expectations
            if item["goal_kind"] in {
                "customer_goal",
                "media_request",
                "service_action",
            }
        ]
        observed_goals = [
            _runtime_goal_contract(item)
            for item in _dicts(projection.get("goals"))
        ]

        def count_matches(expected_rows: list[dict[str, Any]], predicate) -> int:
            remaining = list(observed_goals)
            matched = 0
            for expected in expected_rows:
                for index, observed in enumerate(remaining):
                    if predicate(expected, observed):
                        matched += 1
                        remaining.pop(index)
                        break
            return matched

        presence_count = count_matches(expected_customer_goals, _goal_source_matches)
        identity_count = count_matches(expected_customer_goals, _goal_identity_matches)
        explicit_count = count_matches(expected_explicit_requests, _goal_source_matches)
        scoped_dimensions = [
            item
            for item in expected_customer_goals
            if item["subject_scope"]
        ]
        scope_count = count_matches(
            scoped_dimensions,
            lambda expected, observed: (
                _goal_identity_matches(expected, observed)
                and expected["subject_scope"]
                == observed["effective_subject_scope"]
            ),
        )
        unexpected_goal_count = sum(
            not any(_goal_source_matches(expected, observed) for expected in expectations)
            for observed in observed_goals
        )
        unscored_count = sum(
            _goal_expectation(item) is None
            for item in _dicts(scenario.get("expected_claims"))
        )
        projection_status = str(projection.get("status") or "")
        return {
            "contract": "atomic_goal_identity_and_effective_scope/v4",
            "numerator": presence_count,
            "denominator": len(expected_customer_goals),
            "unexpected_goal_count": unexpected_goal_count,
            "customer_goal_identity_recall": {
                "numerator": identity_count,
                "denominator": len(expected_customer_goals),
                "rate": (
                    identity_count / len(expected_customer_goals)
                    if expected_customer_goals else None
                ),
            },
            "explicit_request_recall": {
                "numerator": explicit_count,
                "denominator": len(expected_explicit_requests),
                "rate": (
                    explicit_count / len(expected_explicit_requests)
                    if expected_explicit_requests else None
                ),
            },
            "dimension_subject_scope_attribution": {
                "numerator": scope_count,
                "denominator": len(scoped_dimensions),
                "rate": (
                    scope_count / len(scoped_dimensions)
                    if scoped_dimensions else None
                ),
            },
            "unscored_expected_claim_count": unscored_count,
            "status": (
                "scored"
                if projection_status == "valid"
                else projection_status or "projection_invalid"
            ),
        }

    expected = Counter(
        _canonical_goal_identity(item)
        for item in _dicts(scenario.get("expected_claims"))
    )
    observed = Counter(
        _canonical_goal_identity(item)
        for item in _dicts(projection.get("goals"))
    )
    matched = sum(
        min(count, observed.get(identity, 0))
        for identity, count in expected.items()
    )
    observed_total = sum(observed.values())
    projection_status = str(projection.get("status") or "")
    return {
        "contract": "canonical_claim_type_and_attribute_slot/v2",
        "numerator": matched,
        "denominator": sum(expected.values()),
        "unexpected_goal_count": max(0, observed_total - matched),
        "status": (
            "scored"
            if projection_status == "valid"
            else projection_status or "projection_invalid"
        ),
    }


def _limited_history(
    scenario: dict[str, Any],
    *,
    limit: int = 6,
) -> list[dict[str, str]]:
    request_template = _dict(scenario.get("api_request_template"))
    history = [
        item for item in request_template.get("conversation_history") or []
        if isinstance(item, dict)
    ]
    result = []
    for item in history[-limit:]:
        role = str(item.get("role") or "").strip().lower()
        if role not in {"buyer", "customer", "agent", "assistant", "system"}:
            role = "unknown"
        result.append({
            "role": role,
            "content": _safe_text(
                item.get("content") or item.get("text")
            ),
        })
    return result


def _earliest_owner_suggestion(
    observation: dict[str, Any],
) -> str:
    score = _dict(observation.get("deterministic_score"))
    composer = _dict(observation.get("composer"))
    final = _dict(observation.get("deterministic_final"))
    unified = _dict(observation.get("unified_audit"))
    if observation.get("error_type"):
        return "provider_execution_error"
    projection = _dict(observation.get("trusted_goal_projection"))
    if not int(projection.get("goal_count") or 0):
        return "goal_understanding_gap"
    if (
        int(score.get("runtime_supported_claim_numerator") or 0)
        < int(score.get("runtime_supported_claim_denominator") or 0)
    ):
        return "evidence_admission_gap"
    if composer.get("status") != "accepted":
        return "composer_completion_gap"
    if final.get("passed") is True and unified.get("passed") is not True:
        return "unified_audit_false_rejection"
    if score.get("unnecessary_handoff"):
        return "unnecessary_handoff"
    if (
        score.get("repeated_known_information_request")
        or score.get("system_tone_terms")
    ):
        return "naturalness_and_progression_gap"
    return "no_deterministic_failure"


def build_review_item(
    scenario: dict[str, Any],
    observation: dict[str, Any],
) -> dict[str, Any]:
    request_template = _dict(scenario.get("api_request_template"))
    review_context = _dict(observation.get("review_context"))
    item = {
        "case_alias": observation["case_alias"],
        "business_domain": observation["business_domain"],
        "risk_level": observation["risk_level"],
        "limited_history": (
            review_context.get("limited_history")
            or _limited_history(scenario)
        ),
        "current_customer_message": (
            review_context.get("current_customer_message")
            or _safe_text(
                request_template.get("message")
                or scenario.get("current_buyer_message")
            )
        ),
        "current_customer_goals": _dict(
            observation.get("trusted_goal_projection")
        ).get("goals") or [],
        "available_formal_facts": observation.get("selected_evidence") or [],
        "agent_customer_visible_reply": observation.get(
            "final_customer_visible_reply"
        ),
        "claim_resolutions": _dict(
            observation.get("trusted_goal_projection")
        ).get("resolutions") or [],
        "risk_boundary": {
            "must_handoff": observation.get("must_handoff"),
            "can_send": _dict(
                observation.get("delivery")
            ).get("can_send"),
            "requires_human_review": _dict(
                observation.get("delivery")
            ).get("requires_human_review"),
        },
        "earliest_owner_suggestion": _earliest_owner_suggestion(
            observation
        ),
        "human_review": {
            "status": "pending_supervisor",
            "factual_correctness": None,
            "goal_completion": None,
            "naturalness": None,
            "empathy": None,
            "business_helpfulness": None,
            "bounded_inference_quality": None,
            "handoff_necessity": None,
            "notes": "",
        },
    }
    _assert_report_safe(item)
    return item


def _load_expert_review(
    path: Path,
    *,
    expected_case_aliases: set[str],
) -> dict[str, Any]:
    payload = _load_json(
        path,
        reason="expert_review_json_invalid",
    )
    if (
        payload.get("schema_version")
        != "p1-codex-expert-review/v1"
        or payload.get("review_type")
        != "codex_expert_offline_review"
        or payload.get("supervisor_approved") is not False
    ):
        raise P1BaselineIntegrityError(
            "expert_review_contract_invalid"
        )
    allowed_reasons = {
        "robotic_process_language",
        "excessive_uncertainty",
        "missing_everyday_explanation",
        "unsupported_guarantee",
        "weak_product_explanation",
        "repeated_information_request",
        "unnecessary_handoff",
        "incomplete_multi_goal_answer",
        "good_partial_answer",
        "gold_service_quality",
    }
    allowed_owners = {
        "bounded_low_risk_inference",
        "natural_gold_service_language",
        "unified_audit_false_rejection",
        "multi-goal_completion",
        "formal_knowledge_tool_coverage",
        "unnecessary_handoff",
        "latency_bottleneck",
        "p0_regression_closure",
    }
    selected_owner = str(
        payload.get("selected_next_owner") or ""
    )
    if selected_owner not in allowed_owners:
        raise P1BaselineIntegrityError(
            "expert_review_next_owner_invalid"
        )
    items = _dicts(payload.get("items"))
    aliases = [str(item.get("case_alias") or "") for item in items]
    if (
        len(aliases) != len(set(aliases))
        or set(aliases) != expected_case_aliases
    ):
        raise P1BaselineIntegrityError(
            "expert_review_case_set_mismatch"
        )
    score_fields = (
        "factual_correctness",
        "goal_completion",
        "naturalness",
        "empathy_politeness",
        "business_helpfulness",
        "bounded_common_sense_reasoning",
    )
    for item in items:
        for field in score_fields:
            value = item.get(field)
            if isinstance(value, bool) or value not in {0, 1, 2}:
                raise P1BaselineIntegrityError(
                    f"expert_review_score_invalid:{field}"
                )
        if item.get("handoff_necessity") not in {
            "necessary",
            "unnecessary",
            "not_applicable",
        }:
            raise P1BaselineIntegrityError(
                "expert_review_handoff_invalid"
            )
        reasons = item.get("reason_codes")
        if (
            not isinstance(reasons, list)
            or any(str(value) not in allowed_reasons for value in reasons)
        ):
            raise P1BaselineIntegrityError(
                "expert_review_reason_invalid"
            )
        item["rewrite_suggestion"] = _safe_text(
            item.get("rewrite_suggestion")
        )
    payload["selection_rationale"] = _safe_text(
        payload.get("selection_rationale")
    )
    payload["items"] = sorted(
        items,
        key=lambda item: str(item.get("case_alias") or ""),
    )
    _assert_report_safe(payload)
    return payload


def _assert_report_safe(value: Any) -> None:
    from app.services.real_accuracy_privacy_service import (
        scan_privacy_output,
    )

    forbidden_paths: list[str] = []
    invalid_fingerprint_paths: list[str] = []

    def visit(item: Any, path: str) -> Any:
        if (
            isinstance(item, float)
            and math.isfinite(item)
            and not item.is_integer()
        ):
            return round(item, 8)
        if isinstance(item, list):
            return [
                visit(child, f"{path}[{index}]")
                for index, child in enumerate(item)
            ]
        if not isinstance(item, dict):
            return item
        projected: dict[str, Any] = {}
        for key, child in item.items():
            normalized = str(key).strip().lower()
            if normalized in _PROHIBITED_REPORT_KEYS:
                forbidden_paths.append(f"{path}.{key}")
            fingerprint_pattern = _CONTROLLED_FINGERPRINT_PATTERNS.get(
                normalized
            )
            if fingerprint_pattern is not None:
                if (
                    not isinstance(child, str)
                    or not fingerprint_pattern.fullmatch(child)
                ):
                    invalid_fingerprint_paths.append(f"{path}.{key}")
                continue
            projected[str(key)] = visit(child, f"{path}.{key}")
        return projected

    privacy_projection = visit(value, "$")
    if forbidden_paths:
        raise P1BaselineIntegrityError(
            "prohibited_report_field:" + ",".join(forbidden_paths)
        )
    if invalid_fingerprint_paths:
        raise P1BaselineIntegrityError(
            "controlled_fingerprint_invalid:"
            + ",".join(invalid_fingerprint_paths)
        )
    serialized = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    if _RAW_INTERNAL_REF_RE.search(serialized):
        raise P1BaselineIntegrityError(
            "raw_internal_goal_reference_forbidden"
        )
    findings = scan_privacy_output(privacy_projection)
    if findings:
        reason_codes = sorted({
            str(item.get("reason_code") or "")
            for item in findings
        })
        raise P1BaselineIntegrityError(
            "report_privacy_validation_failed:"
            + ",".join(reason_codes)
        )


def _write_json(path: Path, payload: Any) -> dict[str, Any]:
    _assert_report_safe(payload)
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = (
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    ).encode("utf-8")
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(encoded)
    with temporary.open("r", encoding="utf-8") as handle:
        json.load(handle)
    temporary.replace(path)
    return {
        "path": path.as_posix(),
        "sha256": hashlib.sha256(encoded).hexdigest(),
        "byte_count": len(encoded),
    }


def _compact_knowledge_fingerprint(
    value: dict[str, Any],
) -> dict[str, Any]:
    return {
        "formal_content_sha256": str(
            value.get("formal_content_sha256") or ""
        ),
        "tables": [
            {
                "table": str(item.get("table") or ""),
                "row_count": int(item.get("row_count") or 0),
                "schema_sha256": str(
                    item.get("schema_sha256") or ""
                ),
                "content_sha256": str(
                    item.get("content_sha256") or ""
                ),
            }
            for item in value.get("formal_tables") or []
            if isinstance(item, dict)
        ],
    }


def _compact_snapshot_fingerprint(
    value: dict[str, Any],
) -> dict[str, Any]:
    tables = []
    for item in value.get("formal_tables") or []:
        if not isinstance(item, dict):
            continue
        tables.append({
            "table": str(item.get("table") or ""),
            "exists": item.get("exists") is True,
            "row_count": int(item.get("row_count") or 0),
            "schema_sha256": str(
                item.get("schema_sha256") or ""
            ),
            "content_sha256": str(
                item.get("content_sha256") or ""
            ),
            "rows": [
                {
                    "row_identity_hmac": str(
                        row.get("row_identity_hmac") or ""
                    ),
                    "row_sha256": str(
                        row.get("row_sha256") or ""
                    ),
                }
                for row in item.get("rows") or []
                if isinstance(row, dict)
            ],
        })
    return {
        "query_only": value.get("query_only") is True,
        "formal_content_sha256": str(
            value.get("formal_content_sha256") or ""
        ),
        "schema_sha256": _canonical_hash([
            [item["table"], item["schema_sha256"]]
            for item in tables
        ]),
        "tables": tables,
    }


def _expanded_snapshot_fingerprint(
    value: dict[str, Any],
) -> dict[str, Any]:
    return {
        "query_only": value.get("query_only") is True,
        "formal_content_sha256": str(
            value.get("formal_content_sha256") or ""
        ),
        "formal_tables": [
            {
                "table": str(item.get("table") or ""),
                "exists": item.get("exists") is True,
                "row_count": int(item.get("row_count") or 0),
                "schema_sha256": str(
                    item.get("schema_sha256") or ""
                ),
                "content_sha256": str(
                    item.get("content_sha256") or ""
                ),
                "rows": [
                    {
                        "row_identity_hmac": str(
                            row.get("row_identity_hmac") or ""
                        ),
                        "row_sha256": str(
                            row.get("row_sha256") or ""
                        ),
                        "column_sha256": {},
                    }
                    for row in item.get("rows") or []
                    if isinstance(row, dict)
                ],
            }
            for item in value.get("tables") or []
            if isinstance(item, dict)
        ],
    }


def _verify_sqlite_query_only(path: Path) -> bool:
    connection = sqlite3.connect(
        f"file:{path.resolve().as_posix()}?mode=ro",
        uri=True,
    )
    try:
        connection.execute("PRAGMA query_only=ON")
        enabled = int(
            connection.execute("PRAGMA query_only").fetchone()[0]
        ) == 1
        connection.execute("SELECT 1").fetchone()
        return enabled
    finally:
        connection.close()


_RECONSTRUCTED_DIRECT_STATUSES = {
    "approved",
    "published",
    "reviewed",
    "verified",
}
_RECONSTRUCTED_DIRECT_ROLE = "direct_product_fact"
_RECONSTRUCTED_SUBJECT_SCOPES = {
    "accessory",
    "component",
    "included_item",
    "packaging",
    "product",
}
_RECONSTRUCTED_SEED_TIMESTAMP = "2000-01-01T00:00:00+00:00"


def _reconstructed_snapshot_seed_projection(
    dataset: dict[str, Any],
) -> dict[str, Any]:
    """Project only versioned input evidence into an isolated eval snapshot."""
    if str(dataset.get("source_class") or "") != "conversation_reconstructed":
        raise P1BaselineIntegrityError(
            "reconstructed_snapshot_source_class_invalid"
        )
    scenarios = _dicts(dataset.get("scenarios"))
    if not scenarios:
        raise P1BaselineIntegrityError(
            "reconstructed_snapshot_scenarios_missing"
        )

    products: list[dict[str, str]] = []
    direct_evidence: list[dict[str, Any]] = []
    excluded_candidate_count = 0
    product_ids: set[str] = set()
    evidence_uids: set[str] = set()
    for scenario in scenarios:
        request_template = _dict(
            scenario.get("api_request_template")
        )
        i_id = str(request_template.get("i_id") or "").strip()
        product_name = str(
            request_template.get("product_name") or ""
        ).strip()
        if not i_id or not product_name:
            raise P1BaselineIntegrityError(
                "reconstructed_snapshot_product_identity_missing"
            )
        if i_id in product_ids:
            raise P1BaselineIntegrityError(
                "reconstructed_snapshot_product_identity_duplicate"
            )
        product_ids.add(i_id)
        products.append({
            "i_id": i_id,
            "product_name": product_name,
        })

        for candidate in _dicts(scenario.get("evidence_candidates")):
            evidence_uid = str(
                candidate.get("evidence_uid") or ""
            ).strip()
            if not evidence_uid or evidence_uid in evidence_uids:
                raise P1BaselineIntegrityError(
                    "reconstructed_snapshot_evidence_uid_invalid"
                )
            evidence_uids.add(evidence_uid)
            status = str(candidate.get("status") or "").strip().lower()
            role = str(candidate.get("role") or "").strip().lower()
            if (
                status not in _RECONSTRUCTED_DIRECT_STATUSES
                or role != _RECONSTRUCTED_DIRECT_ROLE
            ):
                excluded_candidate_count += 1
                continue
            value = candidate.get("value")
            if value in (None, "", [], {}):
                raise P1BaselineIntegrityError(
                    "reconstructed_reviewed_direct_value_missing"
                )
            fact_type = str(
                candidate.get("fact_type") or ""
            ).strip().lower()
            attribute_key = str(
                candidate.get("attribute_key") or ""
            ).strip().lower()
            subject_scope = str(
                candidate.get("subject_scope") or "product"
            ).strip().lower()
            if not fact_type or not attribute_key:
                raise P1BaselineIntegrityError(
                    "reconstructed_snapshot_fact_identity_missing"
                )
            if subject_scope not in _RECONSTRUCTED_SUBJECT_SCOPES:
                raise P1BaselineIntegrityError(
                    "reconstructed_snapshot_subject_scope_invalid"
                )
            direct_evidence.append({
                "evidence_uid": evidence_uid,
                "fact_type": fact_type,
                "attribute_key": attribute_key,
                "value": deepcopy(value),
                "unit": str(candidate.get("unit") or "").strip(),
                "subject_scope": subject_scope,
                "status": status,
                "role": role,
                "i_id": i_id,
                "product_name": product_name,
            })

    return {
        "schema_version": "p1-reconstructed-snapshot-seed/v1",
        "products": sorted(products, key=lambda item: item["i_id"]),
        "direct_evidence": sorted(
            direct_evidence,
            key=lambda item: item["evidence_uid"],
        ),
        "excluded_candidate_count": excluded_candidate_count,
    }


def _reconstructed_fact_text(item: dict[str, Any]) -> str:
    return json.dumps(
        {
            "attribute_key": item["attribute_key"],
            "subject_scope": item["subject_scope"],
            "unit": item["unit"],
            "value": item["value"],
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _seed_reconstructed_snapshot(
    snapshot_path: Path,
    *,
    dataset: dict[str, Any],
    dataset_sha256: str,
) -> dict[str, Any]:
    projection = _reconstructed_snapshot_seed_projection(dataset)
    connection = sqlite3.connect(snapshot_path)
    try:
        table_names = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        required = {
            "kb_product",
            "kb_qa",
            "knowledge_entries",
            "knowledge_chunks",
        }
        if not required.issubset(table_names):
            raise P1BaselineIntegrityError(
                "reconstructed_snapshot_schema_incomplete"
            )

        with connection:
            for product in projection["products"]:
                if connection.execute(
                    "SELECT 1 FROM kb_product WHERE i_id = ?",
                    (product["i_id"],),
                ).fetchone():
                    raise P1BaselineIntegrityError(
                        "reconstructed_snapshot_product_collision"
                    )
                connection.execute(
                    """
                    INSERT INTO kb_product (
                        i_id, product_name, brand, category_l1,
                        category_l2, category_l3, sku_list_json,
                        specs_json, logistics_json, warranty_json,
                        completeness_score, missing_fields_json, status,
                        version, created_by, updated_by, created_at,
                        updated_at, import_batch_id
                    ) VALUES (?, ?, '', 'evaluation', '', '', '[]',
                              '{}', '{}', '{}', 0, '[]', 'published',
                              1, 'p1_eval_snapshot', 'p1_eval_snapshot',
                              ?, ?, ?)
                    """,
                    (
                        product["i_id"],
                        product["product_name"],
                        _RECONSTRUCTED_SEED_TIMESTAMP,
                        _RECONSTRUCTED_SEED_TIMESTAMP,
                        dataset_sha256,
                    ),
                )
            for item in projection["direct_evidence"]:
                fact_text = _reconstructed_fact_text(item)
                scope_json = json.dumps(
                    [item["i_id"], item["product_name"]],
                    ensure_ascii=False,
                    separators=(",", ":"),
                )
                content_hash = _canonical_hash({
                    "dataset_sha256": dataset_sha256,
                    "evidence_uid": item["evidence_uid"],
                    "fact": fact_text,
                })
                cursor = connection.execute(
                    """
                    INSERT INTO knowledge_entries (
                        source_type, title, content, intent, sub_intent,
                        category, category_l3, search_keywords, scene_tag,
                        product_line, product_scope_json, sku_scope_json,
                        platform_scope_json, risk_level,
                        auto_reply_allowed, human_review_required,
                        condition_text, forbidden_usage, status, version,
                        created_by, updated_by, reviewed_by, published_at,
                        created_at, updated_at, source_sheet, row_number,
                        import_batch_id, content_hash, business_key,
                        product_id, sku_id, fact_type, fact_scope,
                        source_confidence, fact_review_status, index_status
                    ) VALUES (
                        'product_facts', ?, ?, 'product_question', '',
                        'reconstructed_evidence', ?, ?, '', '', ?, '[]',
                        '[]', 'low', 1, 0, '', '', 'published', 1,
                        'p1_eval_snapshot', 'p1_eval_snapshot',
                        'p1_eval_snapshot', ?, ?, ?, '', 0, ?, ?, ?,
                        ?, '', ?, ?, 0.95, ?, 'ready'
                    )
                    """,
                    (
                        f"{item['product_name']} {item['attribute_key']}",
                        fact_text,
                        item["fact_type"],
                        f"{item['fact_type']} {item['attribute_key']}",
                        scope_json,
                        _RECONSTRUCTED_SEED_TIMESTAMP,
                        _RECONSTRUCTED_SEED_TIMESTAMP,
                        _RECONSTRUCTED_SEED_TIMESTAMP,
                        dataset_sha256,
                        content_hash,
                        f"evaluation:{item['evidence_uid']}",
                        item["i_id"],
                        item["fact_type"],
                        item["subject_scope"],
                        item["status"],
                    ),
                )
                entry_id = int(cursor.lastrowid)
                metadata = {
                    "attribute_key": item["attribute_key"],
                    "can_direct_answer": True,
                    "direct_answer_allowed": True,
                    "evidence_role": _RECONSTRUCTED_DIRECT_ROLE,
                    "evidence_uid": item["evidence_uid"],
                    "fact_review_status": item["status"],
                    "product_evidence_protocol": True,
                    "reference_only": False,
                    "source_id": item["evidence_uid"],
                    "source_table": "knowledge_entries",
                    "subject_scope": item["subject_scope"],
                    "unit": item["unit"],
                    "value": item["value"],
                    "verification_status": item["status"],
                }
                if item["fact_type"] == "material":
                    metadata["material_provenance"] = (
                        "structured_product_record"
                    )
                connection.execute(
                    """
                    INSERT INTO knowledge_chunks (
                        entry_id, chunk_text, chunk_index, source_type,
                        intent, product_scope_json, sku_scope_json,
                        platform_scope_json, metadata_json, category,
                        category_l3, search_keywords, embedding_status,
                        created_at, embedding_json, source_confidence,
                        fact_review_status, fact_source_type, updated_at
                    ) VALUES (
                        ?, ?, 0, 'product_facts', 'product_question', ?,
                        '[]', '[]', ?, 'reconstructed_evidence', ?, ?,
                        'ready', ?, NULL, 0.95, ?,
                        'direct_product_fact', ?
                    )
                    """,
                    (
                        entry_id,
                        fact_text,
                        scope_json,
                        json.dumps(
                            metadata,
                            ensure_ascii=False,
                            sort_keys=True,
                            separators=(",", ":"),
                        ),
                        item["fact_type"],
                        f"{item['fact_type']} {item['attribute_key']}",
                        _RECONSTRUCTED_SEED_TIMESTAMP,
                        item["status"],
                        _RECONSTRUCTED_SEED_TIMESTAMP,
                    ),
                )

            connection.execute(
                """
                INSERT INTO kb_qa (
                    question, answer, intent, sub_intent, category_l1,
                    category_l2, category_l3, product_id,
                    sku_codes_json, risk_level, auto_reply,
                    human_review, keywords_json, source_type,
                    scenario_category, issue_type, sop_id, status,
                    version, created_by, updated_by, reviewed_by,
                    published_at, created_at, updated_at,
                    import_batch_id, content_hash
                ) VALUES (
                    'evaluation readiness sentinel',
                    'inactive evaluation readiness sentinel',
                    'general', '', 'evaluation', '', '', NULL, '[]',
                    'low', 0, 1, '[]',
                    'evaluation_readiness_sentinel', '', '', NULL,
                    'archived', 1, 'p1_eval_snapshot',
                    'p1_eval_snapshot', '', NULL, ?, ?, ?, ?
                )
                """,
                (
                    _RECONSTRUCTED_SEED_TIMESTAMP,
                    _RECONSTRUCTED_SEED_TIMESTAMP,
                    dataset_sha256,
                    _canonical_hash({
                        "dataset_sha256": dataset_sha256,
                        "kind": "readiness_sentinel",
                    }),
                ),
            )
    except sqlite3.Error as exc:
        raise P1BaselineIntegrityError(
            "reconstructed_snapshot_seed_failed"
        ) from exc
    finally:
        connection.close()

    projection_hash = _canonical_hash(projection)
    return {
        "schema_version": projection["schema_version"],
        "content_sha256": projection_hash,
        "product_count": len(projection["products"]),
        "direct_evidence_count": len(projection["direct_evidence"]),
        "excluded_candidate_count": int(
            projection["excluded_candidate_count"]
        ),
        "readiness_sentinel_count": 1,
        "source": "dataset.evidence_candidates",
    }


def _prepare_knowledge_snapshot(
    *,
    source_path: Path,
    snapshot_path: Path,
    hmac_key: str,
    dataset_sha256: str,
    source_manifest_file_sha256: str,
    runner_source_sha256: str,
    evaluator_source_sha256: str,
    source_tree_sha256: str,
    git_head: str,
    git_dirty: bool,
    provider_identity: dict[str, Any],
    feature_flags: dict[str, Any],
    dml_start_offset: int,
    contract: DatasetContract | None = None,
    dataset: dict[str, Any] | None = None,
) -> dict[str, Any]:
    from app.services.formal_knowledge_database_guard_service import (
        backup_sqlite_database,
        fingerprint_formal_knowledge_tables,
    )

    if not hmac_key:
        raise P1BaselineIntegrityError(
            "formal_kb_audit_hmac_key_required"
        )
    backup_sqlite_database(source_path, snapshot_path)
    resolved_contract = contract or _legacy_dataset_contract()
    evaluation_seed: dict[str, Any] = {}
    if resolved_contract.source_class == "conversation_reconstructed":
        if not isinstance(dataset, dict):
            raise P1BaselineIntegrityError(
                "reconstructed_snapshot_dataset_required"
            )
        evaluation_seed = _seed_reconstructed_snapshot(
            snapshot_path,
            dataset=dataset,
            dataset_sha256=dataset_sha256,
        )
    if not _verify_sqlite_query_only(snapshot_path):
        raise P1BaselineIntegrityError(
            "snapshot_query_only_verification_failed"
        )
    fingerprint = fingerprint_formal_knowledge_tables(
        snapshot_path,
        hmac_key=hmac_key,
    )
    compact = _compact_snapshot_fingerprint(fingerprint)
    manifest = {
        "schema_version": "p1-authoritative-pre-run/v1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "dataset_sha256": dataset_sha256,
        "source_manifest_file_sha256": (
            source_manifest_file_sha256
        ),
        "runner_source_sha256": runner_source_sha256,
        "evaluator_source_sha256": evaluator_source_sha256,
        "source_tree_sha256": source_tree_sha256,
        "git": {
            "head": git_head,
            "worktree_dirty": bool(git_dirty),
        },
        "provider": deepcopy(provider_identity),
        "feature_flags": deepcopy(feature_flags),
        "dml_start_offset": int(dml_start_offset),
        "snapshot": {
            "database_basename": snapshot_path.name,
            "file_sha256": _sha256_file(snapshot_path),
            "query_only_verified": True,
            "formal_knowledge": compact,
        },
    }
    if evaluation_seed:
        manifest["snapshot"]["evaluation_seed"] = evaluation_seed
    manifest.update(
        _contract_report_fields(
            resolved_contract
        )
    )
    _assert_report_safe(manifest)
    return manifest


def _build_post_run_manifest(
    *,
    pre_run_manifest: dict[str, Any],
    snapshot_path: Path,
    hmac_key: str,
    dml_attempt_count: int,
) -> dict[str, Any]:
    from app.services.formal_knowledge_database_guard_service import (
        compare_formal_knowledge_fingerprints,
        fingerprint_formal_knowledge_tables,
    )

    before_compact = _dict(
        _dict(pre_run_manifest.get("snapshot")).get(
            "formal_knowledge"
        )
    )
    after_raw = fingerprint_formal_knowledge_tables(
        snapshot_path,
        hmac_key=hmac_key,
    )
    after_compact = _compact_snapshot_fingerprint(after_raw)
    difference = compare_formal_knowledge_fingerprints(
        _expanded_snapshot_fingerprint(before_compact),
        _expanded_snapshot_fingerprint(after_compact),
    )
    pre_file_sha = str(
        _dict(pre_run_manifest.get("snapshot")).get(
            "file_sha256"
        )
        or ""
    )
    post_file_sha = _sha256_file(snapshot_path)
    unchanged = bool(
        not difference.get("changed")
        and pre_file_sha == post_file_sha
        and int(dml_attempt_count) == 0
        and _verify_sqlite_query_only(snapshot_path)
    )
    result = {
        "schema_version": "p1-authoritative-post-run/v1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "dataset_sha256": str(
            pre_run_manifest.get("dataset_sha256") or ""
        ),
        "snapshot_file_sha256": post_file_sha,
        "query_only_verified": _verify_sqlite_query_only(
            snapshot_path
        ),
        "formal_knowledge": after_compact,
        "snapshot_unchanged": unchanged,
        "changed_row_count": int(
            difference.get("changed_row_count") or 0
        ),
        "changed_table_count": int(
            difference.get("changed_table_count") or 0
        ),
        "dml_attempt_count": int(dml_attempt_count),
    }
    _assert_report_safe(result)
    return result


def _checkpoint_payload(
    *,
    contract: DatasetContract | None = None,
    dataset_hash: str,
    runtime: dict[str, Any],
    runner_source_sha256: str,
    formal_knowledge_before: dict[str, Any],
    dml_start_offset: int,
    completed_files: list[dict[str, Any]],
    capsule_files: list[dict[str, Any]] | None = None,
    evaluator_source_sha256: str = "",
    pre_run_manifest_sha256: str = "",
    snapshot_file_sha256: str = "",
    deterministic_summary: dict[str, Any] | None = None,
    integrity_stop_reason: str = "",
) -> dict[str, Any]:
    projection_capsules = capsule_files or []
    payload = {
        "schema_version": "p1-gold-conversation-checkpoint/v3",
        "dataset_sha256": dataset_hash,
        "runtime_commit": runtime.get("runtime_commit"),
        "source_tree_sha256": runtime.get("source_tree_sha256"),
        "runner_source_sha256": runner_source_sha256,
        "formal_knowledge_before": formal_knowledge_before,
        "dml_start_offset": int(dml_start_offset),
        "completed_case_count": len(completed_files),
        "completed_case_files": completed_files,
        "projection_capsule_count": len(projection_capsules),
        "projection_capsule_files": projection_capsules,
        "resume_allowed": False,
    }
    payload.update(
        _contract_report_fields(
            contract
            or _legacy_dataset_contract()
        )
    )
    if evaluator_source_sha256:
        payload["evaluator_source_sha256"] = (
            evaluator_source_sha256
        )
    if pre_run_manifest_sha256:
        payload["pre_run_manifest_sha256"] = (
            pre_run_manifest_sha256
        )
    if snapshot_file_sha256:
        payload["snapshot_file_sha256"] = snapshot_file_sha256
    if deterministic_summary is not None:
        projected_summary = {
            key: deepcopy(value)
            for key, value in deterministic_summary.items()
            if key in _SUMMARY_METRIC_FIELDS
        }
        projected_summary["policy_intent_ref_total_count"] = sum(
            int(value or 0)
            for value in _dict(
                deterministic_summary.get(
                    "policy_intent_ref_counts"
                )
            ).values()
        )
        payload["deterministic_summary"] = projected_summary
    if integrity_stop_reason:
        payload["integrity_stop_reason"] = integrity_stop_reason
    return payload


def _preflight_dataset(
    dataset_path: Path,
    manifest_path: Path,
    *,
    contract: DatasetContract,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    from app.services.high_quality_long_conversation_review_service import (
        build_review_inventory,
        load_and_validate_review_dataset,
    )

    dataset, validation = load_and_validate_review_dataset(dataset_path)
    inventory = build_review_inventory(dataset)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if contract.source_class == "conversation_reconstructed":
        _validate_reconstructed_dataset_contract(dataset, manifest)
    findings = []
    if validation.get("validation_status") != "passed":
        findings.append("dataset_validation_failed")
    if dataset.get("dataset_id") != contract.dataset_id:
        findings.append("dataset_id_mismatch")
    if dataset.get("dataset_version") != contract.dataset_version:
        findings.append("dataset_version_mismatch")
    if inventory.get("scenario_count") != contract.case_count:
        findings.append("scenario_count_mismatch")
    if (
        inventory.get("conversation_history_turn_count")
        != contract.history_turn_count
    ):
        findings.append("history_turn_count_mismatch")
    if inventory.get("target_missing_count"):
        findings.append("target_turn_missing")
    if inventory.get("privacy_finding_count"):
        findings.append("dataset_privacy_failed")
    if validation.get("computed_content_sha256") != contract.dataset_sha256:
        findings.append("dataset_hash_mismatch")
    if manifest.get("content_sha256") != contract.dataset_sha256:
        findings.append("manifest_content_hash_mismatch")
    if _sha256_file(manifest_path) != contract.manifest_file_sha256:
        findings.append("manifest_file_hash_mismatch")
    if (
        contract.source_class == "conversation_reconstructed"
        and manifest.get("dataset_file_sha256") != _sha256_file(dataset_path)
    ):
        findings.append("dataset_file_hash_mismatch")
    if findings:
        raise P1BaselineIntegrityError(
            "p1_dataset_preflight_blocked:"
            + ",".join(sorted(findings))
        )
    return dataset, inventory, manifest


def _runtime_preflight(
    evaluator: Any,
    *,
    analyze_url: str,
    expected_commit: str,
    expected_source_sha256: str,
    expected_model: str,
) -> dict[str, Any]:
    version_url = analyze_url.rsplit("/api/analyze", 1)[0]
    runtime = evaluator._get_json(
        f"{version_url}/api/runtime/version",
        30,
    )
    findings = evaluator._runtime_contract(
        runtime,
        mode="ON",
        expected_commit=expected_commit,
        expected_source_hash=expected_source_sha256,
        expected_model=expected_model,
    )
    flags = _dict(runtime.get("feature_flags"))
    if flags.get("formal_evidence_convergence") is not True:
        findings.append("formal_evidence_convergence_not_enabled")
    if flags.get("model_first_answer_composer") is not True:
        findings.append("model_first_composer_not_enabled")
    if runtime.get("formal_knowledge_query_only") is not True:
        findings.append("formal_knowledge_not_query_only")
    if _dict(runtime.get("readiness")).get("ready") is not True:
        findings.append("runtime_not_ready")
    if findings:
        raise P1BaselineIntegrityError(
            "runtime_contract_failed:"
            + ",".join(sorted(set(findings)))
        )
    return runtime


def _validate_runtime_binding(
    path: Path,
    *,
    pre_run_manifest: dict[str, Any],
    expected_source_sha256: str,
    expected_runtime_port: int = 5013,
) -> dict[str, Any]:
    binding = _load_json(
        path,
        reason="runtime_binding_invalid",
    )
    snapshot = _dict(pre_run_manifest.get("snapshot"))
    if (
        binding.get("schema_version")
        != "p1-runtime-knowledge-binding/v1"
        or binding.get("snapshot_file_sha256")
        != snapshot.get("file_sha256")
        or binding.get("source_tree_sha256")
        != expected_source_sha256
        or binding.get("formal_knowledge_query_only") is not True
        or binding.get("formal_evidence_convergence") is not True
        or binding.get("model_first_answer_composer") is not True
        or int(binding.get("process_id") or 0) <= 0
        or int(binding.get("runtime_port") or 0) != expected_runtime_port
    ):
        raise P1BaselineIntegrityError(
            "runtime_snapshot_binding_mismatch"
        )
    _assert_report_safe(binding)
    return binding


def _summary_payload(
    *,
    contract: DatasetContract | None = None,
    observations: list[dict[str, Any]],
    scored_rows: list[dict[str, Any]],
    deterministic_summary: dict[str, Any],
    status: str,
    integrity_stop_reason: str,
    owner_counts: Counter[str],
    formal_knowledge: dict[str, Any],
) -> dict[str, Any]:
    contract = contract or _legacy_dataset_contract()
    goal_diagnostics = [
        _dict(item.get("goal_recall_diagnostic"))
        for item in observations
    ]
    goal_contracts = {
        str(item.get("contract") or "").strip()
        for item in goal_diagnostics
        if str(item.get("contract") or "").strip()
    }
    if len(goal_contracts) > 1:
        raise P1BaselineIntegrityError("goal_recall_contract_mixed")
    goal_contract = next(iter(goal_contracts), "canonical_claim_type_and_attribute_slot/v2")
    goal_numerator = sum(
        int(
            item.get(
                "numerator"
            )
            or 0
        )
        for item in goal_diagnostics
    )
    goal_denominator = sum(
        int(
            item.get(
                "denominator"
            )
            or 0
        )
        for item in goal_diagnostics
    )
    metrics = {
        key: deepcopy(value)
        for key, value in deterministic_summary.items()
        if key in _SUMMARY_METRIC_FIELDS
    }
    raw_policy_ref_counts = _dict(
        deterministic_summary.get("policy_intent_ref_counts")
    )
    metrics["policy_intent_ref_total_count"] = int(
        deterministic_summary.get("policy_intent_ref_total_count")
        or sum(
            int(value or 0)
            for value in raw_policy_ref_counts.values()
        )
    )
    metrics["customer_goal_recall"] = {
        "contract": goal_contract,
        "numerator": goal_numerator,
        "denominator": goal_denominator,
        "rate": (
            goal_numerator / goal_denominator
            if goal_denominator else None
        ),
        "unexpected_goal_count": sum(
            int(
                item.get(
                    "unexpected_goal_count"
                )
                or 0
            )
            for item in goal_diagnostics
        ),
    }
    for metric_name in (
        "customer_goal_identity_recall",
        "explicit_request_recall",
        "dimension_subject_scope_attribution",
    ):
        metric_rows = [
            _dict(item.get(metric_name))
            for item in goal_diagnostics
            if isinstance(item.get(metric_name), dict)
        ]
        if not metric_rows:
            continue
        numerator = sum(int(item.get("numerator") or 0) for item in metric_rows)
        denominator = sum(int(item.get("denominator") or 0) for item in metric_rows)
        metrics[metric_name] = {
            "numerator": numerator,
            "denominator": denominator,
            "rate": numerator / denominator if denominator else None,
        }
    if goal_contract == "atomic_goal_identity_and_effective_scope/v4":
        metrics["unscored_expected_claim_count"] = sum(
            int(item.get("unscored_expected_claim_count") or 0)
            for item in goal_diagnostics
        )
    checkpoint_nonempty_reply_count = deterministic_summary.get(
        "nonempty_reply_count"
    )
    if not isinstance(checkpoint_nonempty_reply_count, int) or isinstance(
        checkpoint_nonempty_reply_count,
        bool,
    ):
        checkpoint_nonempty_reply_count = sum(
            bool(row.get("nonempty_reply"))
            for row in scored_rows
        )
    summary = {
        "schema_version": SCHEMA_VERSION,
        "evaluation_tier": "development_diagnostic",
        "status": status,
        "integrity_stop_reason": integrity_stop_reason,
        "real_customer_accuracy": contract.real_customer_accuracy,
        "optimization_verified": False,
        "scenario_count": contract.case_count,
        "evaluated_scenario_count": len(observations),
        "execution_success_count": sum(
            not str(row.get("error_type") or "")
            for row in scored_rows
        ),
        "nonempty_reply_count": checkpoint_nonempty_reply_count,
        "deterministic_metrics": metrics,
        "execution_error_counts": dict(sorted(Counter(
            str(row.get("error_type") or "")
            for row in scored_rows
            if str(row.get("error_type") or "")
        ).items())),
        "human_review_metrics": {
            "naturalness_distribution": {
                "accepted": 0,
                "minor_edit": 0,
                "major_edit": 0,
                "unacceptable": 0,
                "pending_supervisor": len(observations),
            },
            "commercial_helpfulness": {
                "numerator": 0,
                "denominator": 0,
                "rate": None,
                "status": "pending_supervisor",
            },
            "bounded_inference_opportunity_review": {
                "numerator": 0,
                "denominator": 0,
                "rate": None,
                "status": "pending_supervisor",
            },
        },
        "earliest_owner_suggestions": dict(sorted(owner_counts.items())),
        "formal_knowledge": formal_knowledge,
    }
    summary.update(_contract_report_fields(contract))
    return summary


def _dml_count_from_offset(path: Path, offset: int) -> int:
    if not path.is_file():
        return 0
    with path.open("rb") as handle:
        handle.seek(max(0, int(offset)))
        return sum(
            1 for line in handle if line.strip()
        )


def _load_checkpoint_cases(
    *,
    output_dir: Path,
    checkpoint: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    observations = []
    files = []
    for metadata in _dicts(
        checkpoint.get("completed_case_files")
    ):
        relative = str(metadata.get("path") or "")
        path = (output_dir / relative).resolve()
        if (
            output_dir not in path.parents
            or not path.is_file()
            or _sha256_file(path)
            != str(metadata.get("sha256") or "")
        ):
            raise P1BaselineIntegrityError(
                "checkpoint_case_hash_invalid"
            )
        observation = _load_json(
            path,
            reason="checkpoint_case_json_invalid",
        )
        _assert_report_safe(observation)
        observations.append(observation)
        files.append({
            "path": relative,
            "sha256": str(metadata.get("sha256") or ""),
            "byte_count": int(metadata.get("byte_count") or 0),
        })
    if len(observations) != int(
        checkpoint.get("completed_case_count") or 0
    ):
        raise P1BaselineIntegrityError(
            "checkpoint_case_count_mismatch"
        )
    aliases = [
        str(item.get("case_alias") or "")
        for item in observations
    ]
    if (
        not all(aliases)
        or len(aliases) != len(set(aliases))
    ):
        raise P1BaselineIntegrityError(
            "checkpoint_case_alias_invalid"
        )
    return observations, files


def _load_checkpoint_capsules(
    *,
    output_dir: Path,
    checkpoint: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    capsules = []
    files = []
    for metadata in _dicts(
        checkpoint.get("projection_capsule_files")
    ):
        relative = str(metadata.get("path") or "")
        path = (output_dir / relative).resolve()
        if (
            output_dir not in path.parents
            or not path.is_file()
            or _sha256_file(path)
            != str(metadata.get("sha256") or "")
        ):
            raise P1BaselineIntegrityError(
                "checkpoint_projection_capsule_hash_invalid"
            )
        capsule = _load_json(
            path,
            reason="checkpoint_projection_capsule_json_invalid",
        )
        _assert_report_safe(capsule)
        if (
            capsule.get("schema_version")
            != "projection-failure-capsule/v1"
            or capsule.get("projection_status")
            not in {"completed", "projection_failed"}
            or capsule.get("used_for_scoring") is not False
            or capsule.get("used_for_agent_input") is not False
            or capsule.get("can_change_can_send") is not False
            or capsule.get("authoritative_business_result") is not False
        ):
            raise P1BaselineIntegrityError(
                "checkpoint_projection_capsule_contract_invalid"
            )
        capsules.append(capsule)
        files.append({
            "path": relative,
            "sha256": str(metadata.get("sha256") or ""),
            "byte_count": int(metadata.get("byte_count") or 0),
        })
    if len(capsules) != int(
        checkpoint.get("projection_capsule_count") or 0
    ):
        raise P1BaselineIntegrityError(
            "checkpoint_projection_capsule_count_mismatch"
        )
    aliases = [
        str(item.get("case_uid_alias") or "")
        for item in capsules
    ]
    if (
        not all(aliases)
        or len(aliases) != len(set(aliases))
    ):
        raise P1BaselineIntegrityError(
            "checkpoint_projection_capsule_alias_invalid"
        )
    return capsules, files


def _expert_review_metrics(
    review: dict[str, Any] | None,
) -> dict[str, Any]:
    if not review:
        return {
            "review_type": "codex_expert_offline_review",
            "status": "not_generated",
            "supervisor_approved": False,
        }
    items = _dicts(review.get("items"))
    score_fields = (
        "factual_correctness",
        "goal_completion",
        "naturalness",
        "empathy_politeness",
        "business_helpfulness",
        "bounded_common_sense_reasoning",
    )
    averages = {
        field: (
            sum(int(item[field]) for item in items) / len(items)
            if items else None
        )
        for field in score_fields
    }
    return {
        "review_type": "codex_expert_offline_review",
        "status": "completed",
        "supervisor_approved": False,
        "case_count": len(items),
        "average_scores": averages,
        "naturalness_acceptance": {
            "numerator": sum(
                int(item.get("naturalness") or 0) >= 1
                for item in items
            ),
            "denominator": len(items),
            "rate": (
                sum(
                    int(item.get("naturalness") or 0) >= 1
                    for item in items
                )
                / len(items)
                if items else None
            ),
        },
        "handoff_necessity_counts": dict(sorted(Counter(
            str(item.get("handoff_necessity") or "")
            for item in items
        ).items())),
        "reason_code_counts": dict(sorted(Counter(
            str(reason)
            for item in items
            for reason in item.get("reason_codes") or []
        ).items())),
        "selected_next_owner": str(
            review.get("selected_next_owner") or ""
        ),
        "selection_rationale": str(
            review.get("selection_rationale") or ""
        ),
    }


def _finalize_from_checkpoint(
    *,
    contract: DatasetContract | None = None,
    output_dir: Path,
    snapshot_path: Path,
    pre_run_manifest_path: Path,
    dml_path: Path,
    hmac_key: str,
    expert_review_path: Path | None = None,
) -> dict[str, Any]:
    contract = contract or _legacy_dataset_contract()
    checkpoint_path = output_dir / "checkpoint.json"
    checkpoint = _load_json(
        checkpoint_path,
        reason="checkpoint_json_invalid",
    )
    pre_run_manifest = _load_json(
        pre_run_manifest_path,
        reason="pre_run_manifest_invalid",
    )
    if (
        checkpoint.get("dataset_sha256")
        != contract.dataset_sha256
        or pre_run_manifest.get("dataset_sha256")
        != contract.dataset_sha256
        or checkpoint.get("dataset_contract")
        != contract.contract_name
        or pre_run_manifest.get("dataset_contract")
        != contract.contract_name
    ):
        raise P1BaselineIntegrityError(
            "finalization_dataset_identity_mismatch"
        )
    if (
        str(checkpoint.get("pre_run_manifest_sha256") or "")
        != _sha256_file(pre_run_manifest_path)
    ):
        raise P1BaselineIntegrityError(
            "pre_run_manifest_hash_mismatch"
        )
    if (
        str(checkpoint.get("runner_source_sha256") or "")
        != _runner_source_sha256()
        or str(checkpoint.get("evaluator_source_sha256") or "")
        != _evaluator_source_sha256()
    ):
        raise P1BaselineIntegrityError(
            "finalization_source_identity_mismatch"
        )
    observations, case_files = _load_checkpoint_cases(
        output_dir=output_dir,
        checkpoint=checkpoint,
    )
    _validate_reconstructed_delivery_boundary(
        observations,
        contract=contract,
    )
    capsules, capsule_files = _load_checkpoint_capsules(
        output_dir=output_dir,
        checkpoint=checkpoint,
    )
    dml_count = _dml_count_from_offset(
        dml_path,
        int(checkpoint.get("dml_start_offset") or 0),
    )
    post_run_manifest = _build_post_run_manifest(
        pre_run_manifest=pre_run_manifest,
        snapshot_path=snapshot_path,
        hmac_key=hmac_key,
        dml_attempt_count=dml_count,
    )
    post_meta = _write_json(
        output_dir / "post_run_manifest.json",
        post_run_manifest,
    )
    post_meta["path"] = "post_run_manifest.json"

    expected_aliases = {
        str(item.get("case_alias") or "")
        for item in observations
    }
    expert_review = (
        _load_expert_review(
            expert_review_path,
            expected_case_aliases=expected_aliases,
        )
        if expert_review_path else None
    )
    integrity_stop_reason = str(
        checkpoint.get("integrity_stop_reason") or ""
    )
    if not post_run_manifest.get("snapshot_unchanged"):
        integrity_stop_reason = (
            integrity_stop_reason
            or "formal_knowledge_snapshot_changed"
        )
    if dml_count:
        integrity_stop_reason = (
            integrity_stop_reason
            or "formal_knowledge_dml_detected"
        )
    if integrity_stop_reason:
        status = "integrity_blocked"
    elif (
        len(observations) != contract.case_count
        or len(capsules) != contract.case_count
        or any(
            item.get("projection_status") != "completed"
            for item in capsules
        )
    ):
        status = "incomplete_execution"
    elif expert_review is None:
        status = "awaiting_codex_expert_review"
    else:
        status = "baseline_completed"

    deterministic_summary = _dict(
        checkpoint.get("deterministic_summary")
    )
    formal_knowledge = {
        "before": _dict(
            _dict(pre_run_manifest.get("snapshot")).get(
                "formal_knowledge"
            )
        ),
        "after": _dict(
            post_run_manifest.get("formal_knowledge")
        ),
        "changed": not bool(
            post_run_manifest.get("snapshot_unchanged")
        ),
        "changed_row_count": int(
            post_run_manifest.get("changed_row_count") or 0
        ),
        "dml_attempt_count": dml_count,
    }
    owner_counts = Counter(
        _earliest_owner_suggestion(item)
        for item in observations
    )
    summary = _summary_payload(
        contract=contract,
        observations=observations,
        scored_rows=[
            {"error_type": str(item.get("error_type") or "")}
            for item in observations
        ],
        deterministic_summary=deterministic_summary,
        status=status,
        integrity_stop_reason=integrity_stop_reason,
        owner_counts=owner_counts,
        formal_knowledge=formal_knowledge,
    )
    summary["codex_expert_offline_review"] = (
        _expert_review_metrics(expert_review)
    )
    summary["next_owner"] = (
        str(expert_review.get("selected_next_owner") or "")
        if expert_review else ""
    )
    summary["projection_capsule_count"] = len(capsules)
    summary["projection_capsule_status_counts"] = dict(sorted(
        Counter(
            str(item.get("projection_status") or "")
            for item in capsules
        ).items()
    ))
    summary["unsupported_high_risk_cases"] = [
        {
            "case_alias": str(item.get("case_alias") or ""),
            "final_audit_issues": _dict(
                item.get("deterministic_final")
            ).get("issues") or [],
            "unified_audit_issues": _dict(
                item.get("unified_audit")
            ).get("issues") or [],
        }
        for item in observations
        if _dict(item.get("deterministic_score")).get(
            "unsupported_high_risk_claim"
        )
    ]
    summary_meta = _write_json(
        output_dir / "summary.json",
        summary,
    )
    summary_meta["path"] = "summary.json"

    review_items = []
    expert_by_alias = {
        str(item.get("case_alias") or ""): item
        for item in _dicts(
            (expert_review or {}).get("items")
        )
    }
    for observation in observations:
        item = build_review_item({}, observation)
        item["codex_expert_review"] = deepcopy(
            expert_by_alias.get(
                str(observation.get("case_alias") or "")
            )
        )
        review_items.append(item)
    review_pack = {
        "schema_version": "p1-gold-service-review-pack/v2",
        "dataset_id": contract.dataset_id,
        "dataset_version": contract.dataset_version,
        "dataset_sha256": contract.dataset_sha256,
        "review_type": "codex_expert_offline_review",
        "review_status": (
            "completed" if expert_review else "pending_codex_review"
        ),
        "supervisor_approved": False,
        "reference_answers_used_by_agent": False,
        "items": sorted(
            review_items,
            key=lambda item: str(item.get("case_alias") or ""),
        ),
    }
    review_pack.update(_contract_report_fields(contract))
    review_meta = _write_json(
        output_dir / "review_pack.json",
        review_pack,
    )
    review_meta["path"] = "review_pack.json"

    pre_meta = {
        "path": "pre_run_manifest.json",
        "sha256": _sha256_file(pre_run_manifest_path),
        "byte_count": pre_run_manifest_path.stat().st_size,
    }
    manifest_files = sorted(
        [
            pre_meta,
            post_meta,
            summary_meta,
            review_meta,
            *case_files,
            *capsule_files,
        ],
        key=lambda item: str(item.get("path") or ""),
    )
    runtime = {
        "runtime_commit": checkpoint.get("runtime_commit"),
        "source_tree_sha256": checkpoint.get(
            "source_tree_sha256"
        ),
        "formal_provider_identity": _dict(
            pre_run_manifest.get("provider")
        ),
        "feature_flags": deepcopy(
            pre_run_manifest.get("feature_flags")
        ),
        "formal_knowledge_query_only": True,
    }
    manifest = {
        "schema_version": "p1-gold-conversation-manifest/v3",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": status,
        "evaluation_tier": "development_diagnostic",
        "real_customer_accuracy": contract.real_customer_accuracy,
        "dataset": {
            "dataset_id": contract.dataset_id,
            "dataset_version": contract.dataset_version,
            "scenario_count": contract.case_count,
            "history_turn_count": contract.history_turn_count,
            "content_sha256": contract.dataset_sha256,
            "source_manifest_file_sha256": (
                contract.manifest_file_sha256
            ),
            "dataset_contract": contract.contract_name,
            "source_class": contract.source_class,
        },
        "runtime": runtime,
        "runner": {
            "runner_source_sha256": checkpoint.get(
                "runner_source_sha256"
            ),
            "evaluator_source_sha256": checkpoint.get(
                "evaluator_source_sha256"
            ),
            "source_tree_drift": False,
        },
        "knowledge_snapshot": {
            "pre_run_manifest_sha256": _sha256_file(
                pre_run_manifest_path
            ),
            "post_run_manifest_sha256": post_meta["sha256"],
            "snapshot_unchanged": post_run_manifest.get(
                "snapshot_unchanged"
            ),
            "changed_row_count": post_run_manifest.get(
                "changed_row_count"
            ),
            "dml_attempt_count": dml_count,
        },
        "integrity_stop_reason": integrity_stop_reason,
        "files": manifest_files,
        "next_owner": summary.get("next_owner"),
    }
    manifest.update(_contract_report_fields(contract))
    manifest["manifest_content_sha256"] = _canonical_hash(
        manifest
    )
    manifest_meta = _write_json(
        output_dir / "manifest.json",
        manifest,
    )
    manifest_meta["path"] = "manifest.json"

    file_hash_manifest = {
        "schema_version": "p1-file-hash-manifest/v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "files": sorted(
            [*manifest_files, manifest_meta],
            key=lambda item: str(item.get("path") or ""),
        ),
    }
    _write_json(
        output_dir / "file_hash_manifest.json",
        file_hash_manifest,
    )
    if status == "baseline_completed":
        checkpoint_path.unlink(missing_ok=True)
    return {
        "status": status,
        "evaluated_scenario_count": len(observations),
        "integrity_stop_reason": integrity_stop_reason,
        "post_run_manifest": post_run_manifest,
        "summary": summary,
    }


def _load_safe_environment(env_file: str) -> None:
    if not env_file:
        return
    env_path = Path(env_file).expanduser()
    if not env_path.is_file():
        raise P1BaselineIntegrityError(
            "safe_provider_configuration_missing"
        )
    load_dotenv(env_path, override=True)


def prepare(args: argparse.Namespace) -> int:
    _load_safe_environment(args.env_file)
    required = {
        "dataset": args.dataset,
        "dataset_manifest": args.dataset_manifest,
        "output_dir": args.output_dir,
        "source_knowledge_db": args.source_knowledge_db,
        "snapshot_db": args.snapshot_db,
        "dml_diagnostics": args.dml_diagnostics,
    }
    missing = sorted(
        key for key, value in required.items() if not value
    )
    if missing:
        raise P1BaselineIntegrityError(
            "prepare_argument_missing:" + ",".join(missing)
        )
    output_dir = Path(args.output_dir).expanduser().resolve()
    if output_dir.exists() and any(output_dir.iterdir()):
        raise P1BaselineIntegrityError(
            "baseline_output_directory_not_empty"
        )
    output_dir.mkdir(parents=True, exist_ok=True)
    contract = _resolve_dataset_contract(args.dataset_contract)
    dataset, _inventory, _manifest = _preflight_dataset(
        Path(args.dataset),
        Path(args.dataset_manifest),
        contract=contract,
    )
    if not _dicts(dataset.get("scenarios")):
        raise P1BaselineIntegrityError("dataset_scenarios_missing")
    source_path = Path(
        args.source_knowledge_db
    ).expanduser().resolve()
    snapshot_path = Path(args.snapshot_db).expanduser().resolve()
    if not source_path.is_file():
        raise P1BaselineIntegrityError(
            "formal_knowledge_source_missing"
        )
    hmac_key = str(
        os.environ.get("COPILOT_P1_BASELINE_HMAC_KEY")
        or os.environ.get("COPILOT_FORMAL_KB_AUDIT_HMAC_KEY")
        or os.environ.get("COPILOT_GOLD_SET_HMAC_KEY")
        or ""
    )
    from app.services.strict_decision_provider_service import (
        safe_provider_identity,
    )

    provider = safe_provider_identity(
        provider_name="formal_agent",
        api_base=os.environ.get("COPILOT_LLM_API_BASE", ""),
        model=os.environ.get("COPILOT_LLM_MODEL", ""),
    )
    provider = _provider_projection(provider)
    if not provider.get("configured"):
        raise P1BaselineIntegrityError(
            "formal_provider_identity_unconfigured"
        )
    git = _git_identity()
    dml_path = Path(
        args.dml_diagnostics
    ).expanduser().resolve()
    manifest = _prepare_knowledge_snapshot(
        source_path=source_path,
        snapshot_path=snapshot_path,
        hmac_key=hmac_key,
        dataset_sha256=contract.dataset_sha256,
        source_manifest_file_sha256=(
            contract.manifest_file_sha256
        ),
        runner_source_sha256=_runner_source_sha256(),
        evaluator_source_sha256=_evaluator_source_sha256(),
        source_tree_sha256=_runtime_source_tree_sha256(),
        git_head=git["head"],
        git_dirty=git["worktree_dirty"],
        provider_identity=provider,
        feature_flags={
            "formal_evidence_convergence": True,
            "model_first_answer_composer": True,
            "answer_memory_shadow": False,
            "grounded_reasoning_shadow": False,
            "llm_decision_shadow": False,
            "evidence_action_shadow": False,
        },
        dml_start_offset=(
            dml_path.stat().st_size if dml_path.is_file() else 0
        ),
        contract=contract,
        dataset=dataset,
    )
    metadata = _write_json(
        output_dir / "pre_run_manifest.json",
        manifest,
    )
    _load_json(
        output_dir / "pre_run_manifest.json",
        reason="pre_run_manifest_roundtrip_failed",
    )
    print(json.dumps({
        "status": "pre_run_snapshot_ready",
        "dataset_sha256": contract.dataset_sha256,
        **_contract_report_fields(contract),
        "runner_source_sha256": manifest[
            "runner_source_sha256"
        ],
        "evaluator_source_sha256": manifest[
            "evaluator_source_sha256"
        ],
        "source_tree_sha256": manifest["source_tree_sha256"],
        "snapshot_file_sha256": manifest["snapshot"][
            "file_sha256"
        ],
        "pre_run_manifest_sha256": metadata["sha256"],
        "provider": provider,
        "query_only_verified": True,
    }, ensure_ascii=False))
    return 0


def offline_reconstruct(args: argparse.Namespace) -> int:
    if not args.offline_baseline_dir:
        raise P1BaselineIntegrityError(
            "offline_baseline_dir_required"
        )
    result = assess_offline_reconstruction(
        args.offline_baseline_dir
    )
    if args.json_output:
        _write_json(
            Path(args.json_output).expanduser().resolve(),
            result,
        )
    print(json.dumps(result, ensure_ascii=False))
    return 0


def finalize(args: argparse.Namespace) -> int:
    _load_safe_environment(args.env_file)
    required = {
        "output_dir": args.output_dir,
        "snapshot_db": args.snapshot_db,
        "pre_run_manifest": args.pre_run_manifest,
        "dml_diagnostics": args.dml_diagnostics,
    }
    missing = sorted(
        key for key, value in required.items() if not value
    )
    if missing:
        raise P1BaselineIntegrityError(
            "finalize_argument_missing:" + ",".join(missing)
        )
    hmac_key = str(
        os.environ.get("COPILOT_P1_BASELINE_HMAC_KEY")
        or os.environ.get("COPILOT_FORMAL_KB_AUDIT_HMAC_KEY")
        or os.environ.get("COPILOT_GOLD_SET_HMAC_KEY")
        or ""
    )
    if not hmac_key:
        raise P1BaselineIntegrityError(
            "formal_kb_audit_hmac_key_required"
        )
    contract = _resolve_dataset_contract(args.dataset_contract)
    result = _finalize_from_checkpoint(
        contract=contract,
        output_dir=Path(args.output_dir).expanduser().resolve(),
        snapshot_path=Path(args.snapshot_db).expanduser().resolve(),
        pre_run_manifest_path=Path(
            args.pre_run_manifest
        ).expanduser().resolve(),
        dml_path=Path(
            args.dml_diagnostics
        ).expanduser().resolve(),
        hmac_key=hmac_key,
        expert_review_path=(
            Path(args.expert_review).expanduser().resolve()
            if args.expert_review else None
        ),
    )
    print(json.dumps({
        "status": result["status"],
        "evaluated_scenario_count": result[
            "evaluated_scenario_count"
        ],
        "integrity_stop_reason": result[
            "integrity_stop_reason"
        ],
        "snapshot_unchanged": result["post_run_manifest"][
            "snapshot_unchanged"
        ],
        "changed_row_count": result["post_run_manifest"][
            "changed_row_count"
        ],
        "dml_attempt_count": result["post_run_manifest"][
            "dml_attempt_count"
        ],
    }, ensure_ascii=False))
    return 0 if result["status"] == "baseline_completed" else 2


def run(args: argparse.Namespace) -> int:
    _load_safe_environment(args.env_file)

    from scripts import compare_model_first_answer_composer as evaluator

    required = {
        "dataset": args.dataset,
        "dataset_manifest": args.dataset_manifest,
        "analyze_url": args.analyze_url,
        "output_dir": args.output_dir,
        "expected_commit": args.expected_commit,
        "expected_source_sha256": args.expected_source_sha256,
        "snapshot_db": args.snapshot_db,
        "pre_run_manifest": args.pre_run_manifest,
        "runtime_binding": args.runtime_binding,
        "dml_diagnostics": args.dml_diagnostics,
    }
    missing = sorted(
        key for key, value in required.items() if not value
    )
    if missing:
        raise P1BaselineIntegrityError(
            "run_argument_missing:" + ",".join(missing)
        )
    hmac_key = str(
        os.environ.get("COPILOT_P1_BASELINE_HMAC_KEY")
        or os.environ.get("COPILOT_FORMAL_KB_AUDIT_HMAC_KEY")
        or os.environ.get("COPILOT_GOLD_SET_HMAC_KEY")
        or ""
    )
    if not hmac_key:
        raise P1BaselineIntegrityError(
            "formal_kb_audit_hmac_key_required"
        )
    runner_source_sha256 = _runner_source_sha256()
    evaluator_source_sha256 = _evaluator_source_sha256()
    output_dir = Path(args.output_dir).expanduser().resolve()
    cases_dir = output_dir / "cases"
    capsules_dir = output_dir / "projection_capsules"
    output_dir.mkdir(parents=True, exist_ok=True)
    if (output_dir / "checkpoint.json").exists() or (
        cases_dir.exists() and any(cases_dir.iterdir())
    ) or (
        capsules_dir.exists() and any(capsules_dir.iterdir())
    ):
        raise P1BaselineIntegrityError(
            "fresh_agent_run_required"
        )
    contract = _resolve_dataset_contract(args.dataset_contract)
    dataset, _inventory, _source_manifest = _preflight_dataset(
        Path(args.dataset),
        Path(args.dataset_manifest),
        contract=contract,
    )
    pre_run_manifest_path = Path(
        args.pre_run_manifest
    ).expanduser().resolve()
    pre_run_manifest = _load_json(
        pre_run_manifest_path,
        reason="pre_run_manifest_invalid",
    )
    snapshot_path = Path(args.snapshot_db).expanduser().resolve()
    if (
        pre_run_manifest.get("dataset_sha256")
        != contract.dataset_sha256
        or pre_run_manifest.get("dataset_contract")
        != contract.contract_name
        or pre_run_manifest.get("source_class")
        != contract.source_class
        or pre_run_manifest.get("runner_source_sha256")
        != runner_source_sha256
        or pre_run_manifest.get("evaluator_source_sha256")
        != evaluator_source_sha256
        or pre_run_manifest.get("source_tree_sha256")
        != _runtime_source_tree_sha256()
        or _dict(pre_run_manifest.get("git")).get("head")
        != args.expected_commit
        or _dict(pre_run_manifest.get("snapshot")).get(
            "file_sha256"
        )
        != _sha256_file(snapshot_path)
    ):
        raise P1BaselineIntegrityError(
            "pre_run_identity_mismatch"
        )
    _validate_runtime_binding(
        Path(args.runtime_binding).expanduser().resolve(),
        pre_run_manifest=pre_run_manifest,
        expected_source_sha256=args.expected_source_sha256,
        expected_runtime_port=args.expected_runtime_port,
    )
    runtime = _runtime_preflight(
        evaluator,
        analyze_url=args.analyze_url,
        expected_commit=args.expected_commit,
        expected_source_sha256=args.expected_source_sha256,
        expected_model=args.expected_model,
    )
    if _provider_projection(
        runtime.get("formal_provider_identity")
    ) != _dict(pre_run_manifest.get("provider")):
        raise P1BaselineIntegrityError(
            "pre_run_provider_identity_mismatch"
    )
    alias_secret = secrets.token_bytes(32)
    pre_run_manifest_sha256 = _sha256_file(
        pre_run_manifest_path
    )
    run_uid_alias = _run_alias(
        dataset_sha256=contract.dataset_sha256,
        pre_run_manifest_sha256=pre_run_manifest_sha256,
        runner_source_sha256=runner_source_sha256,
        alias_secret=alias_secret,
    )
    knowledge_path = snapshot_path
    knowledge_before = evaluator._fingerprint(knowledge_path)
    if (
        _compact_snapshot_fingerprint(knowledge_before)
        != _dict(
            _dict(pre_run_manifest.get("snapshot")).get(
                "formal_knowledge"
            )
        )
    ):
        raise P1BaselineIntegrityError(
            "pre_run_snapshot_fingerprint_mismatch"
        )
    dml_path = Path(args.dml_diagnostics).expanduser().resolve()
    dml_offset = int(
        pre_run_manifest.get("dml_start_offset") or 0
    )
    observations: list[dict[str, Any]] = []
    scored_rows: list[dict[str, Any]] = []
    case_files: list[dict[str, Any]] = []
    capsule_files: list[dict[str, Any]] = []
    integrity_stop_reason = ""

    for case_index, scenario in enumerate(
        dataset.get("scenarios") or [],
        start=1,
    ):
        try:
            payload = evaluator._agent_payload(scenario)
            status_code, response, latency_ms, error_type = (
                evaluator._post_json(
                    args.analyze_url,
                    payload,
                    args.timeout,
                )
            )
            scored = evaluator._score_response(
                scenario,
                response,
                status_code=status_code,
                error_type=error_type,
                latency_ms=latency_ms,
            )
            case_uid_alias = _case_alias(
                str(scenario.get("scenario_uid") or ""),
                alias_secret,
            )
            capsule_path = (
                capsules_dir / f"{case_uid_alias}.json"
            )
            observation = _build_case_observation_with_capsule(
                output_dir=output_dir,
                capsule_path=capsule_path,
                capsule_records=capsule_files,
                run_uid_alias=run_uid_alias,
                case_uid_alias=case_uid_alias,
                case_index=case_index,
                status_code=status_code,
                scenario=scenario,
                response=response,
                scored=scored,
                alias_secret=alias_secret,
            )
            _validate_reconstructed_delivery_boundary(
                [observation],
                contract=contract,
            )
            if observation.get("case_alias") != case_uid_alias:
                raise P1BaselineIntegrityError(
                    "projection_capsule_case_alias_mismatch"
                )
            file_path = (
                cases_dir / f"{observation['case_alias']}.json"
            )
            file_meta = _write_json(file_path, observation)
            file_meta["path"] = file_path.relative_to(
                output_dir
            ).as_posix()
            case_files.append(file_meta)
            observations.append(observation)
            scored_rows.append(scored)
            _write_json(
                output_dir / "checkpoint.json",
                _checkpoint_payload(
                    contract=contract,
                    dataset_hash=contract.dataset_sha256,
                    runtime=runtime,
                    runner_source_sha256=runner_source_sha256,
                    formal_knowledge_before=(
                        _compact_snapshot_fingerprint(
                            knowledge_before
                        )
                    ),
                    dml_start_offset=dml_offset,
                    completed_files=case_files,
                    capsule_files=capsule_files,
                    evaluator_source_sha256=(
                        evaluator_source_sha256
                    ),
                    pre_run_manifest_sha256=(
                        pre_run_manifest_sha256
                    ),
                    snapshot_file_sha256=_sha256_file(
                        snapshot_path
                    ),
                    deterministic_summary=evaluator._summarize(
                        scored_rows
                    ),
                ),
            )
            if evaluator._dml_count(dml_path, dml_offset):
                raise P1BaselineIntegrityError(
                    "formal_knowledge_dml_detected"
                )
            current_runtime = _runtime_preflight(
                evaluator,
                analyze_url=args.analyze_url,
                expected_commit=args.expected_commit,
                expected_source_sha256=args.expected_source_sha256,
                expected_model=args.expected_model,
            )
            if (
                current_runtime.get("source_tree_sha256")
                != runtime.get("source_tree_sha256")
            ):
                raise P1BaselineIntegrityError(
                    "runtime_source_drift"
                )
        except P1BaselineIntegrityError as exc:
            integrity_stop_reason = str(exc)
            break
        except Exception as exc:
            integrity_stop_reason = (
                f"report_integrity_error:{type(exc).__name__}"
            )
            break

    try:
        _preflight_dataset(
            Path(args.dataset),
            Path(args.dataset_manifest),
            contract=contract,
        )
    except Exception as exc:
        if not integrity_stop_reason:
            integrity_stop_reason = (
                f"dataset_end_validation_failed:{type(exc).__name__}"
            )
    if (
        _runner_source_sha256() != runner_source_sha256
        or _evaluator_source_sha256() != evaluator_source_sha256
    ) and not integrity_stop_reason:
        integrity_stop_reason = "runner_source_drift"
    deterministic_summary = evaluator._summarize(scored_rows)
    checkpoint = _checkpoint_payload(
        contract=contract,
        dataset_hash=contract.dataset_sha256,
        runtime=runtime,
        runner_source_sha256=runner_source_sha256,
        formal_knowledge_before=_compact_snapshot_fingerprint(
            knowledge_before
        ),
        dml_start_offset=dml_offset,
        completed_files=case_files,
        capsule_files=capsule_files,
        evaluator_source_sha256=evaluator_source_sha256,
        pre_run_manifest_sha256=pre_run_manifest_sha256,
        snapshot_file_sha256=_sha256_file(snapshot_path),
        deterministic_summary=deterministic_summary,
        integrity_stop_reason=integrity_stop_reason,
    )
    _write_json(output_dir / "checkpoint.json", checkpoint)
    result = _finalize_from_checkpoint(
        contract=contract,
        output_dir=output_dir,
        snapshot_path=snapshot_path,
        pre_run_manifest_path=pre_run_manifest_path,
        dml_path=dml_path,
        hmac_key=hmac_key,
    )
    print(json.dumps({
        "status": result["status"],
        "evaluated_scenario_count": result[
            "evaluated_scenario_count"
        ],
        "integrity_stop_reason": result[
            "integrity_stop_reason"
        ],
        "agent_run_complete": (
            len(observations) == contract.case_count
        ),
        **_contract_report_fields(contract),
        "next_step": (
            "offline_codex_expert_review"
            if result["status"]
            == "awaiting_codex_expert_review"
            else "stop"
        ),
    }, ensure_ascii=False))
    return (
        0
        if result["status"] == "awaiting_codex_expert_review"
        else 2
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--operation",
        choices=("prepare", "run", "finalize", "offline-reconstruct"),
        default="run",
    )
    parser.add_argument("--dataset")
    parser.add_argument("--dataset-manifest")
    parser.add_argument(
        "--dataset-contract",
        default="legacy-real-derived-v4",
    )
    parser.add_argument("--analyze-url")
    parser.add_argument("--output-dir")
    parser.add_argument("--expected-commit")
    parser.add_argument("--expected-source-sha256")
    parser.add_argument("--expected-model", default="MiniMax-M3")
    parser.add_argument("--source-knowledge-db")
    parser.add_argument("--snapshot-db")
    parser.add_argument("--pre-run-manifest")
    parser.add_argument("--runtime-binding")
    parser.add_argument("--expected-runtime-port", type=int, default=5013)
    parser.add_argument("--dml-diagnostics")
    parser.add_argument("--env-file")
    parser.add_argument("--expert-review")
    parser.add_argument("--offline-baseline-dir")
    parser.add_argument("--json-output")
    parser.add_argument("--timeout", type=int, default=180)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.operation == "prepare":
        return prepare(args)
    if args.operation == "offline-reconstruct":
        return offline_reconstruct(args)
    if args.operation == "finalize":
        return finalize(args)
    return run(args)


if __name__ == "__main__":
    raise SystemExit(main())
