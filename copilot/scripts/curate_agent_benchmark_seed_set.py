"""Curate a small reviewed Agent benchmark seed set from existing candidates.

This script is intentionally conservative. It creates reviewed benchmark
answers only for scenarios where the sidecar context exists and the expected
answer can be framed without inventing concrete product facts.
"""

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
from app.services.agent_benchmark_dataset_service import AgentBenchmarkDatasetService, expected_reply_quality
from app.services.eval_sanitizer_service import sanitize_obj, sanitize_text


REVIEWER = "codex_seed_curator"
REVIEW_NOTE = "seed benchmark curated from real replay"

CONCRETE_FACT_TYPES = {
    "dimensions",
    "gross_weight",
    "load_capacity",
    "material",
    "certification_report",
    "accessory_availability",
}
SUPPORTED_SCENARIO_TYPES = {"installation", "promotion", "aftersales", "logistics", "presales"}
INSTALLATION_SENDABLE_ASSET_TYPES = {
    "install_video",
    "installation_video",
    "video",
    "install_image",
    "installation_guide",
    "manual",
    "manual_image",
    "pack_guide_image",
}
INSTALLATION_SENDABLE_ROLES = {
    "installation_video",
    "install_video",
    "installation_diagram",
    "install_image",
    "installation_guide",
    "manual",
    "manual_image",
    "pack_guide_image",
}
ORDER_BACKEND_FACT_TYPES = {"refund_status", "order_status", "delivery_tracking"}
ORDER_BACKEND_TEXT_TERMS = (
    "退款",
    "退了",
    "到账",
    "打款",
    "支付宝",
    "发货",
    "物流",
    "签收",
)
UNCLEAR_TEXT_TERMS = ("这个", "这个呢", "这款", "可以吗", "有吗")
FORBIDDEN_NUMERIC_CHARS = set("0123456789０１２３４５６７８９")


def _has_main_sidecar(sidecar: dict[str, Any]) -> bool:
    return bool(
        sanitize_text(sidecar.get("product_title") or sidecar.get("product_name"))
        or sanitize_text(sidecar.get("sku_code"))
        or sanitize_text(sidecar.get("i_id"))
        or sanitize_text(sidecar.get("order_id") or sidecar.get("platform_order_id"))
    )


def _query_fact_type(item: dict[str, Any]) -> str:
    metadata = item.get("metadata") or {}
    expected = item.get("expected_reply") or {}
    return sanitize_text(metadata.get("query_fact_type") or expected.get("query_fact_type") or item.get("scenario_type"))


def _conversation_text(item: dict[str, Any]) -> str:
    parts: list[str] = []
    for turn in item.get("conversation_turns") or []:
        if isinstance(turn, dict):
            text = sanitize_text(turn.get("text") or turn.get("message"))
            if text:
                parts.append(text)
    return "\n".join(parts)


def _iter_candidate_assets(item: dict[str, Any]) -> list[dict[str, Any]]:
    assets: list[dict[str, Any]] = []
    containers = [
        item,
        item.get("metadata") or {},
        item.get("answer_trace") or {},
        (item.get("metadata") or {}).get("answer_trace") or {},
    ]
    for container in containers:
        if not isinstance(container, dict):
            continue
        for key in ("recommended_assets", "product_media_assets", "media_assets"):
            value = container.get(key)
            if isinstance(value, list):
                assets.extend(asset for asset in value if isinstance(asset, dict))
        pack = container.get("product_first_evidence_pack") or container.get("product_context_pack") or {}
        if isinstance(pack, dict):
            value = pack.get("product_media_assets")
            if isinstance(value, list):
                assets.extend(asset for asset in value if isinstance(asset, dict))
    return assets


