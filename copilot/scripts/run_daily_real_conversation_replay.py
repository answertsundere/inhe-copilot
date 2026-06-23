"""Daily real conversation eval replay MVP.

This script does not configure Windows Task Scheduler. Run it from an external
scheduler after choosing dry-run or --apply/--replay-only explicitly.
"""

import argparse
import json
from pathlib import Path

from app.services.real_conversation_import_service import (
    build_import_report,
    collect_real_conversation_samples,
    default_source_dir,
    write_samples_to_db,
)
from app.services.real_conversation_replay_service import RealConversationReplayService, ReplayOptions


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-dir", default=default_source_dir())
    parser.add_argument("--limit", type=int, default=50)
    parser.add_argument("--date", default="")
    parser.add_argument("--min-turns", type=int, default=6)
    parser.add_argument("--output", default="")
    parser.add_argument("--apply", action="store_true", help="write imported samples before replay")
    parser.add_argument("--sample-only", action="store_true", help="extract/import samples only, no Agent replay")
    parser.add_argument("--replay-only", action="store_true", help="skip extraction and replay existing real_conversation cases")
    args = parser.parse_args()

    report = {
        "apply": args.apply,
        "sample_only": args.sample_only,
        "replay_only": args.replay_only,
        "source_dir": args.source_dir,
        "date": args.date,
    }

    if not args.replay_only:
        samples = collect_real_conversation_samples(
            source_dir=args.source_dir,
            limit=args.limit,
            min_turns=args.min_turns,
            date=args.date or None,
        )
        stats = write_samples_to_db(samples) if args.apply else {}
        report["import"] = build_import_report(samples, apply=args.apply, stats=stats)
    else:
        report["import"] = {"skipped": True}

    if not args.sample_only:
        if not args.apply and not args.replay_only:
            report["replay"] = {
                "skipped": True,
                "reason": "dry-run import; pass --apply to write samples or --replay-only to replay existing cases",
            }
        else:
            service = RealConversationReplayService()
            report["replay"] = service.replay_cases(ReplayOptions(limit_cases=args.limit))
    else:
        report["replay"] = {"skipped": True, "reason": "sample-only"}

    output = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        path = Path(args.output)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(output, encoding="utf-8")
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
