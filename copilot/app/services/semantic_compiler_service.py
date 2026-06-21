"""Final semantic compiler for customer-facing replies.

The compiler is a deterministic final gate. It validates the final text, uses
validated answer blocks to re-render blocked drafts, and falls back to a
controlled human-review reply when no safe block can answer the question.
"""

from __future__ import annotations

from typing import Any

from app.services.answer_blocks_service import (
    build_answer_blocks,
    raw_field_leakage_issues,
    validate_customer_text,
)
from app.services.customer_answer_renderer import controlled_fallback_reply, render_customer_answer
from app.services.generic_service_rule_service import unsafe_promise_terms


_INTERNAL_TEXT_TERMS = (
    "fact_type",
    "query_fact_type",
    "evidence_debug",
    "RAG",
    "知识库",
    "系统检索",
)

_MEDIA_SEND_CLAIMS = ("下面发", "发图给您", "发图片给您", "发视频给您", "视频发您", "图片发您")

_FACT_CUES = {
    "dimensions": ("尺寸", "大小", "长宽高", "高度", "宽度", "长度", "cm", "厘米", "预留空间"),
    "load_capacity": ("承重", "载重", "重一点", "均匀摆放", "放书", "放绘本", "压塌", "压弯", "更稳"),
    "stability": ("稳", "晃", "倒", "倾倒", "平整", "下层", "均匀摆放", "更稳"),
    "space_fit": ("放得下", "空间", "预留", "占地", "长宽高", "宽度", "深度"),
    "placement_scene": ("卧室", "客厅", "书房", "摆放", "干燥", "通风", "平整"),
    "material": ("材质", "材料", "用料", "PP", "钢管", "防潮", "安全", "通风"),
    "certification_report": ("检测报告", "证书", "报告素材", "检测结论", "页面展示"),
    "installation": ("安装", "组装", "说明书", "配件", "卡扣", "螺丝", "视频"),
    "visual_asset": ("图片", "图", "照片", "视频", "素材", "截图"),
    "stock_shipping": ("发货", "库存", "仓库", "下单页", "今天"),
}

_CONFLICTS = {
    "dimensions": {"load_capacity", "material", "installation"},
    "space_fit": {"load_capacity", "material", "installation"},
    "placement_scene": {"load_capacity", "dimensions"},
    "certification_report": {"load_capacity", "dimensions", "installation"},
    "installation": {"load_capacity", "material"},
    "visual_asset": {"load_capacity", "material"},
    "age_range": {"load_capacity", "dimensions", "installation"},
    "material": {"load_capacity", "installation"},
}