def _is_approved_usable_auto_asset(asset: dict[str, Any]) -> bool:
    status_values = {
        sanitize_text(asset.get("status")).lower(),
        sanitize_text(asset.get("review_status")).lower(),
        sanitize_text(asset.get("approval_status")).lower(),
        sanitize_text(asset.get("verification_status")).lower(),
    }
    if status_values & {"rejected", "disabled", "expired", "superseded"}:
        return False
    approved = (
        asset.get("approved") is True
        or asset.get("is_approved") is True
        or asset.get("usable") is True
        or asset.get("is_usable") is True
        or bool(status_values & {"approved", "usable", "verified", "active"})
    )
    auto_send_level = sanitize_text(asset.get("auto_send_level") or asset.get("send_level")).lower()
    auto = asset.get("auto_send") is True or auto_send_level in {"auto", "auto_when_platform_connected"}
    return bool(approved and auto)


def _has_sendable_installation_asset(item: dict[str, Any]) -> bool:
    for asset in _iter_candidate_assets(item):
        if not _is_approved_usable_auto_asset(asset):
            continue
        asset_type = sanitize_text(asset.get("asset_type") or asset.get("type")).lower()
        role = sanitize_text(
            asset.get("media_role")
            or asset.get("asset_role")
            or asset.get("evidence_role")
            or asset.get("purpose")
        ).lower()
        if asset_type in INSTALLATION_SENDABLE_ASSET_TYPES or role in INSTALLATION_SENDABLE_ROLES:
            return True
    return False


def _too_unclear_for_seed(item: dict[str, Any]) -> bool:
    text = sanitize_text(_conversation_text(item))
    compact = "".join(text.split())
    if len(compact) <= 4:
        return True
    return compact in UNCLEAR_TEXT_TERMS


def _requires_order_backend_state(item: dict[str, Any]) -> bool:
    scenario_type = sanitize_text(item.get("scenario_type"))
    qft = _query_fact_type(item)
    if scenario_type not in {"aftersales", "logistics"} and qft not in {
        "aftersales",
        "aftersales_policy",
        "logistics",
        "delivery_not_received",
    }:
        return False
    text = _conversation_text(item)
    return any(term in text for term in ORDER_BACKEND_TEXT_TERMS)


def _base_rubric(item: dict[str, Any], expected: dict[str, Any]) -> dict[str, Any]:
    return sanitize_obj({
        "seed_curated": True,
        "scenario_type": item.get("scenario_type"),
        "query_fact_type": _query_fact_type(item),
        "key_points": expected.get("key_points") or [],
        "forbidden_claims": expected.get("forbidden_claims") or [],
        "must_handoff": bool(expected.get("must_handoff")),
        "auto_send_allowed": bool(expected.get("auto_send_allowed")),
        "reviewer": REVIEWER,
        "review_note": REVIEW_NOTE,
    })


def _installation_expected_for_item(item: dict[str, Any]) -> dict[str, Any]:
    if not _has_sendable_installation_asset(item):
        return {
            "expected_reply": (
                "亲，我先帮您按当前这款商品的安装资料核对。"
                "现在没有确认到可直接发送的安装视频、安装图或说明书，"
                "我不直接承诺有安装视频；您卡在哪一步可以拍照发来，"
                "我这边转人工按这款结构帮您确认。"
            ),
            "key_points": [
                "按当前这款商品",
                "不直接承诺有安装视频",
                "转人工",
            ],
            "forbidden_claims": [
                "一定有安装视频",
                "通用安装方式都适用",
                "随便装",
            ],
            "must_handoff": True,
            "auto_send_allowed": False,
        }
    return {
        "expected_reply": (
            "亲，我先按当前这款商品帮您核对安装资料。"
            "如果资料里只有安装图或步骤说明，就不能直接承诺有安装视频；"
            "可以先把可发送的安装示意图或说明书发您参考。"
            "您按图纸装的时候如果卡在哪一步，可以把当前位置和配件拍照发来继续核对。"
        ),
        "key_points": ["按当前这款商品", "不直接承诺有安装视频", "安装图或说明书"],
        "forbidden_claims": ["一定有安装视频", "通用安装方式都适用", "随便装"],
        "must_handoff": False,
        "auto_send_allowed": True,
    }


