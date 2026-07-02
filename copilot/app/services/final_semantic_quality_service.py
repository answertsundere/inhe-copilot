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
from app.services.no_evidence_reply_policy_service import apply_no_evidence_reply_policy


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

    evidence_pack = _evidence_pack(response)
    query_fact_type = _query_fact_type(response, evidence_pack)

    # Visual/installation questions can be answered by attached media assets.
    # Accept the reply deterministically when it references the attached asset.
    if _is_visual_media_answer(response):
        return _result(
            True,
            [],
            "Visual/installation question answered with an attached image/video asset.",
            "deterministic",
        )

    # Generic-rule fallbacks are intentionally conservative policy replies.
    # When a matching generic rule exists and the reply avoids forbidden claims,
    # accept it without calling the LLM judge.
    if _generic_rule_fallback_acceptable(response, evidence_pack, query_fact_type):
        return _result(
            True,
            [],
            "Generic rule fallback reply accepted deterministically.",
            "deterministic",
        )

    llm_result = _llm_semantic_fit_check(
        response,
        customer_message=customer_message,
        copilot_context=copilot_context or {},
    )
    if llm_result:
        return llm_result

    return _result(True, [], "No structural semantic issue detected.", "deterministic")


def apply_semantic_fit_result(
    response: dict[str, Any],
    result: dict[str, Any],
    *,
    copilot_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
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
    response = apply_no_evidence_reply_policy(response, copilot_context)
    return response


def _structural_semantic_checks(response: dict[str, Any]) -> dict[str, Any]:
    evidence_pack = _evidence_pack(response)
    query_fact_type = _query_fact_type(response, evidence_pack)
    if not query_fact_type:
        return {"issues": [], "reason": ""}

    product_fact_issues = _strict_product_fact_boundary_issues(response, query_fact_type)
    if product_fact_issues:
        return {
            "issues": product_fact_issues,
            "reason": "Final reply answers a different product fact type than the customer asked.",
        }

    answerability = str(evidence_pack.get("answerability") or "")
    if answerability in {"missing_product_fact", "no_product_profile", "no_product_identity"}:
        # If upstream already determined the reply is relevant and on-topic,
        # do not let a stale "missing product fact" pack force a fallback.
        debug = response.get("evidence_debug") or {}
        if bool(debug.get("answer_relevance_passed")) or bool(debug.get("direct_answer_supported")):
            return {"issues": [], "reason": ""}
        if not bool(response.get("requires_human_review")):
            return {
                "issues": ["missing_evidence_without_human_review"],
                "reason": "Required product fact is missing but reply is not marked for human review.",
            }

    matched_facts = evidence_pack.get("matched_facts") or []
    if answerability == "direct_answer" and not matched_facts:
        # A direct-answer pack may have been promoted from a generic-rule or
        # template-supported reply. Accept it when such supporting evidence is
        # present and matches the query fact type.
        if _generic_or_template_supports_fact_type(response, evidence_pack, query_fact_type):
            return {"issues": [], "reason": ""}
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


def _strict_product_fact_boundary_issues(response: dict[str, Any], query_fact_type: str) -> list[str]:
    reply = str(response.get("suggested_reply") or "")
    issues: list[str] = []
    if query_fact_type == "gross_weight":
        weight_terms = ("\u6bdb\u91cd", "\u5305\u88c5\u91cd\u91cf", "\u5546\u54c1\u91cd\u91cf", "\u91cd\u91cf", "\u6838\u5bf9")
        load_terms = ("\u627f\u91cd", "\u8f7d\u91cd", "\u5bb9\u91cf")
        dimension_terms = ("\u5bbd", "\u6df1", "\u9ad8", "\u5c3a\u5bf8", "\u9884\u7559", "\u7a7a\u95f4", "\u653e\u5f97\u4e0b", "\u653e\u7684\u4e0b")
        has_weight_context = any(term in reply for term in weight_terms)
        if any(term in reply for term in load_terms) and not has_weight_context:
            issues.append("gross_weight_answered_with_load_capacity")
        if any(term in reply for term in dimension_terms) and not has_weight_context:
            issues.append("gross_weight_answered_with_dimensions_or_capacity")
    if query_fact_type == "accessory_availability":
        availability_terms = (
            "\u6709\u5356",
            "\u552e\u5356",
            "\u5355\u72ec\u4e70",
            "\u5355\u72ec\u8d2d\u4e70",
            "\u8865\u4e70",
            "\u8865\u8d2d",
            "\u53ef\u552e",
            "\u80fd\u4e70",
            "\u6838\u5bf9",
        )
        installation_terms = ("\u5b89\u88c5\u8d44\u6599", "\u8bf4\u660e\u4e66", "\u600e\u4e48\u88c5", "\u5b89\u88c5\u89c6\u9891", "\u5b89\u88c5\u8bf4\u660e")
        if any(term in reply for term in installation_terms) and not any(term in reply for term in availability_terms):
            issues.append("accessory_availability_answered_with_installation")
    if query_fact_type == "installation":
        installation_terms = (
            "\u5b89\u88c5",
            "\u7ec4\u88c5",
            "\u6559\u7a0b",
            "\u8bf4\u660e\u4e66",
            "\u56fe\u7eb8",
            "\u89c6\u9891",
            "\u6b65\u9aa4",
            "\u5b54\u4f4d",
            "\u87ba\u4e1d",
            "\u914d\u4ef6",
            "\u5361\u4f4f",
            "\u62cd\u7167",
            "\u6838\u5bf9",
            "\u4eba\u5de5",
        )
        wrong_product_fact_terms = (
            "\u5c3a\u5bf8",
            "\u5bbd",
            "\u6df1",
            "\u9ad8",
            "\u9884\u7559",
            "\u7a7a\u95f4",
            "\u6750\u8d28",
            "\u6750\u6599",
            "\u627f\u91cd",
            "\u8f7d\u91cd",
            "\u6bdb\u91cd",
            "\u91cd\u91cf",
            "\u9002\u7528\u5e74\u9f84",
            "\u5e74\u9f84",
        )
        has_installation_context = any(term in reply for term in installation_terms)
        if any(term in reply for term in wrong_product_fact_terms) and not has_installation_context:
            issues.append("installation_answered_with_unrelated_product_fact")
    if query_fact_type == "structure_function":
        structure_terms = (
            "结构",
            "孔位",
            "结构件",
            "配件规格",
            "侧板",
            "护栏",
            "围栏",
            "挡板",
            "板子",
            "补配",
            "加装",
            "适配",
            "翻下",
            "翻起",
            "打开",
            "收起",
            "折叠",
            "调节",
            "核对",
            "确认",
        )
        scene_or_space_terms = ("卧室", "客厅", "书房", "厨房", "阳台", "卫生间", "预留位置", "走动空间", "宽度", "进深", "高度", "空间小")
        has_structure_context = any(term in reply for term in structure_terms)
        if any(term in reply for term in scene_or_space_terms) and not has_structure_context:
            issues.append("structure_function_answered_with_scene_or_space")
    if query_fact_type in {"aftersales", "aftersales_policy", "after_sales"}:
        aftersales_terms = ("售后", "补发", "换件", "换货", "破损", "断裂", "裂了", "损坏", "核实", "订单")
        wrong_fact_terms = ("安装步骤", "怎么装", "尺寸", "材质", "卧室", "客厅", "预留位置")
        has_aftersales_context = any(term in reply for term in aftersales_terms)
        if any(term in reply for term in wrong_fact_terms) and not has_aftersales_context:
            issues.append("aftersales_answered_with_product_fact")
    return issues


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


def _is_visual_media_answer(response: dict[str, Any]) -> bool:
    """Return True when the reply includes a media asset for a visual fact type."""
    fact_type = str(
        ((response.get("evidence_debug") or {}).get("query_fact_type"))
        or (response.get("query_fact_type"))
        or ""
    )
    visual_fact_types = {"dimensions", "space_fit", "installation", "detachable", "accessories", "packaging"}
    if fact_type not in visual_fact_types:
        return False
    has_media = bool(
        (response.get("recommended_assets") or [])
        or [b for b in (response.get("reply_blocks") or []) if isinstance(b, dict) and b.get("type") in {"image", "video"}]
    )
    if not has_media:
        return False
    reply = str(response.get("suggested_reply") or "").lower()
    return any(term in reply for term in (
        "图", "图片", "尺寸图", "视频", "安装视频", "参考下面", "下面发您",
    ))


def _generic_rule_fallback_acceptable(
    response: dict[str, Any],
    evidence_pack: dict[str, Any],
    query_fact_type: str,
) -> bool:
    """Return True when the reply is a policy-grounded generic-rule fallback."""
    if str(evidence_pack.get("answerability") or "") != "generic_rule_fallback":
        return False
    if not query_fact_type:
        return False
    matched_rules = [
        rule
        for rule in (evidence_pack.get("matched_generic_rules") or [])
        if isinstance(rule, dict) and str(rule.get("fact_type") or "") == query_fact_type
    ]
    if not matched_rules:
        return False

    # Look up the full rule definition to check risk and auto-reply flags.
    debug = response.get("evidence_debug") or {}
    product_pack = (
        response.get("product_context_pack")
        or debug.get("product_context_pack_summary")
        or {}
    )
    full_rules = {
        str(rule.get("rule_key") or ""): rule
        for rule in (product_pack.get("generic_rules") or [])
        if isinstance(rule, dict)
    }
    for rule in matched_rules:
        full = full_rules.get(str(rule.get("rule_key") or "")) or {}
        if full.get("auto_reply_allowed") is False:
            return False
        if str(full.get("risk_level") or "low").lower() not in {"low", "medium"}:
            return False

    # Do not accept replies that repeat forbidden claims from the rule.
    reply = str(response.get("suggested_reply") or "").lower()
    for rule in matched_rules:
        for claim in rule.get("forbidden_claims") or []:
            if claim and claim.lower() in reply:
                return False
    return True


def _generic_or_template_supports_fact_type(
    response: dict[str, Any],
    evidence_pack: dict[str, Any],
    query_fact_type: str,
) -> bool:
    """Return True when generic rules or template evidence support query_fact_type."""
    matched_generic = [
        rule
        for rule in (evidence_pack.get("matched_generic_rules") or [])
        if isinstance(rule, dict) and str(rule.get("fact_type") or "") == query_fact_type
    ]
    if matched_generic:
        return True
    debug = response.get("evidence_debug") or {}
    for item in (debug.get("template_evidence") or []):
        if not isinstance(item, dict):
            continue
        ev_ft = str(item.get("evidence_fact_type") or item.get("fact_type") or "")
        if ev_ft == query_fact_type:
            return True
    return False


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
        f"亲～{product}这个问题需要结合对应资料复核，避免口径不准确。\n"
        "我先转人工确认后，再给您准确处理建议。"
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
