"""Export a privacy-safe real-derived evidence fixture from a query-only SQLite source."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from app.services.real_derived_evidence_fixture_service import (
    RealDerivedFixtureError,
    build_real_derived_fixture,
    source_inventory,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-db", required=True)
    parser.add_argument("--fixture-output")
    parser.add_argument("--manifest-output")
    parser.add_argument("--limit-products", type=int, default=5)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    try:
        inventory = source_inventory(args.source_db)
        print(json.dumps({"mode": "dry_run" if not args.apply else "apply", "inventory": inventory}, ensure_ascii=False))
        if not args.apply:
            return 0
        if not args.fixture_output or not args.manifest_output:
            raise RealDerivedFixtureError("apply_requires_fixture_and_manifest_output")
        fixture, manifest = build_real_derived_fixture(
            args.source_db,
            pseudonymization_key=os.environ.get("COPILOT_REAL_DERIVED_FIXTURE_KEY", ""),
            limit_products=args.limit_products,
        )
        for output, payload in ((Path(args.fixture_output), fixture), (Path(args.manifest_output), manifest)):
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({"fixture": args.fixture_output, "manifest": args.manifest_output, "fact_count": manifest["fact_count"]}, ensure_ascii=False))
        return 0
    except RealDerivedFixtureError as exc:
        print(json.dumps({"status": "blocked", "reason": str(exc)}, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
