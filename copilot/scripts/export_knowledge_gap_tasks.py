"""Export knowledge gap tasks to an Excel review workbook."""

from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill

from app.db import SessionLocal, init_db
from app.models.eval_tables import KnowledgeGapTask
from app.services.eval_sanitizer_service import sanitize_text


HEADERS = [
    "任务ID",
    "缺口类型",
    "商品标题",
    "SKU",
    "商品ID",
    "问题类型",
    "失败类型",
    "建议归口",
    "优先级",
    "样本数量",
    "买家问题示例",
    "Agent 当前回复示例",
    "原客服回复参考",
    "缺什么资料",
    "建议补充内容",
    "是否需要图片/视频",
    "是否高风险",
    "审核状态",
    "负责人",
    "备注",
]


def default_output_path() -> str:
    today = datetime.now().strftime("%Y%m%d")
    return str(Path("D:/") / f"知识缺口任务_{today}.xlsx")


def _joined(values: list[str]) -> str:
    return "\n".join(sanitize_text(value) for value in values[:5] if sanitize_text(value))


def _suggested_content(task: KnowledgeGapTask) -> str:
    if task.gap_type == "media_asset_gap":
        return f"补充并审核 {task.media_needed_type or '图片/视频/说明书'}，确认适用商品和可发送范围。"
    if task.gap_type == "activity_rule_gap":
        return "补充活动/福利规则，包含活动时间、参与条件、退货后的处理口径。"
    if task.gap_type == "service_rule_gap":
        return "补充售后/服务规则，包含触发条件、客户需提供材料和处理边界。"
    if task.gap_type == "human_policy_gap":
        return "补充人工复核策略，说明哪些问题必须人工确认。"
    if task.gap_type == "agent_logic_gap":
        return "补充 Agent 规则或审核任务，避免同类样本答非所问。"
    return f"补充 {task.query_fact_type or '商品资料'} 的可核验证据，发布前人工审核。"


def export_knowledge_gap_tasks(output: str | None = None, status: str = "open") -> dict:
    init_db()
    path = Path(output or default_output_path())
    path.parent.mkdir(parents=True, exist_ok=True)

    db = SessionLocal()
    try:
        query = db.query(KnowledgeGapTask).order_by(KnowledgeGapTask.updated_at.desc(), KnowledgeGapTask.id.desc())
        if status:
            query = query.filter(KnowledgeGapTask.status == sanitize_text(status))
        tasks = query.all()

        workbook = Workbook()
        sheet = workbook.active
        sheet.title = "知识缺口任务"
        sheet.append(HEADERS)
        for cell in sheet[1]:
            cell.font = Font(bold=True)
            cell.fill = PatternFill("solid", fgColor="D9EAF7")

        for task in tasks:
            sheet.append([
                sanitize_text(task.task_uid),
                sanitize_text(task.gap_type),
                sanitize_text(task.product_title),
                sanitize_text(task.sku_code),
                sanitize_text(task.item_id),
                sanitize_text(task.query_fact_type),
                sanitize_text(task.failure_type),
                sanitize_text(task.suggested_fix_area),
                sanitize_text(task.priority),
                int(task.sample_count or 0),
                _joined(task.get_latest_buyer_questions()),
                _joined(task.get_latest_agent_replies()),
                _joined(task.get_latest_original_cs_replies()),
                sanitize_text(task.missing_evidence_type),
                sanitize_text(_suggested_content(task)),
                "是" if task.media_needed_type else "否",
                "是" if task.risk_level == "high" else "否",
                sanitize_text(task.status),
                sanitize_text(task.suggested_owner),
                sanitize_text(task.summary),
            ])

        for col in sheet.columns:
            letter = col[0].column_letter
            sheet.column_dimensions[letter].width = min(max(len(str(col[0].value or "")) + 4, 12), 36)
        workbook.save(path)
        return {"output": str(path), "count": len(tasks)}
    finally:
        db.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Export knowledge gap tasks to Excel.")
    parser.add_argument("--output", default="", help="Excel output path")
    parser.add_argument("--status", default="open", help="Task status filter; empty exports all tasks")
    args = parser.parse_args()
    result = export_knowledge_gap_tasks(output=args.output or None, status=args.status)
    print(result)


if __name__ == "__main__":
    main()
