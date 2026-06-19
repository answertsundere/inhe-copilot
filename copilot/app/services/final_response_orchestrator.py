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
from app.services.customer_reply_polisher import polish_customer_reply
from app.services.final_answer_auditor import audit_final_answer
from app.services.final_semantic_quality_service import (
    apply_semantic_fit_result,
    audit_customer_reply_semantic_fit,
)
from app.services.generic_service_rule_service import unsafe_promise_terms


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
    try:
        from app.services.answer_trace_service import normalize_answer_trace_inputs
        response = normalize_answer_trace_inputs(response)
    except Exception:
        pass

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
    pipeline.append({
        "stage": "llm_customer_language_polish",
        "enabled": bool(config.COPILOT_FINAL_POLISH_LLM_ENABLED),
        "applied": bool(llm_polish),
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

    semantic_fit = audit_customer_reply_semantic_fit(
        response,
        customer_message=customer_message,
        copilot_context=copilot_context,
    )
    response = apply_semantic_fit_result(response, semantic_fit)
    pipeline.append({
        "stage": "final_semantic_fit_audit",
        "passed": bool(semantic_fit.get("passed", True)),
        "mode": semantic_fit.get("mode", ""),
        "issues": semantic_fit.get("issues", []),
    })

    final_post_issues = _post_polish_redline_issues(str(response.get("suggested_reply") or ""))
    if final_post_issues and not post_issues:
        original_reply = str(response.get("suggested_reply") or "")
        response["suggested_reply"] = _safe_post_polish_fallback(response)
        response["requires_human_review"] = True
        response["generation_mode"] = "post_polish_redline_fallback"
        response["reason_for_review"] = _append_reason(
            str(response.get("reason_for_review") or ""),
            "最终润色后命中红线，已改为保守客服话术",
        )
        response.setdefault("guard_warnings", []).append(
            "post_polish_redline: " + ",".join(final_post_issues)
        )
        response.setdefault("evidence_debug", {})["post_polish_redline"] = {
            "passed": False,
            "issues": final_post_issues,
            "original_reply": original_reply,
        }
        post_issues = final_post_issues
    elif not post_issues:
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
    response["final_response_pipeline"] = {
        "version": "final-response-orchestrator-v1",
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
    response.setdefault("evidence_debug", {})["quality_result"] = {
        "stage": "final_response_orchestrator",
        "passed": bool(
            (response.get("final_answer_audit") or {}).get("passed", True)
            and (response.get("final_semantic_fit_audit") or {}).get("passed", True)
            and not post_issues
        ),
        "final_answer_audit": response.get("final_answer_audit", {}),
        "final_semantic_fit_audit": response.get("final_semantic_fit_audit", {}),
        "post_polish_redline": response.get("evidence_debug", {}).get("post_polish_redline", {}),
    }
    try:
        from app.services.answer_trace_service import attach_answer_trace
        response = attach_answer_trace(response, customer_message=customer_message)
    except Exception:
        pass
    response.setdefault("trace_steps", []).append({
        "node": "final_response_orchestrator",
        "status": "completed",
        "summary": "final semantic audit, redline, polish and block sync completed",
        "stages": pipeline,
    })
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
    intent = str(response.get("intent") or "").lower()
    debug = response.get("evidence_debug") or {}
    query_fact_type = str(debug.get("query_fact_type") or response.get("query_fact_type") or "")
    if intent in {"delivery_not_received", "logistics_eta", "logistics_trace", "shipping"}:
        return (
            "\u4eb2\uff0c\u7269\u6d41\u90e8\u5206\u6211\u5148\u6309\u5f53\u524d\u8ba2\u5355\u6216\u7269\u6d41\u4fe1\u606f\u5e2e\u60a8\u6838\u5b9e\u6700\u65b0\u72b6\u6001\u3002\n"
            "\u5982\u679c\u662f\u7b7e\u6536\u672a\u6536\u5230\uff0c\u60a8\u53ef\u4ee5\u5148\u770b\u4e00\u4e0b\u5bb6\u4eba\u3001\u95e8\u536b\u3001\u9a7f\u7ad9\u6216\u5feb\u9012\u67dc\u662f\u5426\u4ee3\u6536\uff0c\u6211\u8fd9\u8fb9\u4e5f\u4f1a\u7ee7\u7eed\u8ddf\u8fdb\u3002"
        )
    if intent == "aftersales" or query_fact_type == "aftersales_policy":
        return (
            "\u4eb2\uff0c\u8fd9\u4e2a\u552e\u540e\u60c5\u51b5\u6211\u5148\u5e2e\u60a8\u6838\u5b9e\u5904\u7406\u3002\n"
            "\u53d1\u9519\u3001\u5c11\u4ef6/\u7f3a\u914d\u4ef6\u3001\u7834\u635f\u3001\u9000\u8d27\u6216\u6362\u8d27\u90fd\u9700\u8981\u6309\u5e73\u53f0\u552e\u540e\u6d41\u7a0b\u786e\u8ba4\uff1b"
            "\u5982\u679c\u8fd8\u6d89\u53ca\u80fd\u5426\u5b89\u88c5\uff0c\u6211\u4e5f\u4f1a\u7ed3\u5408\u7f3a\u5c11\u7684\u914d\u4ef6\u4e00\u8d77\u6838\u5bf9\u3002\n"
            "\u4e3a\u4e86\u66f4\u5feb\u5904\u7406\uff0c\u65b9\u4fbf\u7684\u8bdd\u60a8\u53ef\u4ee5\u628a\u5b9e\u7269\u3001\u9762\u5355\u6216\u95ee\u9898\u4f4d\u7f6e\u62cd\u6e05\u695a\u53d1\u6211\u3002"
        )
    if intent == "cleaning_care" or query_fact_type == "cleaning_care":
        return (
            "\u4eb2\uff0c\u6e05\u6d17\u65b9\u5f0f\u9700\u8981\u7ed3\u5408\u5177\u4f53\u6750\u8d28\u548c\u7ed3\u6784\u6838\u5b9e\u3002\n"
            "\u6211\u5148\u5e2e\u60a8\u6309\u5f53\u524d\u5546\u54c1\u8d44\u6599\u786e\u8ba4\u662f\u5426\u80fd\u6c34\u6d17\u3001\u673a\u6d17\u6216\u53ea\u80fd\u64e6\u6d17\uff0c\u907f\u514d\u8bf4\u9519\u5f71\u54cd\u4f7f\u7528\u3002"
        )
    if intent == "stock_query" or query_fact_type == "stock_shipping":
        return (
            "\u4eb2\uff0c\u53d1\u8d27\u90e8\u5206\u9700\u8981\u7ed3\u5408\u5e93\u5b58\u3001\u4e0b\u5355\u65f6\u95f4\u548c\u5b9e\u9645\u5904\u7406\u72b6\u6001\u786e\u8ba4\u3002\n"
            "\u5982\u679c\u60a8\u540c\u65f6\u5173\u5fc3\u6750\u8d28\u6216\u5b9d\u5b9d\u4f7f\u7528\u5b89\u5168\uff0c\u6211\u4e5f\u4f1a\u6309\u5546\u54c1\u8d44\u6599\u4e00\u8d77\u6838\u5b9e\u3002"
        )
    if query_fact_type in {"material", "certification_report", "odor"}:
        return (
            "\u4eb2\uff0c\u6750\u8d28\u3001\u5b89\u5168\u6216\u6c14\u5473\u8fd9\u7c7b\u95ee\u9898\u6211\u5148\u6309\u5f53\u524d\u5546\u54c1\u8d44\u6599\u5e2e\u60a8\u6838\u5b9e\u3002\n"
            "\u6ca1\u6709\u8bc1\u636e\u65f6\u6211\u4e0d\u4f1a\u628a\u5b89\u5168\u3001\u6c14\u5473\u6216\u68c0\u6d4b\u8bf4\u6210\u786e\u5b9a\u7ed3\u8bba\uff0c\u786e\u8ba4\u540e\u518d\u7ed9\u60a8\u51c6\u786e\u56de\u590d\u3002"
        )
    if str(response.get("intent") or "").lower() in {"complaint", "high_risk"}:
        return (
            "亲～非常抱歉让您有不好的体验，您的反馈我已经收到，会优先帮您跟进处理。\n"
            "涉及投诉或平台介入的情况我会转人工/主管核实，核实前不做结果性承诺。"
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
    if not display_name or len(display_name) < 16:
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
