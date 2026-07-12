"""Repair report hashes only when current bytes prove a redacted hash prefix/suffix."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import app.models.kb_tables  # noqa: F401
from app.db import SessionLocal
from app.models.kb_tables import KBMediaAsset
from app.services.product_media_observation_service import resolve_product_media_image

REDACTION_MARKER = "[LONG_ID_REDACTED:"


def _matches_redaction(value: str, actual: str) -> bool:
    if REDACTION_MARKER not in value or "]" not in value:
        return False
    prefix, suffix = value.split("]", 1)
    return actual.startswith(prefix.split(REDACTION_MARKER, 1)[0]) and actual.endswith(suffix)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args(argv)
    source, output = PROJECT_ROOT / args.input, PROJECT_ROOT / args.output
    report = json.loads(source.read_text(encoding="utf-8"))
    repaired = 0
    db = SessionLocal()
    try:
        for row in report.get("results") or []:
            asset = db.get(KBMediaAsset, int(row.get("media_asset_id") or 0))
            image = resolve_product_media_image(asset) if asset else None
            if not image:
                continue
            actual = hashlib.sha256(image[0]).hexdigest()
            for observation in row.get("observations") or []:
                value = str(observation.get("observed_media_sha256") or "")
                if _matches_redaction(value, actual):
                    observation["observed_media_sha256"] = actual
                    provenance = observation.get("provenance") or {}
                    provenance["observed_media_sha256"] = actual
                    observation["provenance"] = provenance
                    repaired += 1
    finally:
        db.close()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"repaired_observed_hash_count": repaired}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
