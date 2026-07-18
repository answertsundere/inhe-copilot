"""Build a balanced, non-approving supervisor queue from a Gold review plan."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.services.real_accuracy_claim_review_service import build_minimum_supervisor_queue  # noqa: E402
from app.services.real_accuracy_gold_set_service import scan_sensitive_data  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", required=True)
    parser.add_argument("--json-output", required=True)
    parser.add_argument("--target-claims", type=int, default=30)
    parser.add_argument("--minimum-domains", type=int, default=5)
    args = parser.parse_args(argv)
    try:
        plan = json.loads(Path(args.plan).read_text(encoding="utf-8"))
        queue = build_minimum_supervisor_queue(
            plan,
            target_claim_count=args.target_claims,
            minimum_domain_count=args.minimum_domains,
        )
        findings = scan_sensitive_data(queue)
        if findings:
            raise ValueError("supervisor_queue_privacy_validation_failed")
        queue["privacy_scan"] = {"passed": True, "finding_count": 0}
        output = Path(args.json_output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(queue, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({
            "queue_status": queue["queue_status"],
            "selected_claim_count": queue["selected_claim_count"],
            "domain_distribution": queue["domain_distribution"],
            "supervisor_approved_claim_count": 0,
        }, ensure_ascii=False))
        return 0
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(json.dumps({"status": "blocked", "reason": str(exc)}, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
