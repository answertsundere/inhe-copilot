"""Suggest review-only expected replies for Agent benchmark candidates."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from openpyxl import Workbook

from app.db import init_db
from app.models.eval_tables import AgentBenchmarkScenario  # noqa: F401 - register table before init_db
from app.services.agent_benchmark_dataset_service import (
    AgentBenchmarkDatasetService,
    expected_reply_quality,
    is_low_quality_reference_reply,
)
from app.services.eval_sanitizer_service import sanitize_obj, sanitize_text


HEADERS = [
    "scenario_uid",
    "状态",
    "场景类型",
    "问题类型",
    "千牛侧栏商品",
    "客户完整对话",
    "客服原始回复参考",
    "建议标准答案草稿",
    "关键点",
    "禁止话术",
    "必须转人工",
    "允许自动发送",
    "草稿原因",
]


def _join_turns(turns: list[dict[str, Any]]) -> str:
    lines = []
    for turn in turns or []:
        speaker = sanitize_text(turn.get("speaker"))
        text = sanitize_text(turn.get("text") or turn.get("message"))
        if text:
            lines.append(f"{speaker or 'unknown'}: {text}")
    return "\n".join(lines)


def _has_sidecar(sidecar: dict[str, Any]) -> bool:
    return bool(
        sanitize_text(sidecar.get("product_title") or sidecar.get("product_name"))
        or sanitize_text(sidecar.get("sku_code"))
        or sanitize_text(sidecar.get("i_id"))
        or sanitize_text(sidecar.get("order_id") or sidecar.get("platform_order_id"))
    )


def _is_generic_reference(text: str) -> bool:
    value = sanitize_text(text).lower()
    if not value:
        return True
    generic_terms = (
        "welcome to our shop",
        "how can i help",
        "please wait",
        "one moment",
        "ok",
        "sure",
        "欢迎光临",
        "看中哪些宝贝",
        "我可以帮您介绍",
        "稍等",
        "好的亲",
        "在的",
    )
    return any(term in value for term in generic_terms)


def _query_fact_type(item: dict[str, Any]) -> str:
    metadata = item.get("metadata") or {}
    expected = item.get("expected_reply") or {}
    return sanitize_text(
        metadata.get("query_fact_type")
        or expected.get("query_fact_type")
        or item.get("scenario_type")
        or ""
    )


def _suggestion_for_item(item: dict[str, Any]) -> dict[str, Any]:
    sidecar = item.get("sidecar_context") or {}
    expected = item.get("expected_reply") or {}
    metadata = item.get("metadata") or {}
    existing = sanitize_text(expected.get("expected_reply"))
    if existing and not _is_generic_reference(existing) and expected_reply_quality(existing).get("quality") == "valid":
        return sanitize_obj({
            "scenario_uid": item.get("scenario_uid"),
            "suggested_expected_reply": existing,
            "key_points": expected.get("key_points") or [],
            "forbidden_claims": expected.get("forbidden_claims") or [],
            "must_handoff": bool(expected.get("must_handoff")),
            "auto_send_allowed": bool(expected.get("auto_send_allowed")),
            "draft_reason": "existing_valid_expected_reply",
            "can_apply_draft": True,
        })

    if not _has_sidecar(sidecar):
        return sanitize_obj({
            "scenario_uid": item.get("scenario_uid"),
            "suggested_expected_reply": "",
            "key_points": ["补充商品或订单上下文"],
            "forbidden_claims": ["编造商品事实", "承诺具体数值"],
            "must_handoff": True,
            "auto_send_allowed": False,
            "draft_reason": "missing_sidecar_context_cannot_activate",
            "can_apply_draft": False,
        })

    reference = sanitize_text(metadata.get("original_cs_reply"))
    if (
        reference
        and not _is_generic_reference(reference)
        and not is_low_quality_reference_reply(reference)
        and expected_reply_quality(reference).get("quality") == "valid"
    ):
        return sanitize_obj({
            "scenario_uid": item.get("scenario_uid"),
            "suggested_expected_reply": reference,
            "key_points": [],
            "forbidden_claims": ["绝对安全", "0甲醛", "一定可以", "保证"],
            "must_handoff": True,
            "auto_send_allowed": False,
            "draft_reason": "usable_reference_reply_needs_review",
            "can_apply_draft": True,
        })

    scenario_type = sanitize_text(item.get("scenario_type"))
    qft = _query_fact_type(item)
    if scenario_type == "installation" or qft in {"installation", "accessory_usage"}:
        reply = "先按这款商品对应的安装资料核对；如果只有安装图纸就不要承诺有视频，可请客户发当前位置照片后由人工确认下一步安装指引。"
        key_points = ["按这款商品核对安装资料", "无视频不承诺视频", "可让客户发当前位置照片"]
        forbidden = ["保证有视频", "直接说通用安装方式适用"]
        must_handoff = True
    elif scenario_type == "promotion" or qft in {"promotion", "promotion_policy", "price_negotiation"}:
        reply = "优惠需要按当前商品和下单页活动核对，不承诺额外优惠；可引导客户查看店铺券、满减或活动页，并交由人工确认可用优惠。"
        key_points = ["按当前商品和下单页核对", "不承诺额外优惠", "人工确认可用优惠"]
        forbidden = ["承诺额外优惠", "保证最低价"]
        must_handoff = True
    elif scenario_type in {"aftersales", "logistics"} or qft in {"aftersales", "aftersales_policy", "delivery_not_received"}:
        reply = "先安抚客户，并请客户提供订单信息、实物照片和问题位置；售后方案需要人工核实后再确认补发、换货或退款处理。"
        key_points = ["安抚客户", "提供订单信息和问题照片", "人工核实售后方案"]
        forbidden = ["直接承诺补发", "直接承诺退款", "直接定责"]
        must_handoff = True
    elif qft in {"material", "dimensions", "load_capacity", "gross_weight", "certification_report", "accessory_availability"}:
        reply = "这个问题需要按当前商品资料核对后回复；没有明确字段证据时不要编造具体数值、检测结论或配件可售状态，应交由人工确认。"
        key_points = ["按当前商品资料核对", "无证据不编造具体事实", "人工确认后回复"]
        forbidden = ["编造尺寸", "编造重量", "编造检测报告", "绝对安全"]
        must_handoff = True
    else:
        reply = "先确认客户当前问题对应的商品和上下文；证据不足时不要做具体事实判断，应让人工根据商品资料和对话上下文核对后回复。"
        key_points = ["确认商品和上下文", "证据不足不做事实判断", "人工核对"]
        forbidden = ["编造商品事实", "承诺未核实结论"]
        must_handoff = True

    return sanitize_obj({
        "scenario_uid": item.get("scenario_uid"),
        "suggested_expected_reply": reply,
        "key_points": key_points,
        "forbidden_claims": forbidden,
        "must_handoff": must_handoff,
        "auto_send_allowed": False,
        "draft_reason": "deterministic_safe_review_draft",
        "can_apply_draft": True,
    })


def _write_json(path: str, payload: dict[str, Any]) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(sanitize_obj(payload), ensure_ascii=False, indent=2), encoding="utf-8")


def _write_excel(path: str, items: list[dict[str, Any]]) -> None:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "建议草稿"
    sheet.append(HEADERS)
    for item in items:
        sidecar = item.get("sidecar_context") or {}
        suggestion = item.get("suggestion") or {}
        metadata = item.get("metadata") or {}
        sheet.append([
            item.get("scenario_uid", ""),
            item.get("status", ""),
            item.get("scenario_type", ""),
            metadata.get("query_fact_type") or "",
            sidecar.get("product_title") or sidecar.get("product_name") or "",
            _join_turns(item.get("conversation_turns") or []),
            metadata.get("original_cs_reply") or "",
            suggestion.get("suggested_expected_reply") or "",
            "\n".join(suggestion.get("key_points") or []),
            "\n".join(suggestion.get("forbidden_claims") or []),
            bool(suggestion.get("must_handoff")),
            bool(suggestion.get("auto_send_allowed")),
            suggestion.get("draft_reason") or "",
        ])
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    workbook.save(target)


def suggest_expected_replies(
    status: str = "candidate",
    scenario_type: str = "",
    scenario_uids: list[str] | None = None,
    limit: int | None = None,
    apply_draft: bool = False,
    json_output: str = "",
    excel_output: str = "",
    db_factory=None,
) -> dict[str, Any]:
    service = AgentBenchmarkDatasetService()
    if scenario_uids:
        source_items = []
        for uid in scenario_uids:
            detail = service.get_scenario_detail(uid, db_factory=db_factory)
            if detail:
                source_items.append(detail)
    else:
        result = service.list_scenarios({"status": status, "scenario_type": scenario_type}, db_factory=db_factory)
        source_items = result.get("items", [])
    if limit:
        source_items = source_items[: max(int(limit), 1)]

    items: list[dict[str, Any]] = []
    applied: list[str] = []
    skipped: list[dict[str, str]] = []
    reason_counts: dict[str, int] = {}
    for item in source_items:
        suggestion = _suggestion_for_item(item)
        reason = sanitize_text(suggestion.get("draft_reason")) or "unknown"
        reason_counts[reason] = reason_counts.get(reason, 0) + 1
        decorated = sanitize_obj({**item, "suggestion": suggestion})
        items.append(decorated)
        if apply_draft:
            if not suggestion.get("can_apply_draft"):
                skipped.append({"scenario_uid": item.get("scenario_uid", ""), "reason": reason})
                continue
            service.update_expected_reply_draft(
                item.get("scenario_uid", ""),
                expected_reply=suggestion.get("suggested_expected_reply") or "",
                key_points=suggestion.get("key_points") or [],
                forbidden_claims=suggestion.get("forbidden_claims") or [],
                auto_send_allowed=bool(suggestion.get("auto_send_allowed")),
                must_handoff=bool(suggestion.get("must_handoff")),
                draft_reason=reason,
                db_factory=db_factory,
            )
            applied.append(item.get("scenario_uid", ""))

    payload = sanitize_obj({
        "status": status,
        "scenario_type": scenario_type,
        "apply_draft": bool(apply_draft),
        "total": len(items),
        "applied_count": len(applied),
        "skipped_count": len(skipped),
        "draft_reason_counts": reason_counts,
        "applied_scenario_uids": applied,
        "skipped": skipped,
        "items": items,
    })
    if json_output:
        _write_json(json_output, payload)
    if excel_output:
        _write_excel(excel_output, items)
    return payload


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Suggest review-only expected replies for Agent benchmark candidates.")
    parser.add_argument("--status", default="candidate")
    parser.add_argument("--scenario-type", default="")
    parser.add_argument("--scenario-uid", action="append", default=[])
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--apply-draft", action="store_true")
    parser.add_argument("--json-output", default="")
    parser.add_argument("--excel-output", default="")
    args = parser.parse_args(argv)

    init_db()
    result = suggest_expected_replies(
        status=args.status,
        scenario_type=args.scenario_type,
        scenario_uids=args.scenario_uid or None,
        limit=args.limit or None,
        apply_draft=bool(args.apply_draft),
        json_output=args.json_output,
        excel_output=args.excel_output,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
