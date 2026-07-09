import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.models.eval_tables import AgentAnswerMemory
from app.services import answer_memory_service as memory_module
from app.services.answer_memory_adapter_service import (
    AnswerMemoryAdapterService,
    build_answer_memory_guidance,
    guidance_copy_text,
    has_internal_jargon_guidance,
    has_mojibake_guidance,
)


@pytest.fixture()
def client():
    import app.models.kb_tables  # noqa: F401
    from app.db import init_db
    from app.main import create_app

    init_db()
    flask_app = create_app()
    flask_app.config["TESTING"] = True
    return flask_app.test_client()


def _session_factory(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=engine, tables=[AgentAnswerMemory.__table__])
    factory = sessionmaker(autocommit=False, autoflush=False, bind=engine, expire_on_commit=False)
    monkeypatch.setattr(memory_module, "SessionLocal", factory)
    return factory


def _add_memory(factory, **kwargs):
    db = factory()
    row = AgentAnswerMemory(
        memory_uid=kwargs.get("memory_uid", "adapter_memory_1"),
        product_title=kwargs.get("product_title", "Memory Product"),
        sku_code=kwargs.get("sku_code", ""),
        query_fact_type=kwargs.get("query_fact_type", "installation"),
        scenario_type=kwargs.get("scenario_type", "installation"),
    )
    row.approved_answer = kwargs.get("approved_answer", "Check the matching installation material, then guide the customer.")
    row.reference_reply = kwargs.get("reference_reply", "")
    row.review_status = kwargs.get("review_status", "verified_answer")
    row.answer_quality = kwargs.get("answer_quality", "verified_answer")
    row.risk_level = kwargs.get("risk_level", "medium")
    row.can_auto_send = False
    row.requires_human_review = kwargs.get("requires_human_review", True)
    row.source_type = "test"
    row.set_required_fact_types([kwargs.get("query_fact_type", "installation")])
    row.set_forbidden_claims(kwargs.get("forbidden_claims", []))
    db.add(row)
    db.commit()
    db.close()
    return row.memory_uid


def _assert_guidance_copy_clean(guidance):
    copy_text = guidance_copy_text(guidance)
    assert copy_text
    assert has_mojibake_guidance(guidance) is False
    assert has_internal_jargon_guidance(guidance) is False
    for term in (
        "RAG",
        "final gate",
        "Evidence",
        "query_fact_type",
        "used_for_fact",
        "can_change_can_send",
        "reference_only",
        "风控",
        "证据不足",
    ):
        assert term not in copy_text


def test_adapter_guidance_is_reference_only_and_cannot_change_sendability(monkeypatch):
    factory = _session_factory(monkeypatch)
    _add_memory(factory)

    guidance = AnswerMemoryAdapterService().build_for_context(
        customer_message="Do you have an install video?",
        product_title="Memory Product",
        query_fact_type="installation",
        scenario_type="installation",
    )

    assert guidance["matched_memories"]
    assert guidance["reference_only"] is True
    assert guidance["used_for_fact"] is False
    assert guidance["can_change_can_send"] is False
    assert guidance["matched_memories"][0]["used_for_fact"] is False
    assert guidance["matched_memories"][0]["can_change_can_send"] is False
    _assert_guidance_copy_clean(guidance)


def test_high_risk_memory_remains_human_review_only(monkeypatch):
    factory = _session_factory(monkeypatch)
    _add_memory(
        factory,
        memory_uid="adapter_memory_high_risk",
        query_fact_type="material",
        scenario_type="product_fact",
        risk_level="high",
        forbidden_claims=["non-toxic", "certified"],
    )

    guidance = AnswerMemoryAdapterService().build_for_context(
        customer_message="Is it non-toxic?",
        product_title="Memory Product",
        query_fact_type="material",
        scenario_type="product_fact",
    )

    assert guidance["risk_level"] == "high"
    assert guidance["forbidden_claims"] == ["non-toxic", "certified"]
    assert guidance["matched_memories"][0]["requires_human_review"] is True
    assert guidance["can_change_can_send"] is False
    _assert_guidance_copy_clean(guidance)


def test_adapter_does_not_copy_internal_jargon_from_memory_answer(monkeypatch):
    factory = _session_factory(monkeypatch)
    _add_memory(
        factory,
        memory_uid="adapter_memory_internal_words",
        approved_answer="Use RAG evidence and final gate before reply.",
    )

    guidance = AnswerMemoryAdapterService().build_for_context(
        customer_message="Do you have an install video?",
        product_title="Memory Product",
        query_fact_type="installation",
        scenario_type="installation",
    )

    assert guidance["matched_memories"]
    assert guidance["used_for_fact"] is False
    _assert_guidance_copy_clean(guidance)


