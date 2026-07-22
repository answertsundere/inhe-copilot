"""Build privacy-safe, supervisor-reviewable claim proposals for Gold cases.

This evaluation-only module groups cases from structured Gold metadata.  It
does not inspect buyer wording to choose a policy, does not create product
facts, and never changes an Agent request or knowledge-base record.
"""

from __future__ import annotations

from collections import Counter
import re
from typing import Any

from app.services.fact_type_alias_service import is_high_risk_fact_type
from app.services.real_accuracy_gold_set_service import canonical_text


STRATEGY_GROUPS: dict[str, dict[str, str]] = {
    "product_fact_direct": {
        "label": "商品事实直接回答",
        "description": "仅在同商品的正式已审核证据齐全时，允许审核为支持型商品事实。",
    },
    "known_fact_high_risk_remainder": {
        "label": "已知事实与高风险子问题",
        "description": "低风险事实可单独核对；安全、认证、承重等子问题保持未确认或禁止断言。",
    },
    "order_logistics_service_action": {
        "label": "订单与物流核对动作",
        "description": "先核对订单和物流状态，不把服务动作或后台状态写成商品事实。",
    },
    "aftersales_verification": {
        "label": "售后核对与处理动作",
        "description": "先确认问题、订单和已有凭证；退款、补发、赔付须由授权结果决定。",
    },
    "promotion_gift_invoice": {
        "label": "优惠、赠品与发票规则",
        "description": "以当前订单和活动规则为准，不预先承诺优惠、赠品或开票结果。",
    },
    "installation_accessory": {
        "label": "安装与配件处理",
        "description": "定位步骤、部位和配件；没有同款安装证据时不提供高风险安装处方。",
    },
    "media_evidence": {
        "label": "图片或素材依赖",
        "description": "核对现有图片、视频和素材角色；素材候选不代表已经发送。",
    },
    "context_insufficient": {
        "label": "上下文不足",
        "description": "先补齐当前问题、商品或订单上下文，避免在身份不明时作出判断。",
    },
    "not_scorable": {
        "label": "不可自动评分",
        "description": "角色、隐私、输入或评测目标不满足条件，只能单独复核。",
    },
}

_GROUP_BY_QUERY_CLASS = {
    "尺寸": "product_fact_direct",
    "产品事实": "product_fact_direct",
    "物流": "order_logistics_service_action",
    "订单协助": "order_logistics_service_action",
    "售后": "aftersales_verification",
    "活动": "promotion_gift_invoice",
    "优惠": "promotion_gift_invoice",
    "赠品": "promotion_gift_invoice",
    "发票": "promotion_gift_invoice",
    "安装": "installation_accessory",
    "配件": "installation_accessory",
}
_HIGH_RISK_QUERY_CLASSES = {"材质安全", "年龄适配", "质检", "儿童安全", "承重"}
_UNSCORABLE_CLASSIFICATIONS = {
    "privacy_review_required",
    "role_unresolved",
    "conversation_truncated",
    "invalid",
    "media_only",
}
_CONTROLLED_TOKEN_RE = re.compile(r"\[[^\]]+\]")


def _clean(value: Any) -> str:
    return canonical_text(value, limit=240).strip()


def _identifier(value: Any) -> str:
    """Keep controlled HMAC identifiers byte-for-byte stable."""
    return str(value or "").strip()


def _query_class(case: dict[str, Any]) -> str:
    return _clean(case.get("query_class"))


def _direct_evidence(case: dict[str, Any]) -> list[dict[str, Any]]:
    """Return only explicitly eligible, identity-scoped formal evidence."""
    selected: list[dict[str, Any]] = []
    for item in case.get("expected_evidence") or []:
        if not isinstance(item, dict):
            continue
        uid = _identifier(item.get("evidence_uid"))
        if not uid:
            continue
        review = _clean(item.get("review_status")).lower()
        role = _clean(item.get("evidence_role") or item.get("role")).lower()
        direct = item.get("direct_answer_allowed") is True or item.get("evidence_allowed_for_direct_answer") is True
        identity = item.get("identity_matched") is True or item.get("identity_scope_match") is True
        blocked = bool(item.get("reference_only") or item.get("placeholder") or item.get("conflicting"))
        if review not in {"reviewed", "published", "approved", "verified"}:
            continue
        if role not in {"product_fact_direct", "faq_direct", "product_structured_fact"}:
            continue
        if not direct or not identity or blocked:
            continue
        selected.append({
            "evidence_uid": uid,
            "fact_type": _clean(item.get("fact_type")),
            "attribute_key": _clean(item.get("attribute_key")),
            "review_status": review,
            "evidence_role": role,
            "identity_scope": "matched",
        })
    return sorted(selected, key=lambda item: (item["fact_type"], item["attribute_key"], item["evidence_uid"]))


