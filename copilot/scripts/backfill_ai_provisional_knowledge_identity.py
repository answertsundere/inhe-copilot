"""Backfill product identity for existing AI provisional knowledge drafts."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.services.ai_provisional_knowledge_service import AIProvisionalKnowledgeService


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill AI provisional knowledge product identity.")
    parser.add_argument("--run-uid", default="", help="Optional source replay run uid.")
    parser.add_argument("--limit", type=int, default=500)
    parser.add_argument("--apply", action="store_true", help="Persist identity updates; default is dry-run.")
    parser.add_argument("--json-output", default="", help="Optional JSON summary output path.")
    args = parser.parse_args()

    result = AIProvisionalKnowledgeService().backfill_identity(
        run_uid=args.run_uid,
        apply=bool(args.apply),
        limit=args.limit,
    )
    text = json.dumps(result, ensure_ascii=False, indent=2)
    if args.json_output:
        path = Path(args.json_output)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
