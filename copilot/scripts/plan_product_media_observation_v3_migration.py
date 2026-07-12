"""Read-only inventory for retiring v2 media observations from future v3 review gates."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.db import SessionLocal
from app.models.product_media_observation import ProductMediaObservationCandidate


def build_report() -> dict:
    session = SessionLocal()
    try:
        rows = session.query(ProductMediaObservationCandidate).all()
    finally:
        session.close()
    by_status = Counter(str(row.status or "") for row in rows)
    return {
        "report_type": "product_media_observation_v3_migration_plan",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "v2_candidate_count": len(rows),
        "v2_status_counts": dict(sorted(by_status.items())),
        "v2_eligible_for_v3_review_gate_count": 0,
        "action": "retain_legacy_read_only",
        "next_step": "reextract_from_source_media_with_v3_object_binding",
        "writes_performed": 0,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json-output", default="outputs/product_media_observation_v3_migration_plan.json")
    args = parser.parse_args()
    report = build_report()
    output = Path(args.json_output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
