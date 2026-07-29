"""Evidence-bounded, review-only model-first answer composition."""

from __future__ import annotations

import hashlib
import json
import time
from copy import deepcopy
from typing import Any

from app.services.customer_facing_safe_handoff_service import (
    CUSTOMER_FACING_INTERNAL_REDLINE_TERMS,
)
from app.services.media_asset_service import is_delivery_media_asset_eligible
from app.services.no_evidence_reply_policy_service import (
    _claimed_delivery_media_kinds,
    contains_unsupported_media_promise,
    has_attached_sendable_media_asset,
    media_delivery_claim_issues,
)


COMPOSER_VERSION = "model-first-answer-composer-v3"
COMPOSER_ENVELOPE_CONTRACT_VERSION = "bounded-json-envelope-v1"
_ALLOWED_OUTPUT_FIELDS = {
    "clauses",
}
_ALLOWED_CLAUSE_FIELDS = {
    "goal_ref",
    "clause_kind",
    "text",
    "evidence_refs",
}
_ALLOWED_CLAUSE_KINDS = {
    "supported_fact",
    "unresolved",
    "allowed_inference",
    "service_action",
    "empathy_or_transition",
}
_UNRESOLVED_STATUSES = {"unresolved", "conflicting", "prohibited"}
_INFERENCE_RISK_RANK = {"low": 0, "medium": 1}
_NON_RENDERABLE_GOAL_KINDS = {
    "evidence_dependency",
    "service_action",
    "media_request",
    "media_candidate",
    "contextual_constraint",
}
_AUTHORITATIVE_GOAL_SCHEMA = "turn-understanding-goal-identity/v2"
_AUTHORITATIVE_GOAL_OWNER = "turn_understanding_owner"
_AUTHORITATIVE_GOAL_SOURCE = "current_customer_message"
_PROCESS_LANGUAGE_TERMS = (
    "帮您核对",
    "我先核对",
    "确认后回复",
    "确认后再回复",
    "请稍等",
    "您稍等",
    "转人工",
    "资料显示",
    "系统显示",
    "公司资料",
)