def _seed_expected_for_item(item: dict[str, Any]) -> dict[str, Any]:
    scenario_type = sanitize_text(item.get("scenario_type"))
    qft = _query_fact_type(item)
    if scenario_type == "installation" or qft in {"installation", "accessory_usage", "accessory_compatibility"}:
        return _installation_expected_for_item(item)
    if scenario_type == "promotion" or qft in {"promotion", "promotion_policy", "price_negotiation", "coupon", "discount"}:
        return {
            "expected_reply": (
                "亲，优惠需要按当前商品和下单页正在生效的活动核对。"
                "我不能直接承诺额外降价或最低价，您可以把下单页优惠截图发来，"
                "我这边转人工帮您确认能用的券、满减或活动口径。"
            ),
            "key_points": ["按当前商品", "下单页", "不能直接承诺额外降价", "转人工"],
            "forbidden_claims": ["保证最低价", "一定能便宜", "额外优惠"],
            "must_handoff": True,
            "auto_send_allowed": False,
        }
    if scenario_type == "aftersales" or qft in {"aftersales", "aftersales_policy", "after_sales"}:
        return {
            "expected_reply": (
                "亲，先别着急，我帮您按当前订单和问题情况核实。"
                "麻烦您补充订单信息、问题位置和实物照片，"
                "我这边转人工确认后再给您处理补发、换货或退款方案。"
            ),
            "key_points": ["先别着急", "订单信息", "实物照片", "转人工"],
            "forbidden_claims": ["直接补发", "直接退款", "一定赔付"],
            "must_handoff": True,
            "auto_send_allowed": False,
        }
    if scenario_type == "logistics" or qft in {"logistics", "delivery_not_received"}:
        return {
            "expected_reply": (
                "亲，我先帮您按当前订单的物流信息核对。"
                "如果页面显示异常、已签收未收到或需要确认送货服务，"
                "我这边会转人工结合订单记录和物流轨迹继续处理。"
            ),
            "key_points": ["当前订单", "物流信息", "转人工"],
            "forbidden_claims": ["一定今天送到", "已经丢件", "保证上门"],
            "must_handoff": True,
            "auto_send_allowed": False,
        }
    return {
        "expected_reply": (
            "亲，这个问题我会先按当前商品资料帮您核对。"
            "如果资料里没有明确证据，我不会直接编具体结论，"
            "会转人工根据商品信息和您的使用场景确认后再回复。"
        ),
        "key_points": ["当前商品资料", "没有明确证据不编结论", "转人工"],
        "forbidden_claims": ["绝对安全", "保证适用", "具体数值"],
        "must_handoff": True,
        "auto_send_allowed": False,
    }


def _contains_numeric_fact(reply: str) -> bool:
    return any(char in FORBIDDEN_NUMERIC_CHARS for char in sanitize_text(reply))


def evaluate_seed_candidate(item: dict[str, Any]) -> dict[str, Any]:
    sidecar = item.get("sidecar_context") or {}
    scenario_type = sanitize_text(item.get("scenario_type"))
    qft = _query_fact_type(item)
    if not _has_main_sidecar(sidecar):
        return {"selected": False, "reason": "missing_sidecar_context"}
    if scenario_type not in SUPPORTED_SCENARIO_TYPES:
        return {"selected": False, "reason": "unsupported_scenario_type"}
    if qft in CONCRETE_FACT_TYPES:
        return {"selected": False, "reason": "specific_product_fact_requires_verified_evidence"}
    if qft in ORDER_BACKEND_FACT_TYPES:
        return {"selected": False, "reason": "order_backend_state_required"}
    if _requires_order_backend_state(item):
        return {"selected": False, "reason": "order_backend_state_required"}
    if _too_unclear_for_seed(item):
        return {"selected": False, "reason": "unclear_or_too_short_context"}

    expected = _seed_expected_for_item(item)
    quality = expected_reply_quality(expected["expected_reply"])
    if quality.get("quality") != "valid":
        return {"selected": False, "reason": quality.get("block_reason") or "expected_reply_low_quality"}
    if _contains_numeric_fact(expected["expected_reply"]):
        return {"selected": False, "reason": "generated_reply_contains_numeric_fact"}
    return {
        "selected": True,
        "reason": "seed_candidate_selected",
        "expected": expected,
        "rubric": _base_rubric(item, expected),
    }


