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
from app.services.answer_blocks_service import raw_field_leakage_issues
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
    "certification_report": ("检测报告", "质检", "认证", "证书", "合格证", "甲醛", "报告"),
    "odor": ("气味", "味道", "味儿", "异味", "刺鼻", "通风", "散味"),
    "space_fit": ("空间", "放得下", "放的下", "预留", "宽度", "进深", "高度", "尺寸"),
    "placement_scene": ("卧室", "客厅", "书房", "摆放", "放在", "干燥", "平整"),
    "age_range": ("适合", "适龄", "年龄", "月龄", "宝宝", "一岁", "两岁", "三岁", "几个月", "多大"),
    "installation": ("安装", "组装", "打孔", "免打孔", "租房", "教程", "视频", "说明"),
    "aftersales_policy": ("抱歉", "反馈", "售后", "处理", "跟进", "核实", "投诉", "平台"),
}

_FACT_TOPIC_CONTRACTS = {
    "space_fit": {
        "allowed": {"space_fit", "dimensions", "visual_asset"},
        "conflicts": {"load_capacity", "material", "installation"},
    },
    "placement_scene": {
        "allowed": {"placement_scene"},
        "conflicts": {"material", "load_capacity", "dimensions"},
    },
    "dimensions": {
        "allowed": {"dimensions", "visual_asset"},
        "conflicts": {"load_capacity", "material"},
    },
    "load_capacity": {
        "allowed": {"load_capacity"},
        "conflicts": {"dimensions", "material"},
    },
    "visual_asset": {
        "allowed": {"visual_asset"},
        "conflicts": {"material", "load_capacity"},
    },
    "certification_report": {
        "allowed": {"certification_report"},
        "conflicts": {"material", "load_capacity", "dimensions"},
    },
    "age_range": {
        "allowed": {"age_range"},
        "conflicts": {"load_capacity", "material", "dimensions", "installation"},
    },
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
        if _llm_only_complains_about_review_flag(response, llm_result):
            return _result(
                True,
                [],
                "LLM semantic fit only complained about a human-review flag while the reply directly used selected evidence.",
                "deterministic_review_flag_override",
                details={"llm_semantic_fit": llm_result},
            )
        if not llm_result.get("passed", True) and _safe_composition_fallback(response):
            return _result(
                True,
                [],
                "LLM semantic fit false negative overridden by safe answer_composition_trace fallback.",
                "deterministic_composition_fallback_override",
                details={"llm_semantic_fit": llm_result},
            )
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
    raw_field_issues = raw_field_leakage_issues(reply)
    if raw_field_issues:
        issues.extend(raw_field_issues)

    if not query_fact_type:
        return _structural_result(issues, "Final reply contains blocked language." if issues else "")

    if query_fact_type == "dimensions" and _has_topic(reply, "load_capacity") and not _has_topic(reply, "dimensions"):
        issues.append("off_topic:dimensions_answered_as_load_capacity")
    issues.extend(_fact_type_topic_contract_issues(query_fact_type, reply, selected_assets))
    issues.extend(_media_reference_contract_issues(query_fact_type, reply, response))
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
        if not bool(response.get("requires_human_review")) and not _safe_composition_fallback(response):
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


def _safe_composition_fallback(response: dict[str, Any]) -> bool:
    reply = str(response.get("suggested_reply") or "")
    if unsafe_promise_terms(reply):
        return False
    debug = response.get("evidence_debug") or {}
    trace = debug.get("answer_composition_trace") or response.get("answer_composition_trace") or {}
    if not isinstance(trace, dict) or not trace.get("answer_sections"):
        return False
    if any(trace.get("missing_fact_types") or []):
        return False
    safe_fact_types = {
        "space_fit",
        "placement_scene",
        "stock_shipping",
        "visual_asset",
        "aftersales_policy",
        "installation",
    }
    fallback = trace.get("fallback_used_by_fact_type") or {}
    covered = [
        str(item)
        for item in trace.get("answered_fact_types", trace.get("covered_fact_types", []))
        if str(item).strip()
    ]
    if not covered:
        return False
    for fact_type in covered:
        if fallback.get(fact_type) and fact_type not in safe_fact_types:
            return False
        if not _has_topic(reply, fact_type):
            return False
    return True


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
        if hasattr(client, "is_configured"):
            if not client.is_configured("judge_model"):
                return None
        elif not getattr(client, "api_key", ""):
            return None

        payload = _semantic_payload(response, customer_message, copilot_context)
        messages = [
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
                    "You are a judge only. Never output a customer reply or rewrite text. "
                    "Return strict JSON only with this schema: "
                    "{\"passed\": boolean, \"issues\": string[], \"reason\": string, "
                    "\"semantic_mismatch\": boolean, \"risk_level\": \"low|medium|high\", "
                    "\"requires_human_review\": boolean}."
                ),
            },
            {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
        ]
        if hasattr(client, "chat_completion"):
            result = client.chat_completion(
                model_alias="judge_model",
                node_name="final_semantic_quality_judge",
                messages=messages,
                temperature=0,
                max_tokens=240,
                response_format={"type": "json_object"},
            )
        else:
            result = client.client.chat.completions.create(
                model=client.model,
                messages=messages,
                temperature=0,
                max_tokens=240,
                response_format={"type": "json_object"},
            )
        raw = result.choices[0].message.content
        parsed = json.loads(raw)
        return _normalize_llm_judge_result(parsed)
    except Exception as exc:
        return _result(
            True,
            [],
            f"LLM semantic judge unavailable, deterministic gate used: {type(exc).__name__}",
            "deterministic",
            details={"llm_judge_fallback": True, "llm_error": type(exc).__name__},
        )


