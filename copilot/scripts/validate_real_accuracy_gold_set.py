"""Validate a privacy-safe Gold Set without touching production data."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from app.services.real_accuracy_gold_set_service import validate_gold_dataset  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True)
    args = parser.parse_args(argv)
    dataset = json.loads(Path(args.input).read_text(encoding="utf-8"))
    findings = validate_gold_dataset(dataset)
    print(json.dumps({"valid": not findings, "findings": findings}, ensure_ascii=False))
    return 0 if not findings else 2


if __name__ == "__main__":
    raise SystemExit(main())
