"""Strict-schema semantic grading for Tier D customer-visible replies only."""

from __future__ import annotations

import os
from typing import Any

from app.services.canonical_conversation_turn_service import project_text_for_external_model
from app.services.strict_decision_provider_service import (
    StrictDecisionProviderConfig,
    StrictDecisionProviderError,
    StrictDecisionProviderService,
)


SCHEMA_VERSION = "tier-d-transcript-grader/v1"
_ACTION_CONTRACTS = {
    "use_identity_scoped_evidence": "Reply grounds the answer in the current matched product or order context, rather than a generic product claim.",
    "use_sidecar_first": "Reply acknowledges and uses the supplied current product or order context without asking again for already available identity.",
    "verify_live_state": "Reply states a concrete next step to check the current live state and does not claim that check already happened.",
    "review_existing_evidence": "Reply states a concrete next step to review the already available material, image, instruction, or proof relevant to the question.",
    "verify_order_and_issue": "Reply states a concrete next step to verify the current order together with the reported issue or needed evidence.",
    "verify_current_rule": "Reply states a concrete next step to verify the currently applicable activity, offer, or page rule without promising an unverified benefit.",
    "locate_step_or_component": "Reply asks for or identifies the relevant installation step, component, or location as the next action.",
    "review_matching_material": "Reply states a concrete next step to review a matching instruction, installation image, manual, or video; merely naming one is insufficient.",
    "verify_media_role_and_delivery_block": "Reply distinguishes checking matching media from claiming media was sent or available, and gives a concrete next step.",
    "request_minimum_missing_context": "Reply asks for the minimum missing context needed to continue, such as one relevant image, location, model, or order detail.",
}


def _enabled(value: str) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _bounded_timeout(value: str) -> int:
    try:
        return max(1, min(int(value), 120))
    except (TypeError, ValueError):
        return 30


def _config_from_environment() -> StrictDecisionProviderConfig:
    """Use an independently qualified evaluation provider, never formal LLM config."""
    return StrictDecisionProviderConfig(
        provider_name=str(os.getenv("COPILOT_TIER_D_GRADER_PROVIDER") or "").strip(),
        api_base=str(os.getenv("COPILOT_TIER_D_GRADER_API_BASE") or "").strip(),
        api_key=str(os.getenv("COPILOT_TIER_D_GRADER_API_KEY") or "").strip(),
        model=str(os.getenv("COPILOT_TIER_D_GRADER_MODEL") or "").strip(),
        capability=str(os.getenv("COPILOT_TIER_D_GRADER_CAPABILITY") or "").strip().lower(),
        timeout_seconds=_bounded_timeout(os.getenv("COPILOT_TIER_D_GRADER_TIMEOUT_SECONDS") or "30"),
        qualified=_enabled(os.getenv("COPILOT_TIER_D_GRADER_QUALIFIED") or ""),
        disable_thinking=_enabled(os.getenv("COPILOT_TIER_D_GRADER_DISABLE_THINKING") or ""),
    )


