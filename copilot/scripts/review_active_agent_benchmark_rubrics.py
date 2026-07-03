"""Recalculate reviewed benchmark rubrics for active scenarios.

This script does not call the Agent. It only re-applies the reviewed benchmark
rubric contract to existing scenarios so local DB state is reproducible.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from openpyxl import Workbook

from app.db import init_db
from app.models.eval_tables import AgentBenchmarkScenario  # noqa: F401 - register table before init_db
from app.services.agent_benchmark_dataset_service import AgentBenchmarkDatasetService
from app.services.eval_sanitizer_service import sanitize_obj, sanitize_text
from scripts.curate_agent_benchmark_seed_set import REVIEWER, build_seed_expected_for_item


REVIEW_NOTE = "active benchmark rubric recalculated from media evidence contract"


def _list_values(values: list[Any] | None) -> str:
    return "\n".join(sanitize_text(item) for item in (values or []) if sanitize_text(item))


def _diff_record(item: dict[str, Any], reviewed: dict[str, Any]) -> dict[str, Any]:
    old_expected = item.get("expected_reply") or {}
    new_expected = reviewed.get("expected") or {}
    changed = (
        bool(old_expected.get("must_handoff")) != bool(new_expected.get("must_handoff"))
        or bool(old_expected.get("auto_send_allowed")) != bool(new_expected.get("auto_send_allowed"))
        or [sanitize_text(v) for v in (old_expected.get("key_points") or [])]
        != [sanitize_text(v) for v in (new_expected.get("key_points") or [])]
        or [sanitize_text(v) for v in (old_expected.get("forbidden_claims") or [])]
        != [sanitize_text(v) for v in (new_expected.get("forbidden_claims") or [])]
        or sanitize_text(old_expected.get("expected_reply")) != sanitize_text(new_expected.get("expected_reply"))
    )
    return sanitize_obj({
        "scenario_uid": item.get("scenario_uid"),
        "title": item.get("title"),
        "scenario_type": item.get("scenario_type"),
        "query_fact_type": (item.get("metadata") or {}).get("query_fact_type")
        or old_expected.get("query_fact_type")
        or item.get("scenario_type"),
        "changed": changed,
        "reason": reviewed.get("reason") or "seed_rubric_recalculated",
        "old_must_handoff": bool(old_expected.get("must_handoff")),
        "new_must_handoff": bool(new_expected.get("must_handoff")),
        "old_auto_send_allowed": bool(old_expected.get("auto_send_allowed")),
        "new_auto_send_allowed": bool(new_expected.get("auto_send_allowed")),
        "old_key_points": old_expected.get("key_points") or [],
        "new_key_points": new_expected.get("key_points") or [],
        "old_forbidden_claims": old_expected.get("forbidden_claims") or [],
        "new_forbidden_claims": new_expected.get("forbidden_claims") or [],
        "new_expected_reply": new_expected.get("expected_reply") or "",
    })


def _write_json(path: str, payload: dict[str, Any]) -> None:
    if not path:
        return
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(sanitize_obj(payload), ensure_ascii=True, indent=2), encoding="utf-8")


def _write_excel(path: str, items: list[dict[str, Any]]) -> None:
    if not path:
        return
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "重审结果"
    sheet.append([
        "场景 UID",
        "标题",
        "场景类型",
        "问题类型",
        "是否变化",
        "原需人工",
        "新需人工",
        "原允许自动发送",
        "新允许自动发送",
        "原关键点",
        "新关键点",
        "原因",
    ])
    for item in items:
        sheet.append([
            item.get("scenario_uid", ""),
            item.get("title", ""),
            item.get("scenario_type", ""),
            item.get("query_fact_type", ""),
            bool(item.get("changed")),
            bool(item.get("old_must_handoff")),
            bool(item.get("new_must_handoff")),
            bool(item.get("old_auto_send_allowed")),
            bool(item.get("new_auto_send_allowed")),
            _list_values(item.get("old_key_points") or []),
            _list_values(item.get("new_key_points") or []),
            item.get("reason", ""),
        ])
    workbook.save(target)


def review_active_rubrics(
    status: str = "active",
    scenario_type: str = "installation",
    limit: int | None = None,
    apply: bool = False,
    json_output: str = "",
    excel_output: str = "",
    db_factory=None,
) -> dict[str, Any]:
    service = AgentBenchmarkDatasetService()
    source = service.list_scenarios({"status": status, "scenario_type": scenario_type}, db_factory=db_factory)
    items = source.get("items", [])
    if limit:
        items = items[: max(int(limit), 1)]

    changes: list[dict[str, Any]] = []
    reviewed_uids: list[str] = []
    errors: list[dict[str, str]] = []
    for item in items:
        scenario_uid = sanitize_text(item.get("scenario_uid"))
        reviewed = build_seed_expected_for_item(item)
        record = _diff_record(item, reviewed)
        changes.append(record)
        if not apply or not record.get("changed"):
            continue
        expected = reviewed.get("expected") or {}
        try:
            service.mark_expected_reply_reviewed(
                scenario_uid,
                reviewer=REVIEWER,
                expected_reply=expected.get("expected_reply") or "",
                key_points=expected.get("key_points") or [],
                forbidden_claims=expected.get("forbidden_claims") or [],
                auto_send_allowed=bool(expected.get("auto_send_allowed")),
                must_handoff=bool(expected.get("must_handoff")),
                review_note=REVIEW_NOTE,
                db_factory=db_factory,
            )
            reviewed_uids.append(scenario_uid)
        except Exception as exc:  # pragma: no cover - surfaced in CLI output
            errors.append({"scenario_uid": scenario_uid, "reason": sanitize_text(str(exc))})

    changed_count = sum(1 for item in changes if item.get("changed"))
    payload = sanitize_obj({
        "dry_run": not bool(apply),
        "apply": bool(apply),
        "status": status,
        "scenario_type": scenario_type,
        "source_total": source.get("total", 0),
        "processed_count": len(items),
        "changed_count": changed_count,
        "reviewed_count": len(reviewed_uids),
        "reviewed_scenario_uids": reviewed_uids,
        "errors": errors,
        "items": changes,
    })
    _write_json(json_output, payload)
    _write_excel(excel_output, changes)
    return payload


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Review active Agent benchmark rubrics without calling the Agent.")
    parser.add_argument("--status", default="active")
    parser.add_argument("--scenario-type", default="installation")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--json-output", default="")
    parser.add_argument("--excel-output", default="")
    args = parser.parse_args(argv)

    init_db()
    result = review_active_rubrics(
        status=args.status,
        scenario_type=args.scenario_type,
        limit=args.limit or None,
        apply=bool(args.apply),
        json_output=args.json_output,
        excel_output=args.excel_output,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
