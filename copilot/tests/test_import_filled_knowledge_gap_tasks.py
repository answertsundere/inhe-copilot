from pathlib import Path

from openpyxl import Workbook
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.models.eval_tables import KnowledgeGapTask
from scripts.export_latest_run_knowledge_gaps import SHEET_ALL, TASK_HEADERS
from scripts.import_filled_knowledge_gap_tasks import import_filled_knowledge_gap_tasks


def _session_factory():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    return sessionmaker(autocommit=False, autoflush=False, bind=engine, expire_on_commit=False)


def _add_task(db, task_uid="kgap_import_1", *, run_uid="run_import_1", status="open"):
    task = KnowledgeGapTask(
        task_uid=task_uid,
        gap_type="product_field_gap",
        product_title="\u513f\u7ae5\u6536\u7eb3\u67dc",
        item_id="ITEM-IMPORT",
        sku_code="SKU-IMPORT",
        query_fact_type="material",
        failure_type="rag_miss",
        suggested_fix_area="knowledge_rag",
        suggested_owner="knowledge_ops",
        missing_evidence_type="product_material",
        risk_level="medium",
        sample_count=1,
        priority="medium",
        status=status,
        summary="missing material",
    )
    task.set_metadata({
        "source_run_uid": run_uid,
        "gap_category": "product_field_gap",
        "required_evidence_type": "product_material",
        "target_system": "product_profile",
    })
    db.add(task)
    return task


def _write_workbook(path: Path, rows: list[dict[str, str]], *, include_task_uid: bool = True) -> None:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = SHEET_ALL
    headers = list(TASK_HEADERS)
    if not include_task_uid:
        headers = [header for header in headers if header != "\u4efb\u52a1ID"]
    sheet.append(headers)
    for row in rows:
        sheet.append([row.get(header, "") for header in headers])
    workbook.save(path)


def _seed(monkeypatch):
    session_factory = _session_factory()
    monkeypatch.setattr("scripts.import_filled_knowledge_gap_tasks.SessionLocal", session_factory)
    monkeypatch.setattr("scripts.import_filled_knowledge_gap_tasks.init_db", lambda: None)
    db = session_factory()
    try:
        _add_task(db)
        db.commit()
    finally:
        db.close()
    return session_factory


def test_import_filled_knowledge_gap_dry_run_does_not_write(monkeypatch, tmp_path):
    session_factory = _seed(monkeypatch)
    workbook_path = tmp_path / "filled.xlsx"
    _write_workbook(workbook_path, [{
        "\u4efb\u52a1ID": "kgap_import_1",
        "\u4eba\u5de5\u5904\u7406\u7ed3\u679c": "\u5df2\u6838\u5bf9",
        "\u4eba\u5de5\u8865\u5145\u5185\u5bb9": "\u6750\u8d28\u4e3a\u5df2\u5ba1\u6838\u8d44\u6599",
        "\u5904\u7406\u4eba": "lead",
    }])

    result = import_filled_knowledge_gap_tasks(
        input_path=str(workbook_path),
        run_uid="run_import_1",
        apply=False,
    )

    assert result["dry_run"] is True
    assert result["matched_count"] == 1
    assert result["updated_task_uids"] == []
    db = session_factory()
    try:
        task = db.query(KnowledgeGapTask).filter(KnowledgeGapTask.task_uid == "kgap_import_1").one()
        assert task.status == "open"
        assert "manual_fill" not in task.get_metadata()
    finally:
        db.close()