class TierDTranscriptGrader:
    """Assess requested actions from customer-visible formal replies.

    The Agent never receives hidden goals, action contracts, or grader output.
    A missing or unqualified grader reports no coverage rather than falling back
    to text keywords.
    """

    def __init__(self, provider: StrictDecisionProviderService | None = None):
        self.provider = provider or StrictDecisionProviderService(config=_config_from_environment())

    def metadata(self) -> dict[str, Any]:
        metadata = dict(self.provider.metadata())
        metadata.update({"schema_version": SCHEMA_VERSION, "role": "tier_d_transcript_grader"})
        return metadata

    def ready(self) -> bool:
        return self.provider.ready_for_shadow()

    def configured_candidate(self) -> bool:
        """A configured candidate may run read-only qualification, not Tier D."""
        return bool(self.provider.metadata().get("configured"))

    def grade(
        self,
        required_action_ids: set[str],
        turns: list[dict[str, Any]],
        *,
        allow_unqualified: bool = False,
    ) -> dict[str, Any]:
        required = sorted(str(action_id) for action_id in required_action_ids)
        unknown = [action_id for action_id in required if action_id not in _ACTION_CONTRACTS]
        if unknown:
            return self._not_qualified("grader_action_contract_missing", required, unknown)
        if not self.configured_candidate():
            return self._not_qualified("grader_not_configured", required, [])
        if not allow_unqualified and not self.ready():
            return self._not_qualified("grader_not_qualified", required, [])

        visible_turns = [
            {"turn_number": index + 1, "reply": project_text_for_external_model(self._reply_text(turn))}
            for index, turn in enumerate(turns)
            if self._reply_text(turn)
        ]
        if not visible_turns:
            return self._completed(required, [], [])

        payload = {
            "action_contracts": [
                {"action_id": action_id, "definition": _ACTION_CONTRACTS[action_id]}
                for action_id in required
            ],
            "customer_visible_agent_replies": visible_turns,
        }
        schema = {
            "type": "object",
            "additionalProperties": False,
            "required": ["grades"],
            "properties": {
                "grades": {
                    "type": "array",
                    "minItems": len(required),
                    "maxItems": len(required),
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": ["action_id", "status", "reply_turn_numbers"],
                        "properties": {
                            "action_id": {"type": "string", "enum": required},
                            "status": {"type": "string", "enum": ["completed", "not_completed", "unclear"]},
                            "reply_turn_numbers": {"type": "array", "items": {"type": "integer", "minimum": 1}},
                        },
                    },
                },
            },
        }
        try:
            result = self.provider.request(
                name="tier_d_transcript_action_grade",
                schema=schema,
                system_prompt=(
                    "Grade only the customer-visible agent replies against each action definition. "
                    "A reply that denies, refuses, or says an action will not be done is not completed. "
                    "Naming an object without a concrete action is not completed. "
                    "Cite only reply turn numbers that visibly support the judgment."
                ),
                payload=payload,
                max_tokens=480,
                allow_unqualified=allow_unqualified,
            )
        except StrictDecisionProviderError as exc:
            return self._not_qualified(f"grader_{str(exc)}", required, [])
        return self._validate_result(required, visible_turns, result)

    @staticmethod
    def _reply_text(turn: dict[str, Any]) -> str:
        observation = turn.get("observation") or {}
        if isinstance(observation, dict) and observation.get("reply"):
            return str(observation["reply"]).strip()
        response = turn.get("agent_response") or {}
        return str(response.get("sendable_reply") or response.get("suggested_reply") or response.get("draft_reply") or "").strip()

    def _validate_result(self, required: list[str], visible_turns: list[dict[str, Any]], result: Any) -> dict[str, Any]:
        rows = result.get("grades") if isinstance(result, dict) else None
        if not isinstance(rows, list):
            return self._not_qualified("grader_schema_invalid", required, [])
        by_action: dict[str, dict[str, Any]] = {}
        valid_turn_numbers = {int(item["turn_number"]) for item in visible_turns}
        for row in rows:
            if not isinstance(row, dict):
                return self._not_qualified("grader_schema_invalid", required, [])
            if set(row) != {"action_id", "status", "reply_turn_numbers"}:
                return self._not_qualified("grader_schema_invalid", required, [])
            action_id = str(row.get("action_id") or "")
            status = str(row.get("status") or "")
            references = row.get("reply_turn_numbers")
            if action_id not in required or action_id in by_action or status not in {"completed", "not_completed", "unclear"}:
                return self._not_qualified("grader_schema_invalid", required, [])
            if not isinstance(references, list) or any(not isinstance(value, int) or value not in valid_turn_numbers for value in references):
                return self._not_qualified("grader_schema_invalid", required, [])
            if status == "completed" and not references:
                return self._not_qualified("grader_uncited_completion", required, [])
            by_action[action_id] = {"status": status, "reply_turn_numbers": sorted(set(references))}
        if set(by_action) != set(required):
            return self._not_qualified("grader_schema_incomplete", required, [])
        completed = sorted(action_id for action_id, row in by_action.items() if row["status"] == "completed")
        return self._completed(required, completed, [], grades=by_action)

    def _not_qualified(self, reason: str, required: list[str], unknown: list[str]) -> dict[str, Any]:
        return {
            "status": "grader_not_qualified",
            "reason": reason,
            "required_action_ids": required,
            "covered_action_ids": [],
            "uncovered_action_ids": required,
            "unknown_action_ids": unknown,
            "action_coverage_rate": None,
            "grader": self.metadata(),
        }

    def _completed(self, required: list[str], completed: list[str], unknown: list[str], *, grades: dict[str, Any] | None = None) -> dict[str, Any]:
        rate = len(completed) / len(required) if required else None
        return {
            "status": "completed",
            "reason": "",
            "required_action_ids": required,
            "covered_action_ids": completed,
            "uncovered_action_ids": sorted(set(required).difference(completed)),
            "unknown_action_ids": unknown,
            "action_coverage_rate": round(rate, 4) if rate is not None else None,
            "grades": grades or {},
            "grader": self.metadata(),
        }
