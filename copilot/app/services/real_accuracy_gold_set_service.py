"""Privacy-safe, read-only contracts for real customer-service accuracy evaluation.

The production Agent never imports this module.  It turns reviewed source rows
into an evaluation artifact and makes the boundary between labels and runtime
inputs explicit.  A correct answer is assessment data, not customer-service
knowledge or Agent context.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
import sqlite3
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable

from app.services.eval_sanitizer_service import sanitize_text


DATASET_SCHEMA_VERSION = "real-accuracy-gold-set-v1"
DEFAULT_MINIMUM_GOLD_LABELS = 30
_REQUIRED_SAMPLE_COLUMNS = {
    "id", "customer_quote", "full_context", "product_title", "sku", "order_no",
    "question_type", "correct_answer", "review_status", "risk_level", "need_media",
}
_IMAGE_OR_LINK_RE = re.compile(r"(?:\[图片[^\]]*\]|https?://\S+|data:image/)", re.I)
_HTML_RE = re.compile(r"<[^>]+>")
_PHONE_RE = re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)")
_LONG_ID_RE = re.compile(r"(?<!\d)\d{12,}(?!\d)")
_SECRET_RE = re.compile(r"(?i)(?:api[_-]?key|token|secret|password|authorization)\s*[:=]\s*[^\s&]+")

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
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.I)
    text = re.sub(r"</(?:p|div|li|tr|h\d)>", "\n", text, flags=re.I)
    text = _HTML_RE.sub(" ", text)
    text = re.sub(r"\s+", " ", text).strip()
    text = sanitize_text(text)
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


def _has_sidecar(sample: dict[str, Any]) -> bool:
    return any(str(sample.get(key) or "").strip() for key in ("product_title", "sku", "order_no"))


def classify_sample(sample: dict[str, Any]) -> str:
    """Classify eligibility only; this does not infer a customer fact type."""
    if _is_media_only(sample):
        return "media_only"
    if not _has_text_question(sample):
        return "invalid"
    if not _has_sidecar(sample):
        return "context_gap"
    if canonical_text(sample.get("correct_answer"), limit=120):
        return "accuracy_scorable"
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
            result[key] = hmac_identifier(secret, namespace, value)
    return result


def build_gold_case(secret: str, sample: dict[str, Any]) -> dict[str, Any]:
    classification = classify_sample(sample)
    source_uid = hmac_identifier(secret, "training_sample", sample.get("id"))
    reference = canonical_text(sample.get("correct_answer"), limit=1800)
    action_points = reference_action_points(reference) if classification == "accuracy_scorable" else []
    return {
        "case_uid": source_uid,
        "source": {"kind": "reviewed_training_sample", "pseudonymous_id": source_uid},
        "classification": classification,
        "customer_message": canonical_text(sample.get("customer_quote")),
        "conversation_context": canonical_text(sample.get("full_context"), limit=2400),
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
            "needs_claim_level_review": bool(reference) and not action_points,
            "media_requested": bool(sample.get("need_media")),
            "source_text_sanitized": True,
            "identity_pseudonymized": True,
        },
    }


def _dataset_hash(cases: list[dict[str, Any]]) -> str:
    canonical = json.dumps(cases, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def build_gold_dataset(secret: str, samples: Iterable[dict[str, Any]]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    cases = [build_gold_case(secret, sample) for sample in samples]
    cases.sort(key=lambda item: item["case_uid"])
    counts = Counter(item["classification"] for item in cases)
    accuracy_candidates = counts["accuracy_scorable"]
    claim_labeled = sum(1 for item in cases if item["reference_label"]["expected_claims"])
    dataset = {
        "dataset_id": "real_customer_service_gold_v0_1",
        "dataset_version": "0.1",
        "schema_version": DATASET_SCHEMA_VERSION,
        "source_provenance": "reviewed_training_samples_read_only",
        "privacy": {
            "identity_mode": "hmac_pseudonymized",
            "source_text_sanitized": True,
            "raw_source_identifiers_included": False,
            "agent_input_contains_labels": False,
        },
        "dataset_status": "ready_for_manual_claim_labeling" if claim_labeled >= DEFAULT_MINIMUM_GOLD_LABELS else "insufficient_gold_labels",
        "minimum_project_accuracy_denominator": DEFAULT_MINIMUM_GOLD_LABELS,
        "summary": {
            "total_cases": len(cases),
            "classification_counts": dict(sorted(counts.items())),
            "accuracy_candidate_count": accuracy_candidates,
            "claim_labeled_accuracy_count": claim_labeled,
            "project_accuracy_publishable": claim_labeled >= DEFAULT_MINIMUM_GOLD_LABELS,
        },
        "cases": cases,
    }
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
        if item["classification"] in {"accuracy_scorable", "label_gap", "safety_scorable"}
    ]
    return dataset, manual_queue


def scan_sensitive_data(value: Any) -> list[str]:
    serialized = json.dumps(value, ensure_ascii=False, sort_keys=True)
    findings: list[str] = []
    if _PHONE_RE.search(serialized):
        findings.append("phone_number_detected")
    if _LONG_ID_RE.search(serialized):
        findings.append("long_numeric_identifier_detected")
    if _SECRET_RE.search(serialized):
        findings.append("credential_detected")
    return findings


def validate_gold_dataset(dataset: dict[str, Any]) -> list[str]:
    findings: list[str] = []
    if dataset.get("schema_version") != DATASET_SCHEMA_VERSION:
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
        if "reference_label" not in case:
            findings.append("reference_label_missing")
        if any(key in case for key in ("order_no", "sku", "product_title", "sample_id")):
            findings.append("raw_identity_field_present")
        for namespace, value in (case.get("sidecar_identity") or {}).items():
            if not re.fullmatch(rf"(?:product|sku|order)_[A-Z2-7]{{20}}", str(value or "")):
                findings.append(f"identity_not_hmac_pseudonymized:{namespace}")
    expected_hash = ((dataset.get("manifest") or {}).get("content_sha256") or "")
    if expected_hash != _dataset_hash(cases):
        findings.append("manifest_hash_mismatch")
    findings.extend(scan_sensitive_data(dataset))
    return sorted(set(findings))


def build_agent_payload(sample: dict[str, Any]) -> dict[str, Any]:
    """Build a runtime input from source data without any evaluation label."""
    return {
        "message": canonical_text(sample.get("customer_quote"), limit=1800),
        "conversation_history": canonical_text(sample.get("full_context"), limit=3000),
        "order_id": str(sample.get("order_no") or "").strip(),
        "sku_code": str(sample.get("sku") or "").strip(),
        "product_name": str(sample.get("product_title") or "").strip(),
        "conversation_id": f"real_accuracy_{sample.get('id')}",
        "copilot_context": {
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
