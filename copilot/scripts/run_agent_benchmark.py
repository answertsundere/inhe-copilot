"""Run active Agent benchmark scenarios."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.db import init_db
from app.models.eval_tables import AgentBenchmarkScenario  # noqa: F401 - register table before init_db
from app.services.agent_benchmark_runner_service import AgentBenchmarkRunnerService
from app.services.eval_sanitizer_service import sanitize_obj


def _write_json(path: str, payload: dict) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(sanitize_obj(payload), ensure_ascii=False, indent=2), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Run Agent benchmark scenarios.")
    parser.add_argument("--status", default="active")
    parser.add_argument("--scenario-uid", action="append", default=[])
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--run-uid", default="")
    parser.add_argument("--json-output", default="")
    args = parser.parse_args(argv)

    init_db()
    result = AgentBenchmarkRunnerService().run_scenarios(
        status=args.status,
        scenario_uids=args.scenario_uid or None,
        limit=args.limit or None,
        run_uid=args.run_uid,
    )
    if args.json_output:
        _write_json(args.json_output, result)
    print(json.dumps(sanitize_obj(result), ensure_ascii=False, indent=2))
    return 0 if result.get("failed", 0) == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
