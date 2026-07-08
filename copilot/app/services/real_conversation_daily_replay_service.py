"""Daily real conversation replay orchestration and trend aggregation."""

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from app.services.eval_sanitizer_service import sanitize_obj, sanitize_text
from app.services.real_conversation_import_service import (
    build_import_report,
    case_uid_for_conversation,
    collect_real_conversation_samples,
    default_source_dir,
    write_samples_to_db,
)
from app.services.real_conversation_replay_service import RealConversationReplayService, ReplayOptions


def _utc_now_iso() -> str:
    return datetime.utcnow().isoformat()


def _new_schedule_uid(run_date: str) -> str:
    date_part = sanitize_text(run_date).replace("-", "") or datetime.utcnow().strftime("%Y%m%d")
    return f"daily_replay_{date_part}_{uuid.uuid4().hex[:8]}"


def _new_run_uid(schedule_uid: str) -> str:
    return f"real_daily_{schedule_uid[-17:]}"


@dataclass
class DailyReplayOptions:
    source_dir: str = ""
    sample_limit: int = 50
    run_date: str = ""
    min_turns: int = 6
    apply: bool = False
    sample_only: bool = False
    replay_only: bool = False
    generate_repair_tasks: bool = False
    created_by: str = "system"
    eval_sidecar_context: dict[str, Any] | None = None
    disable_external_tools: bool = False
    external_tool_timeout_seconds: int | float = 0
    agent_turn_timeout_seconds: int | float = 0
    progress_log: bool = False
    enable_pgvector_shadow_trace: bool = False
    pgvector_shadow_top_k: int = 5


def _pass_rate(passed: int, total: int) -> float:
    return round(passed / total, 4) if total else 0


def _daily_metadata(
    *,
    schedule_uid: str,
    options: DailyReplayOptions,
    status: str,
    started_at: str,
    finished_at: str = "",
    replay: dict[str, Any] | None = None,
    error_message: str = "",
) -> dict[str, Any]:
    replay = replay or {}
    total_turns = int(replay.get("turns") or replay.get("total_turns") or 0)
    failed_turns = int(replay.get("failed") or replay.get("failed_turns") or 0)
    passed_turns = int(replay.get("passed") or replay.get("passed_turns") or 0)
    agent_accuracy_turns = int(replay.get("agent_accuracy_turns") or total_turns)
    agent_accuracy_passed = int(replay.get("agent_accuracy_passed") or passed_turns)
    return sanitize_obj({
        "daily_schedule": {
            "schedule_uid": schedule_uid,
            "source_dir": options.source_dir,
            "sample_limit": options.sample_limit,
            "date": options.run_date,
            "status": status,
            "started_at": started_at,
            "finished_at": finished_at,
            "total_cases": int(replay.get("total_cases") or 0),
            "total_turns": total_turns,
            "failed_turns": failed_turns,
            "pass_rate": _pass_rate(agent_accuracy_passed, agent_accuracy_turns),
            "legacy_scored_pass_rate": _pass_rate(passed_turns, total_turns),
            "agent_accuracy_turns": agent_accuracy_turns,
            "agent_accuracy_passed": agent_accuracy_passed,
            "context_gap_turns": int(replay.get("context_gap") or 0),
            "error_message": sanitize_text(error_message),
            "created_by": sanitize_text(options.created_by),
            "generate_repair_tasks": bool(options.generate_repair_tasks),
            "eval_sidecar_context": sanitize_obj(options.eval_sidecar_context or {}),
            "eval_replay_options": sanitize_obj({
                "disable_external_tools": bool(options.disable_external_tools),
                "external_tool_timeout_seconds": float(options.external_tool_timeout_seconds or 0),
                "agent_turn_timeout_seconds": float(options.agent_turn_timeout_seconds or 0),
                "progress_log": bool(options.progress_log),
                "enable_pgvector_shadow_trace": bool(options.enable_pgvector_shadow_trace),
                "pgvector_shadow_top_k": max(1, min(int(options.pgvector_shadow_top_k or 5), 20)),
            }),
        }
    })


