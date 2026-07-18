"""Build a balanced Tier D long-conversation simulation set from reviewed Gold data."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from app.services.long_conversation_simulation_service import (  # noqa: E402
    build_long_conversation_dataset,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gold-set", required=True)
    parser.add_argument("--review-queue", required=True)
    parser.add_argument("--json-output", required=True)
    parser.add_argument("--limit", type=int, default=12)
    parser.add_argument("--max-per-domain", type=int, default=3)
    parser.add_argument("--history-limit", type=int, default=12)
    parser.add_argument("--min-source-turns", type=int, default=20)
    parser.add_argument("--min-seed-turns", type=int, default=6)
    args = parser.parse_args(argv)

    try:
        gold = json.loads(Path(args.gold_set).read_text(encoding="utf-8"))
        queue = json.loads(Path(args.review_queue).read_text(encoding="utf-8"))
        dataset = build_long_conversation_dataset(
            gold,
            queue,
            limit=args.limit,
            max_per_domain=args.max_per_domain,
            history_limit=args.history_limit,
            min_source_turns=args.min_source_turns,
            min_seed_turns=args.min_seed_turns,
        )
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False))
        return 2

    output = Path(args.json_output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(dataset, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({
        "dataset_status": dataset["dataset_status"],
        "selected_count": dataset["selection"]["selected_count"],
        "domain_count": dataset["selection"]["domain_count"],
        "domain_distribution": dataset["selection"]["domain_distribution"],
        "accuracy_claim_allowed": dataset["accuracy_claim_allowed"],
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
