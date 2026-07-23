from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.services.high_quality_long_conversation_review_service import (
    HighQualityReviewDatasetError,
    build_review_inventory,
    load_and_validate_review_dataset,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Inventory the immutable v4.2 review dataset")
    parser.add_argument("--input", required=True)
    parser.add_argument("--json-output", required=True)
    args = parser.parse_args()
    try:
        payload, _ = load_and_validate_review_dataset(args.input)
        report = build_review_inventory(payload)
    except HighQualityReviewDatasetError as exc:
        report = {"validation_status": "failed", "error": str(exc), "source_mutated": False}
    output = Path(args.json_output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))
    return 0 if report.get("validation_status") == "passed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
