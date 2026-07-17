"""Report reviewed-chat DOM structure without emitting source conversation text."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from app.services.real_accuracy_gold_set_service import load_reviewed_training_samples  # noqa: E402
from app.services.real_accuracy_privacy_service import parse_conversation_context  # noqa: E402


_TAG_RE = re.compile(r"<\s*([a-zA-Z0-9:-]+)", re.I)
_ATTRIBUTE_RE = re.compile(r"\s([\w:-]+)\s*=", re.I)
_CLASS_RE = re.compile(r"\bclass\s*=\s*([\"'])(.*?)\1", re.I | re.S)
_ROLE_RE = re.compile(r"\b(?:data-role|role|sender)\s*=\s*([\"'])(.*?)\1", re.I | re.S)
_STRUCTURAL_CLASSES = frozenset({
    "imui-msg", "imui-msg-l", "imui-msg-r", "imui-msg-system",
    "msg-body-text", "msg-body-html", "msg-content-nobody",
})


def _percentile(values: list[int], quantile: float) -> int | None:
    if not values:
        return None
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, max(0, round((len(ordered) - 1) * quantile)))]


def diagnose(samples: list[dict[str, Any]], hmac_key: str) -> dict[str, Any]:
    tags: Counter[str] = Counter()
    attributes: Counter[str] = Counter()
    structural_classes: Counter[str] = Counter()
    role_tokens: Counter[str] = Counter()
    role_counts: Counter[str] = Counter()
    turn_counts: list[int] = []
    unresolved_case_count = 0
    for sample in samples:
        raw = str(sample.get("full_context") or "")
        tags.update(item.lower() for item in _TAG_RE.findall(raw))
        attributes.update(item.lower() for item in _ATTRIBUTE_RE.findall(raw))
        for _, class_value in _CLASS_RE.findall(raw):
            structural_classes.update(token for token in class_value.split() if token in _STRUCTURAL_CLASSES)
        for _, role_value in _ROLE_RE.findall(raw):
            normalized = role_value.strip().lower()
            role_tokens[normalized if normalized in {"buyer", "agent", "customer", "seller", "system"} else "other"] += 1
        parsed = parse_conversation_context(raw, hmac_key=hmac_key)
        turn_counts.append(len(parsed.get("turns") or []))
        role_counts.update((parsed.get("role_counts") or {}))
        unresolved_case_count += int(bool(parsed.get("role_unresolved_count")))
    return {
        "schema_version": "real-accuracy-conversation-structure-v1",
        "source_sample_count": len(samples),
        "html_tag_counts": dict(tags.most_common()),
        "attribute_name_counts": dict(attributes.most_common()),
        "structural_class_counts": dict(structural_classes.most_common()),
        "role_metadata_token_counts": dict(role_tokens.most_common()),
        "parsed_role_counts": {role: int(role_counts.get(role, 0)) for role in ("BUYER", "AGENT", "SYSTEM")},
        "role_unresolved_case_count": unresolved_case_count,
        "turn_count_p50": _percentile(turn_counts, 0.5),
        "turn_count_p95": _percentile(turn_counts, 0.95),
        "turn_count_max": max(turn_counts, default=0),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-db", required=True)
    parser.add_argument("--json-output", required=True)
    parser.add_argument("--hmac-env", default="COPILOT_GOLD_SET_HMAC_KEY")
    args = parser.parse_args(argv)
    hmac_key = os.environ.get(args.hmac_env, "")
    if not hmac_key:
        print(json.dumps({"error": "gold_set_hmac_key_missing"}, ensure_ascii=False))
        return 2
    report = diagnose(load_reviewed_training_samples(args.source_db), hmac_key)
    output = Path(args.json_output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({key: report[key] for key in ("source_sample_count", "parsed_role_counts", "role_unresolved_case_count")}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
