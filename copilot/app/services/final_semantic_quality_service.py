"""Final customer-facing semantic fit check.

This service runs after the reply has been polished. It does not route tools,
retrieve data, or create new facts. It only judges the final text against:

- the customer's current question;
- the semantic query/fact type already produced by upstream nodes;
- the product context evidence selected for this turn;
- the media blocks that will be sent with the reply.

The primary path is an LLM judge because "does this answer the question?" is a
semantic task. The deterministic path only enforces structural guarantees and
does not try to classify Chinese customer intent from raw keywords.
"""

from __future__ import annotations

import json
from typing import Any

from app import config


def audit_customer_reply_semantic_fit(
    response: dict[str, Any],
    *,
    customer_message: str,
    copilot_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    reply = str(response.get("suggested_reply") or "").strip()
    if not reply:
        return _result(False, ["empty_reply"], "Final reply is empty.", "deterministic")

    structural = _structural_semantic_checks(response)
    if structural["issues"]:
        return _result(False, structural["issues"], structural["reason"], "deterministic")

    llm_result = _llm_semantic_fit_check(
        response,
        customer_message=customer_message,
        copilot_context=copilot_context or {},
    )
    if llm_result:
        return llm_result

    return _result(True, [], "No structural semantic issue detected.", "deterministic")


def apply_semantic_fit_result(response: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    response["final_semantic_fit_audit"] = result
    response.setdefault("evidence_debug", {})["final_semantic_fit_audit"] = result
    if result.get("passed", True):
        return response

    original = str(response.get("suggested_reply") or "")
    response["suggested_reply"] = _semantic_fit_fallback(response)
    response["requires_human_review"] = True
    response["generation_mode"] = "final_semantic_fit_fallback"
    response["reason_for_review"] = _append_reason(
        str(response.get("reason_for_review") or ""),
        "最终回复语义一致性未通过",
    )
    response.setdefault("guard_warnings", []).append(
        "final_semantic_fit_audit: " + ",".join(result.get("issues") or [])
    )
    response.setdefault("trace_steps", []).append({
        "node": "final_semantic_fit_audit",
        "status": "blocked",
        "issues": result.get("issues", []),
        "summary": result.get("reason", "final semantic fit failed"),
    })
    result["fallback_used"] = True
    result["original_reply"] = original
    return response


def _structural_semantic_checks(response: dict[str, Any]) -> dict[str, Any]:
    evidence_pack = _evidence_pack(response)
    query_fact_type = _query_fact_type(response, evidence_pack)
    if not query_fact_type:
        return {"issues": [], "reason": ""}

    answerability = str(evidence_pack.get("answerability") or "")
    if answerability in {"missing_product_fact", "no_product_profile", "no_product_identity"}:
        if not bool(response.get("requires_human_review")):
            return {
                "issues": ["missing_evidence_without_human_review"],
                "reason": "Required product fact is missing but reply is not marked for human review.",
            }

    matched_facts = evidence_pack.get("matched_facts") or []
    if answerability == "direct_answer" and not matched_facts:
        return {
            "issues": ["direct_answer_without_matched_fact"],
            "reason": "Evidence pack claims direct answer but no matched fact is attached.",
        }

    for fact in matched_facts:
        alignment = fact.get("semantic_alignment") or {}
        if alignment and alignment.get("direct_answer_allowed") is False:
            return {
                "issues": ["selected_fact_not_direct_answer_allowed"],
                "reason": "A selected fact is marked as non-direct-answer evidence.",
            }

    return {"issues": [], "reason": ""}


def _llm_semantic_fit_check(
    response: dict[str, Any],
    *,
    customer_message: str,
    copilot_context: dict[str, Any],
) -> dict[str, Any] | None:
    if not config.COPILOT_FINAL_AUDIT_LLM_ENABLED:
        return None
    try:
        from app.llm.client import get_llm_client

        client = get_llm_client()
        if not client.api_key:
            return None

        payload = _semantic_payload(response, customer_message, copilot_context)
        result = client.client.chat.completions.create(
            model=client.model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are the final semantic quality judge for a customer-service agent. "
                        "Judge only whether final_reply can be sent as a coherent answer to customer_message. "
                        "Use semantic_query and selected_evidence as ground truth. "
                        "Do not require exact wording. Do not judge style unless it affects answerability. "
                        "Fail if the reply answers a different fact type, asks for information already provided, "
                        "turns to human review while direct evidence is available, or claims facts not supported by evidence. "
                        "Pass if the reply gives a safe handoff because evidence is missing or risk requires review. "
                        "Return strict JSON: {\"passed\": boolean, \"issues\": string[], \"reason\": string}."
                    ),
                },
                {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
            ],
            temperature=0,
            max_tokens=240,
            response_format={"type": "json_object"},
        )
        raw = result.choices[0].message.content
        parsed = json.loads(raw)
        return _result(
            bool(parsed.get("passed", True)),
            [str(item) for item in (parsed.get("issues") or [])],
            str(parsed.get("reason") or "")[:500],
            "llm_semantic_fit",
        )
    except Exception as exc:
        return _result(True, [], f"LLM semantic fit unavailable: {type(exc).__name__}", "deterministic")