def strategy_group_for_case(case: dict[str, Any]) -> str:
    """Group by reviewed structured metadata, never by buyer-message keywords."""
    classification = _clean(case.get("classification"))
    if classification in _UNSCORABLE_CLASSIFICATIONS:
        return "not_scorable"
    if classification == "context_gap" or not case.get("sidecar_present"):
        return "context_insufficient"
    query_class = _query_class(case)
    normalized = query_class.lower()
    if query_class in _HIGH_RISK_QUERY_CLASSES or is_high_risk_fact_type(normalized):
        return "known_fact_high_risk_remainder"
    if query_class in _GROUP_BY_QUERY_CLASS:
        return _GROUP_BY_QUERY_CLASS[query_class]
    if bool((case.get("notes") or {}).get("media_requested")):
        return "media_evidence"
    return "not_scorable"


def _claim(
    case_uid: str,
    suffix: str,
    *,
    claim_kind: str,
    query_fact_type: str,
    attribute_key: str,
    expected_status: str,
    strategy_group: str,
    risk_level: str = "medium",
    required_action_points: tuple[str, ...] = (),
    required_tool: str | None = None,
    must_handoff: bool = False,
    forbidden_claims: tuple[str, ...] = (),
    evidence: list[dict[str, Any]] | None = None,
    source_reference: str = "source_reviewed_candidate",
) -> dict[str, Any]:
    evidence = evidence or []
    return {
        "claim_uid": f"{case_uid}:{suffix}",
        "claim_kind": claim_kind,
        "query_fact_type": query_fact_type,
        "attribute_key": attribute_key,
        "expected_status": expected_status,
        "acceptable_values": [],
        "normalized_value": None,
        "unit": None,
        "required_terms": [],
        "supporting_evidence_uids": [item["evidence_uid"] for item in evidence],
        "required_tool": required_tool,
        "required_action_points": list(required_action_points),
        "must_handoff": must_handoff,
        "forbidden_claims": list(forbidden_claims),
        "partial_answer_allowed": True,
        "review_status": "draft",
        "proposal_status": "policy_validated",
        "source_reference": source_reference,
        "evidence_provenance": evidence,
        "risk_level": risk_level,
        "identity_scope": "matched" if evidence else "not_evaluated",
        "can_support_auto_send": False,
        "strategy_group": strategy_group,
    }


