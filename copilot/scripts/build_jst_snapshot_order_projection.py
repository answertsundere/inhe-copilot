"""Build a PII-minimized, identity-only order snapshot for read fallback.

The runtime must never scan historical raw JST exports. This command projects
only exact order-item references and internal product identifiers into a small
JSON data directory for the existing JSON order repository. The projection is
not a logistics source and must not be used to represent current order status.
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SCHEMA_VERSION_V1 = "jst_snapshot_order_projection/v1"
SCHEMA_VERSION_V2 = "jst_snapshot_order_projection/v2"
ORDERS_FILENAME = "orders.json"
MANIFEST_FILENAME = "snapshot_order_projection.manifest.json"


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _text(value: Any) -> str:
    return str(value or "").strip()


def _projection_record_uid(item: dict[str, str]) -> str:
    """Create a stable opaque item reference without retaining raw order rows."""
    payload = json.dumps(item, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:32]


def _order_reference_hmac(order_reference: str, secret: str) -> str:
    return hmac.new(
        secret.encode("utf-8"),
        order_reference.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def _project_items(raw_record: dict[str, Any]) -> list[dict[str, str]]:
    items: list[dict[str, str]] = []
    for raw_item in raw_record.get("items") or []:
        if not isinstance(raw_item, dict):
            continue
        outer_oi_id = _text(raw_item.get("outer_oi_id"))
        sku_id = _text(raw_item.get("sku_id"))
        i_id = _text(raw_item.get("i_id"))
        if not outer_oi_id or not sku_id:
            continue
        items.append({
            "outer_oi_id": outer_oi_id,
            "sku_id": sku_id,
            "i_id": i_id,
        })
    return sorted(items, key=lambda item: (item["outer_oi_id"], item["sku_id"], item["i_id"]))


def _write_json_atomic(path: Path, value: Any) -> None:
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def build_projection(
    source_path: Path | str,
    output_dir: Path | str,
    *,
    overwrite: bool = False,
    order_reference_secret: str = "",
) -> dict[str, Any]:
    """Create the runtime projection without retaining raw order content."""
    source = Path(source_path).expanduser().resolve()
    destination = Path(output_dir).expanduser().resolve()
    if not source.is_file():
        raise ValueError("snapshot_source_not_found")

    orders_path = destination / ORDERS_FILENAME
    manifest_path = destination / MANIFEST_FILENAME
    if not overwrite and (orders_path.exists() or manifest_path.exists()):
        raise FileExistsError("projection_output_exists")
    destination.mkdir(parents=True, exist_ok=True)

    exact_items_by_external_id: dict[str, dict[tuple[str, str], dict[str, str]]] = {}
    items_by_order_reference_hmac: dict[str, dict[tuple[str, str, str], dict[str, str]]] = {}
    use_order_reference_hmac = bool(str(order_reference_secret or "").strip())
    invalid_json_line_count = 0
    source_record_count = 0
    skipped_record_count = 0
    skipped_missing_order_reference_count = 0
    source_eligible_item_count = 0
    with source.open("r", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            try:
                raw_record = json.loads(line)
            except json.JSONDecodeError:
                invalid_json_line_count += 1
                continue
            if not isinstance(raw_record, dict):
                invalid_json_line_count += 1
                continue
            source_record_count += 1
            projected_items = _project_items(raw_record)
            if not projected_items:
                skipped_record_count += 1
                continue
            order_reference = _text(raw_record.get("o_id"))
            if use_order_reference_hmac and not order_reference:
                skipped_missing_order_reference_count += 1
                continue
            for item in projected_items:
                source_eligible_item_count += 1
                external_item_id = item["outer_oi_id"]
                exact_items_by_external_id.setdefault(external_item_id, {})[
                    (item["sku_id"], item["i_id"])
                ] = item

                if use_order_reference_hmac:
                    reference_hmac = _order_reference_hmac(order_reference, order_reference_secret)
                    items_by_order_reference_hmac.setdefault(reference_hmac, {})[
                        (item["outer_oi_id"], item["sku_id"], item["i_id"])
                    ] = item

    if use_order_reference_hmac:
        projected_records = [
            {
                "snapshot_record_uid": _projection_record_uid({
                    "order_reference_hmac": reference_hmac,
                    "items": [item for _identity, item in sorted(items.items())],
                }),
                "snapshot_identity_only": True,
                "order_reference_hmac": reference_hmac,
                "items": [
                    item
                    for _identity, item in sorted(items.items())
                ],
            }
            for reference_hmac, items in sorted(items_by_order_reference_hmac.items())
        ]
        schema_version = SCHEMA_VERSION_V2
        projected_item_count = sum(len(items) for items in items_by_order_reference_hmac.values())
    else:
        projected_records = [
            {
                "snapshot_record_uid": _projection_record_uid(item),
                "snapshot_identity_only": True,
                "items": [item],
            }
            for external_item_id in sorted(exact_items_by_external_id)
            for _identity, item in sorted(exact_items_by_external_id[external_item_id].items())
        ]
        schema_version = SCHEMA_VERSION_V1
        projected_item_count = len(projected_records)
    external_item_counts = {
        external_item_id: len(items)
        for external_item_id, items in exact_items_by_external_id.items()
    }
    deduplicated_identical_item_count = source_eligible_item_count - projected_item_count

    _write_json_atomic(orders_path, projected_records)
    projection_sha256 = _file_sha256(orders_path)
    manifest = {
        "dataset_id": "jst_snapshot_order_projection",
        "schema_version": schema_version,
        "source_basename": source.name,
        "source_sha256": _file_sha256(source),
        "projection_sha256": projection_sha256,
        "source_record_count": source_record_count,
        "order_count": len(projected_records),
        "source_eligible_item_count": source_eligible_item_count,
        "eligible_item_count": projected_item_count,
        "unique_outer_oi_id_count": len(external_item_counts),
        "duplicate_outer_oi_id_count": sum(
            1 for count in external_item_counts.values() if count > 1
        ),
        "deduplicated_identical_item_count": deduplicated_identical_item_count,
        "invalid_json_line_count": invalid_json_line_count,
        "skipped_record_count": skipped_record_count,
        "skipped_missing_order_reference_count": skipped_missing_order_reference_count,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "privacy_projection": {
            "identity_only": True,
            "included_item_fields": ["outer_oi_id", "sku_id", "i_id"],
            "included_order_reference_fields": ["order_reference_hmac"] if use_order_reference_hmac else [],
            "excluded_order_fields": "all_except_snapshot_record_uid_and_items",
        },
    }
    if use_order_reference_hmac:
        manifest["order_reference_hmac_algorithm"] = "hmac-sha256"
    _write_json_atomic(manifest_path, manifest)
    return {
        "schema_version": schema_version,
        "order_count": manifest["order_count"],
        "eligible_item_count": manifest["eligible_item_count"],
        "duplicate_outer_oi_id_count": manifest["duplicate_outer_oi_id_count"],
        "deduplicated_identical_item_count": manifest["deduplicated_identical_item_count"],
        "projection_sha256": projection_sha256,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Build an identity-only JST order snapshot projection.")
    parser.add_argument("--source-jsonl", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--order-reference-secret-env", default="")
    args = parser.parse_args()
    secret_env_name = str(args.order_reference_secret_env or "").strip()
    order_reference_secret = os.environ.get(secret_env_name, "") if secret_env_name else ""
    if secret_env_name and not order_reference_secret:
        raise ValueError("snapshot_order_reference_secret_missing")
    summary = build_projection(
        args.source_jsonl,
        args.output_dir,
        overwrite=args.overwrite,
        order_reference_secret=order_reference_secret,
    )
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
