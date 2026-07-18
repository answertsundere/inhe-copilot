"""Create a read-only, pseudonymous material review-batch plan."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.services.material_knowledge_governance_service import build_material_governance_report
from app.services.material_review_batch_service import build_material_review_batches


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-database", required=True)
    parser.add_argument("--json-output", required=True)
    args = parser.parse_args()
    key = os.environ.get("COPILOT_MATERIAL_AUDIT_HMAC_KEY", "")
    if not key:
        print(json.dumps({"status": "blocked", "reason": "pseudonymization_key_required"}))
        return 2
    report = build_material_governance_report(args.source_database, pseudonymization_key=key)
    batches = build_material_review_batches(report)
    result = {
        "schema_version": "material-review-batch-plan-v1",
        "source": report["source"],
        "batch_count": len(batches),
        "impacted_count": sum(batch["impacted_count"] for batch in batches),
        "batches": batches,
        "safety_contract": {"formal_kb_writes": 0, "can_change_can_send": False, "dry_run": True},
    }
    Path(args.json_output).write_text(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: result[key] for key in ("batch_count", "impacted_count", "safety_contract")}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
