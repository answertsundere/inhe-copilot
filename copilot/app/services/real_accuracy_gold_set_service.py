"""Privacy-safe, read-only contracts for real customer-service accuracy evaluation.

The production Agent never imports this module.  It turns reviewed source rows
into an evaluation artifact and makes the boundary between labels and runtime
inputs explicit.  A correct answer is assessment data, not customer-service
knowledge or Agent context.
"""

from __future__ import annotations

import base64
import copy
import hashlib
import hmac
import json
import re
import sqlite3
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable

from app.services.real_accuracy_privacy_service import (
    parse_conversation_context,
    sanitize_gold_text,
    scan_privacy_output,
    validate_controlled_identifiers,
)


DATASET_SCHEMA_VERSION = "real-accuracy-gold-set-v3"
DATASET_V2_SCHEMA_VERSION = "real-accuracy-gold-set-v4"
DEFAULT_MINIMUM_GOLD_LABELS = 30
DEFAULT_MINIMUM_GOLD_DOMAINS = 5
_REQUIRED_SAMPLE_COLUMNS = {
    "id", "customer_quote", "full_context", "product_title", "sku", "order_no",
    "question_type", "correct_answer", "review_status", "risk_level", "need_media",
}
_IMAGE_OR_LINK_RE = re.compile(r"(?:\[图片[^\]]*\]|https?://\S+|data:image/)", re.I)
_HTML_RE = re.compile(r"<[^>]+>")
_UNSAFE_CONTROL_CHAR_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
# This taxonomy is intentionally confined to offline evaluation.  It assesses
# whether a human-reviewed reference asks for a general service action; it is
# never imported by the Agent or used to generate a reply.
REFERENCE_ACTIONS: dict[str, tuple[str, ...]] = {
    "acknowledge": ("抱歉", "不好意思", "理解", "别着急", "安抚"),
    "verify_order": ("核对订单", "查一下订单", "订单信息", "订单号"),
    "request_visual_proof": ("拍照", "照片", "视频", "截图", "凭证"),
    "verify_product": ("商品资料", "商品信息", "确认款式", "核对型号"),
    "logistics_follow_up": ("物流", "快递", "发货", "配送"),
    "aftersales_follow_up": ("售后", "补发", "换货", "退货", "退款"),
    "installation_guidance": ("安装", "说明书", "步骤", "配件"),
}


def canonical_text(value: Any, limit: int = 1800) -> str:
    text = str(value or "")
    # Historical exported chat HTML can include invisible terminal controls.
    # They are neither customer-visible content nor useful evaluation context.
    text = _UNSAFE_CONTROL_CHAR_RE.sub(" ", text)
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.I)
    text = re.sub(r"</(?:p|div|li|tr|h\d)>", "\n", text, flags=re.I)
    text = _HTML_RE.sub(" ", text)
    text = re.sub(r"\s+", " ", text).strip()
    text = sanitize_gold_text(text)
    return text[:limit].rstrip()


def hmac_identifier(secret: str, namespace: str, raw_value: Any) -> str:
    if not secret:
        raise ValueError("gold_set_hmac_key_missing")
    digest = hmac.new(
        secret.encode("utf-8"),
        f"{namespace}:{raw_value}".encode("utf-8"),
        hashlib.sha256,
    ).digest()
    # Base32 avoids long digit runs that privacy scanners correctly treat as
    # residual identifiers while remaining deterministic and opaque.
    encoded = base64.b32encode(digest).decode("ascii").rstrip("=")[:20]
    return f"{namespace}_{encoded}"


def _sqlite_readonly(path: str | Path) -> sqlite3.Connection:
    resolved = Path(path).expanduser().resolve()
    if not resolved.is_file():
        raise FileNotFoundError(f"source_db_not_found:{resolved}")
    return sqlite3.connect(f"file:{resolved.as_uri()[5:]}?mode=ro", uri=True)


def load_reviewed_training_samples(source_db: str | Path) -> list[dict[str, Any]]:
    """Read source rows without using ORM startup or writing migrations."""
    connection = _sqlite_readonly(source_db)
    try:
        columns = {row[1] for row in connection.execute("PRAGMA table_info(kb_training_sample)")}
        missing = sorted(_REQUIRED_SAMPLE_COLUMNS - columns)
        if missing:
            raise ValueError(f"training_sample_schema_missing:{','.join(missing)}")
        selected = sorted(_REQUIRED_SAMPLE_COLUMNS | {"auto_reply_type", "notes"})
        rows = connection.execute(
            f"SELECT {','.join(selected)} FROM kb_training_sample WHERE review_status = ? ORDER BY id",
            ("已确认",),
        ).fetchall()
        return [dict(zip(selected, row)) for row in rows]
    finally:
        connection.close()


