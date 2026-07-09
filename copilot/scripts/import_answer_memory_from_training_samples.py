"""Import reviewed training samples into Answer Memory shadow table."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.db import init_db
from app.models.eval_tables import AgentAnswerMemory  # noqa: F401 - register table
from app.services.answer_memory_service import AnswerMemoryService
from app.services.eval_sanitizer_service import sanitize_obj


def _load_samples(path: Path) -> list[dict]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, list):
        return data
    return list(data.get("items") or [])


def _write_json(path: str, payload: dict) -> None:
    if not path:
        return
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(sanitize_obj(payload), ensure_ascii=False, indent=2), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Import reviewed training sample answers into Answer Memory.")
    parser.add_argument("--input", required=True)
    parser.add_argument("--apply", action="store_true", help="Persist rows. Default is dry-run.")
    parser.add_argument("--json-output", default="")
    args = parser.parse_args(argv)

    init_db()
    samples = _load_samples(Path(args.input))
    result = AnswerMemoryService().import_training_samples(samples, apply=bool(args.apply))
    _write_json(args.json_output, result)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
