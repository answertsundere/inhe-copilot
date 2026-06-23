"""Import sanitized real conversation samples into eval_cases.

Default mode is dry-run. Use --apply to write sanitized cases and turns.
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


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-dir", default=default_source_dir())
    parser.add_argument("--limit", type=int, default=50)
    parser.add_argument("--date", default="")
    parser.add_argument("--min-turns", type=int, default=6)
    parser.add_argument("--output", default="")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--intent-balance", action="store_true", help="reserved for future sampling balance")
    args = parser.parse_args()

    samples = collect_real_conversation_samples(
        source_dir=args.source_dir,
        limit=args.limit,
        min_turns=args.min_turns,
        date=args.date or None,
    )
    stats = write_samples_to_db(samples) if args.apply else {}
    report = build_import_report(samples, apply=args.apply, stats=stats)
    report["source_dir"] = args.source_dir
    report["min_turns"] = args.min_turns
    report["date"] = args.date
    report["intent_balance"] = "reserved" if args.intent_balance else "off"

    output = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        path = Path(args.output)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(output, encoding="utf-8")
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
