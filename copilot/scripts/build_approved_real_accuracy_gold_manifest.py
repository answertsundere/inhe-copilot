"""Create a privacy-checked manifest for the currently approved Gold labels.

The manifest contains no buyer content or claim payload.  The Tier A runner
still reads the validated Gold artifact and independent label store, keeping
evaluation labels out of the Agent request.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.services.real_accuracy_gold_set_service import (  # noqa: E402
    apply_approved_claim_labels,
    scan_sensitive_data,
    validate_gold_dataset,
)
from app.services.real_accuracy_label_service import (  # noqa: E402
    RealAccuracyLabelStore,
    approved_claim_gate_summary,
)


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
        gate = approved_claim_gate_summary(labels, events)
        if gate["audit_findings"]:
            raise ValueError("approved_gold_audit_validation_failed")
        approved_view = apply_approved_claim_labels(dataset, labels)
        approved_findings = validate_gold_dataset(approved_view)
        if approved_findings:
            raise ValueError("approved_gold_manifest_validation_failed")
        approved_cases = [
            item for item in approved_view.get("cases") or []
            if item.get("classification") == "claim_accuracy_scorable"
        ]
        manifest = {
            "schema_version": "real-accuracy-approved-manifest-v1",
            "dataset_id": approved_view.get("dataset_id"),
            "dataset_version": approved_view.get("dataset_version"),
            "source_snapshot_hash": (dataset.get("manifest") or {}).get("content_sha256"),
            "content_sha256": (approved_view.get("manifest") or {}).get("content_sha256"),
            "approved_case_count": len(approved_cases),
            "approved_claim_count": gate["approved_claim_count"],
            "approved_domain_count": gate["approved_domain_count"],
            "approved_domains": gate["approved_domains"],
            "approved_domain_distribution": gate["approved_domain_distribution"],
            "minimum_approved_claim_count": gate["minimum_approved_claim_count"],
            "minimum_approved_domain_count": gate["minimum_approved_domain_count"],
            "missing_approved_claim_count": gate["missing_approved_claim_count"],
            "missing_approved_domain_count": gate["missing_approved_domain_count"],
            "reviewer_audit_summary": gate["label_record_counts"],
            "approval_event_count": gate["approval_event_count"],
            "scenario_distribution": gate["approved_domain_distribution"],
            "publish_status": gate["publish_status"],
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
