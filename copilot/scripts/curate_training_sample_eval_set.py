"""Curate one reviewed training sample into the evaluation set.

This script is intentionally single-sample only. Evaluation-set samples must be
read and rewritten by a human or an agent before conversion; batch conversion is
blocked in the API/service layer.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.db import init_db  # noqa: E402
from app.services.training_sample_eval_set_service import TrainingSampleEvalSetService  # noqa: E402


def _read_text(value: str | None, file_path: str | None) -> str:
    if file_path:
        return Path(file_path).read_text(encoding="utf-8-sig")
    return value or ""


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Convert exactly one curated training sample into the evaluation set. "
            "Provide customer_said and suggested_answer after reading the full sample."
        )
    )
    parser.add_argument("--sample-id", type=int, required=True, help="Training sample id to convert.")
    parser.add_argument("--customer-said", default="", help="Curated customer dialogue text.")
    parser.add_argument("--customer-said-file", default="", help="UTF-8 file containing curated customer dialogue text.")
    parser.add_argument("--suggested-answer", default="", help="Curated suggested answer text.")
    parser.add_argument("--suggested-answer-file", default="", help="UTF-8 file containing curated suggested answer text.")
    parser.add_argument("--preview", action="store_true", help="Only preview the current auto-built contract; do not convert.")
    return parser


def main() -> int:
    args = _build_parser().parse_args()
    init_db()
    service = TrainingSampleEvalSetService()
    if args.preview:
        result = service.preview_sample(args.sample_id)
    else:
        contract = {
            "customer_said": _read_text(args.customer_said, args.customer_said_file),
            "suggested_answer": _read_text(args.suggested_answer, args.suggested_answer_file),
        }
        result = service.convert_curated_sample(args.sample_id, contract=contract)

    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("converted") or args.preview else 2


if __name__ == "__main__":
    raise SystemExit(main())
