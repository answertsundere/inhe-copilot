import os
import sys

import pandas as pd
import pytest

from app.db import Base
from app.models.knowledge_base import KnowledgeEntry


sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
from import_customer_service_knowledge import run_import, rollback_batch


@pytest.fixture()
def fresh_db(tmp_path, monkeypatch):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from app import db as db_module

    db_path = tmp_path / "knowledge.db"
    monkeypatch.setenv("COPILOT_KNOWLEDGE_DB_PATH", str(db_path))
    engine = create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autocommit=False, autoflush=False, expire_on_commit=False)
    monkeypatch.setattr(db_module, "engine", engine)
    monkeypatch.setattr(db_module, "SessionLocal", Session)
    return Session


def _write_workbook(path):
    rows = [
        {
            "序号": 1,
            "一级类目": "存储收纳",
            "二级类目": "书架",
            "三级类目": "多功能书架",
            "关联商品": "三层火箭书架",
            "关联SKU": "SKU001, SKU002",
            "客户问题": "三层火箭书架安装方便吗？",
            "金牌回答": "安装简单，配有说明书和五金配件，一般20-30分钟可以装好。",
            "意图": "安装指导",
            "风险等级": "低",
            "可自动回复": "是",
            "需人工审核": "否",
        },
        {
            "序号": 2,
            "一级类目": "存储收纳",
            "二级类目": "书架",
            "三级类目": "多功能书架",
            "关联商品": "三层火箭书架",
            "关联SKU": "SKU001",
            "客户问题": "三层火箭书架适合多大宝宝？",
            "金牌回答": "适合0-6岁的宝宝使用，低层开放式设计方便宝宝自己拿取绘本。",
            "意图": "产品咨询",
            "风险等级": "低",
            "可自动回复": "是",
            "需人工审核": "否",
        },
    ]
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        pd.DataFrame(rows).to_excel(writer, sheet_name="金牌客服问答（增强版）", index=False)


def test_dry_run_does_not_write_entries(fresh_db, tmp_path):
    xlsx = tmp_path / "faq.xlsx"
    _write_workbook(xlsx)

    result = run_import(str(xlsx), apply=False, batch_id="batch_dry")

    session = fresh_db()
    try:
        assert result["mode"] == "dry-run"
        assert result["selected"]["items"] == 2
        assert session.query(KnowledgeEntry).count() == 0
    finally:
        session.close()


def test_apply_limit_can_rollback_drafts(fresh_db, tmp_path):
    xlsx = tmp_path / "faq.xlsx"
    _write_workbook(xlsx)

    result = run_import(str(xlsx), apply=True, batch_id="batch_apply", limit=1)

    session = fresh_db()
    try:
        assert result["created"] == 1
        entry = session.query(KnowledgeEntry).one()
        assert entry.status == "draft"
        assert entry.index_status == "pending"
        assert entry.import_batch_id == "batch_apply"
        assert entry.source_type == "faq"
    finally:
        session.close()

    rollback = rollback_batch("batch_apply")
    session = fresh_db()
    try:
        assert rollback["deleted_draft_entries"] == 1
        assert session.query(KnowledgeEntry).count() == 0
    finally:
        session.close()
