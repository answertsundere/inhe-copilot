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
from app.services.generic_service_rule_service import unsafe_promise_terms


_INTERNAL_LANGUAGE = (
    "知识库",
    "RAG",
    "资料库",
    "系统里没有",
    "系统里",
    "我不能凭感觉",
    "fact_type",
    "query_fact_type",
)

_FACT_REPLY_CUES = {
    "dimensions": ("尺寸", "大小", "多高", "多宽", "多长", "宽度", "高度", "长度", "长宽高", "规格", "cm", "厘米"),
    "load_capacity": ("承重", "载重", "放多重", "放多少", "多少本", "压弯", "结实"),
    "visual_asset": ("图片", "照片", "图", "实物图", "效果图", "下面发", "参考我下面"),
    "material": ("材质", "材料", "用料", "PP", "HDPE", "钢管", "板材", "实木"),
    "odor": ("气味", "味道", "味儿", "异味", "刺鼻", "通风", "散味"),
    "space_fit": ("空间", "放得下", "放的下", "预留", "宽度", "进深", "高度", "尺寸"),
    "placement_scene": ("卧室", "客厅", "书房", "摆放", "放在", "干燥", "平整"),
    "installation": ("安装", "组装", "打孔", "免打孔", "租房", "教程", "视频", "说明"),
    "aftersales_policy": ("抱歉", "反馈", "售后", "处理", "跟进", "核实", "投诉", "平台"),
}


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
        return _result(
            False,
            structural["issues"],
            structural["reason"],
            "deterministic",
            details=structural,
        )

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
    reply = str(response.get("suggested_reply") or "")
    selected_assets = response.get("selected_assets") or response.get("recommended_assets") or []
    debug = response.get("evidence_debug") or {}
    if not selected_assets and isinstance(debug, dict):
        selected_assets = debug.get("selected_assets") or []
    issues: list[str] = []

    leaked = [term for term in _INTERNAL_LANGUAGE if term.lower() in reply.lower()]
    if leaked:
        issues.append("internal_language_leak:" + ",".join(leaked[:3]))
    leaked_product_names = _leaked_internal_product_names(response, reply)
    if leaked_product_names:
        issues.append("product_name_leak:" + ",".join(leaked_product_names[:2]))
    unsafe = unsafe_promise_terms(reply)
    if unsafe:
        issues.append("unsafe_claim:" + ",".join(unsafe[:3]))

    if not query_fact_type:
        return _structural_result(issues, "Final reply contains blocked language." if issues else "")

    if query_fact_type == "dimensions" and _has_topic(reply, "load_capacity") and not _has_topic(reply, "dimensions"):
        issues.append("off_topic:dimensions_answered_as_load_capacity")
    if query_fact_type == "visual_asset":
        has_asset = bool(selected_assets)
        if not has_asset and not _has_topic(reply, "visual_asset"):
            issues.append("missing_answer:visual_asset")
        if _has_topic(reply, "material") and not (_has_topic(reply, "visual_asset") or has_asset):
            issues.append("off_topic:visual_asset_answered_as_material")
    if query_fact_type == "odor" and not _has_topic(reply, "odor") and not _is_human_review_reply(reply):
        issues.append("missing_answer:odor")

    intent = str(response.get("intent") or "").lower()
    risk = str(response.get("risk_level") or "").lower()
    if intent in {"complaint", "high_risk"} or risk in {"high", "critical"}:
        if not _has_topic(reply, "aftersales_policy") and (
            _has_topic(reply, "dimensions") or _has_topic(reply, "material") or _has_topic(reply, "load_capacity")
        ):
            issues.append("off_topic:complaint_answered_as_product_fact")

    answerability = str(evidence_pack.get("answerability") or "")
    if answerability in {"missing_product_fact", "no_product_profile", "no_product_identity"}:
        if not bool(response.get("requires_human_review")):
            issues.append("missing_evidence_without_human_review")

    matched_facts = evidence_pack.get("matched_facts") or []
    if answerability == "direct_answer" and not matched_facts:
        issues.append("direct_answer_without_matched_fact")

    for fact in matched_facts:
        alignment = fact.get("semantic_alignment") or {}
        if alignment and alignment.get("direct_answer_allowed") is False:
            issues.append("selected_fact_not_direct_answer_allowed")

    reason = "Final reply failed deterministic semantic quality gate." if issues else ""
    return _structural_result(issues, reason)


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
            details={
                "score": float(parsed.get("score") or (1.0 if parsed.get("passed", True) else 0.0)),
                "off_topic": bool(parsed.get("off_topic", False)),
                "missing_answer": bool(parsed.get("missing_answer", False)),
                "unsupported_claim": bool(parsed.get("unsupported_claim", False)),
                "unsafe_claim": bool(parsed.get("unsafe_claim", False)),
                "internal_language_leak": bool(parsed.get("internal_language_leak", False)),
                "product_name_leak": bool(parsed.get("product_name_leak", False)),
                "should_retry": bool(parsed.get("should_retry", not parsed.get("passed", True))),
                "rewrite_instruction": str(parsed.get("rewrite_instruction") or "")[:500],
            },
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
        "product_display_name": response.get("display_product_name", ""),
        "classified_intent": response.get("intent", ""),
        "classified_fact_type": _query_fact_type(response, evidence_pack),
        "draft_answer": response.get("suggested_reply", ""),
        "risk_level": response.get("risk_level", ""),
        "selected_evidence": (debug.get("selected_evidence") or [])[:8],
        "selected_assets": (response.get("selected_assets") or debug.get("selected_assets") or response.get("recommended_assets") or [])[:5],
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


