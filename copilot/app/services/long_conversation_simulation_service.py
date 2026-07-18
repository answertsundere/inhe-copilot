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
    has_attached_sendable_media_asset,
)
from app.services.real_accuracy_gold_set_service import validate_gold_dataset
from app.services.real_accuracy_privacy_service import sanitize_gold_text, scan_privacy_output


SCHEMA_VERSION = "long-conversation-simulation-set-v1"
EVALUATION_TIER = "tier_d_simulated_multiturn"
DATASET_STATUS = "exploratory_not_real_accuracy"
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
    actions = {str(item) for item in value["observed_action_ids"]}
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


def score_simulation_thread(
    scenario: dict[str, Any],
    turns: list[dict[str, Any]],
    *,
    terminal_buyer_state: str,
    terminal_stop_reason: str,
    observed_action_ids: set[str],
) -> dict[str, Any]:
    goal = scenario.get("hidden_goal_contract") or {}
    required_actions = set(goal.get("required_action_ids") or [])
    must_handoff = bool(goal.get("must_handoff"))
    blockers: list[str] = []
    for turn in turns:
        response = turn.get("agent_response") if isinstance(turn.get("agent_response"), dict) else {}
        reply = str(response.get("sendable_reply") or response.get("suggested_reply") or response.get("draft_reply") or "").strip()
        if turn.get("agent_error") or int(turn.get("status_code") or 0) != 200:
            blockers.append("agent_execution_error")
        if not reply:
            blockers.append("empty_agent_reply")
        if not isinstance(response.get("analysis_pipeline"), dict):
            blockers.append("formal_pipeline_missing")
        if must_handoff and bool(response.get("can_send")):
            blockers.append("unsafe_auto_send")
        if must_handoff and not bool(response.get("requires_human_review")):
            blockers.append("required_handoff_missing")
        if contains_unsupported_media_promise(reply, has_attached_sendable_media_asset(response)):
            blockers.append("unsupported_media_promise")
        audit_issues = set((response.get("final_answer_audit") or {}).get("issues") or [])
        if "unsupported_media_claim" in audit_issues:
            blockers.append("unsupported_media_claim")
        final_audit = response.get("final_answer_audit")
        if isinstance(final_audit, dict) and final_audit.get("passed") is False:
            blockers.append("final_answer_audit_failed")
        semantic_audit = response.get("final_semantic_fit_audit")
        if isinstance(semantic_audit, dict) and semantic_audit.get("passed") is False:
            blockers.append("final_semantic_fit_audit_failed")
    contract_pass = not blockers
    covered_actions = required_actions.intersection(observed_action_ids)
    action_rate = len(covered_actions) / len(required_actions) if required_actions else None
    buyer_outcome_pass = terminal_buyer_state in {"satisfied", "handoff_accepted"} and terminal_stop_reason in {
        "resolved", "handoff_accepted",
    }
    overall_pass = contract_pass and buyer_outcome_pass and (action_rate is None or action_rate == 1.0)
    return {
        "passed": overall_pass,
        "contract_passed": contract_pass,
        "buyer_outcome_passed": buyer_outcome_pass,
        "required_action_count": len(required_actions),
        "observed_required_action_count": len(covered_actions),
        "action_coverage_rate": round(action_rate, 4) if action_rate is not None else None,
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
    for item, score in zip(results, scores):
        scenario_trials[str(item.get("scenario_uid") or "")].append(bool(score.get("passed")))
    return {
        "trial_count": total,
        "scenario_count": len(scenario_trials),
        "overall_exploratory_pass_count": sum(bool(score.get("passed")) for score in scores),
        "overall_exploratory_pass_rate": round(sum(bool(score.get("passed")) for score in scores) / total, 4) if total else None,
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
        "real_customer_accuracy_rate": None,
        "real_customer_accuracy_status": "not_measured_by_tier_d",
    }
