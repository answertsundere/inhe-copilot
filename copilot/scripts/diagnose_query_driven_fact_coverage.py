"""Create a query-driven evidence coverage matrix from read-only Gold outputs."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from app.services.real_accuracy_gold_set_service import query_coverage_rows  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gold-set", required=True)
    parser.add_argument("--baseline", default="")
    parser.add_argument("--json-output", required=True)
    args = parser.parse_args(argv)
    gold = json.loads(Path(args.gold_set).read_text(encoding="utf-8"))
    baseline = json.loads(Path(args.baseline).read_text(encoding="utf-8")) if args.baseline else {}
    rows = query_coverage_rows(gold.get("cases") or [], baseline.get("results") or [])
    report = {
        "schema_version": "query-driven-fact-coverage-v1",
        "dataset_id": gold.get("dataset_id"),
        "dataset_hash": (gold.get("manifest") or {}).get("content_sha256"),
        "rows": rows,
        "top_gaps": [row for row in rows if row["coverage_gap"] != "no_observed_gap"][:20],
        "read_only": True,
        "used_for_final_reply": False,
        "can_change_can_send": False,
    }
    output = Path(args.json_output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"rows": len(rows), "top_gaps": len(report["top_gaps"])}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