def _has_text_question(sample: dict[str, Any]) -> bool:
    text = canonical_text(sample.get("customer_quote"), limit=300)
    without_non_text = _IMAGE_OR_LINK_RE.sub("", text)
    return len(without_non_text.strip()) >= 2


def _is_media_only(sample: dict[str, Any]) -> bool:
    text = canonical_text(sample.get("customer_quote"), limit=300)
    return bool(text) and not _has_text_question(sample) and bool(_IMAGE_OR_LINK_RE.search(text))


def _has_reviewable_question_text(value: Any) -> bool:
    text = canonical_text(value, limit=1800)
    return len(_IMAGE_OR_LINK_RE.sub("", text).strip()) >= 2


def _has_sidecar(sample: dict[str, Any]) -> bool:
    return any(str(sample.get(key) or "").strip() for key in ("product_title", "sku", "order_no"))


def classify_sample(sample: dict[str, Any]) -> str:
    """Classify source availability; claim labels remain a separate human gate."""
    if _is_media_only(sample):
        return "media_only"
    if not _has_text_question(sample):
        return "invalid"
    if not _has_sidecar(sample):
        return "context_gap"
    if canonical_text(sample.get("correct_answer"), limit=120):
        return "reference_available"
    if str(sample.get("risk_level") or "").strip() or str(sample.get("auto_reply_type") or "").strip():
        return "safety_scorable"
    return "label_gap"


def reference_action_points(reference_text: str) -> list[str]:
    text = canonical_text(reference_text, limit=1800)
    return [name for name, terms in REFERENCE_ACTIONS.items() if any(term in text for term in terms)]


def _identity(secret: str, sample: dict[str, Any]) -> dict[str, str]:
    result: dict[str, str] = {}
    for key, namespace in (("product_title", "product"), ("sku", "sku"), ("order_no", "order")):
        value = str(sample.get(key) or "").strip()
        if value:
            result[namespace] = hmac_identifier(secret, namespace, value)
    return result


def build_gold_case(secret: str, sample: dict[str, Any]) -> dict[str, Any]:
    classification = classify_sample(sample)
    source_uid = hmac_identifier(secret, "training_sample", sample.get("id"))
    reference = canonical_text(sample.get("correct_answer"), limit=1800)
    conversation = parse_conversation_context(
        sample.get("full_context"),
        hmac_key=secret,
        source_provenance="reviewed_training_sample",
        conversation_uid=source_uid,
    )
    if conversation["privacy_review_required"]:
        classification = "privacy_review_required"
    elif conversation.get("conversation_truncated"):
        classification = "conversation_truncated"
    elif conversation.get("role_unresolved_count"):
        classification = "role_unresolved"
    elif classification == "reference_available":
        classification = "claim_label_pending"
    action_points = reference_action_points(reference) if reference else []
    case = {
        "case_uid": source_uid,
        "source": {"kind": "reviewed_training_sample", "pseudonymous_id": source_uid},
        "classification": classification,
        "customer_message": canonical_text(sample.get("customer_quote")),
        "conversation": conversation,
        "query_class": canonical_text(sample.get("question_type"), limit=120) or "unclassified",
        "risk_level": canonical_text(sample.get("risk_level"), limit=40) or "unknown",
        "sidecar_identity": _identity(secret, sample),
        "sidecar_present": _has_sidecar(sample),
        "reference_label": {
            "label_status": "reviewed_reference_available" if reference else "manual_label_required",
            "reference_text": reference,
            "expected_action_points": action_points,
            "expected_claims": [],
            "forbidden_claims": [],
            "must_handoff": None,
        },
        "expected_evidence": [],
        "notes": {
            "needs_claim_level_review": bool(reference),
            "media_requested": bool(sample.get("need_media")),
            "source_text_sanitized": False,
            "identity_pseudonymized": True,
            "role_unresolved": bool(conversation.get("role_unresolved_count")),
            "conversation_truncated": bool(conversation.get("conversation_truncated")),
        },
    }
    return case


