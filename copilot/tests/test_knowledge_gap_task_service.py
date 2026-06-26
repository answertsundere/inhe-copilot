import subprocess
import sys
from pathlib import Path

from openpyxl import load_workbook
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.models.eval_tables import (
    EvalFailure,
    EvalReview,
    EvalRun,
    EvalTrace,
    KnowledgeGapTask,
)
from app.services.knowledge_gap_task_service import KnowledgeGapTaskService
from scripts.export_knowledge_gap_tasks import export_knowledge_gap_tasks


EXPECTED_EXPORT_HEADERS = [
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


def _session_factory():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    return sessionmaker(autocommit=False, autoflush=False, bind=engine, expire_on_commit=False)


def _add_trace(db, turn_uid, query_fact_type, *, product_title="收纳柜", sku_code="", item_id=""):
    trace = EvalTrace(
        run_uid="kgap_run_1",
        case_uid=f"case_{turn_uid}",
        turn_uid=turn_uid,
        turn_index=1,
        buyer_message=f"买家手机号 13812345678 询问 {query_fact_type}",
        reference_human_reply="原客服参考，订单号 123456789012345",
        agent_reply="Agent 回复 https://demo.oss-cn/a.jpg?Signature=secret&Expires=999",
        query_fact_type=query_fact_type,
        passed=False,
        requires_human_review=True,
    )
    trace.set_product_identity({
        "display_product_name": product_title,
        "sku_code": sku_code,
        "item_id": item_id,
    })
    trace.set_selected_evidence([])
    db.add(trace)
    return trace


def _seed_gap_run(session_factory):
    db = session_factory()
    try:
        db.add(EvalRun(run_uid="kgap_run_1", source_type="real_conversation", status="completed"))
        cases = [
            ("turn_fact", "material", "rag_miss", "knowledge_rag", "knowledge_ops"),
            ("turn_media", "installation", "unsupported_media_claim", "media_pipeline", "media_ops"),
            ("turn_promo", "promotion_policy", "rag_miss", "knowledge_rag", "knowledge_ops"),
            ("turn_service", "aftersales_policy", "rag_miss", "knowledge_rag", "knowledge_ops"),
            ("turn_correct", "dimensions", "rag_miss", "knowledge_rag", "knowledge_ops"),
        ]
        for turn_uid, fact_type, failure_type, fix_area, owner in cases:
            _add_trace(db, turn_uid, fact_type, sku_code="SKU-1", item_id="ITEM-1")
            db.add(EvalFailure(
                run_uid="kgap_run_1",
                case_uid=f"case_{turn_uid}",
                turn_uid=turn_uid,
                failure_type=failure_type,
                severity="high" if turn_uid == "turn_media" else "medium",
                suggested_fix_area=fix_area,
                suggested_owner=owner,
                message="missing evidence for 13812345678",
            ))
        db.add(EvalReview(
            run_uid="kgap_run_1",
            case_uid="case_turn_correct",
            turn_uid="turn_correct",
            decision="correct",
            reviewer="qa",
        ))
        db.commit()
    finally:
        db.close()


def test_knowledge_gap_generation_maps_failure_types_and_skips_correct_review():
    session_factory = _session_factory()
    _seed_gap_run(session_factory)
    db = session_factory()
    try:
        result = KnowledgeGapTaskService().generate_for_run(db, "kgap_run_1", created_by="lead")

        assert result.generated == 3
        assert result.skipped_correct == 1
        gap_types = {task.gap_type for task in db.query(KnowledgeGapTask).all()}
        assert "product_fact_gap" in gap_types
        assert "activity_rule_gap" in gap_types
        assert "service_rule_gap" in gap_types
        assert not any("turn_correct" in task.get_related_turn_uids() for task in db.query(KnowledgeGapTask).all())
    finally:
        db.close()


def test_knowledge_gap_generation_updates_existing_task_instead_of_duplicating():
    session_factory = _session_factory()
    _seed_gap_run(session_factory)
    db = session_factory()
    try:
        first = KnowledgeGapTaskService().generate_for_run(db, "kgap_run_1", created_by="lead")
        second = KnowledgeGapTaskService().generate_for_run(db, "kgap_run_1", created_by="lead")

        assert first.generated == 3
        assert second.generated == 0
        assert second.updated == 3
        assert db.query(KnowledgeGapTask).count() == 3
    finally:
        db.close()


def test_knowledge_gap_export_excel_is_sanitized(monkeypatch, tmp_path):
    import app.db as db_module

    session_factory = _session_factory()
    monkeypatch.setattr(db_module, "SessionLocal", session_factory)
    monkeypatch.setattr("scripts.export_knowledge_gap_tasks.SessionLocal", session_factory)
    monkeypatch.setattr("scripts.export_knowledge_gap_tasks.init_db", lambda: None)
    _seed_gap_run(session_factory)
    db = session_factory()
    try:
        KnowledgeGapTaskService().generate_for_run(db, "kgap_run_1", created_by="lead")
    finally:
        db.close()

    output = tmp_path / "knowledge_gap.xlsx"
    result = export_knowledge_gap_tasks(output=str(output), status="open")

    assert result["count"] == 3
    workbook = load_workbook(output)
    sheet = workbook.active
    assert sheet.title == "知识缺口任务"
    assert [cell.value for cell in sheet[1]] == EXPECTED_EXPORT_HEADERS
    values = "\n".join(str(cell.value or "") for row in sheet.iter_rows() for cell in row)
    assert "13812345678" not in values
    assert "123456789012345" not in values
    assert "Signature=secret" not in values


def test_knowledge_gap_export_script_help_runs_from_project_root():
    project_root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [sys.executable, "scripts/export_knowledge_gap_tasks.py", "--help"],
        cwd=project_root,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0
    assert "--output" in result.stdout
    assert "--status" in result.stdout


def test_knowledge_gap_export_empty_template_has_chinese_headers(monkeypatch, tmp_path):
    import app.db as db_module

    session_factory = _session_factory()
    monkeypatch.setattr(db_module, "SessionLocal", session_factory)
    monkeypatch.setattr("scripts.export_knowledge_gap_tasks.SessionLocal", session_factory)
    monkeypatch.setattr("scripts.export_knowledge_gap_tasks.init_db", lambda: None)

    output = tmp_path / "empty_knowledge_gap.xlsx"
    result = export_knowledge_gap_tasks(output=str(output), status="__none__")

    workbook = load_workbook(output)
    sheet = workbook.active
    assert result["count"] == 0
    assert sheet.max_row == 1
    assert [cell.value for cell in sheet[1]] == EXPECTED_EXPORT_HEADERS