def test_import_filled_knowledge_gap_apply_writes_staging_metadata_only(monkeypatch, tmp_path):
    session_factory = _seed(monkeypatch)
    workbook_path = tmp_path / "filled.xlsx"
    _write_workbook(workbook_path, [{
        "\u4efb\u52a1ID": "kgap_import_1",
        "\u4eba\u5de5\u5904\u7406\u7ed3\u679c": "\u5df2\u6838\u5bf9",
        "\u4eba\u5de5\u8865\u5145\u5185\u5bb9": "\u8054\u7cfb\u7535\u8bdd13812345678\uff0c\u8ba2\u5355123456789012345",
        "\u5546\u54c1\u5b57\u6bb5\u503c": "\u5b9e\u6728\u9897\u7c92\u677f",
        "\u8bc1\u636e\u6765\u6e90/\u7d20\u6750\u94fe\u63a5": "https://demo.oss/a.jpg?Signature=secret&Expires=999",
        "\u662f\u5426\u5df2\u8865\u9f50": "\u662f",
        "\u5904\u7406\u4eba": "lead",
        "\u5907\u6ce8": "\u7b49\u5f85\u590d\u6d4b",
    }])

    result = import_filled_knowledge_gap_tasks(
        input_path=str(workbook_path),
        run_uid="run_import_1",
        apply=True,
    )

    assert result["dry_run"] is False
    assert result["matched_count"] == 1
    assert result["updated_task_uids"] == ["kgap_import_1"]
    assert result["writes_formal_knowledge_base"] is False
    assert result["requires_retest_before_verified"] is True
    db = session_factory()
    try:
        task = db.query(KnowledgeGapTask).filter(KnowledgeGapTask.task_uid == "kgap_import_1").one()
        metadata = task.get_metadata()
        assert task.status == "resolved_pending_retest"
        assert task.status != "verified"
        assert metadata["manual_fill_status"] == "ready_for_retest"
        assert metadata["manual_fill"]["import_mode"] == "staging_review_only"
        raw = str(metadata)
        assert "13812345678" not in raw
        assert "123456789012345" not in raw
        assert "Signature=secret" not in raw
        assert "\u5b9e\u6728\u9897\u7c92\u677f" in raw
    finally:
        db.close()


def test_import_filled_knowledge_gap_missing_task_uid_does_not_guess_by_product(monkeypatch, tmp_path):
    session_factory = _seed(monkeypatch)
    workbook_path = tmp_path / "missing_uid.xlsx"
    _write_workbook(
        workbook_path,
        [{
            "\u5546\u54c1\u7f16\u7801": "SKU-IMPORT",
            "\u5546\u54c1\u540d\u79f0": "\u513f\u7ae5\u6536\u7eb3\u67dc",
            "\u4eba\u5de5\u8865\u5145\u5185\u5bb9": "\u6709\u5185\u5bb9\u4e5f\u4e0d\u80fd\u731c\u6d4b\u5339\u914d",
        }],
        include_task_uid=False,
    )

    result = import_filled_knowledge_gap_tasks(
        input_path=str(workbook_path),
        run_uid="run_import_1",
        apply=True,
    )

    assert result["matched_count"] == 0
    assert result["updated_task_uids"] == []
    assert any(item["reason"] == "missing_task_uid_header" for item in result["skipped_reasons"])
    db = session_factory()
    try:
        task = db.query(KnowledgeGapTask).filter(KnowledgeGapTask.task_uid == "kgap_import_1").one()
        assert task.status == "open"
        assert "manual_fill" not in task.get_metadata()
    finally:
        db.close()


def test_import_filled_knowledge_gap_run_uid_guard_skips_other_runs(monkeypatch, tmp_path):
    session_factory = _seed(monkeypatch)
    workbook_path = tmp_path / "filled.xlsx"
    _write_workbook(workbook_path, [{
        "\u4efb\u52a1ID": "kgap_import_1",
        "\u4eba\u5de5\u8865\u5145\u5185\u5bb9": "\u5df2\u586b",
    }])

    result = import_filled_knowledge_gap_tasks(
        input_path=str(workbook_path),
        run_uid="other_run",
        apply=True,
    )

    assert result["matched_count"] == 0
    assert result["updated_task_uids"] == []
    assert any(item["reason"] == "run_uid_mismatch" for item in result["skipped_reasons"])


def test_import_filled_knowledge_gap_preserves_internal_task_uid_with_numeric_suffix(monkeypatch, tmp_path):
    session_factory = _session_factory()
    monkeypatch.setattr("scripts.import_filled_knowledge_gap_tasks.SessionLocal", session_factory)
    monkeypatch.setattr("scripts.import_filled_knowledge_gap_tasks.init_db", lambda: None)
    db = session_factory()
    try:
        _add_task(db, task_uid="kgap_123456789012", run_uid="run_import_1")
        db.commit()
    finally:
        db.close()
    workbook_path = tmp_path / "filled.xlsx"
    _write_workbook(workbook_path, [{
        "\u4efb\u52a1ID": "kgap_123456789012",
        "\u4eba\u5de5\u8865\u5145\u5185\u5bb9": "\u5df2\u586b",
    }])

    result = import_filled_knowledge_gap_tasks(
        input_path=str(workbook_path),
        run_uid="run_import_1",
        apply=True,
    )

    assert result["matched_count"] == 1
    assert result["updated_task_uids"] == ["kgap_123456789012"]
