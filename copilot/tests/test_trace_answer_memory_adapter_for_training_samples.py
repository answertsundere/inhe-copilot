from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.models.eval_tables import AgentAnswerMemory
from app.services import answer_memory_service as memory_module
from scripts.trace_answer_memory_adapter_for_training_samples import trace_samples


def _session_factory(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=engine, tables=[AgentAnswerMemory.__table__])
    factory = sessionmaker(autocommit=False, autoflush=False, bind=engine, expire_on_commit=False)
    monkeypatch.setattr(memory_module, "SessionLocal", factory)
    return factory


def test_trace_adapter_reports_shadow_contract_counts(monkeypatch):
    factory = _session_factory(monkeypatch)
    db = factory()
    row = AgentAnswerMemory(
        memory_uid="trace_adapter_memory_1",
        product_title="Trace Product",
        query_fact_type="installation",
        scenario_type="installation",
    )
    row.approved_answer = "Guide the customer to the installation material and hand off if missing."
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
                "customer_quote": "Do you have an install video?",
                "product_title": "Trace Product",
                "question_type": "installation",
            }
        ]
    )

    assert result["total"] == 1
    assert result["guidance_hit_count"] == 1
    assert result["verified_reference_count"] == 1
    assert result["reference_only_count"] == 1
    assert result["can_change_can_send_count"] == 0
    assert result["used_for_fact_count"] == 0
    assert result["non_reference_count"] == 0
    assert result["mojibake_guidance_count"] == 0
    assert result["internal_jargon_guidance_count"] == 0


def test_trace_adapter_keeps_high_risk_human_review(monkeypatch):
    factory = _session_factory(monkeypatch)
    db = factory()
    row = AgentAnswerMemory(
        memory_uid="trace_adapter_memory_high_risk",
        product_title="Trace Product",
        query_fact_type="material",
        scenario_type="product_fact",
    )
    row.approved_answer = "Check material and certificate details before replying."
    row.review_status = "verified_answer"
    row.answer_quality = "verified_answer"
    row.risk_level = "high"
    row.can_auto_send = False
    row.requires_human_review = True
    row.set_forbidden_claims(["non-toxic"])
    db.add(row)
    db.commit()
    db.close()

    result = trace_samples(
        [
            {
                "id": "s1",
                "customer_quote": "Is the material non-toxic?",
                "product_title": "Trace Product",
                "question_type": "product",
            }
        ]
    )

    assert result["guidance_hit_count"] == 1
    assert result["high_risk_guidance_count"] == 1
    assert result["high_risk_without_review_count"] == 0
    assert result["forbidden_claims_count"] == 1
    assert result["mojibake_guidance_count"] == 0
    assert result["internal_jargon_guidance_count"] == 0
