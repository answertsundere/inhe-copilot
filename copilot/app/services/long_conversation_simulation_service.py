"""Read-only dataset and scoring contracts for simulated multi-turn evaluation."""

from __future__ import annotations

import hashlib
import json
import re
import statistics
import unicodedata
from collections import Counter, defaultdict
from typing import Any

from app.services.no_evidence_reply_policy_service import (
    contains_unsupported_media_promise,
)
from app.services.admitted_answer_context_service import (
    AdmittedAnswerContextService,
    build_turn_evidence_funnel,
)
from app.services.real_accuracy_gold_set_service import validate_gold_dataset
from app.services.real_accuracy_privacy_service import sanitize_gold_text, scan_privacy_output


SCHEMA_VERSION = "long-conversation-simulation-set-v2"
EVALUATION_TIER = "tier_d_simulated_multiturn"
DATASET_STATUS = "exploratory_not_real_accuracy"
TURN_OBSERVATION_SCHEMA_VERSION = "tier-d-turn-observation/v2"
FIXED_REPLAY_SCHEMA_VERSION = "fixed-long-conversation-replay-set-v1"
FIXED_REPLAY_OBSERVATION_SCHEMA_VERSION = "fixed-long-conversation-turn-observation/v1"
ALLOWED_SIMULATOR_STATES = frozenset({"continue", "satisfied", "handoff_accepted", "blocked"})
ALLOWED_STOP_REASONS = frozenset({"continue", "resolved", "handoff_accepted", "cannot_continue"})
LABEL_FIELDS = frozenset({
    "correct_answer", "expected_claims", "reference_label", "rubric", "pass_criteria",
    "forbidden_claims", "must_handoff", "required_actions", "atomic_claim",
})
_READ_RECEIPT_RE = re.compile(r"\s*已读\s*$")
_TIMESTAMP_ONLY_RE = re.compile(r"^.{0,32}\d{4}[-/]\d{1,2}[-/]\d{1,2}\s+\d{1,2}:\d{2}(?::\d{2})?$")
_TOKEN_ONLY_RE = re.compile(r"^(?:\[(?:IMAGE|MEDIA_LINK|PRODUCT_LINK|ORDER_LINK|EXTERNAL_LINK)\]\s*)+$")

