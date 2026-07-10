from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.models.eval_tables import AgentAnswerMemory
from app.services import answer_memory_service as memory_module
from scripts.trace_grounded_reasoning_for_training_samples import trace_samples


def _session_factory(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=engine, tables=[AgentAnswerMemory.__table__])
    factory = sessionmaker(autocommit=False, autoflush=False, bind=engine, expire_on_commit=False)
    monkeypatch.setattr(memory_module, "SessionLocal", factory)
    return factory


def test_trace_grounded_reasoning_reports_shadow_safety_counts(monkeypatch):
    factory = _session_factory(monkeypatch)
    db = factory()
    row = AgentAnswerMemory(
        memory_uid="grounded_trace_memory_install",
        product_title="Trace Product",
        query_fact_type="installation",
        scenario_type="installation",
    )
    row.approved_answer = "Help the customer check installation steps and blocked positions."
    row.review_status = "verified_answer"
    row.answer_quality = "verified_answer"
    row.can_auto_send = False
    row.requires_human_review = True
    row.set_required_fact_types(["installation"])
    db.add(row)
    db.commit()
    db.close()

    result = trace_samples(
        [
            {
                "id": "s1",
                "customer_quote": "有没有安装视频？",
                "product_title": "Trace Product",
                "sku": "TRACE-SKU",
                "correct_answer": "按安装资料核对，不承诺没有的视频。",
            },
            {
                "id": "s2",
                "customer_quote": "宝宝咬了一下会不会中毒？",
                "product_title": "Trace Product",
                "correct_answer": "先停止啃咬，检查破损和误吞，再核对材质资料。",
            },
        ]
    )

    assert result["total"] == 2
    assert result["generated_count"] == 2
    assert result["skipped_count"] == 0
    assert result["can_change_can_send_count"] == 0
    assert result["used_answer_memory_as_fact_count"] == 0
    assert result["answer_leakage_count"] == 0
    assert result["forbidden_claim_violation_count"] == 0
    assert result["unsupported_media_claim_count"] == 0
    assert "generic_handoff_only_count" in result
    assert "admission_warning_count" in result
    assert "conflicting_evidence_group_count" in result
    assert "conflict_check_skipped_count" in result
    assert result["requires_human_review_count"] >= 1


def test_trace_grounded_reasoning_skips_empty_question():
    result = trace_samples([{"id": "empty", "customer_quote": "", "product_title": "Trace Product"}])

    assert result["total"] == 1
    assert result["generated_count"] == 0
    assert result["skipped_count"] == 1
    assert result["rows"][0]["skip_reason"] == "missing_context"


def test_trace_does_not_admit_correct_answer_or_image_link_only_questions():
    result = trace_samples([
        {"id": "answer", "customer_quote": "安装怎么弄", "correct_answer": "标准答案不能当证据"},
        {"id": "image", "customer_quote": "图片"},
        {"id": "link", "customer_quote": "https://example.test/item"},
    ])

    assert result["answer_leakage_count"] == 0
    assert result["admitted_fact_count"] == 0
    assert result["skipped_by_reason"] == {"image_only": 1, "link_only": 1}