def _has_topic(text: str, fact_type: str) -> bool:
    cues = _FACT_REPLY_CUES.get(fact_type, ())
    return any(cue.lower() in str(text or "").lower() for cue in cues)


def _is_human_review_reply(text: str) -> bool:
    return any(term in str(text or "") for term in ("核实", "确认", "人工", "跟进", "稍等"))


def _leaked_internal_product_names(response: dict[str, Any], reply: str) -> list[str]:
    display_name = str(
        response.get("display_product_name")
        or response.get("platform_product_title")
        or response.get("front_product_title")
        or ""
    ).strip()
    if not display_name or len(display_name) < 16:
        return []

    candidates: list[str] = []
    for key in ("product_name", "matched_product_name", "internal_product_name"):
        value = str(response.get(key) or "").strip()
        if value:
            candidates.append(value)

    context_used = response.get("context_used") or {}
    if isinstance(context_used, dict):
        for key in ("matched_product_name", "product_name"):
            value = str(context_used.get(key) or "").strip()
            if value:
                candidates.append(value)
        product_pack = context_used.get("product_context_pack") or {}
        if isinstance(product_pack, dict):
            identity = product_pack.get("identity") or {}
            if isinstance(identity, dict):
                for key in ("product_name", "matched_product_name"):
                    value = str(identity.get(key) or "").strip()
                    if value:
                        candidates.append(value)

    leaks: list[str] = []
    for name in candidates:
        if not name or name == display_name or name in display_name:
            continue
        if len(name) > 30:
            continue
        if name in reply and name not in leaks:
            leaks.append(name)
    return leaks


def _structural_result(issues: list[str], reason: str) -> dict[str, Any]:
    return {
        "issues": list(dict.fromkeys(issues)),
        "reason": reason,
        "score": 0.0 if issues else 1.0,
        "off_topic": any(issue.startswith("off_topic") for issue in issues),
        "missing_answer": any(issue.startswith("missing_answer") for issue in issues),
        "unsupported_claim": any("unsupported" in issue for issue in issues),
        "unsafe_claim": any(issue.startswith("unsafe_claim") for issue in issues),
        "internal_language_leak": any(issue.startswith("internal_language_leak") for issue in issues),
        "product_name_leak": any(issue.startswith("product_name_leak") for issue in issues),
        "should_retry": bool(issues),
        "rewrite_instruction": "Rewrite with selected evidence only; remove internal language and answer the current fact type.",
    }


def _result(
    passed: bool,
    issues: list[str],
    reason: str,
    mode: str,
    *,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    details = details or {}
    normalized_issues = list(dict.fromkeys(issues))
    score = float(details.get("score", 1.0 if passed else 0.0))
    result = {
        "checked": True,
        "pass": bool(passed),
        "passed": bool(passed),
        "score": score,
        "off_topic": bool(details.get("off_topic", any(issue.startswith("off_topic") for issue in normalized_issues))),
        "missing_answer": bool(details.get("missing_answer", any(issue.startswith("missing_answer") for issue in normalized_issues))),
        "unsupported_claim": bool(details.get("unsupported_claim", any("unsupported" in issue for issue in normalized_issues))),
        "unsafe_claim": bool(details.get("unsafe_claim", any(issue.startswith("unsafe_claim") for issue in normalized_issues))),
        "internal_language_leak": bool(details.get("internal_language_leak", any(issue.startswith("internal_language_leak") for issue in normalized_issues))),
        "product_name_leak": bool(details.get("product_name_leak", any(issue.startswith("product_name_leak") for issue in normalized_issues))),
        "should_retry": bool(details.get("should_retry", not passed)),
        "failure_reason": reason if not passed else "",
        "rewrite_instruction": str(details.get("rewrite_instruction") or ("Use selected evidence only and answer the current user query." if not passed else "")),
        "issues": normalized_issues,
        "reason": reason,
        "mode": mode,
    }
    return result
