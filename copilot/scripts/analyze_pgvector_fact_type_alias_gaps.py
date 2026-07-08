"""Analyze pgvector shadow traces for safe fact-type alias gaps."""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import json
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.services.eval_sanitizer_service import sanitize_obj, sanitize_text  # noqa: E402
from app.services.fact_type_alias_service import (  # noqa: E402
    expand_fact_type_aliases,
    is_alias_safe_for_direct_answer,
    risk_level_for_fact_type,
)


def _write_json(path: str, payload: dict[str, Any]) -> None:
    if not path:
        return
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(sanitize_obj(payload), ensure_ascii=False, indent=2), encoding="utf-8")


def _candidate_fact_type(candidate: dict[str, Any]) -> str:
    return sanitize_text(candidate.get("query_fact_type") or candidate.get("fact_type"))


def _candidate_role(candidate: dict[str, Any]) -> str:
    return sanitize_text(candidate.get("evidence_role"))


def _source_type(candidate: dict[str, Any]) -> str:
    return sanitize_text(candidate.get("source_type"))


def _recommendation(requested: str, candidates: list[dict[str, Any]]) -> tuple[str, str]:
    if not requested:
        return "fix_metadata", "requested fact type is empty"
    if not candidates:
        return "ignore_noise", "no no_fact_type candidates to inspect"
    aliases = set(expand_fact_type_aliases(requested, context="retrieval"))
    safe_alias_hits = [
        candidate for candidate in candidates
        if _candidate_fact_type(candidate) in aliases
        and _candidate_fact_type(candidate) != requested
        and is_alias_safe_for_direct_answer(
            requested,
            _candidate_fact_type(candidate),
            _candidate_role(candidate),
            _source_type(candidate),
        )
    ]
    if safe_alias_hits:
        return "add_alias", "safe alias candidate exists with direct evidence role"
    if risk_level_for_fact_type(requested) == "high":
        return "keep_strict", "requested fact type is high risk"
    non_direct = [
        candidate for candidate in candidates
        if _candidate_role(candidate) in {"service_action", "media_reference", "fallback_only"}
        or _source_type(candidate) in {"generic_rule", "generic_rules", "media_asset"}
    ]
    if len(non_direct) == len(candidates):
        return "ignore_noise", "only service/media/reference candidates were found"
    return "fix_metadata", "candidate fact types or evidence roles do not match the safe alias contract"


def analyze_alias_gaps(trace_json: str, *, json_output: str = "") -> dict[str, Any]:
    payload = json.loads(Path(trace_json).read_text(encoding="utf-8"))
    groups: dict[str, dict[str, Any]] = defaultdict(lambda: {
        "count": 0,
        "candidate_fact_type_distribution": Counter(),
        "source_type_distribution": Counter(),
        "evidence_role_distribution": Counter(),
        "media_role_distribution": Counter(),
        "samples": [],
        "candidates": [],
    })
    inspected_rows = 0
    for row in payload.get("rows", []):
        shadow = row.get("pgvector_shadow") if isinstance(row.get("pgvector_shadow"), dict) else {}
        modes = shadow.get("filter_mode_results") if isinstance(shadow.get("filter_mode_results"), dict) else {}
        strict_count = int((modes.get("strict") or {}).get("candidate_count") or 0)
        no_fact_type = modes.get("no_fact_type") or {}
        no_fact_type_count = int(no_fact_type.get("candidate_count") or 0)
        if strict_count > 0 or no_fact_type_count <= 0:
            continue
        inspected_rows += 1
        requested = sanitize_text(row.get("query_fact_type"))
        group = groups[requested]
        group["count"] += 1
        candidates = no_fact_type.get("top_candidates") or []
        group["candidates"].extend(candidates)
        for candidate in candidates:
            group["candidate_fact_type_distribution"][_candidate_fact_type(candidate) or "__empty__"] += 1
            group["source_type_distribution"][_source_type(candidate) or "__empty__"] += 1
            group["evidence_role_distribution"][_candidate_role(candidate) or "__empty__"] += 1
            group["media_role_distribution"][sanitize_text(candidate.get("media_role")) or "__empty__"] += 1
        if len(group["samples"]) < 3:
            group["samples"].append({
                "case_uid": sanitize_text(row.get("case_uid")),
                "turn_uid": sanitize_text(row.get("turn_uid")),
                "buyer_message_preview": sanitize_text(row.get("buyer_message_preview"))[:120],
                "candidate_previews": [
                    {
                        "query_fact_type": _candidate_fact_type(candidate),
                        "source_type": _source_type(candidate),
                        "evidence_role": _candidate_role(candidate),
                        "preview": sanitize_text(candidate.get("preview"))[:120],
                    }
                    for candidate in candidates[:3]
                ],
            })

    rows: list[dict[str, Any]] = []
    recommendation_counts: Counter[str] = Counter()
    risk_counts: Counter[str] = Counter()
    for requested, data in sorted(groups.items(), key=lambda item: (-item[1]["count"], item[0])):
        recommendation, reason = _recommendation(requested, data["candidates"])
        risk_level = risk_level_for_fact_type(requested)
        recommendation_counts[recommendation] += 1
        risk_counts[risk_level] += 1
        rows.append({
            "requested_fact_type": requested,
            "candidate_fact_type_distribution": dict(data["candidate_fact_type_distribution"].most_common()),
            "source_type_distribution": dict(data["source_type_distribution"].most_common()),
            "evidence_role_distribution": dict(data["evidence_role_distribution"].most_common()),
            "media_role_distribution": dict(data["media_role_distribution"].most_common()),
            "count": data["count"],
            "representative_samples": data["samples"][:3],
            "risk_level": risk_level,
            "alias_recommendation": recommendation,
            "reason": reason,
        })

    result = sanitize_obj({
        "summary": {
            "trace_json": str(trace_json),
            "inspected_gap_count": inspected_rows,
            "group_count": len(rows),
            "recommendation_counts": dict(recommendation_counts.most_common()),
            "risk_level_counts": dict(risk_counts.most_common()),
        },
        "rows": rows,
    })
    _write_json(json_output, result)
    return result


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Analyze pgvector shadow fact-type alias gaps.")
    parser.add_argument("--input", required=True)
    parser.add_argument("--json-output", default="")
    args = parser.parse_args(argv)
    result = analyze_alias_gaps(args.input, json_output=args.json_output)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

