"""Build a privacy-safe, read-only material knowledge governance report."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.services.material_knowledge_governance_service import (
    MaterialKnowledgeAuditError,
    build_material_governance_report,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit material knowledge without writing the knowledge base")
    parser.add_argument("--source-database", required=True)
    parser.add_argument("--json-output", required=True)
    parser.add_argument("--hmac-env", default="COPILOT_MATERIAL_AUDIT_HMAC_KEY")
    args = parser.parse_args()
    secret = os.environ.get(args.hmac_env, "")
    if not secret:
        print(json.dumps({"ok": False, "error": "pseudonymization_key_missing"}, ensure_ascii=False))
        return 2
    try:
        report = build_material_governance_report(
            args.source_database,
            pseudonymization_key=secret,
        )
    except MaterialKnowledgeAuditError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        return 2
    output = Path(args.json_output)
    output.parent.mkdir(parents=True, exist_ok=True)
    # The BOM keeps Windows PowerShell 5.1 Get-Content/ConvertFrom-Json reliable.
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8-sig")
    print(json.dumps({"ok": True, "output": str(output), "summary": report["summary"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
