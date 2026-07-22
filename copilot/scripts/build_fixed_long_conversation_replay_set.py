"""Build a privacy-safe fixed-buyer-turn replay set from reviewed conversations."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import secrets
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from app.services.long_conversation_simulation_service import (  # noqa: E402
    FIXED_REPLAY_SCHEMA_VERSION,
    conversation_content_digest,
    conversation_linkage_fingerprint,
    scan_long_conversation_privacy,
    validate_fixed_long_conversation_dataset,
)
from app.services.real_accuracy_gold_set_service import (  # noqa: E402
    build_gold_dataset,
    load_reviewed_training_samples,
)
from app.services.real_accuracy_privacy_service import sanitize_gold_text  # noqa: E402
from scripts.run_long_conversation_simulation import _resolve_sources, _source_db_fingerprint  # noqa: E402


def _canonical_hash(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _stable_turn_uid(conversation_digest: str, position: int, turn: dict[str, Any]) -> str:
    payload = "\x1f".join((
        conversation_digest,
        str(position),
        str(turn.get("speaker_role") or ""),
        str(turn.get("message_type") or "text"),
        sanitize_gold_text(turn.get("text")),
    ))
    digest = hashlib.sha256(payload.encode("utf-8")).digest()
    return f"turn_{base64.b32encode(digest).decode('ascii').rstrip('=')[:20]}"


def _project_turn(conversation_digest: str, position: int, turn: dict[str, Any]) -> dict[str, Any]:
    return {
        "turn_uid": _stable_turn_uid(conversation_digest, position, turn),
        "turn_index": position + 1,
        "speaker_role": str(turn.get("speaker_role") or "SYSTEM"),
        "message_type": str(turn.get("message_type") or "text"),
        "text": sanitize_gold_text(turn.get("text")),
    }


def build_fixed_replay_set(
    source_dataset: dict[str, Any],
    samples: list[dict[str, Any]],
    *,
    fixed_buyer_turn_count: int = 4,
    source_database: dict[str, Any] | None = None,
) -> dict[str, Any]:
    scenarios = list(source_dataset.get("scenarios") or [])
    resolved, missing_count, ambiguous_count = _resolve_sources(scenarios, samples, "")
    if missing_count or ambiguous_count or len(resolved) != len(scenarios):
        raise ValueError("fixed_replay_source_resolution_failed")

    output_scenarios: list[dict[str, Any]] = []
    for scenario in scenarios:
        source = resolved[str(scenario["scenario_uid"])]
        ephemeral_key = secrets.token_hex(32)
        gold, _ = build_gold_dataset(ephemeral_key, [source])
        turns = list(((gold.get("cases") or [{}])[0].get("conversation") or {}).get("turns") or [])
        conversation_digest = conversation_content_digest(turns)
        if conversation_digest != str(scenario.get("source_conversation_digest") or ""):
            raise ValueError("fixed_replay_conversation_digest_mismatch")
        buyer_positions = [
            position for position, turn in enumerate(turns)
            if turn.get("speaker_role") == "BUYER"
            and str(turn.get("message_type") or "text") == "text"
            and sanitize_gold_text(turn.get("text"))
        ]
        if len(buyer_positions) < fixed_buyer_turn_count:
            raise ValueError("fixed_replay_buyer_turns_insufficient")
        selected_positions = buyer_positions[-fixed_buyer_turn_count:]
        first_position = selected_positions[0]
        seed_positions = [
            position for position in range(first_position)
            if sanitize_gold_text(turns[position].get("text"))
        ][-12:]
        seed_history = [_project_turn(conversation_digest, position, turns[position]) for position in seed_positions]
        fixed_turns = [_project_turn(conversation_digest, position, turns[position]) for position in selected_positions]
        first_message = fixed_turns[0]["text"]
        output_scenarios.append({
            "scenario_uid": str(scenario["scenario_uid"]),
            "source_case_uid": str(scenario.get("source_case_uid") or ""),
            "source_conversation_digest": conversation_digest,
            "source_linkage_fingerprint": conversation_linkage_fingerprint(seed_history, first_message),
            "primary_domain": str(scenario.get("primary_domain") or ""),
            "scenario_domains": sorted(str(item) for item in (scenario.get("scenario_domains") or [])),
            "query_fact_types": sorted(str(item) for item in (scenario.get("query_fact_types") or [])),
            "risk_levels": sorted(str(item) for item in (scenario.get("risk_levels") or [])),
            "sidecar_present": bool(scenario.get("sidecar_present")),
            "sidecar_quality": str(scenario.get("sidecar_quality") or "unknown"),
            "source_turn_count": len(turns),
            "seed_history": seed_history,
            "fixed_buyer_turns": fixed_turns,
            "future_agent_replies_included": False,
            "gold_labels_included": False,
            "correct_answer_included": False,
        })

    output_scenarios.sort(key=lambda item: item["scenario_uid"])
    dataset: dict[str, Any] = {
        "schema_version": FIXED_REPLAY_SCHEMA_VERSION,
        "evaluation_tier": "tier_d_fixed_real_turn_replay",
        "dataset_status": "exploratory_not_real_accuracy",
        "accuracy_claim_allowed": False,
        "source": {
            "kind": "privacy_checked_reviewed_conversation",
            "source_dataset_schema_version": source_dataset.get("schema_version"),
            "source_dataset_content_sha256": (source_dataset.get("manifest") or {}).get("content_sha256"),
            "database": source_database or {},
        },
        "manifest": {
            "scenario_count": len(output_scenarios),
            "fixed_buyer_turn_count": sum(len(item["fixed_buyer_turns"]) for item in output_scenarios),
            "source_missing_count": 0,
            "source_ambiguous_count": 0,
            "contains_ai_generated_buyer_turns": False,
            "contains_future_agent_replies": False,
            "contains_gold_labels": False,
            "privacy_scan_status": "pending",
        },
        "scenarios": output_scenarios,
    }
    privacy_findings = scan_long_conversation_privacy(dataset)
    dataset["manifest"]["privacy_scan_status"] = "passed" if not privacy_findings else "failed"
    dataset["manifest"]["privacy_violation_count"] = len(privacy_findings)
    dataset["manifest"]["content_sha256"] = _canonical_hash(dataset)
    findings = validate_fixed_long_conversation_dataset(dataset)
    if findings:
        raise ValueError(f"fixed_replay_dataset_invalid:{','.join(findings)}")
    return dataset


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dataset", required=True)
    parser.add_argument("--source-db", required=True)
    parser.add_argument("--fixed-buyer-turns", type=int, default=4)
    parser.add_argument("--json-output", required=True)
    args = parser.parse_args()
    source_dataset = json.loads(Path(args.source_dataset).read_text(encoding="utf-8"))
    samples = load_reviewed_training_samples(args.source_db)
    dataset = build_fixed_replay_set(
        source_dataset,
        samples,
        fixed_buyer_turn_count=max(1, min(int(args.fixed_buyer_turns), 8)),
        source_database=_source_db_fingerprint(args.source_db),
    )
    output = Path(args.json_output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(dataset, ensure_ascii=True, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({
        "scenario_count": dataset["manifest"]["scenario_count"],
        "fixed_buyer_turn_count": dataset["manifest"]["fixed_buyer_turn_count"],
        "content_sha256": dataset["manifest"]["content_sha256"],
        "privacy_scan_status": dataset["manifest"]["privacy_scan_status"],
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
