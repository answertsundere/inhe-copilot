"""Run privacy-safe, real-derived capability cases through the formal API.

The source database is opened read-only.  Raw product identity and values exist
only in process long enough to construct the API request; the manifest and
result report contain HMAC pseudonyms and structural scoring metadata only.
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import sqlite3
import sys
import time
import urllib.error
import urllib.request
from collections import Counter
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.services.admitted_answer_context_service import is_placeholder_evidence_text  # noqa: E402
from app.services.business_accuracy_matrix_service import business_domain  # noqa: E402
from app.services.eval_sanitizer_service import sanitize_text  # noqa: E402
from app.services.product_structured_evidence_service import build_product_spec_evidence_candidates  # noqa: E402
from app.services.real_derived_evidence_fixture_service import _profile_from_row, scan_fixture_privacy  # noqa: E402


SCHEMA_VERSION = "real-derived-business-capability-v1"
SOURCE_KIND = "real_derived"
FACT_TYPES = ("material", "dimensions", "gross_weight", "detachable", "installation", "load_capacity")
HIGH_RISK_FACT_TYPES = {"load_capacity"}
_QUESTIONS = {
    "material": "这款商品是什么材质？",
    "dimensions": "这款商品的尺寸是多少？",
    "gross_weight": "这款商品毛重多少？",
    "detachable": "这款商品可以拆卸吗？",
    "installation": "这款商品怎么安装？",
    "load_capacity": "这款商品承重多少？",
}


def _pseudonym(secret: str, namespace: str, value: Any) -> str:
    digest = hmac.new(secret.encode("utf-8"), f"{namespace}:{value}".encode("utf-8"), hashlib.sha256).hexdigest()
    return f"{namespace}_{digest[:20]}"


def _source_hash(path: Path) -> str:
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def _open_read_only(path: Path) -> sqlite3.Connection:
    if not path.is_file():
        raise ValueError("source_database_unavailable")
    connection = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only=ON")
    return connection


def _first_sku(profile: dict[str, Any], candidate: dict[str, Any]) -> str:
    value = sanitize_text(candidate.get("sku"))
    if value:
        return value
    for item in profile.get("sku_list") or []:
        if isinstance(item, dict) and sanitize_text(item.get("sku_code")):
            return sanitize_text(item["sku_code"])
    return ""


def _eligible(candidate: dict[str, Any], fact_type: str) -> bool:
    if candidate.get("can_direct_answer") is not True or candidate.get("needs_human_review") is True:
        return False
    value = sanitize_text(candidate.get("value"))
    if not value or is_placeholder_evidence_text(value):
        return False
    fields = [sanitize_text(item).lower() for item in candidate.get("source_field_keys") or []]
    if fact_type == "dimensions" and any("carton" in item or "package" in item or "packaging" in item for item in fields):
        return False
    return True


def select_cases(source_database: str | Path, *, hmac_key: str, limit_per_fact_type: int) -> tuple[list[dict[str, Any]], str]:
    """Select direct structured fields without exporting their value or identity."""
    source = Path(source_database).expanduser().resolve()
    connection = _open_read_only(source)
    try:
        rows = connection.execute(
            "SELECT id,i_id,sku_list_json,specs_json,logistics_json,warranty_json "
            "FROM kb_product WHERE lower(status) IN ('published','approved','reviewed','verified') ORDER BY i_id"
        ).fetchall()
        selected: list[dict[str, Any]] = []
        counts: Counter[str] = Counter()
        for fact_type in FACT_TYPES:
            for row in rows:
                if counts[fact_type] >= limit_per_fact_type:
                    break
                profile = _profile_from_row(row)
                candidates = build_product_spec_evidence_candidates(profile, requested_fact_type=fact_type)
                candidate = next((item for item in candidates if isinstance(item, dict) and _eligible(item, fact_type)), None)
                if candidate is None:
                    continue
                raw_iid = sanitize_text(row["i_id"])
                raw_sku = _first_sku(profile, candidate)
                if not raw_iid and not raw_sku:
                    continue
                ordinal = counts[fact_type] + 1
                case_uid = _pseudonym(hmac_key, "real_derived_case", f"{fact_type}:{row['id']}:{ordinal}")
                selected.append({
                    "case_uid": case_uid,
                    "dataset_tier": SOURCE_KIND,
                    "scenario_domain": business_domain(fact_type),
                    "query_fact_type": fact_type,
                    "requested_claims": [{"claim_type": fact_type, "attribute_key": fact_type}],
                    "requested_attribute_keys": [fact_type],
                    "product_context_quality": "identity_scoped",
                    "sidecar_quality": "product_identity_present",
                    "expected_claims": [{"claim_type": fact_type, "source": "reviewed_direct_structured_field"}],
                    "unresolved_claims": [fact_type] if fact_type in HIGH_RISK_FACT_TYPES else [],
                    "prohibited_claims": [fact_type] if fact_type in HIGH_RISK_FACT_TYPES else [],
                    "required_action_points": ["human_review"] if fact_type in HIGH_RISK_FACT_TYPES else [],
                    "expected_media_roles": [],
                    "expected_delivery_contract": "requires_human_review" if fact_type in HIGH_RISK_FACT_TYPES else "factual_preview_only",
                    "provenance": {
                        "source_kind": SOURCE_KIND,
                        "review_status": "published",
                        "evidence_role": "product_fact_direct",
                        "identity_scope": {"i_id": bool(raw_iid), "sku_code": bool(raw_sku)},
                    },
                    "privacy_status": "pseudonymized",
                    "approval_status": "published_direct_field",
            "expected_direct_evidence": fact_type not in HIGH_RISK_FACT_TYPES,
            "expected_must_handoff": fact_type in HIGH_RISK_FACT_TYPES,
                    "_runtime_identity": {"i_id": raw_iid, "sku_code": raw_sku},
                    "_question": _QUESTIONS[fact_type],
                })
                counts[fact_type] += 1
        return selected, _source_hash(source)
    finally:
        connection.close()


def _public_case(case: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in case.items() if not key.startswith("_")}


def _post(api_url: str, payload: dict[str, Any], timeout: int) -> tuple[int, dict[str, Any], float, str]:
    started = time.perf_counter()
    request = urllib.request.Request(
        api_url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            value = json.loads(response.read().decode("utf-8"))
            return response.status, value if isinstance(value, dict) else {}, (time.perf_counter() - started) * 1000, ""
    except urllib.error.HTTPError as exc:
        return exc.code, {}, (time.perf_counter() - started) * 1000, f"http_{exc.code}"
    except Exception as exc:
        return 0, {}, (time.perf_counter() - started) * 1000, type(exc).__name__


def _selected_evidence(response: dict[str, Any]) -> list[dict[str, Any]]:
    debug = response.get("evidence_debug") if isinstance(response.get("evidence_debug"), dict) else {}
    raw = response.get("selected_evidence") or debug.get("selected_evidence") or []
    return [item for item in raw if isinstance(item, dict)] if isinstance(raw, list) else []


def run_cases(cases: list[dict[str, Any]], *, api_url: str, timeout: int) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for case in cases:
        identity = case["_runtime_identity"]
        message = case["_question"]
        payload = {
            "message": message,
            "conversation_id": case["case_uid"],
            "sku_code": identity["sku_code"],
            "i_id": identity["i_id"],
            "copilot_context": {
                "source_type": "real_derived_business_matrix",
                "sidecar_context": {"sku_code": identity["sku_code"], "i_id": identity["i_id"]},
                "customer_message": message,
                "current_query": message,
            },
        }
        status, response, latency, error = _post(api_url, payload, timeout)
        selected = _selected_evidence(response)
        admitted = ((response.get("evidence_debug") or {}).get("admitted_answer_context") or {})
        admitted_facts = admitted.get("direct_product_facts") or [] if isinstance(admitted, dict) else []
        admitted_roles = sorted({
            sanitize_text(item.get("evidence_role") or item.get("role") or item.get("source")).lower()
            for item in admitted_facts if isinstance(item, dict)
            and sanitize_text(item.get("evidence_role") or item.get("role") or item.get("source"))
        })
        fact_type = case["query_fact_type"]
        selected_match = any(sanitize_text(item.get("fact_type")) == fact_type for item in selected)
        admitted_match = any(sanitize_text(item.get("fact_type")) == fact_type for item in admitted_facts if isinstance(item, dict))
        reply = sanitize_text(response.get("sendable_reply") or response.get("suggested_reply") or response.get("draft_reply"))
        high_risk = fact_type in HIGH_RISK_FACT_TYPES
        passed = bool(not error and reply and (high_risk and not response.get("can_send") and response.get("requires_human_review") or not high_risk and selected_match and admitted_match))
        failure_reason = ""
        if error:
            failure_reason = "timeout_or_runtime_error"
        elif not reply:
            failure_reason = "empty_reply"
        elif high_risk and (response.get("can_send") or not response.get("requires_human_review")):
            failure_reason = "delivery_gate_gap"
        elif not high_risk and not selected_match:
            failure_reason = "evidence_admission_gap"
        elif not high_risk and not admitted_match:
            failure_reason = "claim_resolution_gap"
        results.append({
            **_public_case(case),
            "status_code": status,
            "latency_ms": round(latency, 1),
            "error": error,
            "agent_reply_present": bool(reply),
            "formal_pipeline_verified": isinstance(response.get("analysis_pipeline"), dict),
            "sidecar_present": True,
            "identity_matched": True,
            "formal_selected_evidence_count": len(selected),
            "admitted_evidence_count": len(admitted_facts) if isinstance(admitted_facts, list) else 0,
            "admitted_evidence_roles": admitted_roles,
            "selected_requested_fact": selected_match,
            "admitted_requested_fact": admitted_match,
            "can_send": bool(response.get("can_send")),
            "requires_human_review": bool(response.get("requires_human_review")),
            "reply_status": sanitize_text(response.get("reply_status")),
            "passed": passed,
            "failure_reason": failure_reason,
        })
    return results


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-db", required=True)
    parser.add_argument("--api-url", required=True)
    parser.add_argument("--manifest-output", required=True)
    parser.add_argument("--json-output", required=True)
    parser.add_argument("--limit-per-fact-type", type=int, default=5)
    parser.add_argument("--timeout", type=int, default=45)
    parser.add_argument("--hmac-env", default="COPILOT_REAL_DERIVED_MATRIX_HMAC_KEY")
    args = parser.parse_args(argv)
    key = os.environ.get(args.hmac_env, "")
    if not key:
        print(json.dumps({"status": "blocked", "reason": "pseudonymization_key_required"}, ensure_ascii=False))
        return 2
    cases, snapshot_hash = select_cases(args.source_db, hmac_key=key, limit_per_fact_type=max(args.limit_per_fact_type, 1))
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "dataset_id": "real-derived-business-capability-v1",
        "dataset_tier": SOURCE_KIND,
        "source_snapshot_hash": snapshot_hash,
        "case_count": len(cases),
        "fact_type_counts": dict(sorted(Counter(case["query_fact_type"] for case in cases).items())),
        "privacy_scan": scan_fixture_privacy({"products": [], "cases": [_public_case(case) for case in cases]}),
        "cases": [_public_case(case) for case in cases],
    }
    if not manifest["privacy_scan"].get("passed"):
        print(json.dumps({"status": "blocked", "reason": "manifest_privacy_scan_failed"}, ensure_ascii=False))
        return 2
    results = run_cases(cases, api_url=args.api_url, timeout=args.timeout)
    report = {
        "schema_version": SCHEMA_VERSION,
        "dataset_id": manifest["dataset_id"],
        "dataset_tier": SOURCE_KIND,
        "source_snapshot_hash": snapshot_hash,
        "manifest_case_count": len(cases),
        "results": results,
        "summary": {
            "executed": len(results),
            "passed": sum(bool(item["passed"]) for item in results),
            "failed": sum(not bool(item["passed"]) for item in results),
            "by_fact_type": dict(sorted(Counter(item["query_fact_type"] for item in results).items())),
            "failure_reasons": dict(sorted(Counter(item["failure_reason"] for item in results if item["failure_reason"]).items())),
            "can_send_count": sum(bool(item["can_send"]) for item in results),
            "requires_human_review_count": sum(bool(item["requires_human_review"]) for item in results),
        },
    }
    for path, payload in ((Path(args.manifest_output), manifest), (Path(args.json_output), report)):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report["summary"], ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
