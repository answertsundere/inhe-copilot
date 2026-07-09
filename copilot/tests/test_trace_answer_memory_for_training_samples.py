import json

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.models.eval_tables import AgentAnswerMemory
from app.services import answer_memory_service as service_module
from app.services.answer_memory_service import AnswerMemoryService
from scripts import trace_answer_memory_for_training_samples as trace_script


def _session_factory(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=engine, tables=[AgentAnswerMemory.__table__])
    factory = sessionmaker(autocommit=False, autoflush=False, bind=engine, expire_on_commit=False)
    monkeypatch.setattr(service_module, "SessionLocal", factory)
    monkeypatch.setattr(trace_script, "init_db", lambda: None)
    return factory


def test_trace_script_reports_shadow_hits_without_sendability_change(monkeypatch, tmp_path):
    _session_factory(monkeypatch)
    samples = [
        {
            "id": 1,
            "review_status": "已确认",
            "customer_quote": "有什么优惠吗",
            "correct_answer": "按当前页面活动和优惠券规则核对，不承诺额外优惠",
            "product_title": "",
            "sku": "",
            "order_no": "512345678901234",
            "question_type": "活动",
        }
    ]
    AnswerMemoryService().import_training_samples(samples, apply=True)
    input_path = tmp_path / "snapshot.json"
    input_path.write_text(json.dumps({"items": samples}, ensure_ascii=False), encoding="utf-8")
    output_path = tmp_path / "trace.json"

    code = trace_script.main(["--input", str(input_path), "--json-output", str(output_path)])

    result = json.loads(output_path.read_text(encoding="utf-8"))
    assert code == 0
    assert result["hit_count"] == 1
    assert result["can_change_can_send"] is False
    assert result["rows"][0]["has_answer_memory_hit"] is True
    assert result["rows"][0]["top_hit"]["reference_only"] is True
    assert result["rows"][0]["top_hit"]["can_auto_send"] is False
