"""Export Agent benchmark candidates for supervisor review."""

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


HEADERS = [
    "scenario_uid",
    "状态",
    "标题",
    "场景类型",
    "客户完整对话",
    "千牛侧栏商品",
    "千牛侧栏SKU",
    "千牛侧栏i_id",
    "千牛侧栏订单",
    "当前expected_reply",
    "expected_reply质量",
    "阻断原因",
    "关键点",
    "禁止话术",
    "必须转人工",
    "允许自动发送",
    "审核人",
    "审核备注",
    "来源",
]


def _join_turns(turns: list[dict[str, Any]]) -> str:
    lines = []
    for turn in turns or []:
        speaker = sanitize_text(turn.get("speaker"))
        text = sanitize_text(turn.get("text"))
        if text:
            lines.append(f"{speaker or 'unknown'}：{text}")
    return "\n".join(lines)


def _join_list(value: Any) -> str:
    if isinstance(value, list):
        return "\n".join(sanitize_text(item) for item in value if sanitize_text(item))
    return sanitize_text(value)


def export_candidates(
    output: str,
    status: str = "candidate",
    source_type: str = "",
    scenario_type: str = "",
    db_factory=None,
) -> dict[str, Any]:
    filters = {
        "status": status,
        "source_type": source_type,
        "scenario_type": scenario_type,
    }
    result = AgentBenchmarkDatasetService().list_scenarios(filters, db_factory=db_factory)
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Agent强度测试候选"
    sheet.append(HEADERS)
    for item in result.get("items", []):
        sidecar = item.get("sidecar_context") or {}
        expected = item.get("expected_reply") or {}
        metadata = item.get("metadata") or {}
        quality = metadata.get("expected_reply_quality") or expected.get("quality") or ""
        block_reason = metadata.get("expected_reply_block_reason") or expected.get("block_reason") or ""
        if not quality:
            quality_result = expected_reply_quality(expected.get("expected_reply") or "")
            quality = quality_result.get("quality") or ""
            block_reason = block_reason or quality_result.get("block_reason") or ""
        sheet.append([
            item.get("scenario_uid", ""),
            item.get("status", ""),
            item.get("title", ""),
            item.get("scenario_type", ""),
            _join_turns(item.get("conversation_turns") or []),
            sidecar.get("product_title") or sidecar.get("product_name") or "",
            sidecar.get("sku_code") or "",
            sidecar.get("i_id") or "",
            sidecar.get("order_id") or sidecar.get("platform_order_id") or "",
            expected.get("expected_reply") or "",
            quality,
            block_reason,
            _join_list(expected.get("key_points") or []),
            _join_list(expected.get("forbidden_claims") or []),
            bool(expected.get("must_handoff")),
            bool(expected.get("auto_send_allowed")),
            "",
            "",
            metadata.get("created_from") or item.get("source_type") or "",
        ])
    target = Path(output)
    target.parent.mkdir(parents=True, exist_ok=True)
    workbook.save(target)
    return sanitize_obj({
        "output": str(target),
        "status": status,
        "exported_count": len(result.get("items", [])),
    })


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Export Agent benchmark candidates for review.")
    parser.add_argument("--status", default="candidate")
    parser.add_argument("--source-type", default="")
    parser.add_argument("--scenario-type", default="")
    parser.add_argument("--output", required=True)
    args = parser.parse_args(argv)

    init_db()
    result = export_candidates(
        output=args.output,
        status=args.status,
        source_type=args.source_type,
        scenario_type=args.scenario_type,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