def test_attach_shadow_guidance_preserves_response_contract(monkeypatch):
    factory = _session_factory(monkeypatch)
    _add_memory(factory)
    response = {
        "suggested_reply": "draft",
        "sendable_reply": "",
        "can_send": False,
        "requires_human_review": True,
        "selected_evidence": [{"id": "e1"}],
        "evidence_debug": {"query_fact_type": "installation", "selected_evidence": [{"id": "e1"}]},
        "answer_trace": {"query_fact_type": "installation"},
    }

    updated = AnswerMemoryAdapterService().attach_shadow_guidance(
        response,
        customer_message="Do you have an install video?",
        product_title="Memory Product",
    )

    assert updated["can_send"] is False
    assert updated["sendable_reply"] == ""
    assert updated["selected_evidence"] == [{"id": "e1"}]
    assert updated["evidence_debug"]["selected_evidence"] == [{"id": "e1"}]
    assert updated["answer_memory_guidance"]["reference_only"] is True
    assert updated["answer_trace"]["answer_memory_guidance"]["used_for_fact"] is False


def test_build_empty_guidance_keeps_contract():
    guidance = build_answer_memory_guidance([])

    assert guidance["matched_memories"] == []
    assert guidance["reference_only"] is True
    assert guidance["used_for_fact"] is False
    assert guidance["can_change_can_send"] is False


def test_analyze_shadow_guidance_is_env_gated(client, monkeypatch):
    import app.services.analysis_execution_service as execution_service

    def fake_execute_analysis(**kwargs):
        return {
            "intent": "product_question",
            "suggested_reply": "Need review.",
            "requires_human_review": True,
            "can_send": False,
            "sendable_reply": "",
            "selected_evidence": [{"id": "existing"}],
            "evidence_debug": {
                "query_fact_type": "installation",
                "selected_evidence": [{"id": "existing"}],
            },
            "answer_trace": {"query_fact_type": "installation"},
        }

    monkeypatch.setattr(execution_service, "execute_analysis", fake_execute_analysis)
    monkeypatch.delenv("COPILOT_ANSWER_MEMORY_SHADOW_ENABLED", raising=False)

    response = client.post(
        "/api/analyze",
        json={
            "message": "Do you have an install video?",
            "product_name": "Memory Product",
            "conversation_id": "pytest_answer_memory_shadow_disabled",
        },
    )
    data = response.get_json()
    assert response.status_code == 200
    assert "answer_memory_guidance" not in data


def test_analyze_shadow_guidance_enabled_does_not_change_sendability(client, monkeypatch):
    import app.services.analysis_execution_service as execution_service
    from app.db import SessionLocal, init_db

    init_db()
    db = SessionLocal()
    row = db.query(AgentAnswerMemory).filter(AgentAnswerMemory.memory_uid == "api_shadow_memory_enabled").one_or_none()
    if row is None:
        row = AgentAnswerMemory(
            memory_uid="api_shadow_memory_enabled",
            product_title="Memory Product",
            query_fact_type="installation",
            scenario_type="installation",
        )
    row.approved_answer = "Check the installation guide and hand off when evidence is missing."
    row.review_status = "verified_answer"
    row.answer_quality = "verified_answer"
    row.can_auto_send = False
    row.requires_human_review = True
    row.set_required_fact_types(["installation"])
    db.add(row)
    db.commit()
    db.close()

    def fake_execute_analysis(**kwargs):
        return {
            "intent": "product_question",
            "suggested_reply": "Need review.",
            "requires_human_review": True,
            "can_send": False,
            "sendable_reply": "",
            "selected_evidence": [{"id": "existing"}],
            "evidence_debug": {
                "query_fact_type": "installation",
                "selected_evidence": [{"id": "existing"}],
            },
            "answer_trace": {"query_fact_type": "installation"},
        }

    monkeypatch.setattr(execution_service, "execute_analysis", fake_execute_analysis)
    monkeypatch.setenv("COPILOT_ANSWER_MEMORY_SHADOW_ENABLED", "true")

    response = client.post(
        "/api/analyze",
        json={
            "message": "Do you have an install video?",
            "product_name": "Memory Product",
            "conversation_id": "pytest_answer_memory_shadow_enabled",
        },
    )
    data = response.get_json()
    assert response.status_code == 200
    assert data["can_send"] is False
    assert data["sendable_reply"] == ""
    assert data["selected_evidence"] == [{"id": "existing"}]
    assert data["answer_memory_guidance"]["reference_only"] is True
    assert data["answer_memory_guidance"]["used_for_fact"] is False
    assert data["answer_memory_guidance"]["can_change_can_send"] is False