def _dataset_hash(cases: list[dict[str, Any]]) -> str:
    canonical = json.dumps(cases, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _conversation_digest(turns: list[dict[str, Any]]) -> str:
    projection = [
        {
            "turn_uid": str(turn.get("turn_uid") or ""),
            "turn_index": int(turn.get("turn_index") or 0),
            "speaker_role": str(turn.get("speaker_role") or ""),
            "message_type": str(turn.get("message_type") or ""),
            "text_digest": _sha256_text(str(turn.get("text") or "")),
        }
        for turn in turns
    ]
    canonical = json.dumps(projection, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def build_gold_case_v2(secret: str, sample: dict[str, Any]) -> dict[str, Any]:
    """Build a v0.2 case with one explicit current buyer target.

    ``customer_quote`` is an authoritative reviewed-sample field independent
    from the historical HTML transcript.  It is represented as a new final
    turn with explicit provenance instead of being guessed from history.
    """
    return _with_explicit_target_v2(
        secret,
        build_gold_case(secret, sample),
        source_kind="reviewed_training_sample",
        source_field="customer_quote",
    )


def _with_explicit_target_v2(
    secret: str,
    source_case: dict[str, Any],
    *,
    source_kind: str,
    source_field: str,
) -> dict[str, Any]:
    """Attach one independently stored current buyer question as the v0.2 target."""
    case = copy.deepcopy(source_case)
    case_uid = str(case.get("case_uid") or "")
    turns = list((case.get("conversation") or {}).get("turns") or [])
    question = canonical_text(case.get("customer_message"), limit=1800)
    if not _has_reviewable_question_text(question):
        case["explicit_target"] = None
        case["target_status"] = "target_missing"
        case["conversation_digest"] = _conversation_digest(turns)
        return case

    history_end_turn_index = max(
        (int(turn.get("turn_index") or 0) for turn in turns),
        default=-1,
    )
    target_text_digest = _sha256_text(question)
    target_turn_index = history_end_turn_index + 1
    target_turn_uid = hmac_identifier(
        secret,
        "turn",
        f"{case_uid}:reviewed_sample_customer_question:{target_text_digest}",
    )
    target_turn = {
        "turn_index": target_turn_index,
        "turn_uid": target_turn_uid,
        "speaker_role": "BUYER",
        "speaker_uid": hmac_identifier(secret, "actor", f"{case_uid}:current_buyer"),
        "message_type": "text",
        "text": question,
        "role_resolution": "reviewed_sample_customer_question",
        "source_provenance": "reviewed_sample_customer_question",
    }
    turns.append(target_turn)
    conversation = case["conversation"]
    conversation["turns"] = turns
    conversation["role_counts"] = dict(conversation.get("role_counts") or {})
    conversation["role_counts"]["BUYER"] = int(conversation["role_counts"].get("BUYER") or 0) + 1
    conversation["turn_count"] = len(turns)
    conversation_digest = _conversation_digest(turns)
    case["explicit_target"] = {
        "target_turn_uid": target_turn_uid,
        "target_turn_index": target_turn_index,
        "target_speaker_role": "BUYER",
        "target_text_digest": target_text_digest,
        "target_source_type": "reviewed_sample_customer_question",
        "target_source_reference": case_uid,
        "target_provenance": {
            "source_kind": source_kind,
            "source_field": source_field,
            "source_case_uid": case_uid,
            "content_digest": target_text_digest,
        },
        "history_end_turn_index": history_end_turn_index,
        "dataset_version": "0.2",
        "case_uid": case_uid,
        "conversation_digest": conversation_digest,
    }
    case["target_status"] = "explicit_target"
    case["conversation_digest"] = conversation_digest
    return case


def _percentile(values: list[int], quantile: float) -> int | None:
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round((len(ordered) - 1) * quantile)))
    return ordered[index]


def _apply_dataset_label_status(dataset: dict[str, Any]) -> None:
    cases = dataset.get("cases") or []
    classifications = Counter(str(item.get("classification") or "unknown") for item in cases)
    approved_cases = [
        item for item in cases
        if item.get("classification") == "claim_accuracy_scorable"
        and ((item.get("reference_label") or {}).get("expected_claims") or [])
    ]
    approved_claim_count = sum(
        len((item.get("reference_label") or {}).get("expected_claims") or [])
        for item in approved_cases
    )
    approved_domains = {
        str(claim.get("strategy_group") or "").strip()
        for item in approved_cases
        for claim in ((item.get("reference_label") or {}).get("expected_claims") or [])
        if str(claim.get("strategy_group") or "").strip()
    }
    publishable = (
        approved_claim_count >= DEFAULT_MINIMUM_GOLD_LABELS
        and len(approved_domains) >= DEFAULT_MINIMUM_GOLD_DOMAINS
    )
    privacy_violation_count = sum(len(scan_privacy_output(case)) for case in cases)
    turn_counts = [len((item.get("conversation") or {}).get("turns") or []) for item in cases]
    roles = Counter()
    for item in cases:
        roles.update((item.get("conversation") or {}).get("role_counts") or {})
    dataset["dataset_status"] = (
        "privacy_validation_failed" if privacy_violation_count
        else "ready_for_accuracy_baseline" if publishable
        else "insufficient_gold_labels"
    )
    dataset["summary"] = {
        **(dataset.get("summary") or {}),
        "total_cases": len(cases),
        "classification_counts": dict(sorted(classifications.items())),
        "reference_available_count": classifications["reference_available"],
        "claim_label_pending_count": classifications["claim_label_pending"],
        "claim_labeled_accuracy_case_count": len(approved_cases),
        "claim_labeled_accuracy_count": approved_claim_count,
        "claim_labeled_business_domain_count": len(approved_domains),
        "project_accuracy_publishable": publishable,
        "privacy_scan_violation_count": privacy_violation_count,
        "role_counts": {role: int(roles.get(role, 0)) for role in ("BUYER", "AGENT", "SYSTEM")},
        "role_unresolved_case_count": sum(1 for item in cases if (item.get("conversation") or {}).get("role_unresolved_count")),
        "turn_count_p50": _percentile(turn_counts, 0.5),
        "turn_count_p95": _percentile(turn_counts, 0.95),
        "turn_count_max": max(turn_counts, default=0),
    }


