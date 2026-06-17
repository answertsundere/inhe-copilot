#!/usr/bin/env python
"""Import customer-service workbook rows into knowledge_entries drafts.

Default mode is dry-run. Apply mode creates draft entries only; it does not
publish entries and does not build retrieval chunks.
"""

import argparse
import json
import os
import sys
from collections import Counter
from datetime import datetime


SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(SCRIPT_DIR)
sys.path.insert(0, PROJECT_DIR)

from app import db as db_module
from app.models.knowledge_base import KnowledgeEntry
from app.services.knowledge_import_service import KnowledgeImportService


def _batch_id() -> str:
    return f"cs_knowledge_import_{datetime.now().strftime('%Y%m%d_%H%M%S')}"


def _filter_items(items: list[dict], sheets: list[str] | None, limit: int | None) -> list[dict]:
    selected = list(items)
    if sheets:
        wanted = set(sheets)
        selected = [item for item in selected if item.get("source_sheet") in wanted]
    if limit:
        selected = selected[:limit]
    return selected


def _summarize(items: list[dict]) -> dict:
    by_source = Counter(item.get("source_type", "") for item in items)
    by_sheet = Counter(item.get("source_sheet", "") for item in items)
    duplicates = sum(1 for item in items if item.get("duplicate_candidate"))
    high_risk = sum(1 for item in items if item.get("risk_level") in ("high", "critical"))
    human_review = sum(1 for item in items if item.get("human_review_required"))
    return {
        "items": len(items),
        "duplicate_candidates": duplicates,
        "would_import_without_duplicates": len(items) - duplicates,
        "high_risk": high_risk,
        "human_review_required": human_review,
        "by_source_type": dict(sorted(by_source.items())),
        "by_sheet": dict(sorted(by_sheet.items())),
    }


def run_import(
    file_path: str,
    apply: bool = False,
    batch_id: str | None = None,
    limit: int | None = None,
    sheets: list[str] | None = None,
    allow_duplicates: bool = False,
    user: str = "cs_knowledge_import",
) -> dict:
    db_module.init_db()
    batch_id = batch_id or _batch_id()
    preview = KnowledgeImportService.parse_excel_preview(file_path)
    items = _filter_items(preview.get("items", []), sheets, limit)

    summary = {
        "batch_id": batch_id,
        "source_file": os.path.basename(file_path),
        "mode": "apply" if apply else "dry-run",
        "preview_total_rows": preview.get("total_rows", 0),
        "preview_valid_count": preview.get("valid_count", 0),
        "preview_failed_count": preview.get("failed_count", 0),
        "selected": _summarize(items),
        "created": 0,
        "failed": 0,
        "created_ids": [],
        "errors": [],
        "warning_count": len(preview.get("warnings", [])),
        "warning_sample": preview.get("warnings", [])[:20],
    }

    if not apply:
        return summary

    result = KnowledgeImportService.import_from_preview(
        items,
        user=user,
        batch_id=batch_id,
        allow_duplicates=allow_duplicates,
    )
    summary["created"] = result.get("success", 0)
    summary["failed"] = result.get("failed", 0)
    summary["created_ids"] = result.get("created_ids", [])
    summary["errors"] = result.get("errors", [])
    warnings = preview.get("warnings", []) + result.get("warnings", [])
    summary["warning_count"] = len(warnings)
    summary["warning_sample"] = warnings[:20]
    return summary


def rollback_batch(batch_id: str) -> dict:
    db_module.init_db()
    db = db_module.SessionLocal()
    try:
        entries = (
            db.query(KnowledgeEntry)
            .filter(KnowledgeEntry.import_batch_id == batch_id)
            .filter(KnowledgeEntry.status == "draft")
            .all()
        )
        count = len(entries)
        for entry in entries:
            db.delete(entry)
        db.commit()
        return {"batch_id": batch_id, "deleted_draft_entries": count}
    finally:
        db.close()


def main():
    parser = argparse.ArgumentParser(description="Import customer-service workbook into knowledge_entries drafts")
    parser.add_argument("--file", help="Workbook path")
    parser.add_argument("--apply", action="store_true", help="Create draft entries")
    parser.add_argument("--limit", type=int, help="Limit selected valid rows")
    parser.add_argument("--sheet", action="append", help="Only import this sheet; can be repeated")
    parser.add_argument("--batch-id", help="Batch id to write or rollback")
    parser.add_argument("--allow-duplicates", action="store_true", help="Allow duplicate candidates")
    parser.add_argument("--rollback", action="store_true", help="Delete draft entries created by batch id")
    args = parser.parse_args()

    if args.rollback:
        if not args.batch_id:
            raise SystemExit("--rollback requires --batch-id")
        print(json.dumps(rollback_batch(args.batch_id), ensure_ascii=False, indent=2))
        return

    if not args.file:
        raise SystemExit("--file is required")

    result = run_import(
        file_path=args.file,
        apply=args.apply,
        batch_id=args.batch_id,
        limit=args.limit,
        sheets=args.sheet,
        allow_duplicates=args.allow_duplicates,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
