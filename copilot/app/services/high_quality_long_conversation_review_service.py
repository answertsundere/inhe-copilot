"""Fail-closed validation for the manually reviewed long-conversation set."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import re
import sqlite3
import uuid
from collections import Counter
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.services.long_conversation_simulation_service import _content_hash
from app.services.real_accuracy_privacy_service import scan_privacy_output


SCHEMA_VERSION = "high-quality-long-conversation-review/v1"
_APPROVAL_ROLES = {"supervisor", "admin"}
_HEX_HASH_RE = re.compile(r"^[a-f0-9]{64}$")
_SCOPED_UID_RE = re.compile(r"^[a-z][a-z0-9-]*-[a-f0-9]{20}$")
_PRIVACY_CONTROLLED_FIELDS = {
    "content_sha256", "provenance_hash", "scenario_uid", "turn_uid",
    "claim_uid", "evidence_uid", "evidence_uids", "source_case_uid", "source_linkage_fingerprint",
    "source_conversation_digest", "target_turn_uids",
}


class HighQualityReviewDatasetError(ValueError):
    pass


class HighQualityReviewLabelError(ValueError):
    pass


class HighQualityReviewConflictError(ValueError):
    pass


class HighQualityReviewProjectionError(ValueError):
    pass


_LABEL_STATUSES = {"draft", "reviewed", "approved", "rejected"}
_AUTHORITATIVE_AUTH_TYPE = "cloudflare_access"
_TURN_UNDERSTANDING_SCHEMA = "turn-understanding/v2"
_TURN_UNDERSTANDING_OWNER = "turn_understanding_owner"
_TURN_UNDERSTANDING_STAGE = "query_fact_type_classifier"
_PIPELINE_VERSION = "analysis-pipeline-v1"


def load_and_validate_review_dataset(path: str | Path) -> tuple[dict[str, Any], dict[str, Any]]:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise HighQualityReviewDatasetError(f"review_dataset_unreadable:{type(exc).__name__}") from exc
    return payload, validate_review_dataset(payload)


def validate_review_dataset(payload: dict[str, Any]) -> dict[str, Any]:
    findings: list[str] = []
    if not isinstance(payload, dict):
        raise HighQualityReviewDatasetError("review_dataset_object_required")
    if str(payload.get("schema_version") or "") != SCHEMA_VERSION:
        findings.append("schema_version_mismatch")
    scenarios = payload.get("scenarios")
    if not isinstance(scenarios, list) or not scenarios:
        findings.append("scenarios_missing")
        scenarios = []
    manifest = payload.get("manifest") if isinstance(payload.get("manifest"), dict) else {}
    if int(manifest.get("scenario_count") or 0) != len(scenarios):
        findings.append("scenario_count_mismatch")
    expected_hash = str(manifest.get("content_sha256") or "")
    hash_payload = deepcopy(payload)
    hash_payload.setdefault("manifest", {}).pop("content_sha256", None)
    computed_hash = _content_hash(hash_payload)
    if not expected_hash or expected_hash != computed_hash:
        findings.append("content_sha256_mismatch")

    seen: set[str] = set()
    mojibake_fields: list[dict[str, str]] = []
    review_counts: Counter[str] = Counter()
    embedded_authoritative_review_count = 0
    for index, scenario in enumerate(scenarios):
        if not isinstance(scenario, dict):
            findings.append("scenario_object_required")
            continue
        uid = str(scenario.get("scenario_uid") or "").strip()
        if not uid or uid in seen or not _SCOPED_UID_RE.fullmatch(uid):
            findings.append("scenario_uid_missing_or_duplicate")
        seen.add(uid)
        row = deepcopy(scenario)
        row_hash = str(row.pop("content_sha256", "") or "")
        if not row_hash or row_hash != _content_hash(row):
            findings.append(f"scenario_content_sha256_mismatch:{index}")
        for field in ("scenario_title", "business_domain", "current_buyer_message", "gold_reply"):
            value = str(scenario.get(field) or "")
            if "\ufffd" in value:
                mojibake_fields.append({"scenario_uid": uid, "field": field})
        review = scenario.get("review") if isinstance(scenario.get("review"), dict) else {}
        status = str(review.get("status") or "draft").strip()
        review_counts[status] += 1
        if _contains_embedded_authoritative_review(review):
            embedded_authoritative_review_count += 1

    structured_identifier_findings = _validate_structured_identifiers(payload)
    findings.extend(structured_identifier_findings)
    privacy_findings = scan_privacy_output(_privacy_projection(payload))
    if privacy_findings:
        findings.append("privacy_scan_failed")
    if mojibake_fields:
        findings.append("mojibake_customer_content")
    manifest_approved = int(manifest.get("approved_scenario_count") or 0)
    if embedded_authoritative_review_count or manifest_approved:
        findings.append("embedded_authoritative_review_forbidden")

    structurally_valid = not findings
    return {
        "schema_version": SCHEMA_VERSION,
        "dataset_id": str(payload.get("dataset_id") or ""),
        "dataset_version": str(payload.get("dataset_version") or ""),
        "scenario_count": len(scenarios),
        "computed_content_sha256": computed_hash,
        "declared_content_sha256": expected_hash,
        "privacy_finding_count": len(privacy_findings),
        "structured_identifier_finding_count": len(structured_identifier_findings),
        "mojibake_field_count": len(mojibake_fields),
        "mojibake_fields": mojibake_fields,
        "embedded_review_status_counts": dict(sorted(review_counts.items())),
        "embedded_authoritative_review_count": embedded_authoritative_review_count,
        "findings": sorted(set(findings)),
        "validation_status": "passed" if structurally_valid else "failed",
        "evaluation_status": "awaiting_supervisor_approval" if structurally_valid else "invalid_dataset",
        "accuracy_claim_allowed": False,
        "agent_call_allowed": False,
        "exit_code": 2,
    }


def build_review_inventory(payload: dict[str, Any]) -> dict[str, Any]:
    validation = validate_review_dataset(payload)
    scenarios = payload.get("scenarios") or []
    current_turns = 0
    history_turns = 0
    expected_claims = 0
    target_missing: list[str] = []
    for scenario in scenarios:
        current_message = str((scenario or {}).get("current_buyer_message") or "").strip()
        if current_message:
            current_turns += 1
        else:
            target_missing.append(str((scenario or {}).get("scenario_uid") or ""))
        history_turns += len((scenario or {}).get("conversation_history") or [])
        expected_claims += len((scenario or {}).get("expected_claims") or [])
    return {
        "schema_version": validation["schema_version"],
        "dataset_id": validation["dataset_id"],
        "dataset_version": validation["dataset_version"],
        "dataset_sha256": validation["computed_content_sha256"],
        "scenario_count": validation["scenario_count"],
        "unique_scenario_uid_count": len({str(item.get("scenario_uid") or "") for item in scenarios}),
        "current_buyer_turn_count": current_turns,
        "conversation_history_turn_count": history_turns,
        "expected_claim_count": expected_claims,
        "target_missing_count": len(target_missing),
        "target_missing_scenario_uids": sorted(target_missing),
        "privacy_finding_count": validation["privacy_finding_count"],
        "validation_status": validation["validation_status"],
        "source_mutated": False,
    }


def project_trusted_goal_references(
    response: dict[str, Any],
    *,
    customer_message: str,
    conversation_history: list[dict[str, Any]] | None = None,
    alias_secret: bytes | str,
) -> dict[str, Any]:
    """Validate server-owned goal identity before emitting report-safe aliases."""
    from app.services.claim_resolution_service import _claim_uid
    from app.services.semantic_fact_type_service import (
        _validate_canonical_customer_goals,
    )
    from app.services.canonical_conversation_turn_service import (
        canonical_current_customer_turn_uid,
        normalize_conversation_turns,
    )

    if not isinstance(response, dict):
        raise HighQualityReviewProjectionError("pipeline_response_object_required")
    secret = (
        alias_secret.encode("utf-8")
        if isinstance(alias_secret, str)
        else alias_secret
    )
    if not isinstance(secret, bytes) or not secret:
        raise HighQualityReviewProjectionError("alias_secret_required")

    pipeline = response.get("analysis_pipeline")
    if not isinstance(pipeline, dict) or pipeline.get("version") != _PIPELINE_VERSION:
        raise HighQualityReviewProjectionError("trusted_pipeline_result_required")
    stage_status = {
        str(item.get("stage") or ""): str(item.get("status") or "")
        for item in pipeline.get("stages") or []
        if isinstance(item, dict)
    }
    if any(
        stage_status.get(stage) != "completed"
        for stage in ("canonical_input", "graph_execution")
    ):
        raise HighQualityReviewProjectionError("trusted_pipeline_stage_required")

    understanding = _response_turn_understanding(response)
    if (
        understanding.get("schema_version") != _TURN_UNDERSTANDING_SCHEMA
        or understanding.get("owner") != _TURN_UNDERSTANDING_OWNER
        or understanding.get("source_stage") != _TURN_UNDERSTANDING_STAGE
    ):
        raise HighQualityReviewProjectionError("turn_understanding_owner_invalid")
    understanding_status = str(
        understanding.get("goal_understanding_status") or ""
    ).strip().lower()
    if understanding_status not in {"valid", "degraded", "invalid"}:
        raise HighQualityReviewProjectionError(
            "turn_understanding_status_invalid"
        )

    message = str(customer_message or "")
    canonical_history, _history_diagnostics = normalize_conversation_turns(
        conversation_history,
        strict=False,
    )
    source_turn_uid = canonical_current_customer_turn_uid(
        message,
        conversation_history=canonical_history,
    )
    goals = understanding.get("customer_goals")
    goals = goals if isinstance(goals, list) else []
    if understanding_status != "valid":
        if goals:
            raise HighQualityReviewProjectionError(
                "non_authoritative_goal_references_present"
            )
        return {
            "schema_version": "trusted-control-reference-projection/v1",
            "status": "not_authoritative",
            "reason_code": f"goal_understanding_{understanding_status}",
            "goal_understanding_status": understanding_status,
            "goal_count": 0,
            "resolution_count": 0,
            "clause_count": 0,
            "goals": [],
            "resolutions": [],
            "composer_clauses": [],
        }
    if not goals:
        raise HighQualityReviewProjectionError(
            "canonical_customer_goals_missing"
        )
    valid, reasons = _validate_canonical_customer_goals(
        goals,
        message=message,
        source_turn_uid=source_turn_uid,
    )
    if not valid:
        raise HighQualityReviewProjectionError(
            "canonical_goal_provenance_invalid:"
            + ",".join(sorted(set(reasons)))
        )

    goal_alias_by_ref = {
        str(goal["goal_ref"]): _stable_control_alias(
            secret,
            "goal",
            str(goal["goal_ref"]),
        )
        for goal in goals
        if isinstance(goal, dict) and str(goal.get("goal_ref") or "")
    }
    projected_goals = [
        {
            "goal_alias": goal_alias_by_ref[str(goal["goal_ref"])],
            "goal_kind": str(goal.get("goal_kind") or ""),
            "claim_type": str(goal.get("claim_type") or ""),
            "claim_type_status": str(
                goal.get("claim_type_status") or ""
            ),
            "attribute_key": str(goal.get("attribute_key") or ""),
            "semantic_key": str(goal.get("semantic_key") or ""),
            "source_span_start": goal.get("source_span_start"),
            "source_span_end": goal.get("source_span_end"),
            "provenance_status": "validated_current_customer_turn",
        }
        for goal in sorted(
            (item for item in goals if isinstance(item, dict)),
            key=lambda item: str(item.get("goal_ref") or ""),
        )
    ]

    minimal = response.get("minimal_decision_context")
    minimal = minimal if isinstance(minimal, dict) else {}
    resolutions = [
        item
        for item in minimal.get("claim_resolutions") or []
        if (
            isinstance(item, dict)
            and not (
                item.get("supporting_only") is True
                and not str(item.get("goal_ref") or "").strip()
            )
        )
    ]
    claim_alias_by_uid: dict[str, str] = {}
    projected_resolutions: list[dict[str, Any]] = []
    for resolution in sorted(
        resolutions,
        key=lambda item: (
            str(item.get("goal_ref") or ""),
            str(item.get("claim_uid") or ""),
        ),
    ):
        raw_goal_ref = str(resolution.get("goal_ref") or "")
        raw_claim_uid = str(resolution.get("claim_uid") or "")
        if not raw_goal_ref:
            raise HighQualityReviewProjectionError(
                "claim_resolution_goal_ref_missing"
            )
        if raw_goal_ref not in goal_alias_by_ref:
            raise HighQualityReviewProjectionError(
                "claim_resolution_goal_ref_untrusted"
            )
        if not raw_claim_uid or raw_claim_uid != _claim_uid(
            {"goal_ref": raw_goal_ref}
        ):
            raise HighQualityReviewProjectionError(
                "claim_resolution_identity_invalid"
            )
        claim_alias = _stable_control_alias(
            secret,
            "claim",
            raw_claim_uid,
        )
        claim_alias_by_uid[raw_claim_uid] = claim_alias
        projected_resolutions.append({
            "goal_alias": goal_alias_by_ref[raw_goal_ref],
            "claim_alias": claim_alias,
            "claim_type": str(resolution.get("claim_type") or ""),
            "attribute_key": str(resolution.get("attribute_key") or ""),
            "status": str(resolution.get("status") or ""),
            "support_basis": str(
                resolution.get("support_basis") or ""
            ),
            "evidence_aliases": sorted(
                _stable_control_alias(secret, "evidence", str(value))
                for value in resolution.get("evidence_uids") or []
                if str(value or "")
            ),
            "reason_code": str(resolution.get("reason") or ""),
        })

    composer = response.get("model_first_answer_composer")
    composer = composer if isinstance(composer, dict) else {}
    clauses = [
        item for item in composer.get("clauses") or []
        if isinstance(item, dict)
    ]
    projected_clauses: list[dict[str, Any]] = []
    for clause in sorted(
        clauses,
        key=lambda item: str(item.get("clause_ref") or ""),
    ):
        raw_claim_uid = str(clause.get("goal_ref") or "")
        if raw_claim_uid not in claim_alias_by_uid:
            raise HighQualityReviewProjectionError(
                "composer_claim_reference_untrusted"
            )
        projected_clauses.append({
            "clause_alias": _stable_control_alias(
                secret,
                "clause",
                str(clause.get("clause_ref") or raw_claim_uid),
            ),
            "claim_alias": claim_alias_by_uid[raw_claim_uid],
            "clause_kind": str(clause.get("clause_kind") or ""),
            "text": str(clause.get("text") or "").strip(),
            "evidence_aliases": sorted(
                _stable_control_alias(secret, "evidence", str(value))
                for value in clause.get("evidence_uids") or []
                if str(value or "")
            ),
        })

    return {
        "schema_version": "trusted-control-reference-projection/v1",
        "status": "valid",
        "reason_code": "",
        "goal_understanding_status": understanding_status,
        "goal_count": len(projected_goals),
        "resolution_count": len(projected_resolutions),
        "clause_count": len(projected_clauses),
        "goals": projected_goals,
        "resolutions": projected_resolutions,
        "composer_clauses": projected_clauses,
    }


def stable_evaluation_alias(
    namespace: str,
    value: str,
    *,
    alias_secret: bytes | str,
) -> str:
    secret = (
        alias_secret.encode("utf-8")
        if isinstance(alias_secret, str)
        else alias_secret
    )
    if not isinstance(secret, bytes) or not secret:
        raise HighQualityReviewProjectionError("alias_secret_required")
    return _stable_control_alias(secret, namespace, value)


def _stable_control_alias(
    secret: bytes,
    namespace: str,
    value: str,
) -> str:
    normalized_namespace = str(namespace or "").strip().lower()
    normalized_value = str(value or "").strip()
    if not re.fullmatch(r"[a-z][a-z0-9_]{0,31}", normalized_namespace):
        raise HighQualityReviewProjectionError("alias_namespace_invalid")
    if not normalized_value:
        raise HighQualityReviewProjectionError("alias_value_required")
    digest = hmac.new(
        secret,
        f"{normalized_namespace}:{normalized_value}".encode("utf-8"),
        hashlib.sha256,
    ).digest()
    suffix = base64.b32encode(digest).decode("ascii").rstrip("=")[:16]
    return f"{normalized_namespace}_{suffix}"


def _response_turn_understanding(
    response: dict[str, Any],
) -> dict[str, Any]:
    for container in (
        response,
        response.get("evidence_debug"),
        response.get("answer_trace"),
        response.get("context_used"),
    ):
        if not isinstance(container, dict):
            continue
        understanding = container.get("turn_understanding")
        if isinstance(understanding, dict):
            return understanding
    raise HighQualityReviewProjectionError("turn_understanding_missing")


def default_review_label_db_path() -> Path:
    configured = os.environ.get("COPILOT_HQ_LONG_CONVERSATION_LABEL_DB", "").strip()
    if configured:
        return Path(configured).expanduser()
    return Path(__file__).resolve().parents[2] / "outputs" / "high_quality_long_conversation_labels_v4.sqlite"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _event_uid() -> str:
    return f"hqevent-{uuid.uuid4().hex[:20]}"


def _manifest_hash(payload: dict[str, Any]) -> str:
    return _content_hash(payload)


def _formal_db_path() -> Path:
    from app.config import KNOWLEDGE_DB_PATH

    return Path(KNOWLEDGE_DB_PATH).expanduser().resolve()


class HighQualityReviewLabelStore:
    """Independent review metadata store; never a knowledge or Agent input."""

    def __init__(self, path: str | Path | None = None):
        self.path = Path(path) if path else default_review_label_db_path()
        if self.path.expanduser().resolve() == _formal_db_path():
            raise HighQualityReviewLabelError("label_database_must_be_separate_from_formal_knowledge")

    def _connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        return connection

    def initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS hq_review_dataset (
                    dataset_sha256 TEXT PRIMARY KEY,
                    dataset_id TEXT NOT NULL,
                    dataset_version TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS hq_review_scenario_label (
                    scenario_uid TEXT NOT NULL,
                    dataset_sha256 TEXT NOT NULL,
                    status TEXT NOT NULL,
                    reviewer_role TEXT NOT NULL,
                    reviewer_actor_hmac TEXT NOT NULL,
                    version INTEGER NOT NULL,
                    gold_reply_original TEXT NOT NULL,
                    gold_reply_revised TEXT NOT NULL,
                    fact_correct INTEGER NOT NULL,
                    business_action_correct INTEGER NOT NULL,
                    safety_boundary_correct INTEGER NOT NULL,
                    human_tone_correct INTEGER NOT NULL,
                    notes TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (scenario_uid, dataset_sha256),
                    FOREIGN KEY (dataset_sha256) REFERENCES hq_review_dataset(dataset_sha256)
                );
                CREATE TABLE IF NOT EXISTS hq_review_audit_event (
                    event_uid TEXT PRIMARY KEY,
                    scenario_uid TEXT NOT NULL,
                    actor_hmac TEXT NOT NULL,
                    actor_role TEXT NOT NULL,
                    auth_type TEXT NOT NULL,
                    action TEXT NOT NULL,
                    from_status TEXT NOT NULL,
                    to_status TEXT NOT NULL,
                    previous_version INTEGER NOT NULL,
                    new_version INTEGER NOT NULL,
                    dataset_sha256 TEXT NOT NULL,
                    gold_reply_revised TEXT NOT NULL,
                    notes TEXT NOT NULL,
                    timestamp TEXT NOT NULL
                );
                """
            )

    def register_dataset(self, *, dataset_id: str, dataset_version: str, dataset_sha256: str) -> None:
        self.initialize()
        with self._connect() as connection:
            connection.execute(
                "INSERT OR IGNORE INTO hq_review_dataset VALUES (?,?,?,?)",
                (dataset_sha256, dataset_id, dataset_version, _now()),
            )
            connection.commit()

    def get(self, scenario_uid: str, dataset_sha256: str) -> dict[str, Any] | None:
        self.initialize()
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM hq_review_scenario_label WHERE scenario_uid=? AND dataset_sha256=?",
                (scenario_uid, dataset_sha256),
            ).fetchone()
        return self._label_row(row) if row else None

    def list_labels(self, dataset_sha256: str) -> list[dict[str, Any]]:
        self.initialize()
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM hq_review_scenario_label WHERE dataset_sha256=? ORDER BY scenario_uid",
                (dataset_sha256,),
            ).fetchall()
        return [self._label_row(row) for row in rows]

    def list_events(self, dataset_sha256: str) -> list[dict[str, Any]]:
        self.initialize()
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM hq_review_audit_event WHERE dataset_sha256=? ORDER BY scenario_uid,new_version,event_uid",
                (dataset_sha256,),
            ).fetchall()
        return [dict(row) for row in rows]

    def save(
        self,
        *,
        dataset_id: str,
        dataset_version: str,
        dataset_sha256: str,
        scenario_uid: str,
        gold_reply_original: str,
        gold_reply_revised: str,
        fact_correct: bool,
        business_action_correct: bool,
        safety_boundary_correct: bool,
        human_tone_correct: bool,
        notes: str,
        requested_status: str,
        actor_hmac: str,
        actor_role: str,
        auth_type: str,
        expected_version: int | None,
    ) -> dict[str, Any]:
        if requested_status not in _LABEL_STATUSES:
            raise HighQualityReviewLabelError("review_status_invalid")
        if actor_role not in {"reviewer", "supervisor", "admin"}:
            raise HighQualityReviewLabelError("reviewer_role_invalid")
        if requested_status in {"approved", "rejected"}:
            if actor_role not in _APPROVAL_ROLES or auth_type != _AUTHORITATIVE_AUTH_TYPE:
                raise HighQualityReviewLabelError("authoritative_supervisor_required")
        revised = str(gold_reply_revised or "").strip()
        if not revised:
            raise HighQualityReviewLabelError("gold_reply_revised_required")
        clean_notes = str(notes or "").strip()
        if requested_status == "rejected" and not clean_notes:
            raise HighQualityReviewLabelError("rejection_reason_required")
        checks = (fact_correct, business_action_correct, safety_boundary_correct, human_tone_correct)
        if requested_status == "approved" and not all(value is True for value in checks):
            raise HighQualityReviewLabelError("all_manual_checks_required_for_approval")

        self.register_dataset(
            dataset_id=dataset_id,
            dataset_version=dataset_version,
            dataset_sha256=dataset_sha256,
        )
        now = _now()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                "SELECT * FROM hq_review_scenario_label WHERE scenario_uid=? AND dataset_sha256=?",
                (scenario_uid, dataset_sha256),
            ).fetchone()
            previous_version = int(existing["version"]) if existing else 0
            if expected_version is None or int(expected_version) != previous_version:
                raise HighQualityReviewConflictError("optimistic_lock_conflict")
            from_status = str(existing["status"]) if existing else ""
            status = requested_status
            if existing and from_status == "approved" and requested_status == "draft":
                status = "reviewed"
            version = previous_version + 1
            created_at = str(existing["created_at"]) if existing else now
            values = (
                status, actor_role, actor_hmac, version, gold_reply_original, revised,
                int(bool(fact_correct)), int(bool(business_action_correct)),
                int(bool(safety_boundary_correct)), int(bool(human_tone_correct)),
                clean_notes, created_at, now, scenario_uid, dataset_sha256,
            )
            if existing:
                connection.execute(
                    """UPDATE hq_review_scenario_label SET
                    status=?,reviewer_role=?,reviewer_actor_hmac=?,version=?,gold_reply_original=?,
                    gold_reply_revised=?,fact_correct=?,business_action_correct=?,safety_boundary_correct=?,
                    human_tone_correct=?,notes=?,created_at=?,updated_at=?
                    WHERE scenario_uid=? AND dataset_sha256=?""",
                    values,
                )
            else:
                connection.execute(
                    """INSERT INTO hq_review_scenario_label
                    (status,reviewer_role,reviewer_actor_hmac,version,gold_reply_original,gold_reply_revised,
                    fact_correct,business_action_correct,safety_boundary_correct,human_tone_correct,notes,
                    created_at,updated_at,scenario_uid,dataset_sha256) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    values,
                )
            action = {
                "draft": "scenario_draft_saved",
                "reviewed": "scenario_submitted",
                "approved": "scenario_approved",
                "rejected": "scenario_rejected",
            }[status]
            if from_status == "approved" and status == "reviewed":
                action = "approved_scenario_revised"
            connection.execute(
                """INSERT INTO hq_review_audit_event
                (event_uid,scenario_uid,actor_hmac,actor_role,auth_type,action,from_status,to_status,
                previous_version,new_version,dataset_sha256,gold_reply_revised,notes,timestamp)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    _event_uid(), scenario_uid, actor_hmac, actor_role, auth_type, action,
                    from_status, status, previous_version, version, dataset_sha256, revised, clean_notes, now,
                ),
            )
            connection.commit()
        return self.get(scenario_uid, dataset_sha256) or {}

    @staticmethod
    def _label_row(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "scenario_uid": row["scenario_uid"],
            "dataset_sha256": row["dataset_sha256"],
            "status": row["status"],
            "reviewer_role": row["reviewer_role"],
            "reviewer_actor_hmac": row["reviewer_actor_hmac"],
            "version": int(row["version"]),
            "gold_reply_original": row["gold_reply_original"],
            "gold_reply_revised": row["gold_reply_revised"],
            "fact_correct": bool(row["fact_correct"]),
            "business_action_correct": bool(row["business_action_correct"]),
            "safety_boundary_correct": bool(row["safety_boundary_correct"]),
            "human_tone_correct": bool(row["human_tone_correct"]),
            "notes": row["notes"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }


def build_approved_review_manifest(
    payload: dict[str, Any], store: HighQualityReviewLabelStore
) -> dict[str, Any]:
    validation = validate_review_dataset(payload)
    if validation["validation_status"] != "passed":
        raise HighQualityReviewDatasetError("review_dataset_invalid")
    dataset_hash = validation["computed_content_sha256"]
    scenarios = payload.get("scenarios") or []
    labels = {row["scenario_uid"]: row for row in store.list_labels(dataset_hash)}
    events = store.list_events(dataset_hash)
    event_by_scenario: dict[str, list[dict[str, Any]]] = {}
    for event in events:
        event_by_scenario.setdefault(str(event.get("scenario_uid") or ""), []).append(event)
    approved_uids: list[str] = []
    approved_domains: set[str] = set()
    findings: list[str] = []
    approval_event_count = 0
    for scenario in scenarios:
        uid = str(scenario.get("scenario_uid") or "")
        label = labels.get(uid)
        if not label or label["status"] != "approved":
            continue
        versions = [
            int(event.get("new_version") or 0)
            for event in event_by_scenario.get(uid, [])
        ]
        if versions != list(range(1, int(label["version"]) + 1)):
            findings.append(f"optimistic_lock_history_invalid:{uid}")
            continue
        matches = [
            event for event in event_by_scenario.get(uid, [])
            if event.get("action") == "scenario_approved"
            and int(event.get("new_version") or 0) == int(label["version"])
            and event.get("actor_role") in _APPROVAL_ROLES
            and event.get("auth_type") == _AUTHORITATIVE_AUTH_TYPE
            and event.get("dataset_sha256") == dataset_hash
        ]
        if len(matches) != 1:
            findings.append(f"approval_audit_invalid:{uid}")
            continue
        if not all(
            label[key]
            for key in ("fact_correct", "business_action_correct", "safety_boundary_correct", "human_tone_correct")
        ):
            findings.append(f"manual_check_incomplete:{uid}")
            continue
        approved_uids.append(uid)
        approved_domains.add(str(scenario.get("business_domain") or ""))
        approval_event_count += 1
    status_counts = Counter(label["status"] for label in labels.values())
    ready = len(approved_uids) == len(scenarios) and not findings and bool(scenarios)
    manifest = {
        "schema_version": "high-quality-long-conversation-approved-manifest/v1",
        "dataset_id": validation["dataset_id"],
        "dataset_version": validation["dataset_version"],
        "dataset_sha256": dataset_hash,
        "total_scenarios": len(scenarios),
        "approved_count": len(approved_uids),
        "rejected_count": int(status_counts.get("rejected", 0)),
        "reviewed_count": int(status_counts.get("reviewed", 0)),
        "draft_count": int(status_counts.get("draft", 0)) + max(0, len(scenarios) - len(labels)),
        "approval_event_count": approval_event_count,
        "approved_domain_count": len(approved_domains),
        "approved_scenario_uids": sorted(approved_uids),
        "audit_findings": sorted(findings),
        "agent_call_allowed": ready,
        "accuracy_claim_allowed": ready,
        "status": "approved_for_evaluation" if ready else "awaiting_supervisor_approval",
    }
    manifest["manifest_sha256"] = _manifest_hash(manifest)
    return manifest


def _contains_embedded_authoritative_review(review: dict[str, Any]) -> bool:
    status = str(review.get("status") or "").strip().lower()
    decision = str(review.get("reviewer_decision") or "").strip().lower()
    actor_role = str(review.get("reviewer_role") or review.get("actor_role") or "").strip().lower()
    auth_type = str(review.get("auth_type") or "").strip().lower()
    approval_audit = review.get("approval_audit")
    try:
        version = int(review.get("optimistic_lock_version") or 0)
    except (TypeError, ValueError):
        version = 1
    approval_checks = (
        review.get("fact_boundary_approved"),
        review.get("action_boundary_approved"),
        review.get("gold_reply_approved"),
    )
    return bool(
        status in {"approved", "rejected"}
        or decision in {"approve", "reject"}
        or actor_role in _APPROVAL_ROLES
        or auth_type == _AUTHORITATIVE_AUTH_TYPE
        or version > 0
        or bool(approval_audit)
        or any(value is True for value in approval_checks)
    )


def _privacy_projection(value: Any) -> Any:
    if isinstance(value, list):
        return [_privacy_projection(item) for item in value]
    if not isinstance(value, dict):
        return value
    return {
        key: _privacy_projection(item)
        for key, item in value.items()
        if key not in _PRIVACY_CONTROLLED_FIELDS
    }


def _validate_structured_identifiers(value: Any) -> list[str]:
    findings: list[str] = []

    def visit(item: Any) -> None:
        if isinstance(item, list):
            for child in item:
                visit(child)
            return
        if not isinstance(item, dict):
            return
        for key in (
            "content_sha256",
            "provenance_hash",
            "source_linkage_fingerprint",
            "source_conversation_digest",
        ):
            if key in item and not _HEX_HASH_RE.fullmatch(str(item.get(key) or "")):
                findings.append(f"controlled_hash_invalid:{key}")
        for key in ("scenario_uid", "turn_uid", "claim_uid", "evidence_uid", "source_case_uid"):
            if key in item and not _SCOPED_UID_RE.fullmatch(str(item.get(key) or "")):
                findings.append(f"controlled_uid_invalid:{key}")
        if "evidence_uids" in item:
            values = item.get("evidence_uids")
            if not isinstance(values, list) or any(not _SCOPED_UID_RE.fullmatch(str(value or "")) for value in values):
                findings.append("controlled_uid_invalid:evidence_uids")
        if "target_turn_uids" in item:
            values = item.get("target_turn_uids")
            if not isinstance(values, list) or any(not _SCOPED_UID_RE.fullmatch(str(value or "")) for value in values):
                findings.append("controlled_uid_invalid:target_turn_uids")
        for child in item.values():
            visit(child)

    visit(value)
    return sorted(set(findings))
