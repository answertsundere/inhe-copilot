"""Run daily sanitized real conversation replay.

Default mode is dry-run: collect samples and print a sanitized summary without
writing eval cases, replay traces, failures, or repair tasks. Pass --apply to
write data and run the replay.
"""

import argparse
import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.services.eval_sanitizer_service import sanitize_obj
from app.services.real_conversation_daily_replay_service import (
    DailyReplayOptions,
    run_daily_real_conversation_replay,
)
from app.services.real_conversation_import_service import default_source_dir


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-dir", default=default_source_dir())
    parser.add_argument("--sample-limit", "--limit", dest="sample_limit", type=int, default=50)
    parser.add_argument("--date", default="")
    parser.add_argument("--min-turns", type=int, default=6)
    parser.add_argument("--json-output", "--output", dest="json_output", default="")
    parser.add_argument("--apply", action="store_true", help="write imported samples, replay traces, and failures")
    parser.add_argument("--sample-only", action="store_true", help="extract/import samples only, no Agent replay")
    parser.add_argument("--replay-only", action="store_true", help="skip extraction and replay existing real_conversation cases")
    parser.add_argument("--generate-repair-tasks", action="store_true", help="generate repair tasks after replay")
    parser.add_argument("--created-by", default="daily_replay")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    report = run_daily_real_conversation_replay(DailyReplayOptions(
        source_dir=args.source_dir,
        sample_limit=args.sample_limit,
        run_date=args.date,
        min_turns=args.min_turns,
        apply=args.apply,
        sample_only=args.sample_only,
        replay_only=args.replay_only,
        generate_repair_tasks=args.generate_repair_tasks,
        created_by=args.created_by,
    ))
    output = json.dumps(sanitize_obj(report), ensure_ascii=False, indent=2)
    if args.json_output:
        path = Path(args.json_output)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(output, encoding="utf-8")
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
