"""Build a deterministic, privacy-safe supervisor claim-review plan.

The plan is advisory.  It does not save labels, approve claims, call the
Agent, or write product knowledge.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.services.real_accuracy_claim_review_service import build_claim_review_plan  # noqa: E402
from app.services.real_accuracy_gold_set_service import scan_sensitive_data, validate_gold_dataset  # noqa: E402
from app.services.real_accuracy_label_service import RealAccuracyLabelStore  # noqa: E402


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
        labels = RealAccuracyLabelStore(args.label_db).list_for_dataset(str(dataset.get("dataset_version") or ""))
        plan = build_claim_review_plan(dataset, labels)
        privacy_findings = scan_sensitive_data(plan)
        if privacy_findings:
            raise ValueError("claim_review_plan_privacy_validation_failed")
        plan["privacy_scan"] = {"passed": True, "finding_count": 0}
        output = Path(args.json_output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(plan, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({
            "case_count": len(plan["items"]),
            "strategy_counts": plan["strategy_counts"],
            "proposal_status_counts": plan["proposal_status_counts"],
            "auto_approved_count": 0,
        }, ensure_ascii=False))
        return 0
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(json.dumps({"status": "blocked", "reason": str(exc)}, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
