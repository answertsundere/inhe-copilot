"""Repair a sanitized manual technical-validation report as UTF-8 JSON."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _conclusion(item: dict) -> str:
    status = str(item.get("manual_status") or "")
    category = str(item.get("review_category") or "")
    if status == "pixel_match":
        return "技术抽查确认：低风险可见信息与图片内容一致，仍需主管审核后才能进入 shadow 状态。"
    if status == "high_risk_rejected":
        return "技术抽查确认：高风险内容已被拒绝，不能作为审核候选或正式知识。"
    if status == "ambiguity_rejected":
        return "技术抽查确认：多规格尺寸范围不明确，已保持拒绝，不能按单一规格审核。"
    return f"技术抽查记录：{category or '观察结果'} 仅用于离线验证，未形成主管批准。"


def repair(report: dict) -> dict:
    repaired = dict(report)
    repaired["technical_validation_status"] = "technical_validation"
    repaired["approved"] = False
    repaired["items"] = [dict(item, manual_conclusion=_conclusion(item)) for item in report.get("items") or []]
    return repaired


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", default="outputs/product_media_observation_manual_review_local_qwen.json")
    parser.add_argument("--output", default="outputs/product_media_observation_manual_review_local_qwen.json")
    args = parser.parse_args(argv)
    source = PROJECT_ROOT / args.input
    target = PROJECT_ROOT / args.output
    report = repair(json.loads(source.read_text(encoding="utf-8")))
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"technical_validation_status": report["technical_validation_status"], "item_count": len(report["items"])}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