def build_seed_expected_for_item(item: dict[str, Any]) -> dict[str, Any]:
    expected = _seed_expected_for_item(item)
    is_installation = (
        sanitize_text(item.get("scenario_type")) == "installation"
        or _query_fact_type(item) in {"installation", "accessory_usage", "accessory_compatibility"}
    )
    reason = "seed_rubric_recalculated"
    if is_installation:
        reason = (
            "installation_sendable_asset_available"
            if bool(expected.get("auto_send_allowed"))
            else "installation_sendable_asset_missing"
        )
    return sanitize_obj({
        "expected": expected,
        "rubric": _base_rubric(item, expected),
        "reason": reason,
    })


def _write_json(path: str, payload: dict[str, Any]) -> None:
    if not path:
        return
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(sanitize_obj(payload), ensure_ascii=False, indent=2), encoding="utf-8")


def _write_excel(path: str, items: list[dict[str, Any]]) -> None:
    if not path:
        return
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "种子集草案"
    sheet.append([
        "scenario_uid",
        "是否选入",
        "跳过原因",
        "场景类型",
        "问题类型",
        "商品上下文",
        "客户对话",
        "种子标准答案",
        "关键点",
        "禁止话术",
        "必须转人工",
        "允许自动发送",
    ])
    for item in items:
        source = item.get("scenario") or {}
        sidecar = source.get("sidecar_context") or {}
        expected = item.get("expected") or {}
        sheet.append([
            source.get("scenario_uid") or item.get("scenario_uid") or "",
            "是" if item.get("selected") else "否",
            item.get("reason") or "",
            source.get("scenario_type") or "",
            _query_fact_type(source),
            sidecar.get("product_title") or sidecar.get("product_name") or sidecar.get("sku_code") or sidecar.get("i_id") or "",
            _conversation_text(source),
            expected.get("expected_reply") or "",
            "\n".join(expected.get("key_points") or []),
            "\n".join(expected.get("forbidden_claims") or []),
            bool(expected.get("must_handoff")),
            bool(expected.get("auto_send_allowed")),
        ])
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    workbook.save(target)


