"""Run deterministic eval replay locally.

Default mode is dry-run. Use --apply to persist eval_runs/eval_traces/failures.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser(description="Run daily eval replay")
    parser.add_argument("--limit", type=int, default=30)
    parser.add_argument("--category", default="")
    parser.add_argument("--run-type", default="daily")
    parser.add_argument("--dry-run", action="store_true", default=True)
    parser.add_argument("--apply", action="store_true", help="Persist eval run, traces, failures, and repair tasks")
    parser.add_argument("--report-dir", default=str(ROOT / "reports" / "eval_runs"))
    args = parser.parse_args()

    from app.services.eval_replay_service import EvalReplayService

    apply = bool(args.apply)
    result = EvalReplayService().run_replay(
        limit=args.limit,
        category=args.category,
        run_type=args.run_type,
        apply=apply,
        config_snapshot={"script": "run_daily_eval_replay", "limit": args.limit, "category": args.category},
    )
    paths = _write_reports(result, Path(args.report_dir))
    print(json.dumps({
        "run_uid": result.get("run_uid") or (result.get("run") or {}).get("run_uid"),
        "status": result.get("status") or (result.get("run") or {}).get("status"),
        "apply": apply,
        "json_report": str(paths["json"]),
        "md_report": str(paths["md"]),
    }, ensure_ascii=False, indent=2))
    return 0


def _write_reports(result: dict, report_dir: Path) -> dict[str, Path]:
    report_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    run_uid = result.get("run_uid") or (result.get("run") or {}).get("run_uid") or f"dry_run_{stamp}"
    json_path = report_dir / f"eval_run_{stamp}.json"
    md_path = report_dir / f"eval_run_{stamp}.md"
    json_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text(_markdown_report(run_uid, result), encoding="utf-8")
    return {"json": json_path, "md": md_path}


def _markdown_report(run_uid: str, result: dict) -> str:
    run = result.get("run") or result
    failures = result.get("failures") or []
    lines = [
        "# Eval Replay Report",
        "",
        f"- run_uid: {run_uid}",
        f"- status: {run.get('status', '')}",
        f"- total_cases: {run.get('total_cases', 0)}",
        f"- passed_cases: {run.get('passed_cases', 0)}",
        f"- failed_cases: {run.get('failed_cases', 0)}",
        f"- error_cases: {run.get('error_cases', 0)}",
        "",
        "## Failures",
    ]
    if not failures:
        lines.append("- none")
    for failure in failures[:50]:
        lines.append(
            f"- {failure.get('case_uid')}: {failure.get('failure_type')} "
            f"({failure.get('suggested_fix_area')})"
        )
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    raise SystemExit(main())