class ModelFirstAnswerComposerService:
    """Compose one candidate reply without owning facts, safety, or delivery."""

    def compose(
        self,
        response: dict[str, Any],
        *,
        customer_message: str,
        copilot_context: dict[str, Any] | None = None,
        client: Any | None = None,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        original = deepcopy(response)
        minimal_context = self._minimal_context(original)
        result = self._base_result(minimal_context)
        if not minimal_context:
            result["rejection_reason"] = "minimal_decision_context_missing"
            return original, result

        evidence, uid_by_ref = self._project_evidence(minimal_context)
        known_refs = set(uid_by_ref)
        inference_policies, policy_by_ref, policy_error = (
            self._project_bounded_inference_policies(minimal_context)
        )
        if policy_error:
            result["rejection_reason"] = policy_error
            return original, result
        partitions, goal_uid_by_ref, goal_error = self._partition_composer_inputs(
            minimal_context,
            uid_by_ref,
            policy_by_ref,
            actual_media_types=self._actual_media_types(original),
        )
        result["input_eligibility"] = dict(
            partitions.get("eligibility_metrics") or {}
        )
        if goal_error:
            result["rejection_reason"] = goal_error
            return original, result
        customer_goals = partitions["renderable_customer_goals"]
        payload = self._prompt_payload(
            minimal_context,
            customer_message=customer_message,
            evidence=evidence,
            partitions=partitions,
            inference_policies=inference_policies,
        )

        started = time.perf_counter()
        try:
            if client is None:
                from app.llm.client import get_llm_client

                client = get_llm_client()
            if not getattr(client, "api_key", ""):
                result["rejection_reason"] = "formal_llm_not_configured"
                return original, result
            result["provider_diagnostics"]["model_call_count"] = 1
            completion = client.create_chat_completion(
                model=client.model,
                messages=[
                    {"role": "system", "content": self._system_prompt()},
                    {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
                ],
                temperature=0,
                max_tokens=500,
                response_format={"type": "json_object"},
                _single_attempt_no_repair=True,
            )
            choice = completion.choices[0] if completion.choices else None
            content = str(
                getattr(getattr(choice, "message", None), "content", "") or ""
            )
            finish_reason = str(
                getattr(choice, "finish_reason", "") or ""
            )
            self._record_provider_response(
                result,
                content=content,
                finish_reason=finish_reason,
                latency_ms=int((time.perf_counter() - started) * 1000),
            )
            envelope = result["provider_diagnostics"]["response_envelope"]
            if finish_reason == "length":
                result["rejection_reason"] = "composer_truncated_response"
                result["validation_diagnostics"] = self._diagnostics(
                    "truncated_response",
                    json_path="$",
                    expected_type="complete_json_object",
                    actual_type=envelope,
                )
                return original, result
            if not content.strip():
                result["rejection_reason"] = "composer_completion_empty"
                result["validation_diagnostics"] = self._diagnostics(
                    "completion_empty",
                    json_path="$",
                    expected_type="json_object",
                    actual_type="empty",
                )
                return original, result
            (
                json_payload,
                envelope,
                envelope_unwrap_count,
                envelope_error,
            ) = self._unwrap_json_envelope(content)
            result["provider_diagnostics"].update({
                "response_envelope": envelope,
                "envelope_unwrap_count": envelope_unwrap_count,
            })
            if envelope_error:
                result["rejection_reason"] = "composer_fenced_or_free_text"
                result["validation_diagnostics"] = self._diagnostics(
                    envelope_error,
                    json_path="$",
                    expected_type="raw_json_or_single_json_fence",
                    actual_type=envelope,
                )
                return original, result
            try:
                parsed = json.loads(json_payload)
            except json.JSONDecodeError:
                result["rejection_reason"] = "composer_json_parse_error"
                result["validation_diagnostics"] = self._diagnostics(
                    "json_parse_error",
                    json_path="$",
                    expected_type="complete_json_object",
                    actual_type=envelope,
                )
                return original, result
        except Exception as exc:
            result["provider_diagnostics"]["provider_latency_ms"] = int(
                (time.perf_counter() - started) * 1000
            )
            result["provider_diagnostics"]["provider_error_type"] = type(
                exc
            ).__name__
            result["validation_diagnostics"] = self._diagnostics(
                "provider_error",
                json_path="$",
                expected_type="completion",
                actual_type=type(exc).__name__,
            )
            result["rejection_reason"] = f"formal_llm_error:{type(exc).__name__}"
            return original, result

        validation_error, validation_diagnostics = (
            self._validate_output_with_diagnostics(
            parsed,
            known_refs=known_refs,
            customer_goals=customer_goals,
            non_renderable_goal_refs=set(
                partitions.get("non_renderable_goal_refs") or set()
            ),
            response=original,
            )
        )
        result["validation_diagnostics"] = validation_diagnostics
        if validation_error:
            result["rejection_reason"] = validation_error
            if validation_error == "composer_unsupported_media_promise":
                result["media_claim_diagnostics"] = (
                    self._media_claim_diagnostics(
                        parsed,
                        customer_goals=customer_goals,
                        response=original,
                        minimal_context=minimal_context,
                    )
                )
            return original, result

        result["input_eligibility"]["non_customer_goal_clause_count"] = 0
        result["input_eligibility"]["customer_goal_clause_coverage"] = {
            "numerator": len(customer_goals),
            "denominator": len(customer_goals),
            "rate": 1.0 if customer_goals else None,
        }
        if not customer_goals:
            result.update({
                "status": "accepted",
                "rejection_reason": "",
                "candidate_reply": "",
                "used_for_final_reply": False,
                "composition_applicable": False,
            })
            updated = deepcopy(original)
            updated["model_first_answer_composer"] = result
            updated.setdefault("evidence_debug", {})[
                "model_first_answer_composer"
            ] = result
            return updated, result

        clauses_by_goal = {
            str(item["goal_ref"]): item for item in parsed["clauses"]
        }
        ordered_clauses = [
            clauses_by_goal[str(goal["goal_ref"])] for goal in customer_goals
        ]
        reply = "\n".join(str(item["text"]).strip() for item in ordered_clauses)
        used_refs = sorted({
            str(ref)
            for item in ordered_clauses
            for ref in item["evidence_refs"]
        })
        unresolved_types = {
            str(goal["claim_type"])
            for goal in customer_goals
            if goal["resolution_status"] in _UNRESOLVED_STATUSES
            and str(goal.get("claim_type") or "").strip()
        }
        goals_by_ref = {
            str(goal["goal_ref"]): goal for goal in customer_goals
        }
        allowed_reasoning = sorted({
            str(goal.get("scope_qualifier") or "")
            for goal in customer_goals
            if goal.get("required_clause_kind") == "allowed_inference"
            and str(goal.get("scope_qualifier") or "")
        })
        result.update({
            "status": "accepted",
            "rejection_reason": "",
            "candidate_reply": reply,
            "used_evidence_uids": [uid_by_ref[ref] for ref in used_refs],
            "unresolved_claim_types": sorted(unresolved_types),
            "covered_goal_refs": [
                goal_uid_by_ref[str(goal["goal_ref"])] for goal in customer_goals
            ],
            "clauses": [
                {
                    "clause_ref": f"C{index}",
                    "goal_ref": goal_uid_by_ref[str(clause["goal_ref"])],
                    "clause_kind": str(clause["clause_kind"]),
                    "text": str(clause["text"]).strip(),
                    "evidence_uids": [
                        uid_by_ref[str(ref)] for ref in clause["evidence_refs"]
                    ],
                    "inference_policy_refs": list(
                        goals_by_ref[str(clause["goal_ref"])].get(
                            "required_inference_policy_refs"
                        )
                        or []
                    ),
                    "scope_qualifier": str(
                        goals_by_ref[str(clause["goal_ref"])].get(
                            "scope_qualifier"
                        )
                        or ""
                    ),
                    "inference_risk_level": str(
                        goals_by_ref[str(clause["goal_ref"])].get(
                            "inference_risk_level"
                        )
                        or ""
                    ),
                    "maximum_risk_level": str(
                        goals_by_ref[str(clause["goal_ref"])].get(
                            "maximum_risk_level"
                        )
                        or ""
                    ),
                    "inference_review_only": (
                        goals_by_ref[str(clause["goal_ref"])].get(
                            "inference_review_only"
                        )
                        is True
                    ),
                    "required_qualifiers": list(
                        goals_by_ref[str(clause["goal_ref"])].get(
                            "required_qualifiers"
                        )
                        or []
                    ),
                    "prohibited_extensions": list(
                        goals_by_ref[str(clause["goal_ref"])].get(
                            "prohibited_extensions"
                        )
                        or []
                    ),
                }
                for index, clause in enumerate(ordered_clauses, start=1)
            ],
            "used_for_final_reply": True,
            "composition_applicable": True,
            "allowed_low_risk_reasoning": allowed_reasoning,
        })
        updated = deepcopy(original)
        updated["suggested_reply"] = reply
        updated["draft_reply"] = reply
        updated["generation_mode"] = "model_first_answer_composer"
        updated["requires_human_review"] = True
        updated["can_send"] = False
        updated["sendable_reply"] = ""
        updated["reply_status"] = "needs_human_review"
        updated["reason_for_review"] = self._append_reason(
            str(updated.get("reason_for_review") or ""),
            "model_first_candidate_review_only",
        )
        updated["model_first_answer_composer"] = result
        updated.setdefault("evidence_debug", {})["model_first_answer_composer"] = result
        return updated, result

    @staticmethod
    def _minimal_context(response: dict[str, Any]) -> dict[str, Any]:
        candidates = (
            response.get("minimal_decision_context"),
            (response.get("evidence_debug") or {}).get("minimal_decision_context"),
        )
        for candidate in candidates:
            if isinstance(candidate, dict) and candidate:
                return deepcopy(candidate)
        return {}

    @staticmethod
    def _base_result(minimal_context: dict[str, Any]) -> dict[str, Any]:
        stats = minimal_context.get("context_stats") if isinstance(minimal_context, dict) else {}
        return {
            "version": COMPOSER_VERSION,
            "status": "provider_blocked",
            "rejection_reason": "",
            "candidate_reply": "",
            "used_evidence_uids": [],
            "unresolved_claim_types": [],
            "covered_goal_refs": [],
            "clauses": [],
            "context_metrics": dict(stats or {}),
            "used_for_final_reply": False,
            "can_change_can_send": False,
            "requires_human_review": True,
            "can_send": False,
            "provider_diagnostics": {
                "response_envelope": "not_called",
                "response_length": 0,
                "response_sha256": "",
                "finish_reason": "",
                "provider_latency_ms": None,
                "provider_error_type": "",
                "model_call_count": 0,
                "retry_count": 0,
                "repair_count": 0,
                "json_repair_count": 0,
                "envelope_contract_version": COMPOSER_ENVELOPE_CONTRACT_VERSION,
                "envelope_unwrap_count": 0,
            },
            "validation_diagnostics": ModelFirstAnswerComposerService._diagnostics(
                "not_started",
            ),
            "media_claim_diagnostics": {},
            "input_eligibility": {
                "renderable_customer_goal_count": 0,
                "supporting_dependency_count": 0,
                "excluded_compatibility_dependency_count": 0,
                "non_customer_goal_clause_count": 0,
                "customer_goal_clause_coverage": {
                    "numerator": 0,
                    "denominator": 0,
                    "rate": None,
                },
                "dependency_evidence_link_coverage": {
                    "numerator": 0,
                    "denominator": 0,
                    "rate": None,
                },
                "unknown_goal_kind_count": 0,
            },
        }

    @staticmethod
    def _project_evidence(
        minimal_context: dict[str, Any],
    ) -> tuple[list[dict[str, Any]], dict[str, str]]:
        rows = [
            item
            for item in minimal_context.get("admitted_evidence") or []
            if isinstance(item, dict) and str(item.get("evidence_uid") or "").strip()
        ]
        rows.sort(key=lambda item: str(item.get("evidence_uid") or ""))
        projected: list[dict[str, Any]] = []
        uid_by_ref: dict[str, str] = {}
        for index, item in enumerate(rows, start=1):
            ref = f"E{index}"
            uid_by_ref[ref] = str(item["evidence_uid"]).strip()
            projected.append({
                "evidence_ref": ref,
                "fact_type": str(item.get("fact_type") or ""),
                "attribute_key": str(item.get("attribute_key") or ""),
                "content": str(item.get("content") or item.get("value") or ""),
            })
        return projected, uid_by_ref

    @staticmethod
    def _partition_composer_inputs(
        minimal_context: dict[str, Any],
        uid_by_ref: dict[str, str],
        policy_by_ref: dict[str, dict[str, Any]],
        *,
        actual_media_types: list[str],
    ) -> tuple[dict[str, Any], dict[str, str], str]:
        partitions = {
            "renderable_customer_goals": [],
            "supporting_dependencies": [],
            "service_actions": list(
                minimal_context.get("service_actions") or []
            ),
            "media_context": {
                "candidate_count": len(
                    minimal_context.get("media_candidates") or []
                ),
                "request_refs": [],
                "actual_attached_media_types": list(actual_media_types),
            },
            "contextual_constraints": {
                "conflicting_claim_count": len(
                    minimal_context.get("conflicting_claims") or []
                ),
                "constraint_refs": [],
                "safety_constraints": dict(
                    minimal_context.get("safety_constraints") or {}
                ),
            },
            "non_renderable_goal_refs": set(),
            "eligibility_metrics": {
                "renderable_customer_goal_count": 0,
                "supporting_dependency_count": 0,
                "excluded_compatibility_dependency_count": 0,
                "non_customer_goal_clause_count": 0,
                "customer_goal_clause_coverage": {
                    "numerator": 0,
                    "denominator": 0,
                    "rate": None,
                },
                "dependency_evidence_link_coverage": {
                    "numerator": 0,
                    "denominator": 0,
                    "rate": None,
                },
                "unknown_goal_kind_count": 0,
            },
        }
        ref_by_uid = {uid: ref for ref, uid in uid_by_ref.items()}
        requested_claims = [
            item
            for item in minimal_context.get("requested_claims") or []
            if isinstance(item, dict)
        ]
        resolutions = [
            item
            for item in minimal_context.get("claim_resolutions") or []
            if isinstance(item, dict)
        ]
        resolutions_by_goal_ref: dict[str, list[dict[str, Any]]] = {}
        for resolution in resolutions:
            goal_ref = str(resolution.get("goal_ref") or "").strip()
            if goal_ref:
                resolutions_by_goal_ref.setdefault(goal_ref, []).append(
                    resolution
                )

        authoritative_goals: list[dict[str, Any]] = []
        dependencies: list[dict[str, Any]] = []
        non_renderable_claims: list[dict[str, Any]] = []
        seen_refs: set[str] = set()
        for claim in requested_claims:
            goal_kind = str(claim.get("goal_kind") or "").strip()
            goal_ref = str(claim.get("goal_ref") or "").strip()
            if not goal_kind:
                if claim.get("supporting_only") is True:
                    partitions["eligibility_metrics"][
                        "excluded_compatibility_dependency_count"
                    ] += 1
                    continue
                partitions["eligibility_metrics"][
                    "unknown_goal_kind_count"
                ] += 1
                return (
                    partitions,
                    {},
                    "composer_goal_kind_missing",
                )
            if goal_kind == "compatibility_claim":
                if claim.get("customer_goal_eligible") is False:
                    non_renderable_claims.append(claim)
                    continue
                partitions["eligibility_metrics"][
                    "unknown_goal_kind_count"
                ] += 1
                return (
                    partitions,
                    {},
                    "composer_unknown_goal_kind",
                )
            if goal_kind not in {
                "customer_goal",
                *_NON_RENDERABLE_GOAL_KINDS,
            }:
                partitions["eligibility_metrics"][
                    "unknown_goal_kind_count"
                ] += 1
                return (
                    partitions,
                    {},
                    "composer_unknown_goal_kind",
                )
            if not goal_ref or goal_ref in seen_refs:
                return (
                    partitions,
                    {},
                    "composer_goal_ref_invalid",
                )
            seen_refs.add(goal_ref)
            if not ModelFirstAnswerComposerService._has_authoritative_provenance(
                claim
            ):
                return (
                    partitions,
                    {},
                    "composer_goal_provenance_invalid",
                )
            if goal_kind == "customer_goal":
                if (
                    claim.get("supporting_only") is True
                    or claim.get("customer_goal_eligible") is False
                ):
                    non_renderable_claims.append(claim)
                    continue
                authoritative_goals.append(claim)
            elif goal_kind == "evidence_dependency":
                dependencies.append(claim)
            else:
                non_renderable_claims.append(claim)

        authoritative_ref_set = {
            str(item["goal_ref"]).strip() for item in authoritative_goals
        }
        resolution_goal_refs = {
            str(item.get("goal_ref") or "").strip()
            for item in resolutions
            if str(item.get("goal_kind") or "").strip() == "customer_goal"
        }
        if resolution_goal_refs - authoritative_ref_set:
            return (
                partitions,
                {},
                "composer_non_authoritative_customer_resolution",
            )

        goals: list[dict[str, Any]] = []
        goal_uid_by_ref: dict[str, str] = {}
        seen_uids: set[str] = set()
        prompt_ref_by_goal_ref: dict[str, str] = {}
        for index, claim in enumerate(
            sorted(
                authoritative_goals,
                key=lambda item: str(item.get("goal_ref") or ""),
            ),
            start=1,
        ):
            authoritative_goal_ref = str(claim["goal_ref"]).strip()
            matching = resolutions_by_goal_ref.get(
                authoritative_goal_ref,
                [],
            )
            if len(matching) != 1:
                return (
                    partitions,
                    {},
                    "composer_customer_goal_resolution_invalid",
                )
            resolution = matching[0]
            if (
                str(resolution.get("goal_kind") or "").strip()
                != "customer_goal"
                or resolution.get("supporting_only") is True
            ):
                return (
                    partitions,
                    {},
                    "composer_customer_goal_resolution_invalid",
                )
            claim_uid = str(resolution.get("claim_uid") or "").strip()
            claim_type = str(resolution.get("claim_type") or "").strip()
            claim_type_status = str(
                resolution.get("claim_type_status") or ""
            ).strip()
            status = str(resolution.get("status") or "").strip()
            support_basis = str(
                resolution.get("support_basis") or ""
            ).strip()
            unmapped_customer_goal = (
                not claim_type
                and claim_type_status == "unmapped"
                and str(resolution.get("goal_kind") or "").strip()
                == "customer_goal"
                and (
                    (
                        status == "unresolved"
                        and not resolution.get("evidence_uids")
                        and not resolution.get("inference_policy_refs")
                    )
                    or (
                        status == "supported"
                        and support_basis == "bounded_inference"
                    )
                )
            )
            if (
                not claim_uid
                or claim_uid in seen_uids
                or (not claim_type and not unmapped_customer_goal)
                or status not in {"supported", *_UNRESOLVED_STATUSES}
            ):
                return (
                    partitions,
                    {},
                    "composer_customer_goal_contract_invalid",
                )
            seen_uids.add(claim_uid)
            goal_ref = f"goal_{index:02d}"
            prompt_ref_by_goal_ref[authoritative_goal_ref] = goal_ref
            goal_uid_by_ref[goal_ref] = claim_uid
            evidence_refs = sorted({
                ref_by_uid[str(uid)]
                for uid in resolution.get("evidence_uids") or []
                if str(uid) in ref_by_uid
            })
            if status == "supported" and not evidence_refs:
                return (
                    partitions,
                    {},
                    "composer_supported_goal_evidence_missing",
                )
            required_policy_refs: list[str] = []
            scope_qualifier = ""
            inference_risk_level = ""
            maximum_risk_level = ""
            inference_review_only = False
            required_qualifiers: list[str] = []
            prohibited_extensions: list[str] = []
            required_clause_kind = (
                "supported_fact"
                if status == "supported"
                else "unresolved"
            )
            if support_basis == "bounded_inference":
                required_policy_refs = sorted({
                    str(item).strip()
                    for item in resolution.get("inference_policy_refs") or []
                    if str(item).strip()
                })
                if (
                    not required_policy_refs
                    or any(
                        policy_ref not in policy_by_ref
                        for policy_ref in required_policy_refs
                    )
                ):
                    return (
                        partitions,
                        {},
                        "composer_unknown_inference_policy_reference",
                    )
                premise_uids = sorted({
                    str(item).strip()
                    for item in resolution.get("premise_evidence_uids") or []
                    if str(item).strip()
                })
                premise_refs = sorted({
                    ref_by_uid[uid]
                    for uid in premise_uids
                    if uid in ref_by_uid
                })
                if (
                    not premise_uids
                    or len(premise_refs) != len(premise_uids)
                    or set(evidence_refs) != set(premise_refs)
                ):
                    return (
                        partitions,
                        {},
                        "composer_bounded_inference_premise_omitted",
                    )
                selected_policies = [
                    policy_by_ref[policy_ref]
                    for policy_ref in required_policy_refs
                ]
                if len(selected_policies) != 1:
                    return (
                        partitions,
                        {},
                        "composer_unknown_inference_policy_reference",
                    )
                selected_policy = selected_policies[0]
                scope_qualifier = str(
                    resolution.get("scope_qualifier") or ""
                ).strip()
                inference_risk_level = str(
                    resolution.get("inference_risk_level") or ""
                ).strip()
                maximum_risk_level = str(
                    resolution.get("maximum_risk_level") or ""
                ).strip()
                inference_review_only = (
                    resolution.get("inference_review_only") is True
                )
                required_qualifiers = sorted({
                    str(item).strip()
                    for item in resolution.get("required_qualifiers") or []
                    if str(item).strip()
                })
                prohibited_extensions = sorted({
                    str(item).strip()
                    for item in resolution.get("prohibited_extensions") or []
                    if str(item).strip()
                })
                if (
                    status != "supported"
                    or selected_policy.get("review_only") is not True
                    or not scope_qualifier
                    or scope_qualifier != selected_policy["allowed_scope"]
                    or inference_risk_level not in _INFERENCE_RISK_RANK
                    or maximum_risk_level
                    != selected_policy["maximum_risk_level"]
                    or _INFERENCE_RISK_RANK[inference_risk_level]
                    > _INFERENCE_RISK_RANK[maximum_risk_level]
                    or not inference_review_only
                    or required_qualifiers
                    != selected_policy["required_qualifiers"]
                    or prohibited_extensions
                    != selected_policy["prohibited_claim_families"]
                ):
                    return (
                        partitions,
                        {},
                        "composer_bounded_inference_contract_invalid",
                    )
                required_clause_kind = "allowed_inference"
            goals.append({
                "goal_ref": goal_ref,
                "claim_type": claim_type,
                "claim_type_status": claim_type_status,
                "attribute_key": str(
                    resolution.get("attribute_key") or ""
                ).strip(),
                "semantic_key": str(
                    resolution.get("semantic_key") or ""
                ).strip(),
                "goal_summary": str(
                    resolution.get("goal_summary") or ""
                ).strip(),
                "resolution_status": status,
                "support_basis": support_basis,
                "required_clause_kind": required_clause_kind,
                "required_evidence_refs": evidence_refs,
                "required_inference_policy_refs": required_policy_refs,
                "scope_qualifier": scope_qualifier,
                "inference_risk_level": inference_risk_level,
                "maximum_risk_level": maximum_risk_level,
                "inference_review_only": inference_review_only,
                "required_qualifiers": required_qualifiers,
                "prohibited_extensions": prohibited_extensions,
            })

        dependency_rows: list[dict[str, Any]] = []
        dependency_link_denominator = len(dependencies)
        dependency_link_numerator = 0
        for index, dependency in enumerate(
            sorted(
                dependencies,
                key=lambda item: str(item.get("goal_ref") or ""),
            ),
            start=1,
        ):
            dependency_goal_ref = str(dependency["goal_ref"]).strip()
            supporting_for_goal_ref = str(
                dependency.get("supporting_for_goal_ref") or ""
            ).strip()
            if (
                dependency.get("supporting_only") is not True
                or not supporting_for_goal_ref
            ):
                return (
                    partitions,
                    {},
                    "composer_dependency_binding_missing",
                )
            if supporting_for_goal_ref not in prompt_ref_by_goal_ref:
                return (
                    partitions,
                    {},
                    "composer_dependency_target_unknown",
                )
            matching = resolutions_by_goal_ref.get(dependency_goal_ref, [])
            if (
                len(matching) != 1
                or str(matching[0].get("goal_kind") or "").strip()
                != "evidence_dependency"
            ):
                return (
                    partitions,
                    {},
                    "composer_dependency_resolution_invalid",
                )
            resolution = matching[0]
            status = str(resolution.get("status") or "").strip()
            if status not in {"supported", *_UNRESOLVED_STATUSES}:
                return (
                    partitions,
                    {},
                    "composer_dependency_resolution_invalid",
                )
            evidence_uids = sorted({
                str(item).strip()
                for item in resolution.get("evidence_uids") or []
                if str(item).strip()
            })
            evidence_refs = sorted({
                ref_by_uid[uid]
                for uid in evidence_uids
                if uid in ref_by_uid
            })
            if len(evidence_refs) != len(evidence_uids):
                return (
                    partitions,
                    {},
                    "composer_dependency_evidence_unknown",
                )
            dependency_ref = f"dependency_{index:02d}"
            partitions["non_renderable_goal_refs"].add(dependency_ref)
            dependency_rows.append({
                "dependency_ref": dependency_ref,
                "supporting_for_goal_ref": prompt_ref_by_goal_ref[
                    supporting_for_goal_ref
                ],
                "admitted_evidence_refs": evidence_refs,
                "resolution_status": status,
                "provenance_status": "valid",
            })
            dependency_link_numerator += 1

        for index, claim in enumerate(
            sorted(
                non_renderable_claims,
                key=lambda item: (
                    str(item.get("goal_kind") or ""),
                    str(item.get("goal_ref") or ""),
                ),
            ),
            start=1,
        ):
            goal_kind = str(claim.get("goal_kind") or "").strip()
            goal_ref = str(claim.get("goal_ref") or "").strip()
            if not goal_ref or goal_kind == "compatibility_claim":
                continue
            prompt_ref = f"non_renderable_{index:02d}"
            partitions["non_renderable_goal_refs"].add(prompt_ref)
            matching = resolutions_by_goal_ref.get(goal_ref, [])
            status = (
                str(matching[0].get("status") or "").strip()
                if len(matching) == 1
                else "not_resolved"
            )
            projection = {
                "goal_ref": prompt_ref,
                "goal_kind": goal_kind,
                "status": status,
                "renderable": False,
            }
            if goal_kind == "service_action":
                partitions["service_actions"].append(projection)
            elif goal_kind in {"media_request", "media_candidate"}:
                partitions["media_context"]["request_refs"].append(
                    projection
                )
            elif goal_kind == "contextual_constraint":
                partitions["contextual_constraints"][
                    "constraint_refs"
                ].append(projection)

        metrics = partitions["eligibility_metrics"]
        metrics["renderable_customer_goal_count"] = len(goals)
        metrics["supporting_dependency_count"] = len(dependency_rows)
        metrics["customer_goal_clause_coverage"]["denominator"] = len(goals)
        metrics["dependency_evidence_link_coverage"] = {
            "numerator": dependency_link_numerator,
            "denominator": dependency_link_denominator,
            "rate": (
                dependency_link_numerator / dependency_link_denominator
                if dependency_link_denominator
                else None
            ),
        }
        partitions["renderable_customer_goals"] = goals
        partitions["supporting_dependencies"] = dependency_rows
        return partitions, goal_uid_by_ref, ""

    @staticmethod
    def _has_authoritative_provenance(claim: dict[str, Any]) -> bool:
        source_span_start = claim.get("source_span_start")
        source_span_end = claim.get("source_span_end")
        return bool(
            claim.get("schema_version") == _AUTHORITATIVE_GOAL_SCHEMA
            and claim.get("owner") == _AUTHORITATIVE_GOAL_OWNER
            and claim.get("source") == _AUTHORITATIVE_GOAL_SOURCE
            and str(claim.get("source_stage") or "").strip()
            and str(claim.get("source_turn_uid") or "").strip()
            and isinstance(source_span_start, int)
            and not isinstance(source_span_start, bool)
            and isinstance(source_span_end, int)
            and not isinstance(source_span_end, bool)
            and source_span_start >= 0
            and source_span_end >= source_span_start
        )

    @staticmethod
    def _project_bounded_inference_policies(
        minimal_context: dict[str, Any],
    ) -> tuple[
        list[dict[str, Any]],
        dict[str, dict[str, Any]],
        str,
    ]:
        projected: list[dict[str, Any]] = []
        by_ref: dict[str, dict[str, Any]] = {}
        for item in minimal_context.get("bounded_inference_policies") or []:
            if not isinstance(item, dict):
                return [], {}, "composer_inference_policy_schema_invalid"
            policy_ref = str(item.get("policy_ref") or "").strip()
            policy_intent_ref = str(
                item.get("policy_intent_ref") or ""
            ).strip()
            goal_family = str(item.get("goal_family") or "").strip()
            intent_kind = str(item.get("intent_kind") or "").strip()
            allowed_scope = str(item.get("allowed_scope") or "").strip()
            maximum_risk_level = str(
                item.get("maximum_risk_level") or ""
            ).strip()
            required_qualifiers = sorted({
                str(value).strip()
                for value in item.get("required_qualifiers") or []
                if str(value).strip()
            })
            prohibited_claim_families = sorted({
                str(value).strip()
                for value in item.get("prohibited_claim_families") or []
                if str(value).strip()
            })
            if (
                not policy_ref
                or policy_ref in by_ref
                or not policy_intent_ref
                or not goal_family
                or not intent_kind
                or not allowed_scope
                or maximum_risk_level not in _INFERENCE_RISK_RANK
                or not required_qualifiers
                or not prohibited_claim_families
                or item.get("review_only") is not True
            ):
                return [], {}, "composer_inference_policy_schema_invalid"
            projection = {
                "policy_ref": policy_ref,
                "policy_intent_ref": policy_intent_ref,
                "goal_family": goal_family,
                "intent_kind": intent_kind,
                "allowed_scope": allowed_scope,
                "maximum_risk_level": maximum_risk_level,
                "required_qualifiers": required_qualifiers,
                "prohibited_claim_families": prohibited_claim_families,
                "review_only": True,
            }
            by_ref[policy_ref] = projection
            projected.append(projection)
        return (
            sorted(projected, key=lambda item: item["policy_ref"]),
            by_ref,
            "",
        )

    @staticmethod
    def _actual_media_types(response: dict[str, Any]) -> list[str]:
        return sorted({
            str(block.get("type"))
            for block in response.get("reply_blocks") or []
            if (
                isinstance(block, dict)
                and block.get("type") in {"image", "video"}
                and str(block.get("url") or block.get("asset_url") or "").strip()
            )
        })

    @staticmethod
    def _prompt_payload(
        minimal_context: dict[str, Any],
        *,
        customer_message: str,
        evidence: list[dict[str, Any]],
        partitions: dict[str, Any],
        inference_policies: list[dict[str, Any]],
    ) -> dict[str, Any]:
        return {
            "current_customer_question": str(
                minimal_context.get("customer_goal") or customer_message or ""
            ),
            "recent_conversation_turns": list(
                minimal_context.get("recent_conversation_turns") or []
            ),
            "product_scope": {
                "resolved": bool(minimal_context.get("product_identity")),
                "variant_context_present": bool(
                    (minimal_context.get("product_identity") or {}).get("variant_reference")
                ),
            },
            "admitted_evidence": evidence,
            "renderable_customer_goals": list(
                partitions["renderable_customer_goals"]
            ),
            "supporting_dependencies": list(
                partitions["supporting_dependencies"]
            ),
            "bounded_inference_policies": inference_policies,
            "service_actions": list(partitions["service_actions"]),
            "media_context": dict(partitions["media_context"]),
            "contextual_constraints": dict(
                partitions["contextual_constraints"]
            ),
            "allowed_low_risk_reasoning": sorted({
                str(goal.get("scope_qualifier") or "")
                for goal in partitions["renderable_customer_goals"]
                if goal.get("required_clause_kind") == "allowed_inference"
                and str(goal.get("scope_qualifier") or "")
            }),
        }

    @staticmethod
    def _system_prompt() -> str:
        return (
            "你是电商金牌客服，只负责一次性组织候选回复，不决定事实资格和发送权限。"
            "仅使用 admitted_evidence 中的商品事实；service_actions 不是商品事实。"
            "先直接回答已支持部分，再自然说明未确认部分，只问解决当前问题必需的一项信息。"
            "不得声称系统、资料库、RAG、字段缺失或转人工流程；不得承诺稍后回复。"
            "不要对客户说“没有证据”“缺少证据”或“人工审核”；未确认项直接自然说明“目前无法确认”或“不能保证”。"
            "不要重复完整商品标题，不强制使用亲或宝宝。"
            "低风险解释不得升级为承重、无毒、食品级、认证、儿童安全、防倾倒、安装处方、"
            "订单状态、退款、补发或物流结论。"
            "media_context 和 service_actions 不是可渲染商品事实；媒体候选数量不代表已经发送。"
            "输出严格 JSON 对象，且只能包含 clauses。clauses 必须为数组。"
            "renderable_customer_goals 中每个 goal_ref 必须恰好返回一个 clause，"
            "不得遗漏、重复或新增 goal_ref。"
            "goal_ref 必须逐字复制 renderable_customer_goals 中的完整值，"
            "不能缩写、去前缀或改写。"
            "supporting_dependencies 只提供绑定证据，不得为 dependency_ref 输出 clause。"
            "每个 clause 只能包含 goal_ref、clause_kind、text、evidence_refs。"
            "每个 text 只写一句不超过30个汉字的直接客服表达，不重复其他 goal 的内容。"
            "每个 clause 必须逐字复制对应 goal 的 required_clause_kind 和 required_evidence_refs，"
            "不要自行重新判断事实状态或证据引用。"
            "required_clause_kind=supported_fact 时直接陈述已确认事实，"
            "不复述资料来源、审核状态或核对过程；"
            "required_clause_kind=allowed_inference 时只能在给定 policy scope 内解释，"
            "必须保留非绝对边界，不得扩展到 prohibited claim；"
            "required_clause_kind=unresolved 时结合 goal_summary 和当前问题，"
            "自然说明该项目目前无法确认或不能保证。"
            "unresolved clause 不得补充原因、影响条件、发生概率、典型表现、"
            "性能判断、适用结论或使用建议。"
            "不要把 service action、媒体候选、过渡语或同情语句伪装成 customer goal 的事实。"
            "不要输出推理过程。"
        )

    @staticmethod
    def _validate_output(
        parsed: Any,
        *,
        known_refs: set[str],
        customer_goals: list[dict[str, Any]],
        response: dict[str, Any],
    ) -> str:
        reason, _ = ModelFirstAnswerComposerService._validate_output_with_diagnostics(
            parsed,
            known_refs=known_refs,
            customer_goals=customer_goals,
            response=response,
        )
        return reason

    @staticmethod
    def _validate_output_with_diagnostics(
        parsed: Any,
        *,
        known_refs: set[str],
        customer_goals: list[dict[str, Any]],
        response: dict[str, Any],
        non_renderable_goal_refs: set[str] | None = None,
    ) -> tuple[str, dict[str, Any]]:
        if not isinstance(parsed, dict):
            return "composer_schema_invalid", ModelFirstAnswerComposerService._diagnostics(
                "top_level_schema_invalid",
                json_path="$",
                expected_type="object",
                actual_type=ModelFirstAnswerComposerService._type_name(parsed),
            )
        top_fields = set(parsed)
        if top_fields != _ALLOWED_OUTPUT_FIELDS:
            extra = top_fields - _ALLOWED_OUTPUT_FIELDS
            missing = _ALLOWED_OUTPUT_FIELDS - top_fields
            category = "extra_field" if extra else "top_level_schema_invalid"
            return "composer_schema_invalid", ModelFirstAnswerComposerService._diagnostics(
                category,
                json_path="$",
                expected_type="object_with_exact_fields",
                actual_type="object",
                missing_field_count=len(missing),
                extra_field_count=len(extra),
            )
        clauses = parsed.get("clauses")
        if not isinstance(clauses, list):
            return "composer_clauses_invalid", ModelFirstAnswerComposerService._diagnostics(
                "top_level_schema_invalid",
                json_path="$.clauses",
                expected_type="array",
                actual_type=ModelFirstAnswerComposerService._type_name(clauses),
            )
        goals_by_ref = {
            str(goal["goal_ref"]): goal for goal in customer_goals
        }
        clauses_by_ref: dict[str, dict[str, Any]] = {}
        for index, clause in enumerate(clauses):
            path = f"$.clauses[{index}]"
            if not isinstance(clause, dict):
                return "composer_clause_schema_invalid", ModelFirstAnswerComposerService._diagnostics(
                    "clause_schema_invalid",
                    parsed=parsed,
                    json_path=path,
                    expected_type="object",
                    actual_type=ModelFirstAnswerComposerService._type_name(
                        clause
                    ),
                )
            clause_fields = set(clause)
            if clause_fields != _ALLOWED_CLAUSE_FIELDS:
                extra = clause_fields - _ALLOWED_CLAUSE_FIELDS
                missing = _ALLOWED_CLAUSE_FIELDS - clause_fields
                category = "extra_field" if extra else "clause_schema_invalid"
                return "composer_clause_schema_invalid", ModelFirstAnswerComposerService._diagnostics(
                    category,
                    parsed=parsed,
                    json_path=path,
                    expected_type="object_with_exact_fields",
                    actual_type="object",
                    missing_field_count=len(missing),
                    extra_field_count=len(extra),
                )
            goal_ref = str(clause.get("goal_ref") or "").strip()
            clause_kind = str(clause.get("clause_kind") or "").strip()
            text = str(clause.get("text") or "").strip()
            evidence_refs = clause.get("evidence_refs")
            if goal_ref not in goals_by_ref:
                if goal_ref in (non_renderable_goal_refs or set()):
                    return "composer_non_renderable_goal_reference", ModelFirstAnswerComposerService._diagnostics(
                        "non_renderable_goal_ref",
                        parsed=parsed,
                        json_path=f"{path}.goal_ref",
                        expected_type="renderable_customer_goal_ref",
                        actual_type="non_renderable_goal_ref",
                    )
                return "composer_unknown_goal_reference", ModelFirstAnswerComposerService._diagnostics(
                    "unknown_goal_ref",
                    parsed=parsed,
                    json_path=f"{path}.goal_ref",
                    expected_type="known_goal_ref",
                    actual_type="string",
                )
            if goal_ref in clauses_by_ref:
                return "composer_duplicate_goal_clause", ModelFirstAnswerComposerService._diagnostics(
                    "duplicate_goal_clause",
                    parsed=parsed,
                    json_path=f"{path}.goal_ref",
                    expected_type="unique_goal_ref",
                    actual_type="duplicate_string",
                )
            if clause_kind not in _ALLOWED_CLAUSE_KINDS:
                return "composer_clause_kind_invalid", ModelFirstAnswerComposerService._diagnostics(
                    "wrong_clause_kind",
                    parsed=parsed,
                    json_path=f"{path}.clause_kind",
                    expected_type="allowed_enum",
                    actual_type="string",
                    invalid_enum_count=1,
                )
            if not text:
                return "composer_goal_clause_text_missing", ModelFirstAnswerComposerService._diagnostics(
                    "clause_schema_invalid",
                    parsed=parsed,
                    json_path=f"{path}.text",
                    expected_type="non_empty_string",
                    actual_type="empty_string",
                )
            if not isinstance(evidence_refs, list) or any(
                not isinstance(item, str) or not item.strip()
                for item in evidence_refs
            ):
                return "composer_evidence_refs_invalid", ModelFirstAnswerComposerService._diagnostics(
                    "clause_schema_invalid",
                    parsed=parsed,
                    json_path=f"{path}.evidence_refs",
                    expected_type="array_of_non_empty_strings",
                    actual_type=ModelFirstAnswerComposerService._type_name(
                        evidence_refs
                    ),
                )
            refs = [str(item).strip() for item in evidence_refs]
            if len(refs) != len(set(refs)):
                return "composer_duplicate_evidence_reference", ModelFirstAnswerComposerService._diagnostics(
                    "unknown_evidence_ref",
                    parsed=parsed,
                    json_path=f"{path}.evidence_refs",
                    expected_type="unique_known_evidence_refs",
                    actual_type="array_with_duplicates",
                )
            if not set(refs).issubset(known_refs):
                return "composer_unknown_evidence_reference", ModelFirstAnswerComposerService._diagnostics(
                    "unknown_evidence_ref",
                    parsed=parsed,
                    json_path=f"{path}.evidence_refs",
                    expected_type="known_evidence_refs",
                    actual_type="array",
                )
            goal = goals_by_ref[goal_ref]
            required_kind = goal["required_clause_kind"]
            if required_kind == "allowed_inference":
                if clause_kind != "allowed_inference":
                    return "composer_bounded_inference_clause_invalid", ModelFirstAnswerComposerService._diagnostics(
                        "wrong_clause_kind",
                        parsed=parsed,
                        json_path=f"{path}.clause_kind",
                        expected_type="required_clause_kind",
                        actual_type="allowed_enum",
                        invalid_enum_count=1,
                    )
                if set(refs) != set(goal["required_evidence_refs"]):
                    return "composer_bounded_inference_premise_omitted", ModelFirstAnswerComposerService._diagnostics(
                        "unknown_evidence_ref",
                        parsed=parsed,
                        json_path=f"{path}.evidence_refs",
                        expected_type="exact_required_evidence_refs",
                        actual_type="array",
                    )
            elif goal["resolution_status"] == "supported":
                if clause_kind != required_kind:
                    return "composer_supported_goal_clause_invalid", ModelFirstAnswerComposerService._diagnostics(
                        "wrong_clause_kind",
                        parsed=parsed,
                        json_path=f"{path}.clause_kind",
                        expected_type="required_clause_kind",
                        actual_type="allowed_enum",
                        invalid_enum_count=1,
                    )
                if set(refs) != set(goal["required_evidence_refs"]):
                    return "composer_supported_claim_omitted", ModelFirstAnswerComposerService._diagnostics(
                        "unknown_evidence_ref",
                        parsed=parsed,
                        json_path=f"{path}.evidence_refs",
                        expected_type="exact_required_evidence_refs",
                        actual_type="array",
                    )
            else:
                if clause_kind != "unresolved":
                    return "composer_unresolved_goal_asserted", ModelFirstAnswerComposerService._diagnostics(
                        "wrong_clause_kind",
                        parsed=parsed,
                        json_path=f"{path}.clause_kind",
                        expected_type="unresolved",
                        actual_type="allowed_enum",
                        invalid_enum_count=1,
                    )
                if refs:
                    return "composer_unresolved_goal_evidence_invalid", ModelFirstAnswerComposerService._diagnostics(
                        "unknown_evidence_ref",
                        parsed=parsed,
                        json_path=f"{path}.evidence_refs",
                        expected_type="empty_array",
                        actual_type="non_empty_array",
                    )
            clauses_by_ref[goal_ref] = {
                **clause,
                "goal_ref": goal_ref,
                "clause_kind": clause_kind,
                "text": text,
                "evidence_refs": refs,
            }
        if set(clauses_by_ref) != set(goals_by_ref):
            return "composer_goal_clause_omitted", ModelFirstAnswerComposerService._diagnostics(
                "missing_goal_clause",
                parsed=parsed,
                json_path="$.clauses",
                expected_type="one_clause_per_goal",
                actual_type="incomplete_goal_set",
            )
        reply = "\n".join(
            clauses_by_ref[str(goal["goal_ref"])]["text"]
            for goal in customer_goals
        )
        if any(term.lower() in reply.lower() for term in CUSTOMER_FACING_INTERNAL_REDLINE_TERMS):
            return "composer_internal_language", ModelFirstAnswerComposerService._diagnostics(
                "clause_content_invalid",
                parsed=parsed,
                json_path="$.clauses[*].text",
                expected_type="customer_facing_text",
                actual_type="internal_language",
            )
        if any(term in reply for term in _PROCESS_LANGUAGE_TERMS):
            return "composer_process_language", ModelFirstAnswerComposerService._diagnostics(
                "clause_content_invalid",
                parsed=parsed,
                json_path="$.clauses[*].text",
                expected_type="direct_customer_answer",
                actual_type="process_language",
            )
        media_diagnostics = ModelFirstAnswerComposerService._media_claim_diagnostics(
            parsed,
            customer_goals=customer_goals,
            response=response,
            minimal_context=ModelFirstAnswerComposerService._minimal_context(
                response
            ),
        )
        if media_diagnostics:
            return "composer_unsupported_media_promise", ModelFirstAnswerComposerService._diagnostics(
                "unsupported_media_promise",
                parsed=parsed,
                json_path=media_diagnostics["json_path"],
                expected_type="media_delivery_contract",
                actual_type="unsupported_media_claim",
            )
        return "", ModelFirstAnswerComposerService._diagnostics(
            "accepted",
            parsed=parsed,
        )

    @staticmethod
    def _record_provider_response(
        result: dict[str, Any],
        *,
        content: str,
        finish_reason: str,
        latency_ms: int,
    ) -> None:
        stripped = content.strip()
        if not stripped:
            envelope = "empty"
        elif stripped.startswith("```"):
            envelope = "fenced_text"
        elif stripped.startswith("{"):
            envelope = "json_object" if stripped.endswith("}") else "json_fragment"
        elif stripped.startswith("["):
            envelope = "json_value" if stripped.endswith("]") else "json_fragment"
        else:
            envelope = "free_text"
        result["provider_diagnostics"].update({
            "response_envelope": envelope,
            "response_length": len(content),
            "response_sha256": hashlib.sha256(content.encode("utf-8")).hexdigest(),
            "finish_reason": finish_reason,
            "provider_latency_ms": max(0, latency_ms),
        })

    @staticmethod
    def _unwrap_json_envelope(
        content: str,
    ) -> tuple[str, str, int, str]:
        """Unwrap one complete JSON fence without repairing its payload."""

        stripped = str(content or "").strip()
        if "```" not in stripped:
            if stripped.startswith("{"):
                return stripped, "raw_json", 0, ""
            return "", "invalid", 0, "free_text_response"

        lines = stripped.splitlines()
        if (
            len(lines) < 3
            or lines[0].strip().lower() not in {"```", "```json"}
            or lines[-1].strip() != "```"
        ):
            return "", "invalid", 0, "json_envelope_invalid"
        body = "\n".join(lines[1:-1]).strip()
        if not body or "```" in body:
            return "", "invalid", 0, "json_envelope_invalid"
        return body, "single_json_fence", 1, ""

    @staticmethod
    def _diagnostics(
        category: str,
        *,
        parsed: Any = None,
        json_path: str = "",
        expected_type: str = "",
        actual_type: str = "",
        missing_field_count: int = 0,
        extra_field_count: int = 0,
        invalid_enum_count: int = 0,
    ) -> dict[str, Any]:
        clauses = (
            parsed.get("clauses")
            if isinstance(parsed, dict)
            and isinstance(parsed.get("clauses"), list)
            else []
        )
        clause_rows = [item for item in clauses if isinstance(item, dict)]
        return {
            "category": category,
            "json_path": json_path,
            "expected_type": expected_type,
            "actual_type": actual_type,
            "missing_field_count": max(0, missing_field_count),
            "extra_field_count": max(0, extra_field_count),
            "invalid_enum_count": max(0, invalid_enum_count),
            "clause_count": len(clauses),
            "goal_ref_count": sum(
                1
                for item in clause_rows
                if str(item.get("goal_ref") or "").strip()
            ),
            "evidence_ref_count": sum(
                len(item.get("evidence_refs") or [])
                for item in clause_rows
                if isinstance(item.get("evidence_refs"), list)
            ),
        }

    @staticmethod
    def _type_name(value: Any) -> str:
        if value is None:
            return "null"
        if isinstance(value, bool):
            return "boolean"
        if isinstance(value, dict):
            return "object"
        if isinstance(value, list):
            return "array"
        if isinstance(value, str):
            return "string"
        if isinstance(value, (int, float)):
            return "number"
        return type(value).__name__

    @staticmethod
    def _media_claim_diagnostics(
        parsed: Any,
        *,
        customer_goals: list[dict[str, Any]],
        response: dict[str, Any],
        minimal_context: dict[str, Any],
    ) -> dict[str, Any]:
        if not isinstance(parsed, dict) or not isinstance(
            parsed.get("clauses"),
            list,
        ):
            return {}
        goals_by_ref = {
            str(goal.get("goal_ref") or ""): goal
            for goal in customer_goals
            if isinstance(goal, dict)
        }
        actual_types = ModelFirstAnswerComposerService._actual_media_types(
            response
        )
        attached_count = len([
            block
            for block in response.get("reply_blocks") or []
            if (
                isinstance(block, dict)
                and block.get("type") in {"image", "video"}
                and str(block.get("url") or block.get("asset_url") or "").strip()
            )
        ])
        for index, clause in enumerate(parsed["clauses"]):
            if not isinstance(clause, dict):
                continue
            text = str(clause.get("text") or "").strip()
            makes_delivery_claim = (
                bool(_claimed_delivery_media_kinds(text))
                or contains_unsupported_media_promise(text, False)
                or ModelFirstAnswerComposerService._unsupported_dimension_media_promise(
                    text,
                    {"reply_blocks": []},
                )
            )
            if not makes_delivery_claim:
                continue
            goal_ref = str(clause.get("goal_ref") or "").strip()
            goal = goals_by_ref.get(goal_ref) or {}
            goal_is_media_request = goal.get("media_request") is True
            issue_codes = list(
                media_delivery_claim_issues(response, reply=text)
            )
            if not goal_is_media_request:
                issue_codes.append("media_goal_missing")
            if not actual_types:
                issue_codes.append("actual_media_block_missing")
            fact_type = str(
                response.get("query_fact_type")
                or (response.get("evidence_debug") or {}).get(
                    "query_fact_type"
                )
                or ""
            ).strip()
            if fact_type in {"dimensions", "space_fit"} and actual_types:
                identity_context = (
                    minimal_context.get("product_identity")
                    if isinstance(
                        minimal_context.get("product_identity"),
                        dict,
                    )
                    else {}
                )
                identity = {
                    key: response.get(key) or identity_context.get(key)
                    for key in ("product_id", "i_id", "sku_code")
                }
                attached_blocks = [
                    block
                    for block in response.get("reply_blocks") or []
                    if (
                        isinstance(block, dict)
                        and block.get("type") in {"image", "video"}
                        and str(
                            block.get("url") or block.get("asset_url") or ""
                        ).strip()
                    )
                ]
                if not any(
                    is_delivery_media_asset_eligible(
                        block,
                        query_fact_type=fact_type,
                        product_identity=identity,
                    )
                    for block in attached_blocks
                ):
                    for media_type in actual_types:
                        issue_codes.append(
                            f"{fact_type}_{media_type}_role_or_identity_mismatch"
                        )
            issue_codes = sorted(set(issue_codes))
            if not issue_codes and has_attached_sendable_media_asset(response):
                continue
            return {
                "json_path": f"$.clauses[{index}].text",
                "clause_kind": str(clause.get("clause_kind") or ""),
                "goal_ref": goal_ref,
                "goal_is_media_request": goal_is_media_request,
                "media_candidate_count": len(
                    minimal_context.get("media_candidates") or []
                ),
                "actual_attached_media_count": attached_count,
                "actual_attached_media_type_count": len(actual_types),
                "issue_codes": issue_codes,
                "source": "model_clause",
            }
        return {}

    @staticmethod
    def _unsupported_dimension_media_promise(
        reply: str,
        response: dict[str, Any],
    ) -> bool:
        if has_attached_sendable_media_asset(response):
            return False
        return (
            "尺寸图" in reply
            and any(term in reply for term in ("已发", "已经发", "发给您", "给您发", "下面", "下方"))
        )

    @staticmethod
    def _append_reason(existing: str, reason: str) -> str:
        values = [item for item in (existing.strip(), reason.strip()) if item]
        return "; ".join(dict.fromkeys(values))