def curate_seed_set(
    status: str = "candidate",
    scenario_type: str = "",
    limit: int | None = 5,
    apply_reviewed: bool = False,
    promote_active: bool = False,
    json_output: str = "",
    excel_output: str = "",
    db_factory=None,
) -> dict[str, Any]:
    service = AgentBenchmarkDatasetService()
    source = service.list_scenarios({"status": status, "scenario_type": scenario_type}, db_factory=db_factory)
    selected: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    decorated: list[dict[str, Any]] = []
    applied_reviewed: list[str] = []
    would_review: list[str] = []
    promoted: list[str] = []
    would_promote: list[str] = []
    errors: list[dict[str, str]] = []

    max_selected = max(int(limit or 0), 0) if limit is not None else 0
    for item in source.get("items", []):
        scenario_uid = sanitize_text(item.get("scenario_uid"))
        evaluation = evaluate_seed_candidate(item)
        record = sanitize_obj({
            "scenario_uid": scenario_uid,
            "selected": bool(evaluation.get("selected")),
            "reason": evaluation.get("reason"),
            "scenario": item,
            "expected": evaluation.get("expected") or {},
            "rubric": evaluation.get("rubric") or {},
        })
        if not evaluation.get("selected"):
            skipped.append({"scenario_uid": scenario_uid, "reason": sanitize_text(evaluation.get("reason"))})
            decorated.append(record)
            continue
        if max_selected and len(selected) >= max_selected:
            skipped.append({"scenario_uid": scenario_uid, "reason": "seed_limit_reached"})
            record["selected"] = False
            record["reason"] = "seed_limit_reached"
            decorated.append(record)
            continue

        selected.append(record)
        decorated.append(record)
        expected = evaluation["expected"]
        if apply_reviewed:
            try:
                service.mark_expected_reply_reviewed(
                    scenario_uid,
                    reviewer=REVIEWER,
                    expected_reply=expected["expected_reply"],
                    key_points=expected.get("key_points") or [],
                    forbidden_claims=expected.get("forbidden_claims") or [],
                    auto_send_allowed=bool(expected.get("auto_send_allowed")),
                    must_handoff=bool(expected.get("must_handoff")),
                    review_note=REVIEW_NOTE,
                    db_factory=db_factory,
                )
                applied_reviewed.append(scenario_uid)
            except Exception as exc:  # pragma: no cover - surfaced in result for CLI use
                errors.append({"scenario_uid": scenario_uid, "reason": sanitize_text(str(exc))})
                continue
            if promote_active:
                try:
                    service.promote_to_active(scenario_uid, reviewer=REVIEWER, db_factory=db_factory)
                    promoted.append(scenario_uid)
                except Exception as exc:
                    errors.append({"scenario_uid": scenario_uid, "reason": sanitize_text(str(exc))})
        else:
            would_review.append(scenario_uid)
            if promote_active:
                eligibility = service.validate_active_eligibility(
                    scenario_uid,
                    reviewer=REVIEWER,
                    expected_reply_override=expected["expected_reply"],
                    db_factory=db_factory,
                )
                if eligibility.get("eligible"):
                    would_promote.append(scenario_uid)
                else:
                    errors.append({"scenario_uid": scenario_uid, "reason": sanitize_text(eligibility.get("reason"))})

    reason_counts: dict[str, int] = {}
    for item in skipped:
        reason = item.get("reason") or "unknown"
        reason_counts[reason] = reason_counts.get(reason, 0) + 1

    payload = sanitize_obj({
        "status": status,
        "scenario_type": scenario_type,
        "dry_run": not bool(apply_reviewed),
        "apply_reviewed": bool(apply_reviewed),
        "promote_active": bool(promote_active),
        "source_total": source.get("total", 0),
        "selected_count": len(selected),
        "skipped_count": len(skipped),
        "reviewed_count": len(applied_reviewed),
        "would_review_count": len(would_review),
        "promoted_count": len(promoted),
        "would_promote_count": len(would_promote),
        "selected_scenario_uids": [item["scenario_uid"] for item in selected],
        "reviewed_scenario_uids": applied_reviewed,
        "would_review_scenario_uids": would_review,
        "promoted_scenario_uids": promoted,
        "would_promote_scenario_uids": would_promote,
        "skipped": skipped,
        "skip_reason_counts": reason_counts,
        "errors": errors,
        "items": decorated,
    })
    _write_json(json_output, payload)
    _write_excel(excel_output, decorated)
    return payload


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Curate a conservative active Agent benchmark seed set.")
    parser.add_argument("--status", default="candidate")
    parser.add_argument("--scenario-type", default="")
    parser.add_argument("--limit", type=int, default=5)
    parser.add_argument("--apply-reviewed", action="store_true")
    parser.add_argument("--promote-active", action="store_true")
    parser.add_argument("--json-output", default="")
    parser.add_argument("--excel-output", default="")
    args = parser.parse_args(argv)

    init_db()
    result = curate_seed_set(
        status=args.status,
        scenario_type=args.scenario_type,
        limit=args.limit,
        apply_reviewed=bool(args.apply_reviewed),
        promote_active=bool(args.promote_active),
        json_output=args.json_output,
        excel_output=args.excel_output,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
