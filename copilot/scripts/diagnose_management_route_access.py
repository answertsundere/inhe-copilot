"""Read-only inventory of Flask route access policies."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.api.admin_auth import inventory_route_policies
from app.main import create_app


def build_report() -> dict:
    app = create_app()
    routes = inventory_route_policies(app)
    counts: dict[str, int] = {}
    for row in routes:
        counts[row["policy"]] = counts.get(row["policy"], 0) + 1
    return {
        "schema_version": 1,
        "route_method_count": len(routes),
        "policy_counts": dict(sorted(counts.items())),
        "policy_source_counts": {
            source: sum(1 for row in routes if row["policy_source"] == source)
            for source in sorted({row["policy_source"] for row in routes})
        },
        "unclassified_count": sum(1 for row in routes if row["policy"] == "unclassified"),
        "default_protected_count": sum(1 for row in routes if row["policy"] == "default_protected"),
        "routes": routes,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="List management route access policies")
    parser.add_argument("--json-output", required=True)
    args = parser.parse_args()
    report = build_report()
    output = Path(args.json_output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({key: report[key] for key in (
        "route_method_count", "policy_counts", "policy_source_counts", "default_protected_count", "unclassified_count",
    )}, ensure_ascii=False))
    return 0 if report["unclassified_count"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
