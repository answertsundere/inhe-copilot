#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Seed generic service rules.

Default mode is dry-run. Use --apply to write kb_generic_service_rule.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _report_item(rule: dict, action: str, errors: list[str] | None = None) -> dict:
    return {
        "action": action,
        "rule_key": rule.get("rule_key", ""),
        "title": rule.get("title", ""),
        "intent": rule.get("intent", ""),
        "fact_type": rule.get("fact_type", ""),
        "scenario": rule.get("scenario", ""),
        "errors": errors or [],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Seed generic customer service rules")
    parser.add_argument("--apply", action="store_true", help="Write DB changes. Without this flag, dry-run only.")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--input", default="", help="Optional JSON file with rule list. Defaults to built-in seed rules.")
    parser.add_argument("--output", default=str(PROJECT_ROOT / "reports" / "generic_service_rules_seed_report.json"))
    args = parser.parse_args()

    from app.services.generic_service_rule_service import (
        DEFAULT_GENERIC_SERVICE_RULES,
        normalize_rule,
        validate_rule,
    )

    if args.input:
        rules = json.loads(Path(args.input).read_text(encoding="utf-8"))
        if not isinstance(rules, list):
            raise SystemExit("--input must contain a JSON list")
    else:
        rules = list(DEFAULT_GENERIC_SERVICE_RULES)
    if args.limit:
        rules = rules[: args.limit]

    db = None
    KBGenericServiceRule = None
    upsert_generic_service_rule = None
    if args.apply:
        from app.db import SessionLocal, init_db
        from app.models.kb_tables import KBGenericServiceRule
        from app.services.generic_service_rule_service import upsert_generic_service_rule

        init_db()
        db = SessionLocal()
    report = {
        "mode": "apply" if args.apply else "dry_run",
        "total": len(rules),
        "created": 0,
        "updated": 0,
        "unchanged": 0,
        "invalid": 0,
        "dry_run": 0,
        "items": [],
    }
    try:
        for raw in rules:
            normalized = normalize_rule(raw)
            errors = validate_rule(normalized)
            if errors:
                report["invalid"] += 1
                report["items"].append(_report_item(normalized, "invalid", errors))
                continue

            if args.apply:
                _, action, write_errors = upsert_generic_service_rule(db, KBGenericServiceRule, normalized)
                if write_errors:
                    report["invalid"] += 1
                    report["items"].append(_report_item(normalized, "invalid", write_errors))
                    continue
                report[action] += 1
            else:
                action = "dry_run"
                report["dry_run"] += 1
            report["items"].append(_report_item(normalized, action))
        if args.apply:
            db.commit()
    except Exception:
        if db is not None:
            db.rollback()
        raise
    finally:
        if db is not None:
            db.close()

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k != "items"}, ensure_ascii=False, indent=2))
    print(f"report: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
