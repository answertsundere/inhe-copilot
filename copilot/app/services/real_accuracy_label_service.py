"""Independent, append-audited human labels for the real-accuracy Gold Set.

The store is intentionally SQLite outside the knowledge base.  Labels are
assessment metadata only and never flow into Product Context Pack, retrieval,
Answer Memory, or the customer-facing Agent.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


_CLAIM_KINDS = {
    "product_fact", "factual_claim", "tool_action", "service_action", "handoff", "prohibited",
    "unresolved_claim", "delivery_constraint", "context_requirement",
}
_EXPECTED_STATUSES = {"supported", "unresolved", "conflicting", "prohibited"}
_REVIEW_STATUSES = {"draft", "reviewed", "approved", "rejected"}
_APPROVAL_ACTOR_ROLES = {"supervisor", "admin"}
_PROPOSAL_STATUSES = {
    "ai_proposed", "source_reviewed_candidate", "policy_validated", "supervisor_approved", "rejected",
}
_SOURCE_REFERENCES = {"", "ai_proposed", "source_reviewed_candidate", "reviewed_answer", "formal_evidence"}
_TURN_UID_RE = re.compile(r"^turn_[A-Z2-7]{20}$")
_HIGH_RISK_ATTRIBUTES = {
    "load_capacity", "non_toxic", "food_grade", "certification", "child_safety",
    "age_range", "anti_tip", "wall_mounting", "refund", "replacement", "compensation",
}


class LabelValidationError(ValueError):
    pass


class LabelConflictError(ValueError):
    pass


def default_label_db_path() -> Path:
    configured = os.environ.get("COPILOT_REAL_ACCURACY_LABEL_DB", "").strip()
    if configured:
        return Path(configured).expanduser()
    return Path(__file__).resolve().parents[2] / "data" / "real_accuracy_labels.db"


def reviewer_actor_hash(actor: str, key: str | None = None) -> str:
    secret = key or os.environ.get("COPILOT_REAL_ACCURACY_LABEL_AUDIT_HMAC_KEY", "")
    if not secret:
        raise LabelValidationError("label_audit_hmac_key_missing")
    digest = hmac.new(secret.encode("utf-8"), str(actor).encode("utf-8"), hashlib.sha256).hexdigest()
    return f"reviewer_{digest[:20]}"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def validate_claims(claims: Any) -> list[dict[str, Any]]:
    if not isinstance(claims, list) or not claims:
        raise LabelValidationError("claims_required")
    normalized: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in claims:
        if not isinstance(raw, dict):
            raise LabelValidationError("claim_object_required")
        claim = {
            "claim_uid": str(raw.get("claim_uid") or "").strip(),
            "claim_kind": str(raw.get("claim_kind") or "").strip(),
            "query_fact_type": str(raw.get("query_fact_type") or "").strip(),
            "attribute_key": str(raw.get("attribute_key") or "").strip(),
            "expected_status": str(raw.get("expected_status") or "").strip(),
            "acceptable_values": list(raw.get("acceptable_values") or []),
            "normalized_value": raw.get("normalized_value"),
            "unit": raw.get("unit"),
            "required_terms": [str(item).strip() for item in raw.get("required_terms") or [] if str(item).strip()],
            "supporting_evidence_uids": [str(item).strip() for item in raw.get("supporting_evidence_uids") or [] if str(item).strip()],
            "required_tool": str(raw.get("required_tool") or "").strip() or None,
            "required_action_points": [str(item).strip() for item in raw.get("required_action_points") or [] if str(item).strip()],
            "must_handoff": bool(raw.get("must_handoff")),
            "forbidden_claims": [str(item).strip() for item in raw.get("forbidden_claims") or [] if str(item).strip()],
            "partial_answer_allowed": bool(raw.get("partial_answer_allowed")),
            "review_status": str(raw.get("review_status") or "draft").strip(),
            "proposal_status": str(raw.get("proposal_status") or "ai_proposed").strip(),
            "source_reference": str(raw.get("source_reference") or "").strip(),
            "evidence_provenance": [
                {
                    "evidence_uid": str(item.get("evidence_uid") or "").strip(),
                    "fact_type": str(item.get("fact_type") or "").strip(),
                    "attribute_key": str(item.get("attribute_key") or "").strip(),
                    "review_status": str(item.get("review_status") or "").strip(),
                    "evidence_role": str(item.get("evidence_role") or "").strip(),
                    "identity_scope": str(item.get("identity_scope") or "").strip(),
                }
                for item in raw.get("evidence_provenance") or [] if isinstance(item, dict)
            ],
            "risk_level": str(raw.get("risk_level") or "unknown").strip(),
            "identity_scope": str(raw.get("identity_scope") or "not_evaluated").strip(),
            "can_support_auto_send": bool(raw.get("can_support_auto_send")),
            "strategy_group": str(raw.get("strategy_group") or "").strip(),
        }
        if not claim["claim_uid"] or claim["claim_uid"] in seen:
            raise LabelValidationError("claim_uid_missing_or_duplicate")
        seen.add(claim["claim_uid"])
        if claim["claim_kind"] not in _CLAIM_KINDS or claim["expected_status"] not in _EXPECTED_STATUSES:
            raise LabelValidationError("claim_enum_invalid")
        if claim["review_status"] not in _REVIEW_STATUSES:
            raise LabelValidationError("claim_review_status_invalid")
        if claim["proposal_status"] not in _PROPOSAL_STATUSES:
            raise LabelValidationError("claim_proposal_status_invalid")
        if claim["source_reference"] not in _SOURCE_REFERENCES:
            raise LabelValidationError("claim_source_reference_invalid")
        if claim["claim_kind"] in {"product_fact", "factual_claim"} and claim["review_status"] == "approved" and not claim["supporting_evidence_uids"]:
            raise LabelValidationError("approved_product_fact_evidence_required")
        high_risk = claim["attribute_key"] in _HIGH_RISK_ATTRIBUTES or claim["query_fact_type"] in _HIGH_RISK_ATTRIBUTES
        if high_risk and not claim["supporting_evidence_uids"] and claim["expected_status"] == "supported":
            raise LabelValidationError("unsupported_high_risk_claim_must_be_unresolved_or_prohibited")
        normalized.append(claim)
    return normalized


def transition_claims_for_review(claims: Any, *, review_status: str) -> list[dict[str, Any]]:
    """Move existing draft proposals to a reviewer-visible state without approval.

    Supervisor approval is intentionally excluded.  It must remain an explicit
    per-case action so a group rule cannot silently approve factual claims.
    """
    if review_status not in {"draft", "reviewed", "rejected"}:
        raise LabelValidationError("batch_review_status_invalid")
    transitioned = []
    for raw in validate_claims(claims):
        item = dict(raw)
        item["review_status"] = review_status
        if review_status == "rejected":
            item["proposal_status"] = "rejected"
        transitioned.append(item)
    return transitioned


def validate_target_turn_uids(target_turn_uids: Any, *, required: bool) -> list[str]:
    if target_turn_uids is None:
        target_turn_uids = []
    if not isinstance(target_turn_uids, list):
        raise LabelValidationError("target_turn_uids_list_required")
    normalized = [str(item).strip() for item in target_turn_uids if str(item).strip()]
    if len(normalized) != len(set(normalized)):
        raise LabelValidationError("target_turn_uid_duplicate")
    if any(not _TURN_UID_RE.fullmatch(item) for item in normalized):
        raise LabelValidationError("target_turn_uid_invalid")
    if required and not normalized:
        raise LabelValidationError("target_buyer_turn_required")
    return normalized


class RealAccuracyLabelStore:
    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path or default_label_db_path())

    def _connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        return connection

    def initialize(self) -> None:
        with self._connect() as connection:
            connection.execute("""
                CREATE TABLE IF NOT EXISTS real_accuracy_case_label (
                    case_uid TEXT NOT NULL,
                    dataset_version TEXT NOT NULL,
                    label_json TEXT NOT NULL,
                    review_status TEXT NOT NULL,
                    reviewer_actor_hash TEXT NOT NULL,
                    optimistic_lock_version INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (case_uid, dataset_version)
                )
            """)
            connection.execute("""
                CREATE TABLE IF NOT EXISTS real_accuracy_label_event (
                    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    case_uid TEXT NOT NULL,
                    dataset_version TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    actor_hash TEXT NOT NULL,
                    version INTEGER NOT NULL,
                    created_at TEXT NOT NULL
                )
            """)
            columns = {
                str(row[1])
                for row in connection.execute("PRAGMA table_info(real_accuracy_label_event)")
            }
            if "actor_role" not in columns:
                connection.execute(
                    "ALTER TABLE real_accuracy_label_event ADD COLUMN actor_role TEXT NOT NULL DEFAULT ''"
                )
            if "claim_uid" not in columns:
                connection.execute(
                    "ALTER TABLE real_accuracy_label_event ADD COLUMN claim_uid TEXT"
                )

    def get(self, case_uid: str, dataset_version: str) -> dict[str, Any] | None:
        self.initialize()
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM real_accuracy_case_label WHERE case_uid=? AND dataset_version=?",
                (case_uid, dataset_version),
            ).fetchone()
        return self._row(row) if row else None

    def list_for_dataset(self, dataset_version: str) -> list[dict[str, Any]]:
        self.initialize()
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM real_accuracy_case_label WHERE dataset_version=? ORDER BY case_uid", (dataset_version,)
            ).fetchall()
        return [self._row(row) for row in rows]

    def list_events_for_dataset(self, dataset_version: str) -> list[dict[str, Any]]:
        self.initialize()
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT event_id,case_uid,dataset_version,event_type,actor_hash,actor_role,claim_uid,version,created_at "
                "FROM real_accuracy_label_event WHERE dataset_version=? ORDER BY event_id",
                (dataset_version,),
            ).fetchall()
        return [dict(row) for row in rows]

    def save(
        self,
        *,
        case_uid: str,
        dataset_version: str,
        claims: Any,
        target_turn_uids: Any = None,
        review_status: str,
        actor_hash: str,
        expected_version: int | None,
        allow_approval: bool,
        actor_role: str = "",
    ) -> dict[str, Any]:
        if review_status not in _REVIEW_STATUSES:
            raise LabelValidationError("label_review_status_invalid")
        if review_status == "approved" and not allow_approval:
            raise LabelValidationError("supervisor_approval_required")
        normalized_claims = validate_claims(claims)
        actor_role = str(actor_role or "").strip().lower()
        if review_status == "approved" and actor_role not in _APPROVAL_ACTOR_ROLES:
            raise LabelValidationError("supervisor_approval_role_required")
        normalized_target_turn_uids = validate_target_turn_uids(
            target_turn_uids,
            required=review_status in {"reviewed", "approved"},
        )
        if review_status == "approved" and any(item["review_status"] != "approved" for item in normalized_claims):
            raise LabelValidationError("approved_case_requires_approved_claims")
        if review_status == "approved":
            normalized_claims = [
                {**item, "proposal_status": "supervisor_approved"}
                for item in normalized_claims
            ]
        self.initialize()
        now = _now()
        payload = json.dumps(
            {"claims": normalized_claims, "target_turn_uids": normalized_target_turn_uids},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        with self._connect() as connection:
            existing = connection.execute(
                "SELECT * FROM real_accuracy_case_label WHERE case_uid=? AND dataset_version=?", (case_uid, dataset_version)
            ).fetchone()
            if existing:
                if expected_version is None or int(existing["optimistic_lock_version"]) != expected_version:
                    raise LabelConflictError("optimistic_lock_conflict")
                version = int(existing["optimistic_lock_version"]) + 1
                connection.execute(
                    "UPDATE real_accuracy_case_label SET label_json=?, review_status=?, reviewer_actor_hash=?, optimistic_lock_version=?, updated_at=? WHERE case_uid=? AND dataset_version=?",
                    (payload, review_status, actor_hash, version, now, case_uid, dataset_version),
                )
                event_type = "label_updated"
            else:
                if expected_version not in (None, 0):
                    raise LabelConflictError("optimistic_lock_conflict")
                version = 1
                connection.execute(
                    "INSERT INTO real_accuracy_case_label VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (case_uid, dataset_version, payload, review_status, actor_hash, version, now, now),
                )
                event_type = "label_created"
            connection.execute(
                "INSERT INTO real_accuracy_label_event "
                "(case_uid,dataset_version,event_type,actor_hash,actor_role,claim_uid,version,created_at) "
                "VALUES (?,?,?,?,?,?,?,?)",
                (case_uid, dataset_version, event_type, actor_hash, actor_role, None, version, now),
            )
            if review_status == "approved":
                for claim in normalized_claims:
                    connection.execute(
                        "INSERT INTO real_accuracy_label_event "
                        "(case_uid,dataset_version,event_type,actor_hash,actor_role,claim_uid,version,created_at) "
                        "VALUES (?,?,?,?,?,?,?,?)",
                        (
                            case_uid,
                            dataset_version,
                            "claim_approved",
                            actor_hash,
                            actor_role,
                            claim["claim_uid"],
                            version,
                            now,
                        ),
                    )
            connection.commit()
        return self.get(case_uid, dataset_version) or {}

    @staticmethod
    def _row(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "case_uid": row["case_uid"],
            "dataset_version": row["dataset_version"],
            "label": json.loads(row["label_json"]),
            "review_status": row["review_status"],
            "reviewer_actor_hash": row["reviewer_actor_hash"],
            "optimistic_lock_version": row["optimistic_lock_version"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }
