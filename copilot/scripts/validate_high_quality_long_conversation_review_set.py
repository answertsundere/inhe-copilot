"""Validate the v4.2 review set before any Agent or workbench use."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.services.high_quality_long_conversation_review_service import load_and_validate_review_dataset


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate the long-conversation human-review dataset.")
    parser.add_argument("--input", required=True)
    parser.add_argument("--json-output", default="")
    args = parser.parse_args(argv)
    _payload, report = load_and_validate_review_dataset(args.input)
    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    if args.json_output:
        target = Path(args.json_output)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return int(report["exit_code"])


if __name__ == "__main__":
    raise SystemExit(main())
