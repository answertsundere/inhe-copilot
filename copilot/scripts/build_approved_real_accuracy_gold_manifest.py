"""Create a privacy-checked manifest for the currently approved Gold labels.

The manifest contains no buyer content or claim payload.  The Tier A runner
still reads the validated Gold artifact and independent label store, keeping
evaluation labels out of the Agent request.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.services.real_accuracy_gold_set_service import (  # noqa: E402
    apply_approved_claim_labels,
    scan_sensitive_data,
    validate_gold_dataset,
)
from app.services.real_accuracy_label_service import RealAccuracyLabelStore  # noqa: E402


def _validate_approval_audit(
    labels: list[dict],
    events: list[dict],
) -> tuple[dict[str, int], list[str]]:
    """Require a supervisor/admin audit event for every approved atomic claim."""
    findings: list[str] = []
    status_counts = Counter(str(item.get("review_status") or "unknown") for item in labels)
    events_by_case: dict[str, list[dict]] = {}
    for event in events:
        events_by_case.setdefault(str(event.get("case_uid") or ""), []).append(event)
    approval_event_count = 0
    for label in labels:
        if label.get("review_status") != "approved":
            continue
        case_uid = str(label.get("case_uid") or "")
        version = int(label.get("optimistic_lock_version") or 0)
        case_events = events_by_case.get(case_uid, [])
        state_versions = sorted({
            int(event.get("version") or 0)
            for event in case_events
            if event.get("event_type") in {"label_created", "label_updated"}
        })
        if state_versions != list(range(1, version + 1)):
            findings.append(f"optimistic_lock_history_invalid:{case_uid}")
        claims = ((label.get("label") or {}).get("claims") or [])
        for claim in claims:
            claim_uid = str((claim or {}).get("claim_uid") or "")
            matches = [
                event for event in case_events
                if event.get("event_type") == "claim_approved"
                and event.get("claim_uid") == claim_uid
                and int(event.get("version") or 0) == version
                and str(event.get("actor_role") or "") in {"supervisor", "admin"}
            ]
            if not matches:
                findings.append(f"approved_claim_audit_missing:{case_uid}:{claim_uid}")
            else:
                approval_event_count += len(matches)
    return {
        "draft": int(status_counts.get("draft", 0)),
        "reviewed": int(status_counts.get("reviewed", 0)),
        "approved": int(status_counts.get("approved", 0)),
        "rejected": int(status_counts.get("rejected", 0)),
        "approval_event_count": approval_event_count,
    }, findings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gold-set", required=True)
    parser.add_argument("--label-db", required=True)
    parser.add_argument("--json-output", required=True)
    args = parser.parse_args(argv)
    try:
        dataset = json.loads(Path(args.gold_set).read_text(encoding="utf-8"))
        findings = validate_gold_dataset(dataset)
        if findings or (dataset.get("privacy") or {}).get("privacy_scan_status") != "passed":
            raise ValueError("gold_set_privacy_validation_failed")
        store = RealAccuracyLabelStore(args.label_db)
        labels = store.list_for_dataset(str(dataset.get("dataset_version") or ""))
        events = store.list_events_for_dataset(str(dataset.get("dataset_version") or ""))
        audit_summary, audit_findings = _validate_approval_audit(labels, events)
        if audit_findings:
            raise ValueError("approved_gold_audit_validation_failed")
        approved_view = apply_approved_claim_labels(dataset, labels)
        approved_findings = validate_gold_dataset(approved_view)
        if approved_findings:
            raise ValueError("approved_gold_manifest_validation_failed")
        approved_cases = [
            item for item in approved_view.get("cases") or []
            if item.get("classification") == "claim_accuracy_scorable"
        ]
        approved_claim_count = sum(
            len((item.get("reference_label") or {}).get("expected_claims") or [])
            for item in approved_cases
        )
        manifest = {
            "schema_version": "real-accuracy-approved-manifest-v1",
            "dataset_id": approved_view.get("dataset_id"),
            "dataset_version": approved_view.get("dataset_version"),
            "source_snapshot_hash": (dataset.get("manifest") or {}).get("content_sha256"),
            "content_sha256": (approved_view.get("manifest") or {}).get("content_sha256"),
            "approved_case_count": len(approved_cases),
            "approved_claim_count": approved_claim_count,
            "reviewer_audit_summary": audit_summary,
            "approval_event_count": audit_summary["approval_event_count"],
            "scenario_distribution": dict(sorted(Counter(str(item.get("query_class") or "unclassified") for item in approved_cases).items())),
            "publish_status": "ready_for_accuracy_baseline" if approved_cases else "awaiting_supervisor_approval",
            "privacy_scan": {"passed": True, "finding_count": 0},
            "agent_input_contains_labels": False,
        }
        privacy_findings = scan_sensitive_data(manifest)
        if privacy_findings:
            raise ValueError("approved_manifest_privacy_validation_failed")
        output = Path(args.json_output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({
            "approved_case_count": manifest["approved_case_count"],
            "approved_claim_count": manifest["approved_claim_count"],
            "publish_status": manifest["publish_status"],
        }, ensure_ascii=False))
        return 0
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(json.dumps({"status": "blocked", "reason": str(exc)}, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