def _update_run_metadata(run_uid: str, metadata: dict[str, Any], status: str | None = None) -> None:
    from app.db import SessionLocal
    from app.models.eval_tables import EvalRun

    db = SessionLocal()
    try:
        run = db.query(EvalRun).filter(EvalRun.run_uid == run_uid).one_or_none()
        if run is None:
            return
        current = run.get_metadata()
        current.update(metadata)
        run.set_metadata(current)
        if status:
            run.status = status
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def run_daily_real_conversation_replay(options: DailyReplayOptions) -> dict[str, Any]:
    source_dir = options.source_dir or default_source_dir()
    options = DailyReplayOptions(
        source_dir=source_dir,
        sample_limit=max(int(options.sample_limit or 50), 1),
        run_date=sanitize_text(options.run_date),
        min_turns=max(int(options.min_turns or 6), 1),
        apply=bool(options.apply),
        sample_only=bool(options.sample_only),
        replay_only=bool(options.replay_only),
        generate_repair_tasks=bool(options.generate_repair_tasks),
        created_by=sanitize_text(options.created_by) or "system",
        eval_sidecar_context=sanitize_obj(options.eval_sidecar_context or {}),
        disable_external_tools=bool(options.disable_external_tools),
        external_tool_timeout_seconds=float(options.external_tool_timeout_seconds or 0),
        agent_turn_timeout_seconds=float(options.agent_turn_timeout_seconds or 0),
        progress_log=bool(options.progress_log),
        enable_pgvector_shadow_trace=bool(options.enable_pgvector_shadow_trace),
        pgvector_shadow_top_k=max(1, min(int(options.pgvector_shadow_top_k or 5), 20)),
    )
    schedule_uid = _new_schedule_uid(options.run_date)
    run_uid = _new_run_uid(schedule_uid)
    started_at = _utc_now_iso()
    report: dict[str, Any] = {
        "apply": options.apply,
        "dry_run": not options.apply,
        "schedule_uid": schedule_uid,
        "run_uid": run_uid,
        "source_dir": options.source_dir,
        "sample_limit": options.sample_limit,
        "date": options.run_date,
        "generate_repair_tasks": options.generate_repair_tasks,
        "eval_sidecar_context": sanitize_obj(options.eval_sidecar_context or {}),
        "eval_replay_options": sanitize_obj({
            "disable_external_tools": bool(options.disable_external_tools),
            "external_tool_timeout_seconds": float(options.external_tool_timeout_seconds or 0),
            "agent_turn_timeout_seconds": float(options.agent_turn_timeout_seconds or 0),
            "progress_log": bool(options.progress_log),
            "enable_pgvector_shadow_trace": bool(options.enable_pgvector_shadow_trace),
            "pgvector_shadow_top_k": max(1, min(int(options.pgvector_shadow_top_k or 5), 20)),
        }),
    }

    if not options.replay_only:
        samples = collect_real_conversation_samples(
            source_dir=options.source_dir,
            limit=options.sample_limit,
            min_turns=options.min_turns,
            date=options.run_date or None,
        )
        imported_case_uids = [case_uid_for_conversation(sample.conversation_uid) for sample in samples]
        stats = write_samples_to_db(samples) if options.apply else {}
        report["import"] = build_import_report(samples, apply=options.apply, stats=stats)
    else:
        imported_case_uids = []
        report["import"] = {"skipped": True}

    if not options.apply:
        report["replay"] = {
            "skipped": True,
            "reason": "dry-run; pass --apply to import and replay real conversation cases",
        }
        report["status"] = "dry_run"
        return sanitize_obj(report)

    try:
        if options.sample_only:
            replay = {"skipped": True, "reason": "sample-only", "run_uid": run_uid, "status": "sampled"}
        else:
            replay = RealConversationReplayService().replay_cases(
                ReplayOptions(
                    limit_cases=options.sample_limit,
                    run_uid=run_uid,
                    case_uids=imported_case_uids or None,
                    eval_sidecar_context=options.eval_sidecar_context,
                    disable_external_tools=options.disable_external_tools,
                    external_tool_timeout_seconds=options.external_tool_timeout_seconds,
                    agent_turn_timeout_seconds=options.agent_turn_timeout_seconds,
                    progress_log=options.progress_log,
                    enable_pgvector_shadow_trace=options.enable_pgvector_shadow_trace,
                    pgvector_shadow_top_k=options.pgvector_shadow_top_k,
                )
            )
        report["replay"] = replay
        repair_result = None
        if options.generate_repair_tasks and not options.sample_only:
            from app.db import SessionLocal
            from app.services.real_conversation_repair_task_service import RealConversationRepairTaskService

            db = SessionLocal()
            try:
                repair_result = RealConversationRepairTaskService().generate_for_run(
                    db, run_uid=run_uid, created_by=options.created_by
                ).to_dict()
            finally:
                db.close()
        report["repair_tasks"] = repair_result or {"skipped": True}
        finished_at = _utc_now_iso()
        metadata = _daily_metadata(
            schedule_uid=schedule_uid,
            options=options,
            status="completed",
            started_at=started_at,
            finished_at=finished_at,
            replay=replay,
        )
        _update_run_metadata(run_uid, metadata, status="completed" if not options.sample_only else "sampled")
        report["schedule"] = metadata["daily_schedule"]
        report["status"] = "completed"
        return sanitize_obj(report)
    except Exception as exc:
        finished_at = _utc_now_iso()
        metadata = _daily_metadata(
            schedule_uid=schedule_uid,
            options=options,
            status="failed",
            started_at=started_at,
            finished_at=finished_at,
            error_message=str(exc),
        )
        _update_run_metadata(run_uid, metadata, status="failed")
        report["status"] = "failed"
        report["error_message"] = sanitize_text(str(exc))
        report["schedule"] = metadata["daily_schedule"]
        raise


def _date_key(value: datetime | None) -> str:
    return value.date().isoformat() if value else ""