def build_gold_dataset(secret: str, samples: Iterable[dict[str, Any]]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    cases = [build_gold_case(secret, sample) for sample in samples]
    cases.sort(key=lambda item: item["case_uid"])
    privacy_findings_by_case = {
        case["case_uid"]: scan_privacy_output(case)
        for case in cases
    }
    for case in cases:
        findings = privacy_findings_by_case[case["case_uid"]]
        if findings:
            case["classification"] = "privacy_review_required"
            case["notes"]["source_text_sanitized"] = False
            case["notes"]["privacy_review_required"] = True
            case["notes"]["privacy_reason_codes"] = [item["reason_code"] for item in findings]
        else:
            case["notes"]["source_text_sanitized"] = True
    privacy_violation_count = sum(len(items) for items in privacy_findings_by_case.values())
    dataset = {
        "dataset_id": "real_customer_service_gold_v0_1",
        "dataset_version": "0.1",
        "schema_version": DATASET_SCHEMA_VERSION,
        "source_provenance": "reviewed_training_samples_read_only",
        "privacy": {
            "identity_mode": "hmac_pseudonymized",
            "source_text_sanitized": privacy_violation_count == 0,
            "privacy_scan_status": "passed" if privacy_violation_count == 0 else "failed",
            "raw_source_identifiers_included": False if privacy_violation_count == 0 else None,
            "agent_input_contains_labels": False,
        },
        "dataset_status": "insufficient_gold_labels",
        "minimum_project_accuracy_denominator": DEFAULT_MINIMUM_GOLD_LABELS,
        "summary": {
            "total_cases": len(cases),
        },
        "cases": cases,
    }
    _apply_dataset_label_status(dataset)
    dataset["manifest"] = {"content_sha256": _dataset_hash(cases), "case_count": len(cases)}
    manual_queue = [
        {
            "case_uid": item["case_uid"],
            "query_class": item["query_class"],
            "risk_level": item["risk_level"],
            "customer_message": item["customer_message"],
            "sidecar_present": item["sidecar_present"],
            "labeling_required": ["expected_claims", "forbidden_claims", "must_handoff"],
        }
        for item in cases
        if item["classification"] in {"claim_label_pending", "reference_available", "label_gap", "safety_scorable"}
        and not (item.get("conversation") or {}).get("role_unresolved_count")
    ]
    return dataset, manual_queue


def build_gold_dataset_v2(secret: str, samples: Iterable[dict[str, Any]]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Build the immutable v0.2 candidate set without importing v0.1 labels."""
    cases = [build_gold_case_v2(secret, sample) for sample in samples]
    cases.sort(key=lambda item: item["case_uid"])
    privacy_findings_by_case = {
        case["case_uid"]: scan_privacy_output(case)
        for case in cases
    }
    for case in cases:
        findings = privacy_findings_by_case[case["case_uid"]]
        if findings:
            case["classification"] = "privacy_review_required"
            case["notes"]["source_text_sanitized"] = False
            case["notes"]["privacy_review_required"] = True
            case["notes"]["privacy_reason_codes"] = [item["reason_code"] for item in findings]
        else:
            case["notes"]["source_text_sanitized"] = True
    privacy_violation_count = sum(len(items) for items in privacy_findings_by_case.values())
    explicit_target_count = sum(bool(case.get("explicit_target")) for case in cases)
    missing_target_count = len(cases) - explicit_target_count
    dataset = {
        "dataset_id": "real_customer_service_gold_v0_2",
        "dataset_version": "0.2",
        "schema_version": DATASET_V2_SCHEMA_VERSION,
        "source_provenance": "reviewed_training_samples_read_only",
        "privacy": {
            "identity_mode": "hmac_pseudonymized",
            "source_text_sanitized": privacy_violation_count == 0,
            "privacy_scan_status": "passed" if privacy_violation_count == 0 else "failed",
            "raw_source_identifiers_included": False if privacy_violation_count == 0 else None,
            "agent_input_contains_labels": False,
        },
        "dataset_status": "insufficient_gold_labels",
        "minimum_project_accuracy_denominator": DEFAULT_MINIMUM_GOLD_LABELS,
        "summary": {
            "total_cases": len(cases),
            "explicit_target_count": explicit_target_count,
            "missing_target_count": missing_target_count,
            "ambiguous_target_count": 0,
            "automatically_approved_count": 0,
        },
        "cases": cases,
    }
    _apply_dataset_label_status(dataset)
    dataset["summary"].update({
        "explicit_target_count": explicit_target_count,
        "missing_target_count": missing_target_count,
        "ambiguous_target_count": 0,
        "automatically_approved_count": 0,
    })
    dataset["manifest"] = {
        "content_sha256": _dataset_hash(cases),
        "case_count": len(cases),
        "schema_version": DATASET_V2_SCHEMA_VERSION,
    }
    manual_queue = [
        {
            "case_uid": case["case_uid"],
            "query_class": case["query_class"],
            "risk_level": case["risk_level"],
            "customer_message": case["customer_message"],
            "sidecar_present": case["sidecar_present"],
            "target_turn_uid": (case.get("explicit_target") or {}).get("target_turn_uid"),
            "target_provenance": (case.get("explicit_target") or {}).get("target_provenance"),
            "labeling_required": ["expected_claims", "forbidden_claims", "must_handoff"],
        }
        for case in cases
        if case.get("explicit_target")
        and case["classification"] in {"claim_label_pending", "reference_available", "label_gap", "safety_scorable"}
        and not (case.get("conversation") or {}).get("role_unresolved_count")
    ]
    return dataset, manual_queue


def upgrade_gold_dataset_v2(
    secret: str,
    source_dataset: dict[str, Any],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Derive v0.2 from the authoritative v0.1 artifact without rereading its DB."""
    if source_dataset.get("dataset_version") != "0.1":
        raise ValueError("source_gold_dataset_version_invalid")
    findings = validate_gold_dataset(source_dataset)
    if findings:
        raise ValueError("source_gold_dataset_validation_failed:" + ",".join(findings))
    source_hash = str((source_dataset.get("manifest") or {}).get("content_sha256") or "")
    cases = [
        _with_explicit_target_v2(
            secret,
            case,
            source_kind="reviewed_gold_v0_1",
            source_field="customer_message",
        )
        for case in (source_dataset.get("cases") or [])
    ]
    cases.sort(key=lambda item: item["case_uid"])
    privacy_findings_by_case = {
        case["case_uid"]: scan_privacy_output(case)
        for case in cases
    }
    for case in cases:
        findings = privacy_findings_by_case[case["case_uid"]]
        notes = case.setdefault("notes", {})
        if findings:
            case["classification"] = "privacy_review_required"
            notes["source_text_sanitized"] = False
            notes["privacy_review_required"] = True
            notes["privacy_reason_codes"] = [item["reason_code"] for item in findings]
        else:
            notes["source_text_sanitized"] = True
    privacy_violation_count = sum(len(items) for items in privacy_findings_by_case.values())
    explicit_target_count = sum(bool(case.get("explicit_target")) for case in cases)
    dataset = {
        "dataset_id": "real_customer_service_gold_v0_2",
        "dataset_version": "0.2",
        "schema_version": DATASET_V2_SCHEMA_VERSION,
        "source_provenance": "authoritative_gold_v0_1_derived",
        "source_dataset": {
            "dataset_id": source_dataset.get("dataset_id"),
            "dataset_version": source_dataset.get("dataset_version"),
            "content_sha256": source_hash,
        },
        "privacy": {
            "identity_mode": "hmac_pseudonymized",
            "source_text_sanitized": privacy_violation_count == 0,
            "privacy_scan_status": "passed" if privacy_violation_count == 0 else "failed",
            "raw_source_identifiers_included": False if privacy_violation_count == 0 else None,
            "agent_input_contains_labels": False,
        },
        "dataset_status": "insufficient_gold_labels",
        "minimum_project_accuracy_denominator": DEFAULT_MINIMUM_GOLD_LABELS,
        "summary": {
            "total_cases": len(cases),
            "explicit_target_count": explicit_target_count,
            "missing_target_count": len(cases) - explicit_target_count,
            "ambiguous_target_count": 0,
            "automatically_approved_count": 0,
        },
        "cases": cases,
    }
    _apply_dataset_label_status(dataset)
    dataset["summary"].update({
        "explicit_target_count": explicit_target_count,
        "missing_target_count": len(cases) - explicit_target_count,
        "ambiguous_target_count": 0,
        "automatically_approved_count": 0,
    })
    dataset["manifest"] = {
        "content_sha256": _dataset_hash(cases),
        "case_count": len(cases),
        "schema_version": DATASET_V2_SCHEMA_VERSION,
        "source_dataset_sha256": source_hash,
    }
    manual_queue = [
        {
            "case_uid": case["case_uid"],
            "query_class": case["query_class"],
            "risk_level": case["risk_level"],
            "customer_message": case["customer_message"],
            "sidecar_present": case["sidecar_present"],
            "target_turn_uid": (case.get("explicit_target") or {}).get("target_turn_uid"),
            "target_provenance": (case.get("explicit_target") or {}).get("target_provenance"),
            "labeling_required": ["expected_claims", "forbidden_claims", "must_handoff"],
        }
        for case in cases
        if case.get("explicit_target")
        and case["classification"] in {"claim_label_pending", "reference_available", "label_gap", "safety_scorable"}
        and not (case.get("conversation") or {}).get("role_unresolved_count")
    ]
    return dataset, manual_queue


def scan_sensitive_data(value: Any) -> list[str]:
    def scrub_metadata(item: Any) -> Any:
        if isinstance(item, list):
            return [scrub_metadata(child) for child in item]
        if not isinstance(item, dict):
            return item
        return {
            key: scrub_metadata(child)
            for key, child in item.items()
            if key not in {
                "manifest", "case_uid", "turn_uid", "target_turn_uids", "pseudonymous_id", "speaker_uid", "sidecar_identity",
                "content_sha256", "dataset_hash", "source_snapshot_hash", "reviewer_actor_hash",
                "target_text_digest", "conversation_digest", "content_digest",
                "label_db_sha256", "historical_label_db_sha256", "migration_manifest_sha256", "old_audit_event_hash",
                "v1_approval_event_hash", "source_identity_digest",
                "v2_target_text_digest",
            }
        }

    content_findings = scan_privacy_output(scrub_metadata(value))
    controlled_findings = validate_controlled_identifiers(value)
    return sorted({item["reason_code"] for item in content_findings + controlled_findings})


def validate_gold_dataset(dataset: dict[str, Any]) -> list[str]:
    findings: list[str] = []
    schema_version = dataset.get("schema_version")
    if schema_version not in {DATASET_SCHEMA_VERSION, DATASET_V2_SCHEMA_VERSION}:
        findings.append("schema_version_invalid")
    cases = dataset.get("cases")
    if not isinstance(cases, list) or not cases:
        findings.append("no_cases")
        return findings
    seen: set[str] = set()
    for case in cases:
        case_uid = str(case.get("case_uid") or "")
        if not case_uid or case_uid in seen:
            findings.append("duplicate_or_missing_case_uid")
        seen.add(case_uid)
        if "reference_label" not in case or "conversation" not in case:
            findings.append("reference_label_missing")
        if any(key in case for key in ("order_no", "sku", "product_title", "sample_id")):
            findings.append("raw_identity_field_present")
        turns = list((case.get("conversation") or {}).get("turns") or [])
        turn_uids = [str(turn.get("turn_uid") or "") for turn in turns]
        if any(not uid for uid in turn_uids) or len(turn_uids) != len(set(turn_uids)):
            findings.append("conversation_turn_uid_missing_or_duplicate")
        for namespace, value in (case.get("sidecar_identity") or {}).items():
            if not re.fullmatch(rf"(?:product|sku|order)_[A-Z2-7]{{20}}", str(value or "")):
                findings.append(f"identity_not_hmac_pseudonymized:{namespace}")
        if schema_version == DATASET_V2_SCHEMA_VERSION:
            target = case.get("explicit_target")
            if target is None:
                if case.get("target_status") != "target_missing":
                    findings.append("explicit_target_status_invalid")
                continue
            required = {
                "target_turn_uid", "target_turn_index", "target_speaker_role", "target_text_digest",
                "target_source_type", "target_source_reference", "target_provenance",
                "history_end_turn_index", "dataset_version", "case_uid", "conversation_digest",
            }
            if not required.issubset(target):
                findings.append("explicit_target_fields_missing")
                continue
            target_uid = str(target.get("target_turn_uid") or "")
            target_turn = next((turn for turn in turns if str(turn.get("turn_uid") or "") == target_uid), None)
            if not target_turn:
                findings.append("explicit_target_turn_missing")
                continue
            if target.get("target_speaker_role") != "BUYER" or target_turn.get("speaker_role") != "BUYER":
                findings.append("explicit_target_role_invalid")
            if target.get("dataset_version") != "0.2" or target.get("case_uid") != case_uid:
                findings.append("explicit_target_scope_invalid")
            if target.get("target_source_type") != "reviewed_sample_customer_question":
                findings.append("explicit_target_source_invalid")
            if target.get("target_source_reference") != case_uid:
                findings.append("explicit_target_source_reference_invalid")
            text_digest = _sha256_text(str(target_turn.get("text") or ""))
            if target.get("target_text_digest") != text_digest:
                findings.append("explicit_target_text_digest_invalid")
            try:
                target_index = int(target.get("target_turn_index"))
                history_end_index = int(target.get("history_end_turn_index"))
                target_turn_index = int(target_turn.get("turn_index"))
            except (TypeError, ValueError):
                findings.append("explicit_target_index_invalid")
                continue
            if target_index != target_turn_index:
                findings.append("explicit_target_index_invalid")
            if history_end_index >= target_index:
                findings.append("explicit_target_history_boundary_invalid")
            if any(
                int(turn.get("turn_index") or 0) > target_index
                for turn in turns
            ):
                findings.append("future_turn_after_explicit_target")
            digest = _conversation_digest(turns)
            if target.get("conversation_digest") != digest or case.get("conversation_digest") != digest:
                findings.append("conversation_digest_invalid")
    expected_hash = ((dataset.get("manifest") or {}).get("content_sha256") or "")
    if expected_hash != _dataset_hash(cases):
        findings.append("manifest_hash_mismatch")
    findings.extend(scan_sensitive_data(dataset))
    privacy = dataset.get("privacy") or {}
    actual_scan_passed = not scan_sensitive_data(dataset)
    if privacy.get("privacy_scan_status") != ("passed" if actual_scan_passed else "failed"):
        findings.append("privacy_scan_status_unverified")
    if actual_scan_passed and privacy.get("raw_source_identifiers_included") is not False:
        findings.append("raw_identity_claim_unverified")
    return sorted(set(findings))


def apply_approved_claim_labels(dataset: dict[str, Any], labels: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """Attach only approved human labels to an in-memory evaluation view.

    The source Gold artifact remains immutable and labels never become Agent
    payload fields.  A case with approved claims is the only claim-accuracy
    denominator member.
    """
    result = copy.deepcopy(dataset)
    by_case = {
        str(item.get("case_uid")): item
        for item in labels
        if item.get("review_status") == "approved"
    }
    for case in result.get("cases") or []:
        label = by_case.get(str(case.get("case_uid") or ""))
        if not label:
            continue
        claims = ((label.get("label") or {}).get("claims") or [])
        target_turn_uids = list((label.get("label") or {}).get("target_turn_uids") or [])
        explicit_uid = str(((case.get("explicit_target") or {}).get("target_turn_uid") or ""))
        turns_by_uid = {
            str(turn.get("turn_uid") or ""): turn
            for turn in (case.get("conversation") or {}).get("turns") or []
        }
        if (
            not claims
            or not target_turn_uids
            or (explicit_uid and target_turn_uids != [explicit_uid])
            or any(
                uid not in turns_by_uid or turns_by_uid[uid].get("speaker_role") != "BUYER"
                for uid in target_turn_uids
            )
        ):
            continue
        case["reference_label"]["expected_claims"] = claims
        case["evaluation_target"] = {"target_turn_uids": target_turn_uids}
        case["classification"] = "claim_accuracy_scorable"
    _apply_dataset_label_status(result)
    result["manifest"] = {"content_sha256": _dataset_hash(result.get("cases") or []), "case_count": len(result.get("cases") or [])}
    return result


def _targeted_conversation(case: dict[str, Any]) -> tuple[str, list[dict[str, Any]]]:
    turns = list((case.get("conversation") or {}).get("turns") or [])
    target_uids = list((case.get("evaluation_target") or {}).get("target_turn_uids") or [])
    if not target_uids:
        raise ValueError("evaluation_target_missing")
    by_uid = {str(turn.get("turn_uid") or ""): turn for turn in turns}
    selected = [by_uid.get(uid) for uid in target_uids]
    if any(not turn or turn.get("speaker_role") != "BUYER" for turn in selected):
        raise ValueError("evaluation_target_invalid")
    ordered = sorted((turn for turn in selected if turn), key=lambda turn: int(turn.get("turn_index") or 0))
    last_target_index = max(int(turn.get("turn_index") or 0) for turn in ordered)
    message = "\n".join(str(turn.get("text") or "") for turn in ordered).strip()
    history_turns = [
        turn for turn in turns
        if int(turn.get("turn_index") or 0) < last_target_index
    ][-40:]
    from app.services.canonical_conversation_turn_service import normalize_conversation_turns

    canonical_history, _ = normalize_conversation_turns([
        {
            "role": turn.get("speaker_role"),
            "content": canonical_text(turn.get("text"), limit=600),
            "turn_uid": turn.get("turn_uid"),
            "turn_index": int(turn.get("turn_index") or 0),
            "message_type": turn.get("message_type"),
        }
        for turn in history_turns
        if canonical_text(turn.get("text"), limit=600)
    ], strict=True, max_turns=40)
    return canonical_text(message, limit=1800), canonical_history


def build_agent_payload(sample: dict[str, Any], *, case: dict[str, Any] | None = None) -> dict[str, Any]:
    """Build a runtime input from source data without any evaluation label."""
    if case and case.get("classification") == "claim_accuracy_scorable":
        message, conversation_history = _targeted_conversation(case)
    else:
        message = canonical_text(sample.get("customer_quote"), limit=1800)
        conversation_history = []
    return {
        "message": message,
        "conversation_history": conversation_history,
        "order_id": str(sample.get("order_no") or "").strip(),
        "sku_code": str(sample.get("sku") or "").strip(),
        "product_name": str(sample.get("product_title") or "").strip(),
        "conversation_id": f"real_accuracy_{sample.get('id')}",
        "copilot_context": {
            "evaluation_context_contract": "strict",
            "input_context_status": "valid" if case else "degraded_context",
            "sidecar_context": {
                "sidecar_product_title": str(sample.get("product_title") or "").strip(),
                "sidecar_sku_code": str(sample.get("sku") or "").strip(),
                "sidecar_order_id": str(sample.get("order_no") or "").strip(),
                "source": "real_accuracy_gold_set",
            },
        },
    }


def assert_label_not_in_agent_input(payload: dict[str, Any]) -> None:
    prohibited = {"correct_answer", "expected_claims", "forbidden_claims", "must_handoff", "rubric", "reference_label"}

    def walk(value: Any) -> set[str]:
        if isinstance(value, dict):
            return set(value) | set().union(*(walk(item) for item in value.values()))
        if isinstance(value, list):
            return set().union(*(walk(item) for item in value)) if value else set()
        return set()

    leaked = prohibited.intersection(walk(payload))
    if leaked:
        raise ValueError(f"evaluation_label_leaked_to_agent_input:{','.join(sorted(leaked))}")


def score_response(case: dict[str, Any], response: dict[str, Any]) -> dict[str, Any]:
    """Score only explicit manual claims; reviewed free text stays exploratory."""
    label = case.get("reference_label") or {}
    reply = canonical_text(
        response.get("sendable_reply") or response.get("suggested_reply") or response.get("draft_reply"),
        limit=2200,
    )
    expected_claims = label.get("expected_claims") or []
    covered: list[str] = []
    missing: list[str] = []
    for claim in expected_claims:
        claim_uid = str(claim.get("claim_uid") or "")
        terms = [canonical_text(term, limit=120) for term in claim.get("required_terms") or []]
        if not claim_uid or not terms:
            missing.append(claim_uid or "claim_without_match_contract")
        elif all(term in reply for term in terms):
            covered.append(claim_uid)
        else:
            missing.append(claim_uid)
    forbidden = [canonical_text(term, limit=120) for term in label.get("forbidden_claims") or []]
    forbidden_hits = [term for term in forbidden if term and term in reply]
    pipeline = response.get("analysis_pipeline") or {}
    return {
        "claim_score_available": bool(expected_claims),
        "expected_claim_count": len(expected_claims),
        "covered_claim_uids": covered,
        "missing_claim_uids": missing,
        "forbidden_claim_hits": forbidden_hits,
        "passed": bool(expected_claims) and not missing and not forbidden_hits,
        "formal_pipeline_verified": bool(pipeline.get("version")),
        "reply_status": str(response.get("reply_status") or ""),
        "can_send": bool(response.get("can_send")),
        "requires_human_review": bool(response.get("requires_human_review")),
    }


def query_coverage_rows(
    cases: Iterable[dict[str, Any]],
    baseline_results: Iterable[dict[str, Any]] = (),
) -> list[dict[str, Any]]:
    result_by_uid = {str(item.get("case_uid")): item for item in baseline_results if isinstance(item, dict)}
    grouped: dict[str, dict[str, Any]] = defaultdict(lambda: {
        "query_class": "", "question_count": 0, "sidecar_count": 0, "reference_label_count": 0,
        "formal_pipeline_count": 0, "formal_selected_evidence_count": 0, "admitted_evidence_count": 0,
        "unresolved_claim_count": 0, "handoff_count": 0,
    })
    for case in cases:
        key = str(case.get("query_class") or "unclassified")
        row = grouped[key]
        row["query_class"] = key
        row["question_count"] += 1
        row["sidecar_count"] += int(bool(case.get("sidecar_present")))
        row["reference_label_count"] += int(bool((case.get("reference_label") or {}).get("reference_text")))
        evaluated = result_by_uid.get(str(case.get("case_uid"))) or {}
        row["formal_pipeline_count"] += int(bool(evaluated.get("formal_pipeline_verified")))
        row["formal_selected_evidence_count"] += int(evaluated.get("formal_selected_evidence_count") or 0)
        row["admitted_evidence_count"] += int(evaluated.get("admitted_evidence_count") or 0)
        row["unresolved_claim_count"] += int(evaluated.get("unresolved_claim_count") or 0)
        row["handoff_count"] += int(bool(evaluated.get("requires_human_review")))
    rows = list(grouped.values())
    for row in rows:
        row["coverage_gap"] = next(
            (
                reason for reason, condition in (
                    ("context_gap", row["sidecar_count"] == 0),
                    ("label_gap", row["reference_label_count"] == 0),
                    ("pipeline_not_observed", row["formal_pipeline_count"] == 0),
                    ("formal_evidence_not_selected", row["formal_selected_evidence_count"] == 0),
                ) if condition
            ),
            "no_observed_gap",
        )
    return sorted(rows, key=lambda item: (-item["question_count"], item["query_class"]))
