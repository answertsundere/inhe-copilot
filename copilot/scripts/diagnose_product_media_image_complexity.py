"""Read-only pixel and format inventory for a repeatability report's media set."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

from PIL import Image, ImageOps

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import app.models.kb_tables  # noqa: F401
from app.db import SessionLocal
from app.models.kb_tables import KBMediaAsset
from app.services.product_media_observation_service import resolve_product_media_image


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repeatability-input", required=True)
    parser.add_argument("--json-output", required=True)
    args = parser.parse_args(argv)
    repeatability = json.loads((PROJECT_ROOT / args.repeatability_input).read_text(encoding="utf-8"))
    ids = sorted({int(item["media_asset_id"]) for item in repeatability.get("pairs") or []})
    db = SessionLocal(); rows = []
    try:
        for asset_id in ids:
            asset = db.get(KBMediaAsset, asset_id)
            try: image = resolve_product_media_image(asset) if asset else None
            except Exception: image = None
            record = {"media_asset_id": asset_id, "readable": bool(image)}
            if image:
                with Image.open(__import__('io').BytesIO(image[0])) as source:
                    oriented = ImageOps.exif_transpose(source)
                    width, height = oriented.size
                    record.update({"original_media_sha256": hashlib.sha256(image[0]).hexdigest(), "format": source.format,
                                   "file_byte_count": len(image[0]), "width": width, "height": height,
                                   "pixel_count": width * height, "aspect_ratio": round(width / max(height, 1), 4),
                                   "alpha_channel": "A" in oriented.getbands()})
            rows.append(record)
    finally: db.close()
    report = {"shadow_only": True, "image_count": len(rows), "rows": rows}
    output = PROJECT_ROOT / args.json_output; output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"image_count": len(rows), "readable_count": sum(row["readable"] for row in rows)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