def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _content_hash(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _privacy_content_projection(value: Any) -> Any:
    """Remove controlled identifiers while retaining all human-readable content."""
    if isinstance(value, list):
        return [_privacy_content_projection(item) for item in value]
    if not isinstance(value, dict):
        return value
    controlled_fields = {
        "manifest",
        "scenario_uid",
        "source_case_uid",
        "source_linkage_fingerprint",
        "source_conversation_digest",
        "target_turn_uids",
        "turn_uid",
        "gold_content_sha256",
        "review_queue_content_sha256",
    }
    return {
        key: _privacy_content_projection(item)
        for key, item in value.items()
        if key not in controlled_fields
    }


def scan_long_conversation_privacy(value: Any) -> list[dict[str, Any]]:
    return scan_privacy_output(_privacy_content_projection(value))


def conversation_linkage_fingerprint(seed_history: list[dict[str, Any]], initial_message: str) -> str:
    """Return a non-reversible fingerprint for in-process source linkage."""
    cleaned = [
        {
            "speaker_role": str(turn.get("speaker_role") or ""),
            "text": _clean_turn_text(turn.get("text")),
        }
        for turn in seed_history
        if _clean_turn_text(turn.get("text"))
    ]
    compact = cleaned[-12:]
    return _content_hash({"seed": compact, "initial": _clean_turn_text(initial_message)})


def conversation_content_digest(turns: list[dict[str, Any]]) -> str:
    """Identify one sanitised conversation without depending on HMAC namespaces."""
    return _content_hash([
        {
            "turn_index": int(turn.get("turn_index") or position),
            "speaker_role": str(turn.get("speaker_role") or ""),
            "message_type": str(turn.get("message_type") or "text"),
            "text": _clean_turn_text(turn.get("text")),
        }
        for position, turn in enumerate(turns, start=1)
        if _clean_turn_text(turn.get("text"))
    ])


def _clean_turn_text(value: Any) -> str:
    text = sanitize_gold_text(value)
    text = "".join(character for character in text if not unicodedata.category(character).startswith("C"))
    text = _READ_RECEIPT_RE.sub("", text).strip()
    if _TIMESTAMP_ONLY_RE.fullmatch(text):
        return ""
    return text


def _style_profile(turns: list[dict[str, Any]]) -> dict[str, Any]:
    lengths = [len(_clean_turn_text(turn.get("text"))) for turn in turns if turn.get("speaker_role") == "BUYER"]
    lengths = [value for value in lengths if value]
    buyer_turn_count = len(lengths)
    short_count = sum(value <= 12 for value in lengths)
    return {
        "buyer_turn_count": buyer_turn_count,
        "median_message_length": int(statistics.median(lengths)) if lengths else 0,
        "short_message_ratio": round(short_count / buyer_turn_count, 4) if buyer_turn_count else 0.0,
        "style_instruction": "保持自然、简短、会根据上一条客服回复继续追问，不一次说完所有目标。",
    }


def _episode_turns(turns: list[dict[str, Any]], target_index: int, history_limit: int) -> list[dict[str, Any]]:
    prior = [turn for turn in turns if int(turn.get("turn_index") or 0) < target_index]
    cleaned: list[dict[str, Any]] = []
    for turn in prior[-history_limit:]:
        text = _clean_turn_text(turn.get("text"))
        if not text:
            continue
        cleaned.append({
            "speaker_role": str(turn.get("speaker_role") or ""),
            "message_type": str(turn.get("message_type") or "text"),
            "text": text,
            "turn_uid": str(turn.get("turn_uid") or ""),
        })
    return cleaned


def _scenario_candidate(
    *,
    case: dict[str, Any],
    review_items: list[dict[str, Any]],
    history_limit: int,
    min_source_turns: int,
    min_seed_turns: int,
) -> tuple[dict[str, Any] | None, str]:
    conversation = case.get("conversation") or {}
    turns = list(conversation.get("turns") or [])
    if len(turns) < min_source_turns:
        return None, "source_conversation_too_short"
    if conversation.get("role_unresolved_count") or conversation.get("privacy_review_required"):
        return None, "conversation_role_or_privacy_unresolved"
    if conversation.get("conversation_truncated"):
        return None, "source_conversation_truncated"

    target_uids = sorted({
        str(uid)
        for item in review_items
        for uid in (item.get("target_turn_uids") or [])
        if uid
    })
    target_turns = [turn for turn in turns if str(turn.get("turn_uid") or "") in target_uids]
    if not target_turns or any(turn.get("speaker_role") != "BUYER" for turn in target_turns):
        return None, "target_buyer_turn_missing"
    target_turn = sorted(target_turns, key=lambda turn: int(turn.get("turn_index") or 0))[-1]
    initial_message = _clean_turn_text(target_turn.get("text"))
    if (
        str(target_turn.get("message_type") or "text") != "text"
        or len(initial_message) < 4
        or _TOKEN_ONLY_RE.fullmatch(initial_message)
    ):
        return None, "target_buyer_turn_not_readable_text"
    domains = sorted({str(item.get("scenario_domain") or "unclassified") for item in review_items})
    if (
        domains == ["media_evidence"]
        and not case.get("expected_evidence")
        and str(target_turn.get("message_type") or "text") not in {"image", "link", "product_card", "order_card"}
    ):
        return None, "media_goal_without_target_media_contract"
    target_index = int(target_turn.get("turn_index") or 0)
    seed_history = _episode_turns(turns, target_index, history_limit)
    if len(seed_history) < min_seed_turns:
        return None, "seed_history_too_short"

    risk_levels = sorted({str(item.get("risk_level") or "unknown") for item in review_items})
    query_fact_types = sorted({sanitize_gold_text(item.get("query_fact_type")) for item in review_items if item.get("query_fact_type")})
    action_ids = sorted({
        str(action)
        for item in review_items
        for action in (item.get("required_actions") or (item.get("atomic_claim") or {}).get("required_action_points") or [])
        if action
    })
    expected_statuses = sorted({
        str((item.get("atomic_claim") or {}).get("expected_status") or "unresolved")
        for item in review_items
    })
    must_handoff = any(bool((item.get("atomic_claim") or {}).get("must_handoff")) for item in review_items)
    scenario_seed = {
        "case_uid": case.get("case_uid"),
        "target_turn_uids": target_uids,
        "domains": domains,
    }
    return {
        "scenario_uid": f"mts_{_content_hash(scenario_seed)[:20]}",
        "source_case_uid": str(case.get("case_uid") or ""),
        "scenario_domains": domains,
        "primary_domain": domains[0],
        "risk_levels": risk_levels,
        "query_fact_types": query_fact_types,
        "source_turn_count": len(turns),
        "source_buyer_turn_count": int((conversation.get("role_counts") or {}).get("BUYER") or 0),
        "target_turn_uids": target_uids,
        "source_linkage_fingerprint": conversation_linkage_fingerprint(seed_history, initial_message),
        "source_conversation_digest": conversation_content_digest(turns),
        "seed_history": seed_history,
        "initial_buyer_message": initial_message,
        "sidecar_present": bool(case.get("sidecar_present")),
        "sidecar_quality": "identity_present" if case.get("sidecar_present") else "identity_missing",
        "buyer_style": _style_profile(turns),
        "hidden_goal_contract": {
            "goal": f"围绕当前焦点“{initial_message}”继续澄清，直到得到可执行处理方案或明确、合理的人工处理边界。",
            "required_action_ids": action_ids,
            "must_handoff": must_handoff,
            "expected_statuses": expected_statuses,
            "fact_correctness_scorable": False,
            "label_review_status": "not_supervisor_approved",
        },
        "simulation_contract": {
            "max_generated_buyer_turns": 4,
            "buyer_must_not_invent_product_facts": True,
            "buyer_must_not_reveal_hidden_goals": True,
            "agent_receives_evaluation_labels": False,
        },
        "quality": {
            "source_is_real_reviewed_conversation": True,
            "privacy_scan_passed": True,
            "roles_resolved": True,
            "readable_target": True,
            "bounded_seed_history": True,
        },
    }, ""


def build_long_conversation_dataset(
    gold_dataset: dict[str, Any],
    review_queue: dict[str, Any],
    *,
    limit: int = 12,
    max_per_domain: int = 3,
    history_limit: int = 12,
    min_source_turns: int = 20,
    min_seed_turns: int = 6,
) -> dict[str, Any]:
    """Build a balanced, privacy-preserving Tier D scenario set."""
    findings = validate_gold_dataset(gold_dataset)
    if findings or (gold_dataset.get("privacy") or {}).get("privacy_scan_status") != "passed":
        raise ValueError(f"gold_dataset_privacy_validation_failed:{','.join(findings)}")
    if not isinstance(review_queue.get("items"), list):
        raise ValueError("review_queue_items_missing")

    case_by_uid = {str(case.get("case_uid") or ""): case for case in gold_dataset.get("cases") or []}
    review_by_case: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in review_queue.get("items") or []:
        uid = str(item.get("case_uid") or "")
        if uid:
            review_by_case[uid].append(item)

    rejected = Counter()
    candidates: list[dict[str, Any]] = []
    for case_uid, items in sorted(review_by_case.items()):
        case = case_by_uid.get(case_uid)
        if not case:
            rejected["gold_case_missing"] += 1
            continue
        candidate, reason = _scenario_candidate(
            case=case,
            review_items=items,
            history_limit=history_limit,
            min_source_turns=min_source_turns,
            min_seed_turns=min_seed_turns,
        )
        if candidate is None:
            rejected[reason] += 1
        else:
            candidates.append(candidate)

    buckets: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for candidate in candidates:
        buckets[candidate["primary_domain"]].append(candidate)
    for values in buckets.values():
        values.sort(key=lambda item: (-int(item["source_turn_count"]), item["scenario_uid"]))

    selected: list[dict[str, Any]] = []
    domain_counts = Counter()
    while len(selected) < limit:
        added = False
        for domain in sorted(buckets):
            if len(selected) >= limit or domain_counts[domain] >= max_per_domain or not buckets[domain]:
                continue
            selected.append(buckets[domain].pop(0))
            domain_counts[domain] += 1
            added = True
        if not added:
            break

    scenarios_hash = _content_hash(selected)
    result = {
        "schema_version": SCHEMA_VERSION,
        "evaluation_tier": EVALUATION_TIER,
        "dataset_status": DATASET_STATUS,
        "accuracy_claim_allowed": False,
        "source": {
            "gold_dataset_id": gold_dataset.get("dataset_id"),
            "gold_dataset_version": gold_dataset.get("dataset_version"),
            "gold_content_sha256": (gold_dataset.get("manifest") or {}).get("content_sha256"),
            "review_queue_content_sha256": _content_hash(review_queue.get("items") or []),
            "supervisor_approved_claim_count": 0,
        },
        "selection": {
            "candidate_count": len(candidates),
            "selected_count": len(selected),
            "domain_count": len(domain_counts),
            "domain_distribution": dict(sorted(domain_counts.items())),
            "rejected_reason_counts": dict(sorted(rejected.items())),
            "min_source_turns": min_source_turns,
            "min_seed_turns": min_seed_turns,
            "history_limit": history_limit,
            "max_per_domain": max_per_domain,
        },
        "privacy": {
            "source_privacy_validation": "passed",
            "output_privacy_scan_status": "pending",
            "output_privacy_violation_count": 0,
            "raw_customer_identity_included": False,
            "raw_order_or_product_identity_included": False,
            "source_case_identity_mode": "hmac_pseudonymized",
        },
        "scenarios": selected,
        "manifest": {"scenario_count": len(selected), "content_sha256": scenarios_hash},
    }
    privacy_findings = scan_long_conversation_privacy(result)
    result["privacy"]["output_privacy_scan_status"] = "passed" if not privacy_findings else "failed"
    result["privacy"]["output_privacy_violation_count"] = sum(
        int(item.get("count") or 0) for item in privacy_findings
    )
    result_findings = validate_long_conversation_dataset(result)
    if result_findings:
        raise ValueError(f"long_conversation_dataset_invalid:{','.join(result_findings)}")
    return result


def validate_long_conversation_dataset(dataset: dict[str, Any]) -> list[str]:
    findings: list[str] = []
    if dataset.get("schema_version") != SCHEMA_VERSION:
        findings.append("schema_version_invalid")
    if dataset.get("evaluation_tier") != EVALUATION_TIER or dataset.get("accuracy_claim_allowed") is not False:
        findings.append("tier_boundary_invalid")
    privacy_findings = scan_long_conversation_privacy(dataset)
    privacy = dataset.get("privacy") or {}
    if privacy_findings:
        findings.append("output_privacy_scan_failed")
    if privacy.get("output_privacy_scan_status") != ("passed" if not privacy_findings else "failed"):
        findings.append("output_privacy_scan_status_invalid")
    if int(privacy.get("output_privacy_violation_count") or 0) != sum(
        int(item.get("count") or 0) for item in privacy_findings
    ):
        findings.append("output_privacy_violation_count_invalid")
    scenarios = dataset.get("scenarios")
    if not isinstance(scenarios, list) or not scenarios:
        findings.append("scenarios_missing")
        return findings
    if (dataset.get("manifest") or {}).get("content_sha256") != _content_hash(scenarios):
        findings.append("manifest_hash_mismatch")
    if len({item.get("scenario_uid") for item in scenarios}) != len(scenarios):
        findings.append("scenario_uid_duplicate")
    for scenario in scenarios:
        if len(scenario.get("seed_history") or []) < int((dataset.get("selection") or {}).get("min_seed_turns") or 0):
            findings.append("seed_history_too_short")
        if not scenario.get("initial_buyer_message") or _TOKEN_ONLY_RE.fullmatch(str(scenario.get("initial_buyer_message") or "")):
            findings.append("initial_buyer_message_invalid")
        if scenario.get("source_linkage_fingerprint") != conversation_linkage_fingerprint(
            scenario.get("seed_history") or [], str(scenario.get("initial_buyer_message") or ""),
        ):
            findings.append("source_linkage_fingerprint_invalid")
        digest = str(scenario.get("source_conversation_digest") or "")
        if not re.fullmatch(r"[0-9a-f]{64}", digest):
            findings.append("source_conversation_digest_invalid")
        if (scenario.get("hidden_goal_contract") or {}).get("fact_correctness_scorable") is not False:
            findings.append("unapproved_fact_scoring_enabled")
        for turn in scenario.get("seed_history") or []:
            if turn.get("speaker_role") not in {"BUYER", "AGENT", "SYSTEM"}:
                findings.append("seed_role_invalid")
    return sorted(set(findings))


def assert_agent_payload_has_no_evaluation_labels(payload: dict[str, Any]) -> None:
    def walk(value: Any) -> set[str]:
        if isinstance(value, dict):
            found = set(value)
            for item in value.values():
                found.update(walk(item))
            return found
        if isinstance(value, list):
            found: set[str] = set()
            for item in value:
                found.update(walk(item))
            return found
        return set()

    leaked = LABEL_FIELDS.intersection(walk(payload))
    if leaked:
        raise ValueError(f"evaluation_label_leaked_to_agent:{','.join(sorted(leaked))}")


def validate_simulator_output(value: Any, allowed_action_ids: set[str]) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("simulator_output_not_object")
    required = {"next_message", "observed_action_ids", "buyer_state", "stop", "stop_reason"}
    if set(value) != required:
        raise ValueError("simulator_output_schema_mismatch")
    state = str(value.get("buyer_state") or "")
    reason = str(value.get("stop_reason") or "")
    if state not in ALLOWED_SIMULATOR_STATES or reason not in ALLOWED_STOP_REASONS:
        raise ValueError("simulator_output_enum_invalid")
    if not isinstance(value.get("stop"), bool) or not isinstance(value.get("observed_action_ids"), list):
        raise ValueError("simulator_output_type_invalid")
    raw_actions = [str(item) for item in value["observed_action_ids"]]
    actions = set(raw_actions)
    if len(actions) != len(raw_actions):
        raise ValueError("simulator_output_duplicate_action")
    if not actions.issubset(allowed_action_ids):
        raise ValueError("simulator_output_unknown_action")
    message = sanitize_gold_text(value.get("next_message"))
    if not value["stop"] and (not message or len(message) > 500):
        raise ValueError("simulator_next_message_invalid")
    if value["stop"] and reason == "continue":
        raise ValueError("simulator_stop_reason_invalid")
    return {
        "next_message": message,
        "observed_action_ids": sorted(actions),
        "buyer_state": state,
        "stop": value["stop"],
        "stop_reason": reason,
    }


def _stable_evidence_uid(value: Any) -> str:
    raw = str(value or "").strip()
    return f"evidence_{hashlib.sha256(raw.encode('utf-8')).hexdigest()[:20]}" if raw else ""


def build_tier_d_turn_observation(response: dict[str, Any]) -> dict[str, Any]:
    """Project one formal response into the sole immutable scoring/report view."""
    reply = str(
        response.get("sendable_reply")
        or response.get("suggested_reply")
        or response.get("draft_reply")
        or ""
    ).strip()
    media_types = tuple(sorted(
        str(block.get("type") or "").lower()
        for block in (response.get("reply_blocks") or [])
        if isinstance(block, dict) and str(block.get("type") or "").lower() in {"image", "video"}
    ))
    evidence = tuple(sorted((
        _stable_evidence_uid(item.get("evidence_uid") or item.get("chunk_uid") or item.get("id")),
        str(item.get("evidence_role") or ""),
        str(item.get("query_fact_type") or item.get("fact_type") or ""),
        str(item.get("source_type") or ""),
        str(item.get("gate_status") or ""),
        bool(item.get("is_placeholder") or item.get("placeholder")),
    ) for item in (response.get("selected_evidence") or []) if isinstance(item, dict)))
    completed_actions = tuple(sorted({
        str(event.get("action_id") or "")
        for event in (response.get("action_events") or [])
        if isinstance(event, dict)
        and str(event.get("status") or "") == "completed"
        and str(event.get("action_id") or "")
    }))
    final_audit = response.get("final_answer_audit") if isinstance(response.get("final_answer_audit"), dict) else {}
    semantic_audit = response.get("final_semantic_fit_audit") if isinstance(response.get("final_semantic_fit_audit"), dict) else {}
    pipeline = response.get("analysis_pipeline") if isinstance(response.get("analysis_pipeline"), dict) else {}
    debug = response.get("evidence_debug") if isinstance(response.get("evidence_debug"), dict) else {}
    shadow = debug.get("evidence_action_shadow") if isinstance(debug.get("evidence_action_shadow"), dict) else {}
    funnel = shadow.get("evidence_funnel") if isinstance(shadow.get("evidence_funnel"), dict) else {}
    return {
        "schema_version": TURN_OBSERVATION_SCHEMA_VERSION,
        "reply": sanitize_gold_text(reply),
        "can_send": bool(response.get("can_send")),
        "requires_human_review": bool(response.get("requires_human_review")),
        "reply_status": str(response.get("reply_status") or ""),
        "attached_media_block_types": list(media_types),
        "attached_media_block_count": len(media_types),
        "selected_evidence_count": len(evidence),
        "selected_evidence_summary": [
            {
                "evidence_uid": row[0],
                "evidence_role": row[1],
                "fact_type": row[2],
                "source_type": row[3],
                "gate_status": row[4],
                "is_placeholder": row[5],
            }
            for row in evidence
        ],
        "completed_action_ids": list(completed_actions),
        "final_answer_audit": {
            "passed": bool(final_audit.get("passed", True)),
            "issues": sorted(str(issue) for issue in (final_audit.get("issues") or [])),
        },
        "final_semantic_fit_audit": {
            "passed": bool(semantic_audit.get("passed", True)),
            "issues": sorted(str(issue) for issue in (semantic_audit.get("issues") or [])),
        },
        "analysis_pipeline_version": str(pipeline.get("version") or ""),
        "evidence_action_shadow": {
            "available": bool(shadow),
            "evidence_funnel": funnel,
        },
    }


def build_fixed_replay_turn_observation(
    response: dict[str, Any],
    *,
    product_identity: dict[str, Any],
    sidecar_present: bool,
    sidecar_quality: str,
    convergence_enabled: bool,
    latency_ms: float | None,
    status_code: int,
    error_type: str = "",
    previous_reply: str = "",
) -> dict[str, Any]:
    """Build the single report-safe observation used by fixed replay scoring."""
    base = build_tier_d_turn_observation(response)
    debug = response.get("evidence_debug") if isinstance(response.get("evidence_debug"), dict) else {}
    admitted = debug.get("admitted_answer_context") if isinstance(debug.get("admitted_answer_context"), dict) else {}
    query_fact_type = str(debug.get("query_fact_type") or response.get("query_fact_type") or "").strip()
    if not admitted:
        understanding = response.get("turn_understanding")
        if not isinstance(understanding, dict):
            understanding = debug.get("parallel_understanding")
        if not isinstance(understanding, dict):
            understanding = {}
        if not understanding.get("requested_claims") and query_fact_type:
            understanding = {
                **understanding,
                "requested_claims": [{"claim_type": query_fact_type}],
            }
        admitted = AdmittedAnswerContextService().build_for_response(
            response,
            product_identity=product_identity,
            understanding=understanding,
        )
    funnel = build_turn_evidence_funnel(
        response,
        product_identity=product_identity,
        admitted_context=admitted,
        convergence_enabled=convergence_enabled,
    )
    resolutions = admitted.get("claim_resolutions") if isinstance(admitted.get("claim_resolutions"), list) else []
    resolution_counts = Counter(
        str(item.get("status") or "unknown")
        for item in resolutions
        if isinstance(item, dict)
    )
    reply = str(base.get("reply") or "").strip()
    previous = str(previous_reply or "").strip()
    context_status = str(
        debug.get("canonical_context_status")
        or debug.get("conversation_context_status")
        or ("accepted" if status_code == 200 else "invalid")
    )
    return {
        **base,
        "schema_version": FIXED_REPLAY_OBSERVATION_SCHEMA_VERSION,
        "query_fact_type": query_fact_type,
        "context_status": context_status,
        "sidecar_present": bool(sidecar_present),
        "sidecar_quality": str(sidecar_quality or "unknown"),
        "evidence_funnel": funnel,
        "candidate_evidence_count": int((funnel.get("counts") or {}).get("candidate_count") or 0),
        "reviewed_direct_count": int((funnel.get("counts") or {}).get("direct_reviewed_count") or 0),
        "identity_matched_count": int((funnel.get("counts") or {}).get("identity_matched_count") or 0),
        "admitted_evidence_count": int((funnel.get("counts") or {}).get("formally_admissible_count") or 0),
        "unresolved_claim_count": int(resolution_counts.get("unresolved", 0)),
        "conflicting_claim_count": int(resolution_counts.get("conflicting", 0)),
        "handoff_reason": str(response.get("reason_for_review") or ""),
        "latency_ms": latency_ms,
        "status_code": int(status_code or 0),
        "error_type": str(error_type or ""),
        "normalized_reply_sha256": hashlib.sha256(reply.encode("utf-8")).hexdigest() if reply else "",
        "normalized_reply_length": len(reply),
        "repeated_from_previous": bool(reply and previous and reply == previous),
    }


def validate_fixed_long_conversation_dataset(dataset: dict[str, Any]) -> list[str]:
    findings: list[str] = []
    if dataset.get("schema_version") != FIXED_REPLAY_SCHEMA_VERSION:
        findings.append("schema_version_invalid")
    scenarios = dataset.get("scenarios")
    if not isinstance(scenarios, list) or not scenarios:
        findings.append("scenarios_missing")
        scenarios = []
    if int((dataset.get("manifest") or {}).get("scenario_count") or 0) != len(scenarios):
        findings.append("scenario_count_mismatch")
    scenario_uids = [str(item.get("scenario_uid") or "") for item in scenarios if isinstance(item, dict)]
    if not all(scenario_uids) or len(scenario_uids) != len(set(scenario_uids)):
        findings.append("scenario_uid_invalid")
    for item in scenarios:
        if not isinstance(item, dict):
            findings.append("scenario_invalid")
            continue
        turns = item.get("fixed_buyer_turns")
        if not isinstance(turns, list) or not turns:
            findings.append("fixed_buyer_turns_missing")
            continue
        if any(
            not isinstance(turn, dict)
            or turn.get("speaker_role") != "BUYER"
            or not _clean_turn_text(turn.get("text"))
            for turn in turns
        ):
            findings.append("fixed_buyer_turn_invalid")
    expected_hash = str((dataset.get("manifest") or {}).get("content_sha256") or "")
    payload = dict(dataset)
    manifest = dict(payload.get("manifest") or {})
    manifest.pop("content_sha256", None)
    payload["manifest"] = manifest
    if not expected_hash or expected_hash != _content_hash(payload):
        findings.append("content_sha256_mismatch")
    if scan_long_conversation_privacy(dataset):
        findings.append("privacy_scan_failed")
    return sorted(set(findings))


def classify_fixed_replay_breakpoint(observation: dict[str, Any]) -> str:
    if observation.get("error_type") or int(observation.get("status_code") or 0) != 200:
        return "runtime_or_provider_error"
    if observation.get("context_status") in {"invalid", "missing"}:
        return "source_context_missing"
    if not observation.get("sidecar_present"):
        return "sidecar_missing"
    funnel = observation.get("evidence_funnel") or {}
    earliest = str(funnel.get("earliest_breakpoint") or "")
    mapping = {
        "context_missing": "source_context_missing",
        "product_identity_missing": "sidecar_missing",
        "source_coverage_gap": "candidate_evidence_missing",
        "evidence_role_ineligible": "evidence_role_ineligible",
        "review_status_ineligible": "evidence_role_ineligible",
        "identity_mismatch": "identity_mismatch",
        "fact_type_mismatch": "fact_type_mismatch",
        "placeholder_value": "placeholder_or_conflict_blocked",
        "conflicting_evidence": "placeholder_or_conflict_blocked",
        "convergence_disabled": "convergence_disabled",
        "graph_selection_gap": "admitted_but_not_selected",
    }
    if earliest in mapping:
        return mapping[earliest]
    if not (observation.get("final_answer_audit") or {}).get("passed", True):
        return "final_audit_block"
    if not (observation.get("final_semantic_fit_audit") or {}).get("passed", True):
        return "semantic_fit_failure"
    if observation.get("requires_human_review"):
        return "correct_safe_handoff"
    return ""


def summarize_fixed_replay_results(results: list[dict[str, Any]]) -> dict[str, Any]:
    turns = [turn for result in results for turn in (result.get("turns") or [])]
    observations = [turn.get("observation") or {} for turn in turns]

    def ratio(predicate) -> dict[str, Any]:
        numerator = sum(bool(predicate(item)) for item in observations)
        denominator = len(observations)
        return {
            "numerator": numerator,
            "denominator": denominator,
            "rate": round(numerator / denominator, 4) if denominator else None,
        }

    latencies = sorted(float(item.get("latency_ms") or 0) for item in observations if item.get("latency_ms") is not None)
    def percentile(fraction: float) -> float | None:
        if not latencies:
            return None
        index = min(len(latencies) - 1, max(0, round((len(latencies) - 1) * fraction)))
        return round(latencies[index], 1)

    unsafe_auto_send = sum(
        bool(item.get("can_send")) and (
            item.get("unresolved_claim_count", 0) > 0
            or not (item.get("final_answer_audit") or {}).get("passed", True)
        )
        for item in observations
    )
    unsupported_media = sum(
        contains_unsupported_media_promise(
            str(item.get("reply") or ""),
            bool(item.get("attached_media_block_count")),
        )
        for item in observations
    )
    media_role_mismatch = sum(
        bool({"unsupported_media_claim", "media_role_mismatch"}.intersection({
            str(issue)
            for issue in [
                *((item.get("final_answer_audit") or {}).get("issues") or []),
                *((item.get("final_semantic_fit_audit") or {}).get("issues") or []),
            ]
        }))
        for item in observations
    )
    breakpoints = Counter(str(item.get("earliest_breakpoint") or "none") for item in observations)
    repeated_numerator = sum(bool(item.get("repeated_from_previous")) for item in observations)
    repeated_denominator = sum(
        max(0, len(result.get("turns") or []) - 1)
        for result in results
    )
    return {
        "scenario_count": len(results),
        "turn_count": len(observations),
        "execution_success": ratio(lambda item: item.get("status_code") == 200 and not item.get("error_type") and bool(item.get("reply"))),
        "empty_reply_count": sum(not bool(item.get("reply")) for item in observations),
        "error_count": sum(bool(item.get("error_type")) or item.get("status_code") != 200 for item in observations),
        "timeout_count": sum("timeout" in str(item.get("error_type") or "").lower() for item in observations),
        "latency_ms": {"p50": percentile(0.5), "p95": percentile(0.95)},
        "context_preservation_rate": ratio(lambda item: item.get("context_status") not in {"invalid", "missing"}),
        "candidate_evidence_turn_rate": ratio(lambda item: int(item.get("candidate_evidence_count") or 0) > 0),
        "admitted_evidence_turn_rate": ratio(lambda item: int(item.get("admitted_evidence_count") or 0) > 0),
        "selected_evidence_turn_rate": ratio(lambda item: int(item.get("selected_evidence_count") or 0) > 0),
        "selected_evidence_total_count": sum(int(item.get("selected_evidence_count") or 0) for item in observations),
        "supported_low_risk_claim_count": None,
        "unresolved_high_risk_claim_count": sum(int(item.get("unresolved_claim_count") or 0) for item in observations),
        "conflicting_claim_block_count": sum(int(item.get("conflicting_claim_count") or 0) for item in observations),
        "action_completion_rate": None,
        "handoff_appropriateness": None,
        "generic_handoff_rate": ratio(lambda item: item.get("requires_human_review") and not item.get("selected_evidence_count")),
        "consecutive_reply_repetition_rate": {
            "numerator": repeated_numerator,
            "denominator": repeated_denominator,
            "rate": round(repeated_numerator / repeated_denominator, 4) if repeated_denominator else None,
        },
        "query_reply_mismatch_count": sum(not (item.get("final_semantic_fit_audit") or {}).get("passed", True) for item in observations),
        "unsupported_assertion_count": sum(not (item.get("final_answer_audit") or {}).get("passed", True) for item in observations),
        "unsupported_media_promise_count": unsupported_media,
        "media_role_mismatch_count": media_role_mismatch,
        "actual_media_block_count": sum(int(item.get("attached_media_block_count") or 0) for item in observations),
        "unsafe_auto_send_count": unsafe_auto_send,
        "can_send_count": sum(bool(item.get("can_send")) for item in observations),
        "requires_human_review_count": sum(bool(item.get("requires_human_review")) for item in observations),
        "final_audit_failure_count": sum(not (item.get("final_answer_audit") or {}).get("passed", True) for item in observations),
        "semantic_fit_failure_count": sum(not (item.get("final_semantic_fit_audit") or {}).get("passed", True) for item in observations),
        "earliest_breakpoint_counts": dict(sorted(breakpoints.items())),
        "semantic_pass": None,
        "overall_pass": None,
        "real_customer_accuracy": None,
        "accuracy_claim_allowed": False,
    }


def _observation_from_turn(turn: dict[str, Any]) -> dict[str, Any]:
    observation = turn.get("observation")
    if isinstance(observation, dict) and observation.get("schema_version") in {
        "tier-d-turn-observation/v1", TURN_OBSERVATION_SCHEMA_VERSION,
    }:
        return observation
    response = turn.get("agent_response") if isinstance(turn.get("agent_response"), dict) else {}
    return build_tier_d_turn_observation(response)


def recompute_tier_d_blocking_reasons(
    *,
    must_handoff: bool,
    turns: list[dict[str, Any]],
    transcript_grade: dict[str, Any],
) -> list[str]:
    """Recompute deterministic blockers using only report-safe observations."""
    blockers: list[str] = []
    declared_completed_actions: set[str] = set()
    for turn in turns:
        observation = _observation_from_turn(turn)
        reply = str(observation.get("reply") or "").strip()
        if turn.get("agent_error") or int(turn.get("status_code") or 0) != 200:
            blockers.append("agent_execution_error")
        if not reply:
            blockers.append("empty_agent_reply")
        if not observation.get("analysis_pipeline_version"):
            blockers.append("formal_pipeline_missing")
        if must_handoff and bool(observation.get("can_send")):
            blockers.append("unsafe_auto_send")
        if must_handoff and not bool(observation.get("requires_human_review")):
            blockers.append("required_handoff_missing")
        if contains_unsupported_media_promise(
            reply,
            bool(observation.get("attached_media_block_count")),
        ):
            blockers.append("unsupported_media_promise")
        audit = observation.get("final_answer_audit") or {}
        audit_issues = set(audit.get("issues") or [])
        if "unsupported_media_claim" in audit_issues:
            blockers.append("unsupported_media_claim")
        if audit.get("passed") is False:
            blockers.append("final_answer_audit_failed")
        semantic_audit = observation.get("final_semantic_fit_audit") or {}
        if semantic_audit.get("passed") is False:
            blockers.append("final_semantic_fit_audit_failed")
        declared_completed_actions.update(str(item) for item in observation.get("completed_action_ids") or [])
    covered_actions = set(transcript_grade.get("covered_action_ids") or [])
    if (
        transcript_grade.get("status") == "completed"
        and declared_completed_actions
        and declared_completed_actions != covered_actions
    ):
        blockers.append("action_event_text_mismatch")
    return sorted(set(blockers))


def score_simulation_thread(
    scenario: dict[str, Any],
    turns: list[dict[str, Any]],
    *,
    terminal_buyer_state: str,
    terminal_stop_reason: str,
    observed_action_ids: set[str],
    grader: Any | None = None,
) -> dict[str, Any]:
    goal = scenario.get("hidden_goal_contract") or {}
    required_actions = set(goal.get("required_action_ids") or [])
    must_handoff = bool(goal.get("must_handoff"))
    if grader is None:
        transcript_grade = {
            "status": "grader_not_qualified",
            "reason": "semantic_grader_unavailable",
            "required_action_ids": sorted(required_actions),
            "covered_action_ids": [],
            "uncovered_action_ids": sorted(required_actions),
            "unknown_action_ids": [],
            "action_coverage_rate": None,
            "grader": {},
        }
    else:
        transcript_grade = grader.grade(required_actions, turns)
    covered_actions = set(transcript_grade["covered_action_ids"])
    action_rate = transcript_grade.get("action_coverage_rate")
    blockers = recompute_tier_d_blocking_reasons(
        must_handoff=must_handoff,
        turns=turns,
        transcript_grade=transcript_grade,
    )
    contract_pass = not blockers
    buyer_outcome_pass = terminal_buyer_state in {"satisfied", "handoff_accepted"} and terminal_stop_reason in {
        "resolved", "handoff_accepted",
    }
    semantic_pass = action_rate == 1.0 if transcript_grade.get("status") == "completed" else None
    overall_pass = (
        contract_pass and buyer_outcome_pass and semantic_pass
        if semantic_pass is not None
        else None
    )
    evaluation_status = "completed" if semantic_pass is not None else "semantic_grader_unavailable"
    return {
        "passed": overall_pass,
        "overall_pass": overall_pass,
        "semantic_pass": semantic_pass,
        "evaluation_status": evaluation_status,
        "contract_passed": contract_pass,
        "buyer_outcome_passed": buyer_outcome_pass,
        "required_action_count": len(required_actions),
        "graded_required_action_count": len(covered_actions),
        "action_coverage_rate": action_rate,
        "transcript_action_grade": transcript_grade,
        "counterfactual_comparisons": [],
        "simulator_observed_action_ids": sorted(required_actions.intersection(observed_action_ids)),
        "blocking_reasons": sorted(set(blockers)),
        "terminal_buyer_state": terminal_buyer_state,
        "terminal_stop_reason": terminal_stop_reason,
        "accuracy_metric": None,
        "accuracy_claim_allowed": False,
    }


def summarize_simulation_results(results: list[dict[str, Any]]) -> dict[str, Any]:
    scores = [item.get("score") or {} for item in results]
    total = len(scores)
    action_rows = [score for score in scores if score.get("action_coverage_rate") is not None]
    scenario_trials: dict[str, list[bool]] = defaultdict(list)
    semantic_scores = [
        score for score in scores
        if score.get("overall_pass", score.get("passed")) is not None
    ]
    for item, score in zip(results, scores):
        overall = score.get("overall_pass", score.get("passed"))
        if overall is not None:
            scenario_trials[str(item.get("scenario_uid") or "")].append(bool(overall))
    return {
        "trial_count": total,
        "scenario_count": len(scenario_trials),
        "overall_exploratory_pass_count": sum(
            bool(score.get("overall_pass", score.get("passed"))) for score in semantic_scores
        ),
        "overall_exploratory_pass_denominator": len(semantic_scores),
        "overall_exploratory_pass_rate": round(
            sum(bool(score.get("overall_pass", score.get("passed"))) for score in semantic_scores)
            / len(semantic_scores), 4,
        ) if semantic_scores else None,
        "contract_pass_rate": round(sum(bool(score.get("contract_passed")) for score in scores) / total, 4) if total else None,
        "buyer_outcome_pass_rate": round(sum(bool(score.get("buyer_outcome_passed")) for score in scores) / total, 4) if total else None,
        "mean_action_coverage_rate": round(
            sum(float(score["action_coverage_rate"]) for score in action_rows) / len(action_rows), 4,
        ) if action_rows else None,
        "stable_scenario_pass_rate": round(
            sum(all(values) for values in scenario_trials.values()) / len(scenario_trials), 4,
        ) if scenario_trials else None,
        "any_scenario_pass_rate": round(
            sum(any(values) for values in scenario_trials.values()) / len(scenario_trials), 4,
        ) if scenario_trials else None,
        "blocking_reason_counts": dict(sorted(Counter(
            reason for score in scores for reason in (score.get("blocking_reasons") or [])
        ).items())),
        "semantic_grader_unavailable_count": sum(
            score.get("evaluation_status") == "semantic_grader_unavailable" for score in scores
        ),
        "counterfactual_comparison_count": 0,
        "counterfactual_preference_counts": {},
        "counterfactual_grader_error_count": 0,
        "real_customer_accuracy_rate": None,
        "real_customer_accuracy_status": "not_measured_by_tier_d",
    }
