"""Generate Agent benchmark scenario candidates from curated eval sources."""

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
from app.services.agent_benchmark_dataset_service import AgentBenchmarkDatasetService
from app.services.eval_sanitizer_service import sanitize_obj


def _write_json(path: str, payload: dict) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(sanitize_obj(payload), ensure_ascii=False, indent=2), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Generate Agent benchmark candidate scenarios.")
    parser.add_argument("--from-run-uid", default="", help="Source real replay run uid.")
    parser.add_argument("--from-training-samples", action="store_true", help="Generate from reviewed training samples.")
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--apply", action="store_true", help="Persist candidates. Default is dry-run.")
    parser.add_argument("--json-output", default="")
    args = parser.parse_args(argv)

    init_db()
    service = AgentBenchmarkDatasetService()
    if args.from_run_uid:
        result = service.create_candidate_from_real_replay(
            run_uid=args.from_run_uid,
            limit=args.limit,
            apply=bool(args.apply),
        )
    elif args.from_training_samples:
        result = service.create_candidate_from_training_samples(limit=args.limit, apply=bool(args.apply))
    else:
        result = {"error": "source_required", "message": "Pass --from-run-uid or --from-training-samples."}

    if args.json_output:
        _write_json(args.json_output, result)
    print(json.dumps(sanitize_obj(result), ensure_ascii=False, indent=2))
    return 0 if "error" not in result else 2


if __name__ == "__main__":
    raise SystemExit(main())
