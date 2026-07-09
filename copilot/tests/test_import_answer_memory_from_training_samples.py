import json

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.models.eval_tables import AgentAnswerMemory
from app.services import answer_memory_service as service_module
from scripts import import_answer_memory_from_training_samples as import_script


def _session_factory(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=engine, tables=[AgentAnswerMemory.__table__])
    factory = sessionmaker(autocommit=False, autoflush=False, bind=engine, expire_on_commit=False)
    monkeypatch.setattr(service_module, "SessionLocal", factory)
    monkeypatch.setattr(import_script, "init_db", lambda: None)
    return factory


def _snapshot(tmp_path):
    payload = {
        "items": [
            {
                "id": 1,
                "review_status": "已确认",
                "customer_quote": "少了一个配件怎么办",
                "correct_answer": "先安抚客户，核对订单，让客户拍照，再转售后处理补发方案",
                "product_title": "测试商品",
                "sku": "SKU-1",
                "order_no": "512345678901234",
                "question_type": "售后",
            },
            {
                "id": 2,
                "review_status": "已确认",
                "customer_quote": "有图片",
                "correct_answer": "",
                "order_no": "512345678901235",
            },
        ]
    }
    path = tmp_path / "snapshot.json"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


def test_import_script_dry_run_does_not_write(monkeypatch, tmp_path):
    factory = _session_factory(monkeypatch)
    input_path = _snapshot(tmp_path)
    output_path = tmp_path / "result.json"

    code = import_script.main(["--input", str(input_path), "--json-output", str(output_path)])

    db = factory()
    result = json.loads(output_path.read_text(encoding="utf-8"))
    assert code == 0
    assert result["dry_run"] is True
    assert result["scanned_count"] == 2
    assert result["importable_count"] == 1
    assert result["default_can_auto_send_false_count"] == 1
    assert db.query(AgentAnswerMemory).count() == 0
    db.close()


def test_import_script_apply_writes_answer_memory(monkeypatch, tmp_path):
    factory = _session_factory(monkeypatch)
    input_path = _snapshot(tmp_path)

    code = import_script.main(["--input", str(input_path), "--apply"])

    db = factory()
    row = db.query(AgentAnswerMemory).one()
    assert code == 0
    assert row.source_id == "1"
    assert row.can_auto_send is False
    assert row.source_order_id_hash != "512345678901234"
    db.close()