def compile_customer_response(
    response: dict[str, Any],
    *,
    customer_message: str = "",
    copilot_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Validate and, when necessary, re-render the final customer reply."""
    original_reply = str(response.get("suggested_reply") or "")
    block_result = build_answer_blocks(response, customer_message=customer_message)
    blocks = block_result.get("answer_blocks", [])
    initial = semantic_compiler_issues(
        original_reply,
        response=response,
        customer_message=customer_message,
    )
    compiler_result: dict[str, Any] = {
        "deterministic_gate": True,
        "passed": not initial,
        "issues": initial,
        "renderer_used": False,
        "blocked_raw_text": original_reply if initial else "",
        "reject_reason": initial,
        "answer_blocks_count": len(blocks),
        "final_text_passed": not initial,
    }

    if initial:
        rendered = render_customer_answer(blocks, customer_message=customer_message)
        rendered_text = str(rendered.get("rendered_text") or "")
        rendered_issues = semantic_compiler_issues(
            rendered_text,
            response=response,
            customer_message=customer_message,
            answer_blocks=blocks,
        )
        if rendered.get("passed") and not rendered_issues:
            response["suggested_reply"] = rendered_text
            compiler_result.update({
                "passed": True,
                "issues": [],
                "renderer_used": True,
                "render_result": rendered,
                "reject_reason": [],
                "final_text_passed": True,
            })
        else:
            response["suggested_reply"] = controlled_fallback_reply(reason="semantic_compiler_blocked")
            response["requires_human_review"] = True
            response["generation_mode"] = "semantic_compiler_fallback"
            compiler_result.update({
                "passed": False,
                "renderer_used": bool(rendered.get("renderer_used")),
                "render_result": rendered,
                "rendered_issues": rendered_issues,
                "final_fallback_used": True,
                "final_text_passed": False,
            })
            response.setdefault("guard_warnings", []).append(
                "semantic_compiler: " + ",".join(initial or rendered_issues)
            )
    else:
        compiler_result["render_result"] = {"renderer_used": False, "reason": "original_reply_passed"}

    response["semantic_compiler_result"] = compiler_result
    response["final_quality_pass"] = bool(compiler_result.get("passed") or response.get("requires_human_review"))
    debug = response.setdefault("evidence_debug", {})
    debug["semantic_compiler_result"] = compiler_result
    debug["final_quality_pass"] = response["final_quality_pass"]
    return response


def semantic_compiler_issues(
    final_text: str,
    *,
    response: dict[str, Any],
    customer_message: str = "",
    answer_blocks: list[dict[str, Any]] | None = None,
) -> list[str]:
    text = str(final_text or "").strip()
    issues: list[str] = []
    issues.extend(validate_customer_text(text))
    issues.extend(raw_field_leakage_issues(text))
    leaked = [term for term in _INTERNAL_TEXT_TERMS if term.lower() in text.lower()]
    if leaked:
        issues.append("internal_text_leak:" + ",".join(leaked[:3]))
    unsafe = unsafe_promise_terms(text)
    if unsafe:
        issues.append("unsafe_promise:" + ",".join(unsafe[:3]))
    issues.extend(_semantic_fit_issues(text, response=response, customer_message=customer_message))
    issues.extend(_unsupported_media_issues(text, response=response))
    return _ordered_unique(issues)


def validate_final_output_contract(
    response: dict[str, Any],
    *,
    customer_message: str = "",
) -> dict[str, Any]:
    """Run the final deterministic text contract after all downstream rewrites.

    This is intentionally narrower than compile_customer_response: it does not
    rebuild blocks or call an LLM. It verifies the actual text that will be
    returned to the frontend and replaces unsafe text with a controlled fallback.
    """
    final_text = str(response.get("suggested_reply") or "")
    issues = semantic_compiler_issues(
        final_text,
        response=response,
        customer_message=customer_message,
    )
    result = {
        "passed": not issues,
        "issues": issues,
        "checked_text_length": len(final_text),
    }
    compiler = response.setdefault("semantic_compiler_result", {})
    if not isinstance(compiler, dict):
        compiler = {}
        response["semantic_compiler_result"] = compiler
    compiler["deterministic_gate"] = True
    compiler["post_compiler_validation"] = result
    if issues:
        previous_blocked = str(compiler.get("blocked_raw_text") or "")
        if not previous_blocked:
            compiler["blocked_raw_text"] = final_text
        response["suggested_reply"] = controlled_fallback_reply(reason="final_output_contract")
        response["requires_human_review"] = True
        response["generation_mode"] = "final_output_contract_fallback"
        response.setdefault("guard_warnings", []).append(
            "final_output_contract: " + ",".join(issues)
        )
        fallback_issues = semantic_compiler_issues(
            str(response.get("suggested_reply") or ""),
            response=response,
            customer_message=customer_message,
        )
        result["fallback_used"] = True
        result["fallback_issues"] = fallback_issues
        compiler["final_text_passed"] = not fallback_issues
        compiler["passed"] = not fallback_issues
        compiler["issues"] = fallback_issues
        compiler["reject_reason"] = fallback_issues
    else:
        compiler["final_text_passed"] = True
        compiler["passed"] = True
        compiler["issues"] = []
        compiler["reject_reason"] = []
    response["final_quality_pass"] = bool(compiler.get("final_text_passed"))
    debug = response.setdefault("evidence_debug", {})
    debug["semantic_compiler_result"] = compiler
    debug["final_quality_pass"] = response["final_quality_pass"]
    return response


def _semantic_fit_issues(
    text: str,
    *,
    response: dict[str, Any],
    customer_message: str,
) -> list[str]:
    query_fact_type = _query_fact_type(response)
    required = _required_fact_types(response)
    effective = required or ([query_fact_type] if query_fact_type else [])
    issues: list[str] = []
    for fact_type in effective:
        if fact_type and fact_type in _FACT_CUES and not _mentions_fact_type(text, fact_type):
            if not _acceptable_followup(text):
                issues.append(f"missing_answer:{fact_type}")
    if query_fact_type:
        conflicts = _CONFLICTS.get(query_fact_type, set())
        hits = [fact_type for fact_type in conflicts if _mentions_fact_type(text, fact_type)]
        if hits and not _mentions_fact_type(text, query_fact_type):
            issues.append(f"off_topic:{query_fact_type}_answered_as_{','.join(sorted(hits))}")
    if query_fact_type in {"stability", "load_capacity"}:
        if raw_field_leakage_issues(text):
            issues.append("stability_answer_is_raw_field")
        if not any(cue in text for cue in ("适合", "建议", "下层", "均匀", "更稳", "平整")):
            issues.append("stability_answer_not_customer_facing")
    if query_fact_type == "certification_report":
        if _mentions_fact_type(text, "material") and not _mentions_fact_type(text, "certification_report"):
            issues.append("off_topic:certification_report_answered_as_material")
        if any(claim in text for claim in ("有检测报告", "已通过检测", "检测合格", "有认证", "有证书")):
            if not _has_certification_evidence(response):
                issues.append("unsupported_certification_claim")
    return issues


def _unsupported_media_issues(text: str, *, response: dict[str, Any]) -> list[str]:
    if not any(claim in text for claim in _MEDIA_SEND_CLAIMS):
        return []
    if _has_sendable_asset(response):
        return []
    return ["unsupported_media_send_claim"]


def _query_fact_type(response: dict[str, Any]) -> str:
    debug = response.get("evidence_debug") or {}
    trace = response.get("answer_trace") or debug.get("answer_trace") or {}
    for container in (trace, response, debug):
        if isinstance(container, dict):
            value = str(container.get("query_fact_type") or "").strip()
            if value:
                return value
    return ""


def _required_fact_types(response: dict[str, Any]) -> list[str]:
    debug = response.get("evidence_debug") or {}
    trace = response.get("answer_trace") or debug.get("answer_trace") or {}
    composition = response.get("answer_composition_trace") or debug.get("answer_composition_trace") or {}
    grouping = response.get("evidence_grouping") or debug.get("evidence_grouping") or {}
    coverage = grouping.get("coverage") if isinstance(grouping, dict) else {}
    values: list[Any] = []
    for container in (trace, composition, coverage, response, debug):
        if isinstance(container, dict):
            values.extend(container.get("required_fact_types") or [])
    values.append(_query_fact_type(response))
    return _ordered_unique(values)


def _mentions_fact_type(text: str, fact_type: str) -> bool:
    cues = _FACT_CUES.get(fact_type, ())
    return any(cue and cue in text for cue in cues)


def _acceptable_followup(text: str) -> bool:
    return any(cue in text for cue in ("核对", "确认", "页面", "截图", "人工", "报告素材"))


def _has_sendable_asset(response: dict[str, Any]) -> bool:
    debug = response.get("evidence_debug") or {}
    for item in [
        *(response.get("selected_assets") or []),
        *(response.get("recommended_assets") or []),
        *(debug.get("selected_assets") or []),
    ]:
        if not isinstance(item, dict):
            continue
        if item.get("asset_id") or item.get("id") or item.get("url") or item.get("asset_url") or item.get("media_url"):
            return True
    return False


def _has_certification_evidence(response: dict[str, Any]) -> bool:
    debug = response.get("evidence_debug") or {}
    trace = response.get("answer_trace") or debug.get("answer_trace") or {}
    for container in (trace, response, debug):
        if not isinstance(container, dict):
            continue
        for key in ("rag_evidence_used", "media_evidence_used", "asset_evidence_used", "evidence_used_by_fact_type"):
            value = container.get(key)
            if isinstance(value, dict) and value.get("certification_report"):
                return True
    for item in [
        *(response.get("selected_assets") or []),
        *(debug.get("selected_assets") or []),
    ]:
        if not isinstance(item, dict):
            continue
        if str(item.get("asset_type") or "").lower() == "certificate_image":
            return True
    for item in [
        *(debug.get("selected_evidence") or []),
        *(response.get("selected_evidence") or []),
    ]:
        if not isinstance(item, dict):
            continue
        fact_type = str(item.get("evidence_fact_type") or item.get("fact_type") or "")
        text = " ".join(str(item.get(key) or "") for key in ("fact", "chunk_text", "content", "title"))
        if fact_type == "certification_report" and any(
            term in text for term in ("检测报告", "质检报告", "检验报告", "合格证", "认证", "证书", "报告编号", "检测结论")
        ):
            return True
    return False


def _ordered_unique(values: list[Any]) -> list[str]:
    out: list[str] = []
    for value in values or []:
        text = str(value or "").strip()
        if text and text not in out:
            out.append(text)
    return out
