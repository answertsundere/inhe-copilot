"""Run the material Shadow QA from a query-only governance report."""

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
from app.services.material_shadow_qa_service import run_material_shadow_qa


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-database", required=True)
    parser.add_argument("--json-output", required=True)
    parser.add_argument("--product-limit", type=int, default=5)
    args = parser.parse_args()
    key = os.environ.get("COPILOT_MATERIAL_AUDIT_HMAC_KEY", "")
    if not key:
        print(json.dumps({"status": "blocked", "reason": "pseudonymization_key_required"}))
        return 2
    report = build_material_governance_report(args.source_database, pseudonymization_key=key)
    result = run_material_shadow_qa(report, product_limit=args.product_limit)
    Path(args.json_output).write_text(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"case_count": result["case_count"], "metrics": result["metrics"], "safety": result["safety"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
