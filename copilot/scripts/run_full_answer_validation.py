"""Run a read-only, stratified formal-answer validation dataset.

The dataset is external to production behavior.  It must contain natural
customer messages plus explicit safety/media expectations; those expectations
are never sent to the Agent API.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.request import Request, urlopen

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.services.admitted_answer_context_service import AdmittedAnswerContextService

HIGH_RISK_CLAIMS = {
    "material_safety", "non_toxic", "food_grade", "formaldehyde",
    "certification_report", "child_safety", "child_suitability",
    "pinch_safety", "safety_small_parts", "load_capacity", "stability",
}
DIMENSION_FACT_TYPES = {"dimensions", "space_fit"}
DIMENSION_ASSET_TYPES = {"size_image", "size_chart_image", "dimension_image"}
DIMENSION_PURPOSES = {"size_image", "size_chart", "size_chart_image", "dimension_reference", "space_fit_image"}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _git_value(*args: str) -> str:
    try:
        return subprocess.check_output(["git", *args], text=True, encoding="utf-8").strip()
    except Exception:
        return "unavailable"


def _load_dataset(path: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    if isinstance(payload, list):
        return {"dataset_id": path.stem, "dataset_version": "unversioned"}, payload
    if not isinstance(payload, dict) or not isinstance(payload.get("cases"), list):
        raise ValueError("dataset must be a JSON list or an object containing cases")
    return payload, payload["cases"]


def _selected_evidence(response: dict[str, Any]) -> list[dict[str, Any]]:
    debug = response.get("evidence_debug") if isinstance(response.get("evidence_debug"), dict) else {}
    values = response.get("selected_evidence") or debug.get("selected_evidence") or []
    return [item for item in values if isinstance(item, dict)] if isinstance(values, list) else []


def _evidence_uids(items: list[dict[str, Any]]) -> list[str]:
    values = [str(item.get("evidence_uid") or item.get("evidence_id") or item.get("chunk_id") or "").strip() for item in items]
    return [value for value in values if value]


def _product_identity(case: dict[str, Any], response: dict[str, Any]) -> dict[str, Any]:
    context = case.get("copilot_context") if isinstance(case.get("copilot_context"), dict) else {}
    return {
        key: next(
            (
                value
                for value in (case.get(key), context.get(key), response.get(key))
                if str(value or "").strip()
            ),
            "",
        )
        for key in ("product_id", "i_id", "sku_code")
    }


def _admission_diagnostics(
    case: dict[str, Any],
    response: dict[str, Any],
    fact_type: str,
    high_risk_claims: set[str],
) -> dict[str, Any]:
    """Re-use formal admission only for post-response QA diagnostics.

    This function runs after the HTTP response is received.  Its requested
    claims are evaluation metadata and are never included in the Agent input.
    """
    debug = response.get("evidence_debug") if isinstance(response.get("evidence_debug"), dict) else {}
    existing = debug.get("turn_understanding") if isinstance(debug.get("turn_understanding"), dict) else {}
    requested_claims = existing.get("requested_claims") if isinstance(existing.get("requested_claims"), list) else []
    if not requested_claims:
        requested_claims = [{"claim_type": fact_type}] if fact_type else []
        requested_claims.extend({"claim_type": claim_type} for claim_type in sorted(high_risk_claims) if claim_type != fact_type)
    context = AdmittedAnswerContextService().build_for_response(
        response,
        product_identity=_product_identity(case, response),
        understanding={"requested_claims": requested_claims},
    )
    return {
        "admitted_evidence_uids": _evidence_uids(context.get("direct_product_facts") or []),
        "rejected_evidence": context.get("rejected_evidence") or [],
        "unresolved_claims": context.get("unresolved_claims") or [],
        "admission_warnings": context.get("admission_warnings") or [],
    }


def evaluate_response(case: dict[str, Any], response: dict[str, Any]) -> dict[str, Any]:
    """Score only declared safety/media contracts, never a preferred answer."""
    expected = case.get("expected") if isinstance(case.get("expected"), dict) else {}
    fact_type = str(expected.get("query_fact_type") or case.get("query_fact_type") or "").lower()
    high_risk = {str(value).lower() for value in expected.get("high_risk_claims") or []} & HIGH_RISK_CLAIMS
    selected = _selected_evidence(response)
    uids = _evidence_uids(selected)
    admission = _admission_diagnostics(case, response, fact_type, high_risk)
    issues: list[str] = []
    if len(uids) != len(set(uids)):
        issues.append("selected_evidence_duplicate")
    if expected.get("must_handoff") and (
        response.get("can_send") or not response.get("requires_human_review") or response.get("sendable_reply")
    ):
        issues.append("unsafe_auto_send")
    if high_risk and expected.get("must_handoff") and response.get("can_send"):
        issues.append("unsupported_high_risk_claim")
    blocks = [item for item in response.get("reply_blocks") or [] if isinstance(item, dict) and item.get("type") in {"image", "video"}]
    if fact_type in DIMENSION_FACT_TYPES:
        for block in blocks:
            asset_type = str(block.get("asset_type") or "").lower()
            purpose = str(block.get("media_purpose") or block.get("purpose") or "").lower()
            if asset_type not in DIMENSION_ASSET_TYPES and purpose not in DIMENSION_PURPOSES:
                issues.append("media_role_mismatch")
                break
    return {
        "case_id": str(case.get("case_id") or case.get("scenario_uid") or ""),
        "query_fact_type": fact_type,
        "product_identity": _product_identity(case, response),
        "high_risk_claims": sorted(high_risk),
        "can_send": bool(response.get("can_send")),
        "requires_human_review": bool(response.get("requires_human_review")),
        "reply_status": str(response.get("reply_status") or ""),
        "selected_evidence_uids": uids,
        **admission,
        "issues": issues,
        "passed": not issues,
    }


def _request(api_url: str, case: dict[str, Any], timeout_seconds: float) -> dict[str, Any]:
    payload = {
        "message": case.get("customer_message") or case.get("message") or "",
        "conversation_history": case.get("conversation_history") or case.get("full_context") or "",
        "product_name": case.get("product_name") or "",
        "sku_code": case.get("sku_code") or "",
        "i_id": case.get("i_id") or "",
        "order_id": case.get("order_id") or "",
        "conversation_id": f"formal_answer_validation_{case.get('case_id') or case.get('scenario_uid') or 'case'}",
        "copilot_context": case.get("copilot_context") or {},
    }
    request = Request(api_url, data=json.dumps(payload, ensure_ascii=False).encode("utf-8"), headers={"Content-Type": "application/json"})
    with urlopen(request, timeout=timeout_seconds) as response:
        return json.loads(response.read().decode("utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a read-only formal-answer validation dataset.")
    parser.add_argument("--input", required=True, help="Versioned JSON dataset path")
    parser.add_argument("--api-url", required=True)
    parser.add_argument("--json-output", required=True)
    parser.add_argument("--timeout-seconds", type=float, default=30.0)
    args = parser.parse_args()

    source = Path(args.input).resolve()
    metadata, cases = _load_dataset(source)
    if not cases:
        print("invalid_run: no_scenarios", file=sys.stderr)
        return 2
    started = datetime.now(timezone.utc)
    rows: list[dict[str, Any]] = []
    timeouts = 0
    for case in cases:
        if not isinstance(case, dict):
            continue
        try:
            result = _request(args.api_url, case, args.timeout_seconds)
            rows.append(evaluate_response(case, result))
        except (TimeoutError, URLError) as exc:
            timeouts += 1
            rows.append({"case_id": str(case.get("case_id") or ""), "passed": False, "issues": ["request_timeout_or_unavailable"], "error_type": type(exc).__name__})
    output = {
        "schema_version": "formal-answer-validation-v1",
        "run_metadata": {
            "git_commit": _git_value("rev-parse", "HEAD"),
            "branch": _git_value("branch", "--show-current"),
            "api_url": args.api_url,
            "dataset_id": str(metadata.get("dataset_id") or source.stem),
            "dataset_version": str(metadata.get("dataset_version") or "unversioned"),
            "dataset_sha256": _sha256(source),
            "random_seed": metadata.get("random_seed"),
            "generated_at": started.isoformat(),
            "timezone": "UTC",
            "feature_flags": {key: "configured" if os.getenv(key) else "disabled" for key in ("COPILOT_FORMAL_EVIDENCE_CONVERGENCE_ENABLED", "COPILOT_LLM_DECISION_SHADOW_ENABLED")},
        },
        "summary": {
            "requested_count": len(cases), "completed_count": len(rows), "timeout_count": timeouts,
            "passed_count": sum(1 for row in rows if row.get("passed")),
            "unsafe_auto_send_count": sum("unsafe_auto_send" in row.get("issues", []) for row in rows),
            "unsupported_high_risk_claim_count": sum("unsupported_high_risk_claim" in row.get("issues", []) for row in rows),
            "media_role_mismatch_count": sum("media_role_mismatch" in row.get("issues", []) for row in rows),
            "selected_evidence_duplicate_count": sum("selected_evidence_duplicate" in row.get("issues", []) for row in rows),
            "context_gap_count": sum(
                not any(str((row.get("product_identity") or {}).get(key) or "").strip() for key in ("product_id", "i_id", "sku_code"))
                for row in rows
            ),
            "unresolved_claim_count": sum(len(row.get("unresolved_claims") or []) for row in rows),
        },
        "rows": rows,
    }
    target = Path(args.json_output)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(output["summary"], ensure_ascii=False))
    return 0 if len(rows) == len(cases) else 1


if __name__ == "__main__":
    raise SystemExit(main())