def build_real_conversation_trends(
    db,
    *,
    days: int = 7,
    source: str = "real_conversation",
    suggested_fix_area: str = "",
    suggested_owner: str = "",
) -> dict[str, Any]:
    from app.models.eval_tables import EvalFailure, EvalRepairTask, EvalRun

    safe_days = min(max(int(days or 7), 1), 90)
    since = datetime.utcnow() - timedelta(days=safe_days - 1)
    runs = (
        db.query(EvalRun)
        .filter(EvalRun.source_type == sanitize_text(source), EvalRun.created_at >= since)
        .order_by(EvalRun.created_at.asc(), EvalRun.id.asc())
        .all()
    )
    run_uids = [run.run_uid for run in runs]
    failures_query = db.query(EvalFailure)
    tasks_query = db.query(EvalRepairTask)
    if run_uids:
        failures_query = failures_query.filter(EvalFailure.run_uid.in_(run_uids))
        tasks_query = tasks_query.filter(EvalRepairTask.run_uid.in_(run_uids))
    else:
        failures_query = failures_query.filter(EvalFailure.run_uid == "__none__")
        tasks_query = tasks_query.filter(EvalRepairTask.run_uid == "__none__")
    if suggested_fix_area:
        failures_query = failures_query.filter(EvalFailure.suggested_fix_area == sanitize_text(suggested_fix_area))
        tasks_query = tasks_query.filter(EvalRepairTask.suggested_fix_area == sanitize_text(suggested_fix_area))
    if suggested_owner:
        failures_query = failures_query.filter(EvalFailure.suggested_owner == sanitize_text(suggested_owner))
        tasks_query = tasks_query.filter(EvalRepairTask.suggested_owner == sanitize_text(suggested_owner))
    failures = failures_query.all()
    tasks = tasks_query.all()

    daily: dict[str, dict[str, Any]] = {}
    for offset in range(safe_days):
        day = (since + timedelta(days=offset)).date().isoformat()
        daily[day] = {"date": day, "pass_rate": 0, "total_turns": 0, "failed_turns": 0, "agent_accuracy_turns": 0, "context_gap_turns": 0}
    for run in runs:
        day = _date_key(run.created_at)
        if day not in daily:
            daily[day] = {"date": day, "pass_rate": 0, "total_turns": 0, "failed_turns": 0, "agent_accuracy_turns": 0, "context_gap_turns": 0}
        schedule = (run.get_metadata() or {}).get("daily_schedule") or {}
        daily[day]["total_turns"] += int(run.total_turns or 0)
        daily[day]["failed_turns"] += int(run.failed_turns or 0)
        agent_accuracy_turns = int(schedule.get("agent_accuracy_turns") or run.total_turns or 0)
        agent_accuracy_passed = int(schedule.get("agent_accuracy_passed") or run.passed_turns or 0)
        context_gap_turns = int(schedule.get("context_gap_turns") or 0)
        daily[day]["agent_accuracy_turns"] += agent_accuracy_turns
        daily[day]["context_gap_turns"] += context_gap_turns
        daily[day]["pass_rate"] = _pass_rate(
            daily[day].get("_agent_accuracy_passed", 0) + agent_accuracy_passed,
            daily[day]["agent_accuracy_turns"],
        )
        daily[day]["_agent_accuracy_passed"] = daily[day].get("_agent_accuracy_passed", 0) + agent_accuracy_passed

    failure_type_counts: dict[str, int] = {}
    fix_area_counts: dict[str, int] = {}
    owner_counts: dict[str, int] = {}
    for failure in failures:
        failure_type = sanitize_text(failure.failure_type) or "unknown"
        fix_area = sanitize_text(failure.suggested_fix_area) or "manual_triage"
        owner = sanitize_text(failure.suggested_owner) or "unassigned"
        failure_type_counts[failure_type] = failure_type_counts.get(failure_type, 0) + 1
        fix_area_counts[fix_area] = fix_area_counts.get(fix_area, 0) + 1
        owner_counts[owner] = owner_counts.get(owner, 0) + 1

    task_status_counts: dict[str, int] = {}
    for task in tasks:
        status = sanitize_text(task.status) or "open"
        task_status_counts[status] = task_status_counts.get(status, 0) + 1

    def top_items(counts: dict[str, int], limit: int = 5) -> list[dict[str, Any]]:
        return [
            {"name": name, "count": count}
            for name, count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))[:limit]
        ]

    recent_run = runs[-1] if runs else None
    recent_schedule = recent_run.get_metadata().get("daily_schedule", {}) if recent_run else {}
    daily_items = []
    for item in daily.values():
        item.pop("_agent_accuracy_passed", None)
        daily_items.append(item)
    return sanitize_obj({
        "days": safe_days,
        "source": source,
        "daily": sorted(daily_items, key=lambda item: item["date"]),
        "failure_type_counts": failure_type_counts,
        "suggested_fix_area_counts": fix_area_counts,
        "suggested_owner_counts": owner_counts,
        "repair_task_status_counts": task_status_counts,
        "top_failure_types": top_items(failure_type_counts),
        "top_fix_areas": top_items(fix_area_counts),
        "latest_daily_replay": recent_schedule,
    })
