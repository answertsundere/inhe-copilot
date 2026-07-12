"""Import local-VLM observations into shadow-only review staging."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import app.models.kb_tables  # noqa: F401
import app.models.product_media_observation  # noqa: F401
from app.db import SessionLocal, init_db
from app.services.product_media_observation_review_service import ObservationReviewError, import_report


def _safe_input_path(raw: str) -> Path:
    path = Path(raw).resolve()
    outputs = (PROJECT_ROOT / "outputs").resolve()
    if outputs not in path.parents or path.suffix.lower() != ".json":
        raise ObservationReviewError("input_must_be_json_under_project_outputs")
    return path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Stage pending product-media observations for human review.")
    parser.add_argument("--input", required=True)
    parser.add_argument("--apply", action="store_true", help="Write only observation staging and audit tables.")
    parser.add_argument("--json-output", default="")
    args = parser.parse_args(argv)
    try:
        input_path = _safe_input_path(args.input)
        report = json.loads(input_path.read_text(encoding="utf-8"))
        init_db()
        db = SessionLocal()
        try:
            result = import_report(db, report, apply=bool(args.apply))
        finally:
            db.close()
    except (OSError, ValueError, ObservationReviewError) as exc:
        result = {"error": str(exc), "dry_run": not bool(args.apply)}
    rendered = json.dumps(result, ensure_ascii=False, indent=2)
    if args.json_output:
        output = Path(args.json_output)
        if not output.is_absolute():
            output = PROJECT_ROOT / output
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(rendered, encoding="utf-8")
    print(rendered)
    return 0 if "error" not in result else 2


if __name__ == "__main__":
    raise SystemExit(main())