def candidate_claims(case: dict[str, Any], strategy_group: str) -> list[dict[str, Any]]:
    """Produce draft-only atomic expectations from policy and provenance.

    No historical answer can promote a product fact.  A supported product-fact
    proposal appears only when the Gold record itself contains eligible formal
    evidence provenance.
    """
    case_uid = _identifier(case.get("case_uid"))
    query_class = _query_class(case) or "unclassified"
    evidence = _direct_evidence(case)
    high_risk = strategy_group == "known_fact_high_risk_remainder"
    if strategy_group == "product_fact_direct":
        status = "supported" if evidence else "unresolved"
        return [
            _claim(case_uid, "product_fact", claim_kind="factual_claim", query_fact_type=query_class,
                   attribute_key="requested_product_fact", expected_status=status, strategy_group=strategy_group,
                   evidence=evidence, must_handoff=False),
            _claim(case_uid, "evidence_boundary", claim_kind="context_requirement", query_fact_type=query_class,
                   attribute_key="formal_evidence", expected_status="supported", strategy_group=strategy_group,
                   required_action_points=("use_identity_scoped_evidence",), must_handoff=not bool(evidence)),
        ]
    if high_risk:
        return [
            _claim(case_uid, "supported_part", claim_kind="factual_claim", query_fact_type=query_class,
                   attribute_key="low_risk_supported_part", expected_status="unresolved", strategy_group=strategy_group,
                   risk_level="high", must_handoff=False),
            _claim(case_uid, "high_risk_boundary", claim_kind="prohibited", query_fact_type=query_class,
                   attribute_key="high_risk_conclusion", expected_status="prohibited", strategy_group=strategy_group,
                   risk_level="high", must_handoff=True, forbidden_claims=("无证据的高风险结论",)),
        ]
    if strategy_group == "order_logistics_service_action":
        return [
            _claim(case_uid, "verify_live_state", claim_kind="tool_action", query_fact_type=query_class,
                   attribute_key="order_or_logistics_state", expected_status="supported", strategy_group=strategy_group,
                   required_tool="order_or_logistics_lookup", required_action_points=("use_sidecar_first", "verify_live_state")),
            _claim(case_uid, "no_live_state_assumption", claim_kind="prohibited", query_fact_type=query_class,
                   attribute_key="live_state", expected_status="prohibited", strategy_group=strategy_group,
                   must_handoff=True, forbidden_claims=("未核对即承诺订单或物流结果",)),
        ]
    if strategy_group == "aftersales_verification":
        return [
            _claim(case_uid, "verify_case", claim_kind="service_action", query_fact_type=query_class,
                   attribute_key="aftersales_evidence", expected_status="supported", strategy_group=strategy_group,
                   required_action_points=("review_existing_evidence", "verify_order_and_issue")),
            _claim(case_uid, "controlled_outcome", claim_kind="unresolved_claim", query_fact_type=query_class,
                   attribute_key="refund_replacement_compensation", expected_status="unresolved", strategy_group=strategy_group,
                   must_handoff=True),
        ]
    if strategy_group == "promotion_gift_invoice":
        return [
            _claim(case_uid, "verify_rule", claim_kind="tool_action", query_fact_type=query_class,
                   attribute_key="current_rule", expected_status="supported", strategy_group=strategy_group,
                   required_tool="promotion_or_invoice_lookup", required_action_points=("verify_current_rule",)),
            _claim(case_uid, "no_extra_promise", claim_kind="prohibited", query_fact_type=query_class,
                   attribute_key="controlled_benefit", expected_status="prohibited", strategy_group=strategy_group,
                   must_handoff=True, forbidden_claims=("未授权的优惠、赠品或开票承诺",)),
        ]
    if strategy_group == "installation_accessory":
        return [
            _claim(case_uid, "locate_issue", claim_kind="service_action", query_fact_type=query_class,
                   attribute_key="installation_or_accessory_context", expected_status="supported", strategy_group=strategy_group,
                   required_action_points=("locate_step_or_component", "review_matching_material")),
            _claim(case_uid, "installation_boundary", claim_kind="prohibited", query_fact_type=query_class,
                   attribute_key="high_risk_installation", expected_status="prohibited", strategy_group=strategy_group,
                   must_handoff=True, forbidden_claims=("无同款证据的安装或结构安全处方",)),
        ]
    if strategy_group == "media_evidence":
        return [
            _claim(case_uid, "media_role", claim_kind="delivery_constraint", query_fact_type=query_class,
                   attribute_key="matching_media_role", expected_status="unresolved", strategy_group=strategy_group,
                   required_action_points=("verify_media_role_and_delivery_block",), must_handoff=False),
            _claim(case_uid, "no_media_promise", claim_kind="prohibited", query_fact_type=query_class,
                   attribute_key="media_delivery", expected_status="prohibited", strategy_group=strategy_group,
                   forbidden_claims=("没有实际发送块时承诺已发送图片或视频",)),
        ]
    if strategy_group == "context_insufficient":
        return [
            _claim(case_uid, "context_requirement", claim_kind="context_requirement", query_fact_type=query_class,
                   attribute_key="missing_context", expected_status="unresolved", strategy_group=strategy_group,
                   required_action_points=("request_minimum_missing_context",), must_handoff=True),
        ]
    return []


