"""Run Gold Set cases through the formal HTTP AnalysisPipeline only.

The script joins HMAC case identities with a read-only source database in
memory.  Gold labels are deliberately absent from HTTP payloads.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from collections import Counter
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from app.services.eval_sanitizer_service import sanitize_obj  # noqa: E402
from app.services.real_accuracy_gold_set_service import (  # noqa: E402
    apply_approved_claim_labels,
    assert_label_not_in_agent_input,
    build_agent_payload,
    hmac_identifier,
    load_reviewed_training_samples,
    score_response,
    validate_gold_dataset,
)
from app.services.real_accuracy_label_service import RealAccuracyLabelStore, approved_claim_gate_summary  # noqa: E402
from app.services.real_accuracy_privacy_service import sanitize_gold_text  # noqa: E402


def _post(url: str, payload: dict[str, Any], timeout: int) -> tuple[int, dict[str, Any], float, str]:
    started = time.perf_counter()
    request = urllib.request.Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, json.loads(response.read().decode("utf-8")), (time.perf_counter() - started) * 1000, ""
    except urllib.error.HTTPError as exc:
        return exc.code, {}, (time.perf_counter() - started) * 1000, f"http_{exc.code}"
    except Exception as exc:
        return 0, {}, (time.perf_counter() - started) * 1000, type(exc).__name__


def _safe_evidence_count(response: dict[str, Any], key: str) -> int:
    return len(response.get(key) or []) if isinstance(response.get(key), list) else 0


def _run_case(case: dict[str, Any], source: dict[str, Any], url: str, timeout: int) -> dict[str, Any]:
    payload = build_agent_payload(source, case=case)
    assert_label_not_in_agent_input(payload)
    status, response, latency, error = _post(url, payload, timeout)
    score = score_response(case, response)
    debug = response.get("evidence_debug") if isinstance(response.get("evidence_debug"), dict) else {}
    admitted = (response.get("admitted_answer_context") or debug.get("admitted_answer_context") or {})
    reply = sanitize_gold_text(response.get("sendable_reply") or response.get("suggested_reply") or response.get("draft_reply") or "")
    return sanitize_obj({
        "case_uid": case["case_uid"],
        "input_contract": "target_turn_bound" if case.get("evaluation_target") else "source_customer_quote_exploratory",
        "target_turn_uids": list((case.get("evaluation_target") or {}).get("target_turn_uids") or []),
        "classification": case["classification"],
        "query_class": case["query_class"],
        "status_code": status,
        "latency_ms": round(latency, 1),
        "error": error,
        "agent_reply": reply,
        "formal_pipeline_verified": score["formal_pipeline_verified"],
        "formal_selected_evidence_count": _safe_evidence_count(response, "selected_evidence"),
        "admitted_evidence_count": len(admitted.get("direct_product_facts") or []) if isinstance(admitted, dict) else 0,
        "unresolved_claim_count": len(admitted.get("unresolved_claims") or []) if isinstance(admitted, dict) else 0,
        "reply_status": score["reply_status"],
        "can_send": score["can_send"],
        "requires_human_review": score["requires_human_review"],
        "score": score,
        "labels_sent_to_agent": False,
    })


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gold-set", required=True)
    parser.add_argument("--source-db", required=True)
    parser.add_argument("--analyze-url", required=True)
    parser.add_argument("--json-output", required=True)
    parser.add_argument("--timeout", type=int, default=45)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--hmac-env", default="COPILOT_GOLD_SET_HMAC_KEY")
    parser.add_argument("--label-db", default="", help="Optional independent human-label SQLite database")
    parser.add_argument("--approved-only", action="store_true", help="Run only cases with approved claim labels")
    args = parser.parse_args(argv)
    if os.environ.get("COPILOT_FORMAL_EVIDENCE_CONVERGENCE_ENABLED", "").strip().lower() in {"1", "true", "yes", "on"}:
        print(json.dumps({"error": "formal_evidence_convergence_must_remain_disabled"}, ensure_ascii=False))
        return 2
    dataset = json.loads(Path(args.gold_set).read_text(encoding="utf-8"))
    validation_findings = validate_gold_dataset(dataset)
    if validation_findings or (dataset.get("privacy") or {}).get("privacy_scan_status") != "passed":
        print(json.dumps({"error": "gold_set_privacy_validation_failed", "reason_codes": validation_findings}, ensure_ascii=False))
        return 2
    if args.approved_only and not args.label_db:
        print(json.dumps({"error": "approved_only_requires_label_store"}, ensure_ascii=False))
        return 2
    if args.label_db:
        known_case_uids = {str(item.get("case_uid") or "") for item in dataset.get("cases") or []}
        store = RealAccuracyLabelStore(args.label_db)
        labels = [
            item
            for item in store.list_for_dataset(str(dataset.get("dataset_version") or ""))
            if str(item.get("case_uid") or "") in known_case_uids
        ]
        if args.approved_only:
            gate = approved_claim_gate_summary(
                labels,
                store.list_events_for_dataset(str(dataset.get("dataset_version") or "")),
            )
            if gate["publish_status"] != "ready_for_accuracy_baseline":
                print(json.dumps({
                    "error": "awaiting_supervisor_approval",
                    "approved_claim_count": gate["approved_claim_count"],
                    "approved_domain_count": gate["approved_domain_count"],
                    "missing_approved_claim_count": gate["missing_approved_claim_count"],
                    "missing_approved_domain_count": gate["missing_approved_domain_count"],
                }, ensure_ascii=False))
                return 2
        dataset = apply_approved_claim_labels(dataset, labels)
    else:
        labels = []
    secret = os.environ.get(args.hmac_env, "")
    if not secret:
        print(json.dumps({"error": "gold_set_hmac_key_missing"}, ensure_ascii=False))
        return 2
    label_status_counts = Counter(str(item.get("review_status") or "unknown") for item in labels)
    source_by_case = {
        hmac_identifier(secret, "training_sample", sample.get("id")): sample
        for sample in load_reviewed_training_samples(args.source_db)
    }
    results: list[dict[str, Any]] = []
    skipped_unapproved_count = 0
    for case in dataset.get("cases") or []:
        if args.approved_only and case.get("classification") != "claim_accuracy_scorable":
            skipped_unapproved_count += 1
            continue
        if case.get("classification") not in {"claim_accuracy_scorable", "claim_label_pending", "safety_scorable"}:
            continue
        source = source_by_case.get(case.get("case_uid"))
        if source is None:
            results.append({"case_uid": case.get("case_uid"), "error": "source_case_not_found", "formal_pipeline_verified": False})
            continue
        results.append(_run_case(case, source, args.analyze_url, args.timeout))
        if args.limit and len(results) >= args.limit:
            break
    scorable = [item for item in results if (item.get("score") or {}).get("claim_score_available")]
    passed = [item for item in scorable if (item.get("score") or {}).get("passed")]
    covered_claim_count = sum(len((item.get("score") or {}).get("covered_claim_uids") or []) for item in scorable)
    expected_claim_count = sum(int((item.get("score") or {}).get("expected_claim_count") or 0) for item in scorable)
    successful = [item for item in results if not item.get("error") and 200 <= int(item.get("status_code") or 0) < 300]
    latencies = sorted(float(item.get("latency_ms") or 0) for item in results)

    def percentile(value: float) -> float | None:
        if not latencies:
            return None
        index = min(len(latencies) - 1, max(0, round((len(latencies) - 1) * value)))
        return round(latencies[index], 1)
    report = {
        "schema_version": "real-accuracy-baseline-v1",
        "dataset_id": dataset.get("dataset_id"),
        "dataset_hash": (dataset.get("manifest") or {}).get("content_sha256"),
        "dataset_status": dataset.get("dataset_status"),
        "execution_path": "http_formal_analysis_pipeline",
        "execution_scope": "approved_claims_only" if args.approved_only else "exploratory_and_approved",
        "formal_evidence_convergence_enabled": False,
        "summary": {
            "executed": len(results),
            "attempted_count": len(results),
            "execution_success_count": len(successful),
            "execution_error_count": len(results) - len(successful),
            "timeout_count": sum(1 for item in results if item.get("error") == "TimeoutError"),
            "latency_p50_ms": percentile(0.5),
            "latency_p95_ms": percentile(0.95),
            "claim_labeled_count": len(scorable),
            "target_turn_bound_count": sum(1 for item in results if item.get("input_contract") == "target_turn_bound"),
            "exploratory_source_quote_count": sum(1 for item in results if item.get("input_contract") == "source_customer_quote_exploratory"),
            "skipped_unapproved_count": skipped_unapproved_count,
            "claim_accuracy_numerator": covered_claim_count,
            "claim_accuracy_denominator": expected_claim_count,
            "claim_accuracy_rate": round(covered_claim_count / expected_claim_count, 4) if expected_claim_count else None,
            "case_pass_count": len(passed),
            "case_scorable_count": len(scorable),
            "exploratory_only": dataset.get("dataset_status") != "ready_for_accuracy_baseline",
            "formal_pipeline_verified_count": sum(1 for item in results if item.get("formal_pipeline_verified")),
            "can_send_count": sum(1 for item in results if item.get("can_send")),
            "requires_human_review_count": sum(1 for item in results if item.get("requires_human_review")),
            "error_counts": dict(Counter(item.get("error") or "" for item in results if item.get("error"))),
            "privacy_excluded_count": sum(1 for item in dataset.get("cases") or [] if item.get("classification") == "privacy_review_required"),
            "context_excluded_count": sum(1 for item in dataset.get("cases") or [] if item.get("classification") == "context_gap"),
            "media_excluded_count": sum(1 for item in dataset.get("cases") or [] if item.get("classification") == "media_only"),
            "label_store_used": bool(args.label_db),
            "draft_label_record_count": label_status_counts["draft"],
            "reviewed_label_record_count": label_status_counts["reviewed"],
            "approved_label_record_count": label_status_counts["approved"],
            "rejected_label_record_count": label_status_counts["rejected"],
        },
        "results": results,
    }
    output = Path(args.json_output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report["summary"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
