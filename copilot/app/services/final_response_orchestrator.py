"""Final response orchestration for customer-facing replies.

The final layer has four explicit responsibilities:

1. semantic / red-line audit before language polishing;
2. customer-language polish without changing facts;
3. lightweight red-line check after polishing, because polishers can also
   introduce forbidden language;
4. keep text reply blocks in sync with the final suggested reply.
"""

from __future__ import annotations

import json
from typing import Any

from app import config
from app.services.customer_reply_polisher import polish_customer_reply, _polish_text
from app.services.final_answer_auditor import audit_final_answer
from app.services.final_semantic_quality_service import (
    apply_semantic_fit_result,
    audit_customer_reply_semantic_fit,
)
from app.services.generic_service_rule_service import unsafe_promise_terms
from app.services.no_evidence_reply_policy_service import apply_no_evidence_reply_policy


FINAL_RESPONSE_PIPELINE_VERSION = "final-response-orchestrator-v1"


_POST_POLISH_INTERNAL_TERMS = (
    "RAG",
    "Evidence Gate",
    "query_fact_type",
    "fact_type",
    "系统",
    "资料库",
    "知识库",
    "已审核资料",
    "四级控价",
    "大促价",
    "内部价",
    "成本价",
    "利润",
    # Existing files contain mojibake in some generated strings. Keep these
    # variants until the repository-wide encoding cleanup is done.
    "绯荤粺",
    "璧勬枡搴",
    "鐭ヨ瘑搴",
    "宸插鏍歌祫鏂",
)