def _target_recommendation(case: dict[str, Any], label: dict[str, Any] | None) -> dict[str, Any]:
    turns = [item for item in ((case.get("conversation") or {}).get("turns") or []) if isinstance(item, dict)]
    saved = ((label or {}).get("label") or {}).get("target_turn_uids") or []
    if saved:
        return {"turn_uids": [str(item) for item in saved], "reason": "reviewer_selected", "requires_confirmation": False}
    question = _clean(case.get("customer_message"))
    buyer_turns = [item for item in turns if item.get("speaker_role") == "BUYER"]
    exact = [item for item in buyer_turns if _clean(item.get("text")) == question]
    if exact:
        return {"turn_uids": [str(exact[-1].get("turn_uid"))], "reason": "customer_message_exact_match", "requires_confirmation": True}
    if buyer_turns:
        return {"turn_uids": [], "reason": "customer_message_turn_missing", "requires_confirmation": True}
    return {"turn_uids": [], "reason": "buyer_turn_missing", "requires_confirmation": True}


def _safe_saved_label(label: dict[str, Any] | None) -> dict[str, Any] | None:
    if not label:
        return None
    return {
        "label": label.get("label") or {},
        "review_status": _clean(label.get("review_status")),
        "optimistic_lock_version": int(label.get("optimistic_lock_version") or 0),
        "updated_at": _clean(label.get("updated_at")),
    }


def bounded_conversation_window(case: dict[str, Any], target_turn_uids: list[str], *, before: int = 3, after: int = 2) -> dict[str, Any]:
    turns = [item for item in ((case.get("conversation") or {}).get("turns") or []) if isinstance(item, dict)]
    index_by_uid = {str(item.get("turn_uid")): position for position, item in enumerate(turns)}
    anchors = [index_by_uid[uid] for uid in target_turn_uids if uid in index_by_uid]
    if not anchors:
        return {"turns": [], "truncated": bool(turns), "total_turn_count": len(turns)}
    start = max(0, min(anchors) - before)
    end = min(len(turns), max(anchors) + after + 1)
    window_turns = []
    for turn in turns[start:end]:
        safe_turn = dict(turn)
        safe_turn["text"] = canonical_text(turn.get("text"), limit=1800)
        window_turns.append(safe_turn)
    return {
        "turns": window_turns,
        "truncated": start > 0 or end < len(turns),
        "total_turn_count": len(turns),
        "window_start_index": start,
        "window_end_index": end - 1,
    }


