"""Retired compatibility entry point for VLM product-spec enrichment.

Model-derived image observations must remain pending shadow candidates. This
script intentionally has no database, VLM, or product-model imports, so an old
``--apply`` invocation cannot regain a direct write path by configuration.
Use ``extract_product_media_observations.py`` for offline extraction instead.
"""

from __future__ import annotations

import argparse
import json
from typing import Any


def enrich_products(*, dry_run: bool, apply: bool, **_unused: Any) -> dict[str, Any]:
    """Return a compatibility diagnostic without creating a Session or VLM call."""
    if apply:
        raise RuntimeError(
            "Direct VLM writes to KBProduct specs are disabled. "
            "Use extract_product_media_observations.py for pending shadow observations."
        )
    return {
        "shadow_only": True,
        "database_accessed": False,
        "vlm_called": False,
        "next_step": "extract_product_media_observations.py",
        "dry_run": bool(dry_run),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Retired direct VLM product-spec enrichment entry point.")
    parser.add_argument("--limit", type=int, default=None, help="Retained only for command compatibility.")
    parser.add_argument("--dry-run", action="store_true", help="Return a shadow-only compatibility diagnostic.")
    parser.add_argument("--apply", action="store_true", help="Disabled: direct model writes are prohibited.")
    parser.add_argument("--model", default="", help="Retained only for command compatibility.")
    args = parser.parse_args()
    if args.apply:
        parser.error(
            "--apply is disabled: model-derived observations must stay shadow-only and pending review"
        )
    print(json.dumps(enrich_products(dry_run=bool(args.dry_run), apply=False), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