def orchestrate_final_response(
    response: dict[str, Any],
    *,
    customer_message: str,
    copilot_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Run the authoritative final output pipeline.

    This function is intentionally the only API-facing final output entrypoint.
    Do not call final_answer_auditor and customer_reply_polisher separately from
    API handlers; doing so makes the final node order ambiguous.
    """
    pipeline: list[dict[str, Any]] = []

    response = apply_no_evidence_reply_policy(response, copilot_context)

    response = audit_final_answer(
        response,
        customer_message=customer_message,
        copilot_context=copilot_context,
    )
    audit = response.get("final_answer_audit") or {}
    pipeline.append({
        "stage": "semantic_and_redline_audit",
        "passed": bool(audit.get("passed", True)),
        "mode": audit.get("mode", ""),
        "issues": audit.get("issues", []),
    })

    before_polish = str(response.get("suggested_reply") or "")
    response = polish_customer_reply(
        response,
        customer_message=customer_message,
        copilot_context=copilot_context,
    )
    polish = response.get("customer_reply_polish") or {}
    pipeline.append({
        "stage": "customer_language_polish",
        "applied": bool(polish.get("applied")),
        "mode": polish.get("mode", ""),
        "changed": before_polish != str(response.get("suggested_reply") or ""),
    })

    llm_polish = _optional_llm_language_polish(
        response,
        customer_message=customer_message,
        copilot_context=copilot_context or {},
    )
    if llm_polish:
        response["suggested_reply"] = llm_polish["reply"]
        response["llm_customer_language_polish"] = {
            "applied": True,
            "mode": "llm_customer_language_expert",
            "reason": llm_polish.get("reason", ""),
        }
        response.setdefault("evidence_debug", {})["llm_customer_language_polish"] = response["llm_customer_language_polish"]

    # The LLM polish may reintroduce deterministic blocked phrases or handoff
    # wording that the first polish removed. Run the deterministic polish again
    # before the final redline checks.
    before_repolish = str(response.get("suggested_reply") or "")
    repolished = _polish_text(before_repolish)
    response["suggested_reply"] = repolished
    if not _preserves_customer_product_name(before_repolish, repolished, response):
        response["suggested_reply"] = before_repolish
        response.setdefault("evidence_debug", {})["customer_reply_repolish_rejected"] = {
            "reason": "display_product_name_dropped",
        }
    before_second_policy_reply = str(response.get("suggested_reply") or "")
    response = apply_no_evidence_reply_policy(response, copilot_context)
    if (
        str(response.get("suggested_reply") or "") != before_second_policy_reply
        and _is_no_evidence_controlled_response(response)
    ):
        response = audit_final_answer(
            response,
            customer_message=customer_message,
            copilot_context=copilot_context,
        )
    if _is_no_evidence_controlled_response(response):
        _mark_no_evidence_final_answer_audit_passed(response)

    pipeline.append({
        "stage": "llm_customer_language_polish",
        "enabled": bool(config.COPILOT_FINAL_POLISH_LLM_ENABLED),
        "applied": bool(llm_polish),
    })

    semantic_fit = audit_customer_reply_semantic_fit(
        response,
        customer_message=customer_message,
        copilot_context=copilot_context,
    )
    response = apply_semantic_fit_result(response, semantic_fit, copilot_context=copilot_context)
    pipeline.append({
        "stage": "final_semantic_fit_audit",
        "passed": bool(semantic_fit.get("passed", True)),
        "mode": semantic_fit.get("mode", ""),
        "issues": semantic_fit.get("issues", []),
    })

    post_issues = _post_polish_redline_issues(str(response.get("suggested_reply") or ""))
    if post_issues:
        original_reply = str(response.get("suggested_reply") or "")
        response["suggested_reply"] = _safe_post_polish_fallback(response)
        response["requires_human_review"] = True
        response["generation_mode"] = "post_polish_redline_fallback"
        response["reason_for_review"] = _append_reason(
            str(response.get("reason_for_review") or ""),
            "最终润色后命中红线，已改为保守客服话术",
        )
        response.setdefault("guard_warnings", []).append(
            "post_polish_redline: " + ",".join(post_issues)
        )
        response.setdefault("evidence_debug", {})["post_polish_redline"] = {
            "passed": False,
            "issues": post_issues,
            "original_reply": original_reply,
        }
    else:
        response.setdefault("evidence_debug", {})["post_polish_redline"] = {
            "passed": True,
            "issues": [],
        }
    pipeline.append({
        "stage": "post_polish_redline",
        "passed": not post_issues,
        "issues": post_issues,
    })

    _sync_text_reply_block(response)

    # Align the upstream answer_relevance flag with the actual semantic audits.
    # If both final semantic judges agree the reply is on-topic, the upstream
    # evidence-sufficiency gate should not keep reporting a relevance failure.
    final_answer_passed = bool((response.get("final_answer_audit") or {}).get("passed", True))
    semantic_fit_passed = bool((response.get("final_semantic_fit_audit") or {}).get("passed", True))
    if final_answer_passed and semantic_fit_passed:
        response.setdefault("evidence_debug", {})["answer_relevance_passed"] = True

    response["final_response_pipeline"] = {
        "version": FINAL_RESPONSE_PIPELINE_VERSION,
        "order": [
            "semantic_and_redline_audit",
            "customer_language_polish",
            "llm_customer_language_polish",
            "final_semantic_fit_audit",
            "post_polish_redline",
            "reply_block_sync",
        ],
        "stages": pipeline,
    }
    response.setdefault("evidence_debug", {})["final_response_pipeline"] = response["final_response_pipeline"]
    response.setdefault("trace_steps", []).append({
        "node": "final_response_orchestrator",
        "status": "completed",
        "summary": "final semantic audit, redline, polish and block sync completed",
        "stages": pipeline,
    })
    _apply_sendable_reply_contract(response, post_issues=post_issues)
    return response


def _apply_sendable_reply_contract(response: dict[str, Any], *, post_issues: list[str]) -> None:
    draft_reply = str(response.get("suggested_reply") or "")
    final_answer = response.get("final_answer_audit") or {}
    semantic_fit = response.get("final_semantic_fit_audit") or {}
    block_reasons: list[str] = []
    if not bool(final_answer.get("passed", True)):
        block_reasons.extend(str(item) for item in (final_answer.get("issues") or []))
        if final_answer.get("reason"):
            block_reasons.append(str(final_answer.get("reason")))
    if not bool(semantic_fit.get("passed", True)):
        block_reasons.extend(str(item) for item in (semantic_fit.get("issues") or []))
        if semantic_fit.get("reason"):
            block_reasons.append(str(semantic_fit.get("reason")))
    block_reasons.extend(str(item) for item in (post_issues or []))
    if response.get("requires_human_review"):
        block_reasons.append(str(response.get("reason_for_review") or response.get("review_reason") or "requires_human_review"))
    block_reasons = [item for item in dict.fromkeys(block_reasons) if item]
    can_send = bool(draft_reply) and not block_reasons
    response["draft_reply"] = draft_reply
    response["can_send"] = can_send
    response["reply_status"] = "sendable" if can_send else ("needs_human_review" if response.get("requires_human_review") else "blocked")
    response["sendable_reply"] = draft_reply if can_send else ""
    response["block_reasons"] = block_reasons
    delivery = response.get("reply_delivery")
    if isinstance(delivery, dict):
        delivery["auto_send_ready"] = _media_delivery_ready(response) and can_send
        if not can_send:
            delivery["reason"] = "final_sendable_contract_blocked"
        elif delivery["auto_send_ready"]:
            delivery["reason"] = ""
        response["reply_delivery"] = delivery
    response.setdefault("evidence_debug", {})["sendable_reply_contract"] = {
        "can_send": can_send,
        "reply_status": response["reply_status"],
        "block_reasons": block_reasons,
    }


def _is_no_evidence_controlled_response(response: dict[str, Any]) -> bool:
    debug = response.get("evidence_debug") if isinstance(response.get("evidence_debug"), dict) else {}
    mode = str(debug.get("answer_mode") or response.get("answer_mode") or "")
    if mode in {"no_evidence_controlled_reply", "no_evidence_clarification"}:
        return True
    if response.get("generation_mode") == "no_evidence_reply_policy":
        return True
    trace = response.get("answer_trace") if isinstance(response.get("answer_trace"), dict) else {}
    return bool(trace.get("no_evidence_reply_policy") or debug.get("no_evidence_reply_policy"))


def _mark_no_evidence_final_answer_audit_passed(response: dict[str, Any]) -> None:
    audit = {
        "checked": True,
        "passed": True,
        "issues": [],
        "expected_topics": (response.get("final_answer_audit") or {}).get("expected_topics", []),
        "reply_topics": (response.get("final_answer_audit") or {}).get("reply_topics", []),
        "mode": "no_evidence_controlled_reply",
        "no_evidence_controlled_accepted": True,
    }
    response["final_answer_audit"] = audit
    response.setdefault("evidence_debug", {})["final_answer_audit"] = audit


def _media_delivery_ready(response: dict[str, Any]) -> bool:
    media_block_urls: set[str] = set()
    for block in response.get("reply_blocks") or []:
        if not isinstance(block, dict):
            continue
        if block.get("type") not in {"image", "video"}:
            continue
        url = str(block.get("url") or "").strip()
        if not url:
            continue
        if block.get("send_mode") not in ("", None, "auto_when_platform_connected"):
            continue
        media_block_urls.add(_canonical_media_url(url))
    if not media_block_urls:
        return False

    auto_asset_urls: set[str] = set()
    for asset in response.get("recommended_assets") or []:
        if not isinstance(asset, dict):
            continue
        url = str(asset.get("asset_url") or asset.get("url") or "").strip()
        if not url:
            continue
        if str(asset.get("auto_send_level") or "auto").lower() != "auto":
            continue
        auto_asset_urls.add(_canonical_media_url(url))
    return bool(media_block_urls & auto_asset_urls)


def _canonical_media_url(url: str) -> str:
    return str(url or "").split("?", 1)[0].strip().lower()


def ensure_sendable_reply_contract(response: dict[str, Any]) -> dict[str, Any]:
    """Ensure legacy graph/API results expose a conservative sendable contract."""
    response = dict(response or {})
    response["draft_reply"] = str(response.get("draft_reply") or response.get("suggested_reply") or "")
    requested_can_send = bool(response.get("can_send"))
    response["sendable_reply"] = str(response.get("sendable_reply") or "")
    reasons = response.get("block_reasons")
    if not isinstance(reasons, list):
        reasons = []
    if not reasons and response.get("requires_human_review"):
        reasons.append(str(response.get("reason_for_review") or response.get("review_reason") or "requires_human_review"))
    if not reasons and response.get("suggested_reply") and not requested_can_send:
        reasons.append("sendable_contract_missing")
    response["block_reasons"] = [str(item) for item in reasons if str(item)]
    can_send = requested_can_send and bool(response["sendable_reply"]) and not response["block_reasons"] and not response.get("requires_human_review")
    if requested_can_send and not can_send:
        response["block_reasons"] = response["block_reasons"] or ["sendable_contract_invalid"]
    if not can_send:
        response["sendable_reply"] = ""
    response["can_send"] = can_send
    response["reply_status"] = "sendable" if can_send else (
        "needs_human_review" if response.get("requires_human_review") else "blocked"
    )
    evidence_debug = response.get("evidence_debug")
    if not isinstance(evidence_debug, dict):
        evidence_debug = {}
        response["evidence_debug"] = evidence_debug
    evidence_debug["sendable_reply_contract"] = {
        "can_send": bool(response.get("can_send")),
        "reply_status": response.get("reply_status", "blocked"),
        "block_reasons": response.get("block_reasons", []),
    }
    return response


def _post_polish_redline_issues(reply: str) -> list[str]:
    issues: list[str] = []
    lowered = reply.lower()
    leaked = [term for term in _POST_POLISH_INTERNAL_TERMS if term.lower() in lowered]
    if leaked:
        issues.append("internal_language:" + ",".join(leaked[:5]))
    unsafe_terms = unsafe_promise_terms(reply)
    if unsafe_terms:
        issues.append("unsafe_promise:" + ",".join(unsafe_terms[:5]))
    return issues


def _optional_llm_language_polish(
    response: dict[str, Any],
    *,
    customer_message: str,
    copilot_context: dict[str, Any],
) -> dict[str, str] | None:
    if not config.COPILOT_FINAL_POLISH_LLM_ENABLED:
        return None
    reply = str(response.get("suggested_reply") or "").strip()
    if not reply:
        return None
    try:
        from app.llm.client import get_llm_client

        client = get_llm_client()
        if not client.api_key:
            return None

        evidence_debug = response.get("evidence_debug") or {}
        payload = {
            "customer_message": customer_message,
            "draft_reply": reply,
            "intent": response.get("intent", ""),
            "risk_level": response.get("risk_level", ""),
            "requires_human_review": response.get("requires_human_review", False),
            "query_fact_type": evidence_debug.get("query_fact_type", ""),
            "display_product_name": response.get("display_product_name", ""),
            "conversation_context": copilot_context,
            "selected_evidence_summary": {
                "evidence_used": response.get("evidence_used", ""),
                "generic_service_rule_used": response.get("generic_service_rule_used", {}),
                "final_answer_audit": response.get("final_answer_audit", {}),
            },
            "reply_blocks": response.get("reply_blocks", []),
            "recommended_assets": response.get("recommended_assets", []),
        }
        result = client.client.chat.completions.create(
            model=client.model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "你是 INHE 母婴儿童用品店铺的金牌客服语言专家。"
                        "你只负责把 draft_reply 改写成自然、专业、可直接发给客户的话。"
                        "禁止新增事实、禁止编造尺寸/材质/承重/优惠/物流，禁止改变是否需要人工跟进的业务决定。"
                        "如果 draft_reply 表示需要跟进，就把它改写成客户能接受的服务话术，不要说系统、资料库、RAG、已审核资料、fact_type。"
                        "如果有图片/视频 reply_blocks 或 recommended_assets，只能用自然语言提示“下面图片/视频可参考”，不要把链接当正文发。"
                        "不要输出思考过程。只输出 JSON: {\"reply\": string, \"reason\": string}。"
                    ),
                },
                {"role": "user", "content": _json_dumps(payload)},
            ],
            temperature=0.2,
            max_tokens=420,
            response_format={"type": "json_object"},
        )
        parsed = _json_loads(result.choices[0].message.content)
        polished = str(parsed.get("reply") or "").strip()
        if not polished:
            return None
        if _post_polish_redline_issues(polished):
            return None
        if not _preserves_customer_product_name(reply, polished, response):
            return None
        return {
            "reply": polished,
            "reason": str(parsed.get("reason") or "")[:200],
        }
    except Exception:
        return None


def _safe_post_polish_fallback(response: dict[str, Any]) -> str:
    if str(response.get("intent") or "").lower() in {"complaint", "high_risk"}:
        return (
            "亲～非常抱歉让您有不好的体验，您的反馈我已经收到，会优先帮您跟进处理。\n"
            "我这边会按当前情况继续核对并推进处理，尽快给您明确回复。"
        )
    return (
        "亲～这个问题我已经记下来了，我这边继续帮您跟进处理，"
        "确认好后尽快回复您。"
    )


def _preserves_customer_product_name(
    original_reply: str,
    polished_reply: str,
    response: dict[str, Any],
) -> bool:
    display_name = str(response.get("display_product_name") or "").strip()
    if not display_name or len(display_name) < 4:
        return True
    if display_name not in original_reply:
        return True
    return display_name in polished_reply


def _sync_text_reply_block(response: dict[str, Any]) -> None:
    blocks = response.get("reply_blocks")
    reply = str(response.get("suggested_reply") or "")
    if not isinstance(blocks, list) or not blocks:
        response["reply_blocks"] = [{"type": "text", "content": reply}]
        return
    for block in blocks:
        if isinstance(block, dict) and block.get("type") == "text":
            block["content"] = reply
            return
    response["reply_blocks"] = [{"type": "text", "content": reply}] + blocks


def _append_reason(existing: str, reason: str) -> str:
    if not existing:
        return reason
    if reason in existing:
        return existing
    return f"{existing}；{reason}"


def _json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


def _json_loads(value: str) -> dict[str, Any]:
    parsed = json.loads(str(value or "{}"))
    return parsed if isinstance(parsed, dict) else {}
