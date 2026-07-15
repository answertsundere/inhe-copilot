"""Initialize an isolated SQLite database from a versioned benchmark fixture."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.services.agent_benchmark_fixture_service import BenchmarkFixtureError, initialize_fixture_database


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Create an isolated Agent Benchmark fixture database.")
    parser.add_argument("--fixture", required=True)
    parser.add_argument("--manifest", default="")
    parser.add_argument("--output-db", required=True)
    args = parser.parse_args(argv)
    try:
        report = initialize_fixture_database(
            args.fixture,
            args.output_db,
            manifest_path=args.manifest or None,
        )
    except BenchmarkFixtureError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        return 2
    print(json.dumps({"ok": True, **report}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
