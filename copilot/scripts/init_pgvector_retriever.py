"""Initialize the pgvector shadow retriever schema."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.services.eval_sanitizer_service import sanitize_obj  # noqa: E402
from app.services.pgvector_retriever_service import (  # noqa: E402
    PgVectorRetrieverService,
    pgvector_config_from_env,
)


def _write_json(path: str, payload: dict) -> None:
    if not path:
        return
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(sanitize_obj(payload), ensure_ascii=False, indent=2), encoding="utf-8")


def run(*, check: bool = False, apply: bool = False, json_output: str = "") -> dict:
    service = PgVectorRetrieverService()
    result = {
        "config": pgvector_config_from_env(),
        "check": service.check() if check else {},
        "schema": service.init_schema(apply=apply) if (apply or not check) else {},
    }
    _write_json(json_output, result)
    return sanitize_obj(result)


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Initialize pgvector shadow retriever schema.")
    parser.add_argument("--check", action="store_true", help="Check DSN and pgvector extension availability.")
    parser.add_argument("--apply", action="store_true", help="Create extension, table, and indexes. Default is dry-run.")
    parser.add_argument("--json-output", default="")
    args = parser.parse_args(argv)
    result = run(check=args.check, apply=args.apply, json_output=args.json_output)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if args.check and not result.get("check", {}).get("pgvector_available"):
        return 2
    if args.apply and not result.get("schema", {}).get("applied"):
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