def _normalize_llm_judge_result(parsed: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(parsed, dict):
        raise ValueError("LLM judge result must be a JSON object")
    passed = bool(parsed.get("passed", True))
    risk_level = str(parsed.get("risk_level") or ("low" if passed else "medium")).lower()
    if risk_level not in {"low", "medium", "high"}:
        risk_level = "low" if passed else "medium"
    issues = [str(item)[:120] for item in (parsed.get("issues") or []) if str(item or "").strip()]
    return _result(
        passed,
        issues,
        str(parsed.get("reason") or "")[:500],
        "llm_semantic_judge",
        details={
            "score": 1.0 if passed else 0.0,
            "semantic_mismatch": bool(parsed.get("semantic_mismatch", not passed)),
            "risk_level": risk_level,
            "requires_human_review": bool(parsed.get("requires_human_review", False)),
            "off_topic": bool(parsed.get("semantic_mismatch", False)),
            "missing_answer": any("missing" in issue.lower() for issue in issues),
            "unsupported_claim": any("unsupported" in issue.lower() for issue in issues),
            "unsafe_claim": any("unsafe" in issue.lower() for issue in issues),
            "should_retry": False,
            "rewrite_instruction": "",
            "llm_judge_schema_version": "phase9-v1",
        },
    )


def _semantic_payload(
    response: dict[str, Any],
    customer_message: str,
    copilot_context: dict[str, Any],
) -> dict[str, Any]:
    debug = response.get("evidence_debug") or {}
    evidence_pack = _evidence_pack(response)
    required_fact_types = _required_fact_types(response, evidence_pack)
    selected_evidence = debug.get("selected_evidence") or response.get("selected_evidence") or []
    answer_blocks = response.get("answer_blocks") or debug.get("answer_blocks") or response.get("reply_blocks") or []
    answer_trace = response.get("answer_trace") or debug.get("answer_trace") or {}
    query_understanding = (
        debug.get("query_understanding")
        or response.get("query_understanding")
        or debug.get("semantic_query")
        or response.get("semantic_query")
        or {}
    )
    return {
        "user_message": customer_message,
        "customer_message": customer_message,
        "final_text": response.get("suggested_reply", ""),
        "final_reply": response.get("suggested_reply", ""),
        "requires_human_review": bool(response.get("requires_human_review")),
        "review_reason": response.get("reason_for_review") or response.get("review_reason") or "",
        "intent": response.get("intent", ""),
        "query_understanding": query_understanding,
        "semantic_query": debug.get("semantic_query") or response.get("semantic_query") or {},
        "query_fact_type": _query_fact_type(response, evidence_pack),
        "required_fact_types": required_fact_types,
        "product_display_name": response.get("display_product_name", ""),
        "classified_intent": response.get("intent", ""),
        "classified_fact_type": _query_fact_type(response, evidence_pack),
        "draft_answer": response.get("suggested_reply", ""),
        "risk_level": response.get("risk_level", ""),
        "selected_evidence_summary": _selected_evidence_summary(selected_evidence),
        "selected_evidence": _selected_evidence_summary(selected_evidence),
        "answer_blocks": _answer_block_payload(answer_blocks),
        "answer_trace_summary": _answer_trace_summary(answer_trace),
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


def _required_fact_types(response: dict[str, Any], evidence_pack: dict[str, Any]) -> list[str]:
    debug = response.get("evidence_debug") or {}
    values: list[Any] = []
    for container in (response, debug, evidence_pack):
        if isinstance(container, dict):
            values.extend(container.get("required_fact_types") or [])
    query_fact_type = _query_fact_type(response, evidence_pack)
    if query_fact_type:
        values.append(query_fact_type)
    result: list[str] = []
    for value in values:
        fact_type = str(value or "").strip()
        if fact_type and fact_type not in result:
            result.append(fact_type)
    return result


def _selected_evidence_summary(items: Any) -> list[dict[str, Any]]:
    if not isinstance(items, list):
        return []
    summaries: list[dict[str, Any]] = []
    for item in items[:8]:
        if not isinstance(item, dict):
            continue
        preview = (
            item.get("preview")
            or item.get("fact")
            or item.get("content")
            or item.get("text")
            or item.get("answer")
            or ""
        )
        summaries.append({
            "source_type": item.get("source_type") or item.get("evidence_origin") or "",
            "fact_type": item.get("fact_type") or item.get("evidence_fact_type") or "",
            "entry_id": item.get("entry_id") or item.get("id") or "",
            "title": item.get("title") or item.get("question") or "",
            "preview": str(preview)[:240],
        })
    return summaries


def _answer_block_payload(blocks: Any) -> list[dict[str, Any]]:
    if not isinstance(blocks, list):
        return []
    payload: list[dict[str, Any]] = []
    for block in blocks[:8]:
        if not isinstance(block, dict):
            continue
        payload.append({
            "type": block.get("type", ""),
            "title": block.get("title", ""),
            "fact_type": block.get("fact_type", ""),
            "content_preview": str(block.get("content") or block.get("text") or "")[:240],
        })
    return payload


def _answer_trace_summary(trace: Any) -> dict[str, Any]:
    if not isinstance(trace, dict):
        return {}
    return {
        "query_fact_type": trace.get("query_fact_type", ""),
        "required_fact_types": trace.get("required_fact_types", []),
        "evidence_answered_fact_types": trace.get("evidence_answered_fact_types", []),
        "mode": trace.get("mode", ""),
        "final_quality_pass": trace.get("final_quality_pass", None),
        "semantic_compiler_result": trace.get("semantic_compiler_result", {}),
        "final_semantic_fit_audit": trace.get("final_semantic_fit_audit", {}),
    }


def _semantic_fit_fallback(response: dict[str, Any]) -> str:
    evidence_pack = _evidence_pack(response)
    query_fact_type = _query_fact_type(response, evidence_pack)
    intent = str(response.get("intent") or "").lower()
    risk = str(response.get("risk_level") or "").lower()
    debug = response.get("evidence_debug") or {}

    if intent in {"complaint", "high_risk"} or risk in {"high", "critical"}:
        return (
            "\u4eb2\uff0c\u8fd9\u4e2a\u60c5\u51b5\u6211\u5148\u5e2e\u60a8\u8bb0\u5f55\u5e76\u8f6c\u4eba\u5de5/\u4e3b\u7ba1\u6838\u5b9e\u5904\u7406\u3002\n"
            "\u6d89\u53ca\u6295\u8bc9\u3001\u5e73\u53f0\u4ecb\u5165\u6216\u8d39\u7528/\u552e\u540e\u5904\u7406\u7684\u90e8\u5206\uff0c\u9700\u8981\u6309\u8ba2\u5355\u60c5\u51b5\u548c\u5e73\u53f0\u89c4\u5219\u786e\u8ba4\uff0c"
            "\u6838\u5b9e\u524d\u4e0d\u505a\u7ed3\u679c\u6027\u627f\u8bfa\uff0c\u6211\u4f1a\u63a8\u8fdb\u6838\u5b9e\u540e\u7ed9\u60a8\u660e\u786e\u5904\u7406\u65b9\u5411\u3002"
        )

    if intent in {"delivery_not_received", "logistics_eta", "logistics_trace", "shipping"}:
        identifier = response.get("order_id") or response.get("tracking_no") or debug.get("identifier_value") or ""
        if intent == "delivery_not_received":
            reply = (
                "\u4eb2\uff0c\u663e\u793a\u7b7e\u6536\u4f46\u60a8\u6ca1\u6536\u5230\uff0c\u6211\u5148\u5e2e\u60a8\u6838\u5bf9\u6d3e\u9001\u548c\u7b7e\u6536\u60c5\u51b5\u3002\n"
                "\u60a8\u4e5f\u53ef\u4ee5\u5148\u770b\u4e00\u4e0b\u5bb6\u4eba\u3001\u95e8\u536b/\u524d\u53f0\u3001\u9a7f\u7ad9\u3001\u5feb\u9012\u67dc\u6216\u95e8\u53e3\u9644\u8fd1\u662f\u5426\u4ee3\u6536/\u6682\u653e\u3002"
            )
            if identifier:
                return reply + "\n\u6211\u5df2\u6536\u5230\u5f53\u524d\u8ba2\u5355/\u7269\u6d41\u4fe1\u606f\uff0c\u4f1a\u6309\u73b0\u6709\u53f7\u7801\u7ee7\u7eed\u6838\u5bf9\u5e76\u8ddf\u8fdb\u3002"
            return reply + "\n\u9ebb\u70e6\u60a8\u8865\u5145\u4e00\u4e0b\u8ba2\u5355\u53f7\u6216\u7269\u6d41\u5355\u53f7\uff0c\u6211\u8fd9\u8fb9\u6309\u53f7\u7801\u5e2e\u60a8\u6838\u5b9e\u3002"
        return (
            "\u4eb2\uff0c\u7269\u6d41\u65f6\u6548\u9700\u8981\u4ee5\u5feb\u9012\u5b9e\u65f6\u8f68\u8ff9\u548c\u6d3e\u9001\u5b89\u6392\u4e3a\u51c6\uff0c"
            "\u6211\u8fd9\u8fb9\u5148\u6309\u5f53\u524d\u8ba2\u5355/\u7269\u6d41\u4fe1\u606f\u5e2e\u60a8\u6838\u5b9e\u6700\u65b0\u72b6\u6001\u3002\n"
            "\u5177\u4f53\u5230\u8fbe\u65f6\u95f4\u4e0d\u80fd\u505a\u786e\u5b9a\u6027\u627f\u8bfa\uff0c\u6838\u5b9e\u5230\u8f68\u8ff9\u540e\u6211\u518d\u7ed9\u60a8\u66f4\u51c6\u786e\u7684\u53c2\u8003\u3002"
        )

    if intent == "aftersales" or query_fact_type == "aftersales_policy":
        return (
            "\u4eb2\uff0c\u8fd9\u4e2a\u552e\u540e\u60c5\u51b5\u6211\u5148\u5e2e\u60a8\u6309\u8ba2\u5355\u548c\u5b9e\u9645\u95ee\u9898\u6838\u5b9e\u5904\u7406\u3002\n"
            "\u5982\u679c\u662f\u53d1\u9519\u3001\u5c11\u4ef6/\u7f3a\u914d\u4ef6\u3001\u7834\u635f\u6216\u9700\u8981\u9000\u8d27/\u6362\u8d27\uff0c"
            "\u6211\u4f1a\u6309\u5e73\u53f0\u552e\u540e\u6d41\u7a0b\u5e2e\u60a8\u786e\u8ba4\u5904\u7406\u8def\u5f84\uff1b\u5982\u679c\u8fd8\u6d89\u53ca\u80fd\u5426\u5b89\u88c5\uff0c\u4e5f\u4f1a\u7ed3\u5408\u7f3a\u5c11\u7684\u914d\u4ef6\u4e00\u8d77\u6838\u5bf9\u3002\n"
            "\u4e3a\u4e86\u66f4\u5feb\u6838\u5bf9\uff0c\u5982\u679c\u65b9\u4fbf\uff0c\u60a8\u53ef\u4ee5\u628a\u5b9e\u7269\u3001\u5916\u5305\u88c5\u9762\u5355\u6216\u95ee\u9898\u4f4d\u7f6e\u62cd\u6e05\u695a\u53d1\u6211\u3002"
        )

    if intent == "stock_query" or query_fact_type == "stock_shipping":
        return (
            "\u4eb2\uff0c\u53d1\u8d27\u90e8\u5206\u9700\u8981\u7ed3\u5408\u5f53\u524d\u5e93\u5b58\u3001\u4e0b\u5355\u65f6\u95f4\u548c\u53d1\u8d27\u5b89\u6392\u786e\u8ba4\u3002\n"
            "\u5b9e\u9645\u662f\u5426\u4eca\u5929\u53d1\u51fa\u4ee5\u4e0b\u5355\u9875\u663e\u793a\u548c\u5b9e\u9645\u5904\u7406\u72b6\u6001\u4e3a\u51c6\uff0c"
            "\u5177\u4f53\u53d1\u51fa\u65f6\u95f4\u4e0d\u505a\u786e\u5b9a\u6027\u627f\u8bfa\u3002\n"
            "\u5982\u679c\u60a8\u540c\u65f6\u5173\u5fc3\u6750\u8d28\u6216\u5b9d\u5b9d\u4f7f\u7528\u5b89\u5168\uff0c\u6211\u4e5f\u4f1a\u6309\u5546\u54c1\u8d44\u6599\u4e00\u8d77\u6838\u5b9e\u3002"
        )

    if query_fact_type == "installation":
        return (
            "\u4eb2\uff0c\u5b89\u88c5\u90e8\u5206\u9700\u8981\u6309\u5bf9\u5e94\u6b3e\u5f0f\u7684\u5b89\u88c5\u8bf4\u660e\u3001\u6559\u7a0b\u6216\u89c6\u9891\u6765\u6838\u5bf9\u3002\n"
            "\u6211\u5148\u5e2e\u60a8\u786e\u8ba4\u5bf9\u5e94\u8d44\u6599\uff0c\u907f\u514d\u53d1\u9519\u6559\u7a0b\u5f71\u54cd\u5b89\u88c5\u3002"
        )

    if query_fact_type == "dimensions":
        return (
            "\u4eb2\uff0c\u5c3a\u5bf8\u90e8\u5206\u9700\u8981\u6309\u5177\u4f53\u6b3e\u5f0f\u7684\u957f\u3001\u5bbd\u3001\u9ad8\u6216\u5c3a\u5bf8\u56fe\u6838\u5b9e\u3002\n"
            "\u6211\u5148\u5e2e\u60a8\u5bf9\u4e00\u4e0b\u5f53\u524d\u5546\u54c1\u8d44\u6599\uff0c\u786e\u8ba4\u540e\u518d\u7ed9\u60a8\u51c6\u786e\u5c3a\u5bf8\u3002"
        )

    if query_fact_type == "load_capacity":
        return (
            "\u4eb2\uff0c\u627f\u91cd\u6216\u80fd\u653e\u591a\u5c11\u672c\u4e66\u9700\u8981\u7ed3\u5408\u5177\u4f53\u6b3e\u5f0f\u7684\u7ed3\u6784\u548c\u5df2\u786e\u8ba4\u8d44\u6599\u6838\u5b9e\u3002\n"
            "\u6211\u5148\u5e2e\u60a8\u6309\u5f53\u524d\u5546\u54c1\u786e\u8ba4\uff0c\u907f\u514d\u628a\u5176\u4ed6\u6b3e\u5f0f\u7684\u627f\u91cd\u4fe1\u606f\u8bf4\u9519\u3002"
        )

    if query_fact_type == "age_range":
        return (
            "\u4eb2\uff0c\u9002\u5408\u591a\u5927\u5b9d\u5b9d\u9700\u8981\u6309\u5bf9\u5e94\u5546\u54c1\u7684\u9002\u7528\u5e74\u9f84\u3001\u7ed3\u6784\u548c\u4f7f\u7528\u573a\u666f\u6838\u5b9e\u3002\n"
            "\u6211\u5148\u5e2e\u60a8\u6309\u5f53\u524d\u5546\u54c1\u8d44\u6599\u786e\u8ba4\uff1b\u6ca1\u6709\u660e\u786e\u9002\u9f84\u8bc1\u636e\u65f6\uff0c\u4e0d\u76f4\u63a5\u7ed9\u51fa\u9002\u9f84\u7ed3\u8bba\u3002"
        )

    if query_fact_type in {"material", "certification_report", "odor", "safety_small_parts", "pinch_safety"}:
        return (
            "\u4eb2\uff0c\u6750\u8d28\u3001\u5b89\u5168\u6216\u6c14\u5473\u8fd9\u7c7b\u95ee\u9898\u6211\u5148\u6309\u5f53\u524d\u5546\u54c1\u7684\u5df2\u786e\u8ba4\u8d44\u6599\u5e2e\u60a8\u6838\u5b9e\u3002\n"
            "\u6ca1\u6709\u8bc1\u636e\u7684\u60c5\u51b5\u4e0b\u6211\u4e0d\u4f1a\u628a\u5b89\u5168\u3001\u6c14\u5473\u6216\u68c0\u6d4b\u8bf4\u6210\u786e\u5b9a\u7ed3\u8bba\uff0c"
            "\u6838\u5b9e\u6e05\u695a\u540e\u7ed9\u60a8\u51c6\u786e\u56de\u590d\u3002"
        )

    display_name = str(response.get("display_product_name") or "").strip()
    product = f"\u300c{display_name}\u300d" if display_name else "\u8fd9\u6b3e\u5546\u54c1"
    return (
        f"\u4eb2\uff0c{product}\u8fd9\u4e2a\u95ee\u9898\u6211\u5148\u5e2e\u60a8\u6309\u5f53\u524d\u5546\u54c1\u4fe1\u606f\u518d\u6838\u5bf9\u4e00\u4e0b\uff0c"
        "\u907f\u514d\u7ed9\u60a8\u8bf4\u9519\u5f71\u54cd\u4f7f\u7528\u6216\u9009\u62e9\u3002\n"
        "\u60a8\u7a0d\u7b49\u4e00\u4e0b\uff0c\u6211\u8fd9\u8fb9\u786e\u8ba4\u6e05\u695a\u540e\u518d\u56de\u590d\u60a8\u3002"
    )


def _llm_only_complains_about_review_flag(response: dict[str, Any], llm_result: dict[str, Any]) -> bool:
    """Keep a grounded direct answer when the LLM only objects to review metadata.

    Some low-risk product fact answers may keep requires_human_review=True for
    operator review even though the customer-facing reply itself is grounded and
    directly answers the question. That metadata should not cause the semantic
    gate to discard a correct evidence-based reply.
    """
    if llm_result.get("passed", True):
        return False
    if not response.get("requires_human_review"):
        return False

    evidence_pack = _evidence_pack(response)
    query_fact_type = _query_fact_type(response, evidence_pack)
    if not query_fact_type:
        return False
    if evidence_pack.get("answerability") != "direct_answer":
        return False

    matched_facts = evidence_pack.get("matched_facts") or []
    has_direct_fact = any(
        item.get("fact_type") == query_fact_type
        and item.get("direct_answer_allowed", True) is not False
        for item in matched_facts
        if isinstance(item, dict)
    )
    if not has_direct_fact:
        return False

    reply = str(response.get("suggested_reply") or "")
    if _is_human_review_reply(reply):
        return False
    if not _has_topic(reply, query_fact_type):
        return False

    text = " ".join(
        [str(llm_result.get("reason") or "")]
        + [str(issue) for issue in (llm_result.get("issues") or [])]
    ).lower()
    review_markers = (
        "requires_human_review",
        "human review",
        "handoff",
        "turns to human",
        "review is unnecessary",
    )
    return any(marker in text for marker in review_markers)


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


def _fact_type_topic_contract_issues(query_fact_type: str, reply: str, selected_assets: Any) -> list[str]:
    contract = _FACT_TOPIC_CONTRACTS.get(query_fact_type)
    if not contract:
        return []
    if _is_human_review_reply(reply):
        return []

    covered = _covered_reply_topics(reply)
    if query_fact_type == "visual_asset" and selected_assets:
        covered.add("visual_asset")

    allowed = set(contract.get("allowed") or set())
    conflicts = set(contract.get("conflicts") or set())
    has_allowed = bool(covered & allowed)
    conflict_hits = sorted(covered & conflicts)

    issues: list[str] = []
    if conflict_hits and not has_allowed:
        issues.append(f"off_topic:{query_fact_type}_answered_as_{','.join(conflict_hits)}")
    elif not has_allowed:
        issues.append(f"missing_answer:{query_fact_type}")
    return issues


def _media_reference_contract_issues(query_fact_type: str, reply: str, response: dict[str, Any]) -> list[str]:
    if _has_deliverable_media_trace(response):
        return []
    issues: list[str] = []
    if query_fact_type == "installation":
        if _contains_any(reply, ("按图", "图里", "下方图片", "下面发", "看图", "发您参考", "图片/视频", "发视频", "视频发您", "按视频", "安装视频发")):
            issues.append("unsupported_media_reference_without_asset")
        if _contains_any(reply, ("尺寸", "宽度", "进深", "高度", "预留位置", "长宽高")):
            issues.append("off_topic:installation_media_fallback_mentions_dimensions")
    if query_fact_type in {"dimensions", "space_fit"}:
        if _contains_any(reply, ("安装", "配件", "按图", "图里标注", "步骤", "教程")) and not _contains_any(reply, ("尺寸", "宽度", "进深", "高度", "长宽高")):
            issues.append("off_topic:dimensions_fallback_mentions_installation")
    if query_fact_type == "visual_asset":
        if _contains_any(reply, ("下面发", "下方图片", "发您参考", "发您看", "一起发您", "直接参考我下面发")):
            issues.append("unsupported_media_reference_without_asset")
    return list(dict.fromkeys(issues))


def _has_deliverable_media_trace(response: dict[str, Any]) -> bool:
    debug = response.get("evidence_debug") or {}
    trace = debug.get("answer_composition_trace") or response.get("answer_composition_trace") or {}
    sources: list[Any] = [
        response.get("selected_assets"),
        response.get("recommended_assets"),
        response.get("reply_blocks"),
        debug.get("selected_assets") if isinstance(debug, dict) else None,
    ]
    if isinstance(trace, dict):
        sources.extend([
            trace.get("asset_evidence_used"),
            trace.get("media_evidence_used"),
        ])
    context_used = response.get("context_used") or {}
    if isinstance(context_used, dict):
        pack = context_used.get("product_context_pack") or {}
        if isinstance(pack, dict):
            sources.extend([
                pack.get("selected_assets"),
                pack.get("recommended_assets"),
                pack.get("media_evidence"),
            ])
    return any(_source_has_deliverable_media(source) for source in sources)


def _source_has_deliverable_media(source: Any) -> bool:
    if isinstance(source, dict):
        return any(_source_has_deliverable_media(value) for value in source.values())
    if not isinstance(source, list):
        return False
    for item in source:
        if not isinstance(item, dict):
            continue
        media_type = str(item.get("asset_type") or item.get("type") or item.get("media_type") or "").lower()
        has_asset_id = bool(item.get("asset_id") or item.get("id"))
        has_url = bool(
            item.get("asset_url")
            or item.get("url")
            or item.get("oss_url")
            or item.get("signed_url")
            or item.get("media_url")
            or item.get("thumbnail_url")
        )
        if has_url and (has_asset_id or media_type in {"image", "video", "picture", "photo"} or media_type.endswith("_image") or media_type.endswith("_video")):
            return True
    return False


def _contains_any(text: str, terms: tuple[str, ...]) -> bool:
    return any(term in str(text or "") for term in terms)


def _covered_reply_topics(reply: str) -> set[str]:
    return {
        fact_type
        for fact_type in _FACT_REPLY_CUES
        if _has_topic(reply, fact_type)
    }


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
    off_topic = bool(details.get("off_topic", any(issue.startswith("off_topic") for issue in normalized_issues)))
    missing_answer = bool(details.get("missing_answer", any(issue.startswith("missing_answer") for issue in normalized_issues)))
    unsupported_claim = bool(details.get("unsupported_claim", any("unsupported" in issue for issue in normalized_issues)))
    unsafe_claim = bool(details.get("unsafe_claim", any(issue.startswith("unsafe_claim") for issue in normalized_issues)))
    if "rewrite_instruction" in details:
        rewrite_instruction = str(details.get("rewrite_instruction") or "")
    else:
        rewrite_instruction = "Use selected evidence only and answer the current user query." if not passed else ""
    risk_level = str(details.get("risk_level") or ("low" if passed else "medium")).lower()
    if risk_level not in {"low", "medium", "high"}:
        risk_level = "low" if passed else "medium"
    result = {
        "checked": True,
        "pass": bool(passed),
        "passed": bool(passed),
        "score": score,
        "semantic_mismatch": bool(details.get("semantic_mismatch", off_topic or missing_answer)),
        "risk_level": risk_level,
        "requires_human_review": bool(details.get("requires_human_review", False)),
        "off_topic": off_topic,
        "missing_answer": missing_answer,
        "unsupported_claim": unsupported_claim,
        "unsafe_claim": unsafe_claim,
        "internal_language_leak": bool(details.get("internal_language_leak", any(issue.startswith("internal_language_leak") for issue in normalized_issues))),
        "product_name_leak": bool(details.get("product_name_leak", any(issue.startswith("product_name_leak") for issue in normalized_issues))),
        "should_retry": bool(details.get("should_retry", not passed)),
        "failure_reason": reason if not passed else "",
        "rewrite_instruction": rewrite_instruction,
        "issues": normalized_issues,
        "reason": reason,
        "mode": mode,
    }
    for key in ("llm_judge_fallback", "llm_error", "llm_judge_schema_version"):
        if key in details:
            result[key] = details[key]
    return result
