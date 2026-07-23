"""Evidence-bounded, review-only model-first answer composition."""

from __future__ import annotations

import json
from copy import deepcopy
from typing import Any

from app.services.customer_facing_safe_handoff_service import (
    CUSTOMER_FACING_INTERNAL_REDLINE_TERMS,
)
from app.services.no_evidence_reply_policy_service import (
    contains_unsupported_media_promise,
    has_attached_sendable_media_asset,
    media_delivery_claim_issues,
)


COMPOSER_VERSION = "model-first-answer-composer-v1"
ALLOWED_LOW_RISK_REASONING = (
    "用已确认尺寸做直观占地解释",
    "并列比较同商品已确认的规格差异",
    "根据已确认结构或层数解释使用方式",
    "对普通塑料说明轻微磕碰通常不像玻璃一样碎裂，但不得保证耐摔",
)
_ALLOWED_OUTPUT_FIELDS = {
    "reply",
    "used_evidence_refs",
    "unresolved_claim_types",
}
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
        required_refs = self._required_supported_refs(minimal_context, uid_by_ref)
        unresolved_types = self._unresolved_claim_types(minimal_context)
        payload = self._prompt_payload(
            minimal_context,
            customer_message=customer_message,
            evidence=evidence,
            required_refs=required_refs,
            unresolved_types=unresolved_types,
            actual_media_types=self._actual_media_types(original),
        )

        try:
            if client is None:
                from app.llm.client import get_llm_client

                client = get_llm_client()
            if not getattr(client, "api_key", ""):
                result["rejection_reason"] = "formal_llm_not_configured"
                return original, result
            completion = client.create_chat_completion(
                model=client.model,
                messages=[
                    {"role": "system", "content": self._system_prompt()},
                    {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
                ],
                temperature=0,
                max_tokens=900,
                response_format={"type": "json_object"},
            )
            parsed = json.loads(str(completion.choices[0].message.content or ""))
        except Exception as exc:
            result["rejection_reason"] = f"formal_llm_error:{type(exc).__name__}"
            return original, result

        validation_error = self._validate_output(
            parsed,
            known_refs=known_refs,
            required_refs=required_refs,
            unresolved_types=unresolved_types,
            response=original,
        )
        if validation_error:
            result["rejection_reason"] = validation_error
            return original, result

        reply = str(parsed["reply"]).strip()
        used_refs = sorted(set(str(item) for item in parsed["used_evidence_refs"]))
        result.update({
            "status": "accepted",
            "rejection_reason": "",
            "candidate_reply": reply,
            "used_evidence_uids": [uid_by_ref[ref] for ref in used_refs],
            "unresolved_claim_types": sorted(
                set(str(item) for item in parsed["unresolved_claim_types"])
            ),
            "used_for_final_reply": True,
            "allowed_low_risk_reasoning": list(ALLOWED_LOW_RISK_REASONING),
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
            "context_metrics": dict(stats or {}),
            "used_for_final_reply": False,
            "can_change_can_send": False,
            "requires_human_review": True,
            "can_send": False,
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
    def _required_supported_refs(
        minimal_context: dict[str, Any],
        uid_by_ref: dict[str, str],
    ) -> set[str]:
        ref_by_uid = {uid: ref for ref, uid in uid_by_ref.items()}
        required: set[str] = set()
        for claim in minimal_context.get("claim_resolutions") or []:
            if not isinstance(claim, dict) or claim.get("status") != "supported":
                continue
            for uid in claim.get("evidence_uids") or []:
                ref = ref_by_uid.get(str(uid))
                if ref:
                    required.add(ref)
        return required

    @staticmethod
    def _unresolved_claim_types(minimal_context: dict[str, Any]) -> set[str]:
        unresolved: set[str] = set()
        for claim in minimal_context.get("claim_resolutions") or []:
            if not isinstance(claim, dict):
                continue
            if claim.get("status") not in {"unresolved", "conflicting", "prohibited"}:
                continue
            claim_type = str(claim.get("claim_type") or "").strip()
            if claim_type:
                unresolved.add(claim_type)
        return unresolved

    @staticmethod
    def _actual_media_types(response: dict[str, Any]) -> list[str]:
        return sorted({
            str(block.get("type"))
            for block in response.get("reply_blocks") or []
            if isinstance(block, dict) and block.get("type") in {"image", "video"}
        })

    @staticmethod
    def _prompt_payload(
        minimal_context: dict[str, Any],
        *,
        customer_message: str,
        evidence: list[dict[str, Any]],
        required_refs: set[str],
        unresolved_types: set[str],
        actual_media_types: list[str],
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
            "required_supported_evidence_refs": sorted(required_refs),
            "unresolved_claim_types": sorted(unresolved_types),
            "conflicting_claims": list(minimal_context.get("conflicting_claims") or []),
            "service_actions": list(minimal_context.get("service_actions") or []),
            "available_media_candidates": list(
                minimal_context.get("media_candidates") or []
            ),
            "actual_media_types": actual_media_types,
            "safety_constraints": dict(minimal_context.get("safety_constraints") or {}),
            "allowed_low_risk_reasoning": list(ALLOWED_LOW_RISK_REASONING),
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
            "订单状态、退款、补发或物流结论。只有 actual_media_types 中存在的媒体才可说已附上。"
            "available_media_candidates 表示系统已拥有但尚未发送的资料，不要再让客户重复上传同类资料。"
            "输出严格 JSON 对象，且只能包含 reply、used_evidence_refs、unresolved_claim_types。"
            "used_evidence_refs 必须列出回复实际使用的证据引用；不要输出推理过程。"
        )

    @staticmethod
    def _validate_output(
        parsed: Any,
        *,
        known_refs: set[str],
        required_refs: set[str],
        unresolved_types: set[str],
        response: dict[str, Any],
    ) -> str:
        if not isinstance(parsed, dict) or set(parsed) != _ALLOWED_OUTPUT_FIELDS:
            return "composer_schema_invalid"
        if not isinstance(parsed.get("reply"), str) or not parsed["reply"].strip():
            return "composer_reply_empty"
        if not isinstance(parsed.get("used_evidence_refs"), list):
            return "composer_evidence_refs_invalid"
        if not isinstance(parsed.get("unresolved_claim_types"), list):
            return "composer_unresolved_claims_invalid"
        used_refs = {str(item) for item in parsed["used_evidence_refs"]}
        if not used_refs.issubset(known_refs):
            return "composer_unknown_evidence_reference"
        if not required_refs.issubset(used_refs):
            return "composer_supported_claim_omitted"
        reported_unresolved = {str(item) for item in parsed["unresolved_claim_types"]}
        if not unresolved_types.issubset(reported_unresolved):
            return "composer_unresolved_claim_omitted"
        reply = parsed["reply"].strip()
        if any(term.lower() in reply.lower() for term in CUSTOMER_FACING_INTERNAL_REDLINE_TERMS):
            return "composer_internal_language"
        if any(term in reply for term in _PROCESS_LANGUAGE_TERMS):
            return "composer_process_language"
        if contains_unsupported_media_promise(
            reply,
            has_attached_sendable_media_asset(response),
        ) or media_delivery_claim_issues(
            response,
            reply=reply,
        ) or ModelFirstAnswerComposerService._unsupported_dimension_media_promise(
            reply,
            response,
        ):
            return "composer_unsupported_media_promise"
        return ""

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
