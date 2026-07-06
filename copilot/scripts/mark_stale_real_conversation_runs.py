"""Safely mark stale real-conversation replay runs as abandoned.

The script is intentionally narrow: it only targets EvalRun rows with
source_type=real_conversation and status=running, never deletes rows, and
defaults to dry-run.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.db import SessionLocal  # noqa: E402
from app.models.eval_tables import EvalRun  # noqa: E402
from app.services.eval_sanitizer_service import sanitize_obj  # noqa: E402


def find_stale_runs(*, older_than_minutes: int, now: datetime | None = None, db_factory=None) -> dict[str, Any]:
    db_factory = db_factory or SessionLocal
    now = now or datetime.utcnow()
    cutoff = now - timedelta(minutes=older_than_minutes)
    db = db_factory()
    try:
        rows = (
            db.query(EvalRun)
            .filter(
                EvalRun.source_type == "real_conversation",
                EvalRun.status == "running",
                EvalRun.created_at < cutoff,
            )
            .order_by(EvalRun.created_at.asc(), EvalRun.id.asc())
            .all()
        )
        return sanitize_obj(
            {
                "dry_run": True,
                "older_than_minutes": older_than_minutes,
                "cutoff": cutoff.isoformat(timespec="seconds"),
                "matched_count": len(rows),
                "runs": [_run_preview(row, now=now) for row in rows],
            }
        )
    finally:
        db.close()


def mark_stale_runs_abandoned(
    *,
    older_than_minutes: int,
    reason: str,
    apply: bool = False,
    now: datetime | None = None,
    db_factory=None,
) -> dict[str, Any]:
    db_factory = db_factory or SessionLocal
    now = now or datetime.utcnow()
    cutoff = now - timedelta(minutes=older_than_minutes)
    db = db_factory()
    try:
        rows = (
            db.query(EvalRun)
            .filter(
                EvalRun.source_type == "real_conversation",
                EvalRun.status == "running",
                EvalRun.created_at < cutoff,
            )
            .order_by(EvalRun.created_at.asc(), EvalRun.id.asc())
            .all()
        )
        previews = [_run_preview(row, now=now) for row in rows]
        updated: list[str] = []
        if apply:
            for row in rows:
                metadata = row.get_metadata()
                history = metadata.get("status_history")
                if not isinstance(history, list):
                    history = []
                history.append(
                    {
                        "from": row.status,
                        "to": "abandoned",
                        "reason": reason,
                        "at": now.isoformat(timespec="seconds"),
                        "tool": "mark_stale_real_conversation_runs",
                    }
                )
                metadata["status_history"] = history
                metadata["abandoned_reason"] = reason
                metadata["abandoned_at"] = now.isoformat(timespec="seconds")
                metadata["abandoned_by"] = "mark_stale_real_conversation_runs"
                row.status = "abandoned"
                row.updated_at = now
                row.set_metadata(metadata)
                updated.append(row.run_uid)
            db.commit()
        return sanitize_obj(
            {
                "dry_run": not apply,
                "older_than_minutes": older_than_minutes,
                "cutoff": cutoff.isoformat(timespec="seconds"),
                "matched_count": len(rows),
                "updated_count": len(updated),
                "updated_run_uids": updated,
                "runs": previews,
            }
        )
    finally:
        db.close()


def _run_preview(row: EvalRun, *, now: datetime) -> dict[str, Any]:
    age_minutes = None
    if row.created_at:
        age_minutes = round((now - row.created_at).total_seconds() / 60, 1)
    return {
        "run_uid": row.run_uid,
        "status": row.status,
        "source_type": row.source_type,
        "created_at": row.created_at.isoformat(timespec="seconds") if row.created_at else "",
        "updated_at": row.updated_at.isoformat(timespec="seconds") if row.updated_at else "",
        "age_minutes": age_minutes,
    }


def write_json(path: str, payload: dict[str, Any]) -> None:
    if not path:
        return
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Mark stale real-conversation replay EvalRun rows as abandoned.")
    parser.add_argument("--older-than-minutes", type=int, default=60)
    parser.add_argument("--reason", default="stale replay run cleanup")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--json-output", default="")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    payload = mark_stale_runs_abandoned(
        older_than_minutes=args.older_than_minutes,
        reason=args.reason,
        apply=args.apply,
    )
    write_json(args.json_output, payload)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