def build_claim_review_plan(dataset: dict[str, Any], labels: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Create a deterministic, non-approving review plan for the workbench."""
    label_by_case = {_identifier(item.get("case_uid")): item for item in labels or [] if isinstance(item, dict)}
    items: list[dict[str, Any]] = []
    for case in sorted((item for item in dataset.get("cases") or [] if isinstance(item, dict)), key=lambda item: _identifier(item.get("case_uid"))):
        case_uid = _identifier(case.get("case_uid"))
        label = label_by_case.get(case_uid)
        group = strategy_group_for_case(case)
        recommendation = _target_recommendation(case, label)
        claims = candidate_claims(case, group)
        saved_status = _clean((label or {}).get("review_status"))
        if saved_status == "approved":
            proposal_status = "supervisor_approved"
        elif saved_status == "rejected":
            proposal_status = "rejected"
        elif claims:
            proposal_status = "policy_validated"
        elif _clean((case.get("reference_label") or {}).get("reference_text")):
            proposal_status = "source_reviewed_candidate"
        else:
            proposal_status = "ai_proposed"
        exclusion_reason = ""
        if group == "not_scorable":
            exclusion_reason = _clean(case.get("classification")) or "not_scorable"
        elif group == "context_insufficient":
            exclusion_reason = "sidecar_or_context_incomplete"
        eligibility = "ready_for_reviewer" if claims and not exclusion_reason else "not_eligible"
        items.append({
            "case_uid": case_uid,
            "scenario_domain": group,
            "buyer_question": _clean(case.get("customer_message")),
            "sidecar_quality": "identity_present" if case.get("sidecar_present") else "identity_missing",
            "sidecar_context_presence": {
                "product": bool((case.get("sidecar_identity") or {}).get("product") or (case.get("sidecar_identity") or {}).get("sku")),
                "order": bool((case.get("sidecar_identity") or {}).get("order")),
                "identity_values_included": False,
            },
            "strategy": {"id": group, **STRATEGY_GROUPS[group]},
            "proposal_status": proposal_status,
            "source_reference": "reviewed_answer" if _clean((case.get("reference_label") or {}).get("reference_text")) else "no_reviewed_answer",
            "reviewed_answer_source": (case.get("reference_label") or {}).get("label_status") or "manual_label_required",
            "candidate_claims": claims,
            "required_actions": sorted({action for claim in claims for action in claim.get("required_action_points") or []}),
            "prohibited_claims": sorted({phrase for claim in claims for phrase in claim.get("forbidden_claims") or []}),
            "risk_level": _clean(case.get("risk_level")) or "unknown",
            "label_eligibility": eligibility,
            "exclusion_reason": exclusion_reason,
            "target_recommendation": recommendation,
            "conversation_window": bounded_conversation_window(case, recommendation["turn_uids"]),
            "formal_evidence_summary": _direct_evidence(case),
            "evidence_provenance": _direct_evidence(case),
            "saved_label": _safe_saved_label(label),
        })
    return {
        "schema_version": "real-accuracy-claim-review-plan-v1",
        "dataset_id": _clean(dataset.get("dataset_id")),
        "dataset_version": _clean(dataset.get("dataset_version")),
        "items": items,
        "strategy_counts": dict(sorted(Counter(item["scenario_domain"] for item in items).items())),
        "proposal_status_counts": dict(sorted(Counter(item["proposal_status"] for item in items).items())),
        "approved_case_count": sum(item["proposal_status"] == "supervisor_approved" for item in items),
        "auto_approved_count": 0,
        "formal_knowledge_writes": 0,
        "can_change_can_send": False,
    }


def _has_reviewable_question(value: Any) -> bool:
    """Require visible buyer text without assigning policy from its wording."""
    return bool(_CONTROLLED_TOKEN_RE.sub("", _clean(value)).strip())


def _required_evidence_types(claim: dict[str, Any]) -> list[str]:
    roles = sorted({
        _clean(item.get("evidence_role"))
        for item in claim.get("evidence_provenance") or []
        if isinstance(item, dict) and _clean(item.get("evidence_role"))
    })
    if roles:
        return roles
    if claim.get("required_tool"):
        return ["verified_live_tool_result"]
    if claim.get("claim_kind") in {"service_action", "unresolved_claim", "context_requirement"}:
        return ["reviewed_service_policy_or_case_context"]
    if claim.get("claim_kind") == "delivery_constraint":
        return ["approved_matching_delivery_block"]
    if claim.get("expected_status") == "prohibited":
        return ["explicit_reviewed_authorization_required"]
    return ["reviewed_identity_scoped_direct_evidence"]


def build_minimum_supervisor_queue(
    plan: dict[str, Any],
    *,
    target_claim_count: int = 30,
    minimum_domain_count: int = 5,
    max_domain_fraction: float = 0.30,
) -> dict[str, Any]:
    """Select a deterministic, balanced, non-approving Gold review queue.

    This function only rearranges the already privacy-safe review plan.  It
    never writes labels and never converts a proposal into an approval.
    """
    if target_claim_count < 1 or minimum_domain_count < 1 or not 0 < max_domain_fraction <= 1:
        raise ValueError("supervisor_queue_parameters_invalid")
    max_per_domain = max(1, int(target_claim_count * max_domain_fraction))
    candidates_by_domain: dict[str, list[dict[str, Any]]] = {}
    excluded = Counter()
    for item in plan.get("items") or []:
        if not isinstance(item, dict):
            continue
        domain = _clean(item.get("scenario_domain"))
        target = item.get("target_recommendation") or {}
        window = item.get("conversation_window") or {}
        roles = {str(turn.get("speaker_role") or "") for turn in window.get("turns") or [] if isinstance(turn, dict)}
        context_follow_up = (
            domain == "context_insufficient"
            and any(
                isinstance(claim, dict)
                and claim.get("claim_kind") == "context_requirement"
                and claim.get("expected_status") == "unresolved"
                for claim in item.get("candidate_claims") or []
            )
        )
        if item.get("label_eligibility") != "ready_for_reviewer" and not context_follow_up:
            excluded["not_eligible"] += 1
            continue
        if not _has_reviewable_question(item.get("buyer_question")):
            excluded["buyer_question_not_readable"] += 1
            continue
        if not target.get("turn_uids") or not {"BUYER", "AGENT"}.issubset(roles):
            excluded["conversation_context_incomplete"] += 1
            continue
        saved_label = item.get("saved_label") or {}
        saved_case_status = _clean(saved_label.get("review_status"))
        saved_claims = {
            _identifier(claim.get("claim_uid")): claim
            for claim in ((saved_label.get("label") or {}).get("claims") or [])
            if isinstance(claim, dict) and _identifier(claim.get("claim_uid"))
        }
        for claim in item.get("candidate_claims") or []:
            if not isinstance(claim, dict) or not _identifier(claim.get("claim_uid")):
                excluded["claim_invalid"] += 1
                continue
            claim_uid = _identifier(claim.get("claim_uid"))
            saved_claim = saved_claims.get(claim_uid)
            if saved_case_status in {"approved", "rejected"} and not saved_claim:
                excluded["claim_missing_from_terminal_decision"] += 1
                continue
            approval_state = _clean((saved_claim or {}).get("review_status")) or saved_case_status or "draft"
            if approval_state == "rejected":
                excluded["supervisor_rejected"] += 1
                continue
            effective_claim = dict(saved_claim or claim)
            candidate = {
                "case_uid": _identifier(item.get("case_uid")),
                "deidentified_case_uid": _identifier(item.get("case_uid")),
                "scenario_domain": domain,
                "business_domain": domain,
                "conversation_window": item.get("conversation_window"),
                "target_turn_uids": list(target.get("turn_uids") or []),
                "target_turn_uid": str((target.get("turn_uids") or [""])[0]),
                "query_fact_type": _clean(effective_claim.get("query_fact_type")),
                "atomic_claim": effective_claim,
                "expected_claim_status": _clean(effective_claim.get("expected_status")),
                "required_actions": list(effective_claim.get("required_action_points") or []),
                "expected_action": list(effective_claim.get("required_action_points") or []),
                "required_evidence_types": _required_evidence_types(effective_claim),
                "forbidden_claims": list(effective_claim.get("forbidden_claims") or []),
                "evidence_provenance": list(effective_claim.get("evidence_provenance") or []),
                "source_provenance": {
                    "source_reference": _clean(effective_claim.get("source_reference")),
                    "evidence": list(effective_claim.get("evidence_provenance") or []),
                },
                "sidecar_quality": _clean(item.get("sidecar_quality")),
                "product_or_order_context_presence": dict(item.get("sidecar_context_presence") or {}),
                "required_context_summary": (
                    f"有界上下文包含 {len(window.get('turns') or [])} 个回合；"
                    f"身份上下文状态为 {_clean(item.get('sidecar_quality')) or 'unknown'}。"
                ),
                "risk_level": _clean(effective_claim.get("risk_level") or item.get("risk_level")),
                "required_handoff": bool(effective_claim.get("must_handoff")),
                "privacy_scan_status": "passed",
                "approval_state": approval_state,
                "review_audit": {
                    "reviewer_reviewed": _clean((item.get("saved_label") or {}).get("review_status")) in {"reviewed", "approved"},
                    "supervisor_approved": _clean((item.get("saved_label") or {}).get("review_status")) == "approved",
                    "approval_event_present": None,
                    "approval_event_validation_owner": "approved_gold_manifest",
                },
                "review_recommendation": "supervisor_decision_required",
                "review_focus": "verify_provenance_and_expected_boundary",
                "exception_flags": [
                    "formal_evidence_missing"
                    if not effective_claim.get("supporting_evidence_uids") else ""
                ],
            }
            if context_follow_up:
                candidate["exception_flags"].append("context_follow_up_only")
            candidate["exception_flags"] = [item for item in candidate["exception_flags"] if item]
            candidates_by_domain.setdefault(domain, []).append(candidate)

    for domain in candidates_by_domain:
        candidates_by_domain[domain].sort(key=lambda item: (
            _identifier((item.get("atomic_claim") or {}).get("claim_uid")),
            _identifier(item.get("case_uid")),
        ))
    selected: list[dict[str, Any]] = sorted(
        (
            candidate
            for candidates in candidates_by_domain.values()
            for candidate in candidates
            if candidate.get("approval_state") == "approved"
        ),
        key=lambda item: (
            _clean(item.get("business_domain")),
            _identifier((item.get("atomic_claim") or {}).get("claim_uid")),
            _identifier(item.get("case_uid")),
        ),
    )[:target_claim_count]
    selected_per_domain = Counter()
    selected_uids = {
        _identifier((item.get("atomic_claim") or {}).get("claim_uid"))
        for item in selected
    }
    selected_per_domain.update(_clean(item.get("business_domain")) for item in selected)
    for domain, candidates in candidates_by_domain.items():
        candidates_by_domain[domain] = [
            item
            for item in candidates
            if _identifier((item.get("atomic_claim") or {}).get("claim_uid")) not in selected_uids
        ]
    positions = Counter()
    while len(selected) < target_claim_count:
        available = [
            domain for domain, items in candidates_by_domain.items()
            if positions[domain] < len(items) and selected_per_domain[domain] < max_per_domain
        ]
        if not available:
            break
        domain = min(available, key=lambda value: (selected_per_domain[value], value))
        selected.append(candidates_by_domain[domain][positions[domain]])
        positions[domain] += 1
        selected_per_domain[domain] += 1

    domain_counts = dict(sorted(selected_per_domain.items()))
    multi_turn_count = sum(
        len((item.get("conversation_window") or {}).get("turns") or []) > 1
        for item in selected
    )
    partial_answer_count = sum(bool((item.get("atomic_claim") or {}).get("partial_answer_allowed")) for item in selected)
    high_risk_or_handoff_count = sum(
        item.get("risk_level") == "high" or item.get("required_handoff") is True
        for item in selected
    )
    service_action_count = sum(
        item.get("scenario_domain") in {
            "order_logistics_service_action", "aftersales_verification", "promotion_gift_invoice",
        }
        or (item.get("atomic_claim") or {}).get("claim_kind") in {"service_action", "tool_action"}
        for item in selected
    )
    coverage_metrics = {
        "selected_claim_count": len(selected),
        "selected_domain_count": len(domain_counts),
        "multi_turn_claim_count": multi_turn_count,
        "partial_answer_claim_count": partial_answer_count,
        "high_risk_or_handoff_claim_count": high_risk_or_handoff_count,
        "service_action_claim_count": service_action_count,
    }
    coverage_requirements = {
        "minimum_claim_count": target_claim_count,
        "minimum_domain_count": minimum_domain_count,
        "minimum_multi_turn_claim_count": 8,
        "minimum_partial_answer_claim_count": 5,
        "minimum_high_risk_or_handoff_claim_count": 5,
        "minimum_service_action_claim_count": 5,
    }
    coverage_requirements_met = (
        len(selected) >= target_claim_count
        and len(domain_counts) >= minimum_domain_count
        and multi_turn_count >= coverage_requirements["minimum_multi_turn_claim_count"]
        and partial_answer_count >= coverage_requirements["minimum_partial_answer_claim_count"]
        and high_risk_or_handoff_count >= coverage_requirements["minimum_high_risk_or_handoff_claim_count"]
        and service_action_count >= coverage_requirements["minimum_service_action_claim_count"]
    )
    return {
        "schema_version": "real-accuracy-minimum-supervisor-queue-v2",
        "dataset_id": _clean(plan.get("dataset_id")),
        "dataset_version": _clean(plan.get("dataset_version")),
        "target_claim_count": target_claim_count,
        "selected_claim_count": len(selected),
        "minimum_domain_count": minimum_domain_count,
        "selected_domain_count": len(domain_counts),
        "max_claims_per_domain": max_per_domain,
        "domain_distribution": domain_counts,
        "coverage_requirements": coverage_requirements,
        "coverage_metrics": coverage_metrics,
        "coverage_requirements_met": coverage_requirements_met,
        "queue_status": "ready_for_supervisor_review" if coverage_requirements_met else "insufficient_reviewable_claims",
        "items": selected,
        "excluded_candidate_reasons": dict(sorted(excluded.items())),
        "supervisor_approved_claim_count": sum(item.get("approval_state") == "approved" for item in selected),
        "auto_approved_count": 0,
        "formal_knowledge_writes": 0,
        "can_change_can_send": False,
    }
