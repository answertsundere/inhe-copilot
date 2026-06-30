"""Generate AI provisional knowledge drafts from knowledge gap tasks."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from openpyxl import Workbook

from app.db import init_db
from app.services.ai_provisional_knowledge_service import AIProvisionalKnowledgeService


HEADERS = [
    "draft_uid",
    "source_run_uid",
    "case_uid",
    "turn_uid",
    "task_uid",
    "i_id",
    "sku_code",
    "query_fact_type",
    "field_name",
    "provisional_value",
    "provisional_answer",
    "confidence",
    "verification_status",
    "usable_for_eval",
    "usable_for_auto_send",
    "note",
]


def _write_workbook(drafts: list[dict], output: str) -> None:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "AI预填知识"
    sheet.append(HEADERS)
    for draft in drafts:
        sheet.append([
            draft.get("draft_uid", ""),
            draft.get("source_run_uid", ""),
            draft.get("case_uid", ""),
            draft.get("turn_uid", ""),
            draft.get("task_uid", ""),
            draft.get("i_id", ""),
            draft.get("sku_code", ""),
            draft.get("query_fact_type", ""),
            draft.get("field_name", ""),
            draft.get("provisional_value", ""),
            draft.get("provisional_answer", ""),
            draft.get("confidence", ""),
            draft.get("verification_status", ""),
            bool(draft.get("usable_for_eval")),
            False,
            "",
        ])
    Path(output).parent.mkdir(parents=True, exist_ok=True)
    workbook.save(output)


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Generate staging-only AI provisional knowledge drafts.")
    parser.add_argument("--run-uid", default="", help="Source real replay run uid.")
    parser.add_argument("--output", default="", help="Optional xlsx output path.")
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--apply", action="store_true", help="Persist drafts; default is dry-run.")
    args = parser.parse_args()
    init_db()
    result = AIProvisionalKnowledgeService().generate_for_run(
        run_uid=args.run_uid,
        limit=args.limit,
        apply=bool(args.apply),
    )
    if args.output:
        _write_workbook(result.get("drafts", []), args.output)
        result["output"] = args.output
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