def _semantic_payload(
    response: dict[str, Any],
    customer_message: str,
    copilot_context: dict[str, Any],
) -> dict[str, Any]:
    debug = response.get("evidence_debug") or {}
    evidence_pack = _evidence_pack(response)
    return {
        "customer_message": customer_message,
        "final_reply": response.get("suggested_reply", ""),
        "requires_human_review": bool(response.get("requires_human_review")),
        "review_reason": response.get("reason_for_review") or response.get("review_reason") or "",
        "intent": response.get("intent", ""),
        "semantic_query": debug.get("semantic_query") or response.get("semantic_query") or {},
        "query_fact_type": _query_fact_type(response, evidence_pack),
        "evidence_pack": {
            "answerability": evidence_pack.get("answerability", ""),
            "matched_fields": evidence_pack.get("matched_fields", []),
            "missing_fields": evidence_pack.get("missing_fields", []),
            "matched_facts": [
                {
                    "fact_type": item.get("fact_type", ""),
                    "direct_answer_allowed": item.get("direct_answer_allowed", True),
                    "preview": item.get("preview", ""),
                    "semantic_alignment": item.get("semantic_alignment", {}),
                }
                for item in (evidence_pack.get("matched_facts") or [])[:5]
            ],
        },
        "recommended_assets": [
            {
                "asset_type": item.get("asset_type", ""),
                "asset_title": item.get("asset_title", ""),
            }
            for item in (response.get("recommended_assets") or [])[:5]
        ],
        "reply_blocks": [
            {"type": item.get("type", ""), "title": item.get("title", "")}
            for item in (response.get("reply_blocks") or [])[:5]
            if isinstance(item, dict)
        ],
        "copilot_context": {
            "order_id_present": bool(
                copilot_context.get("order_id")
                or copilot_context.get("platform_order_id")
                or copilot_context.get("platform_trade_id")
            ),
            "product_name": copilot_context.get("product_name", ""),
        },
    }


def _evidence_pack(response: dict[str, Any]) -> dict[str, Any]:
    debug = response.get("evidence_debug") or {}
    summary = debug.get("product_context_pack_summary") or {}
    if isinstance(summary, dict):
        pack = summary.get("evidence_pack")
        if isinstance(pack, dict):
            return pack
    pack = response.get("product_card_evidence_pack")
    if isinstance(pack, dict):
        return pack
    product_pack = response.get("product_context_pack")
    if isinstance(product_pack, dict):
        pack = product_pack.get("evidence_pack")
        if isinstance(pack, dict):
            return pack
    return {}


def _query_fact_type(response: dict[str, Any], evidence_pack: dict[str, Any]) -> str:
    debug = response.get("evidence_debug") or {}
    semantic = debug.get("semantic_query") or response.get("semantic_query") or {}
    if isinstance(semantic, dict) and semantic.get("primary_fact_type"):
        return str(semantic.get("primary_fact_type") or "")
    return str(
        evidence_pack.get("query_fact_type")
        or debug.get("query_fact_type")
        or response.get("query_fact_type")
        or ""
    )


def _semantic_fit_fallback(response: dict[str, Any]) -> str:
    display_name = str(response.get("display_product_name") or "").strip()
    product = f"「{display_name}」" if display_name else "这款商品"
    return (
        f"亲～{product}这个问题我先帮您按当前商品信息再核对一下，"
        "避免给您说错影响使用或选择。\n"
        "您稍等一下，我这边确认清楚后再回复您。"
    )


def _append_reason(existing: str, reason: str) -> str:
    existing = str(existing or "").strip()
    if not existing:
        return reason
    if reason in existing:
        return existing
    return f"{existing}; {reason}"


def _result(passed: bool, issues: list[str], reason: str, mode: str) -> dict[str, Any]:
    return {
        "checked": True,
        "passed": bool(passed),
        "issues": issues,
        "reason": reason,
        "mode": mode,
    }
