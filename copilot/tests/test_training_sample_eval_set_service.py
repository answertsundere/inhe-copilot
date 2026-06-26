from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.models.kb_tables import KBTrainingSample
from app.services import training_sample_eval_set_service as service_module
from app.services.training_sample_eval_set_service import (
    EVAL_SET_STATUS,
    REVIEWED_STATUS,
    TrainingSampleEvalSetService,
    build_eval_contract,
)


def _session_factory(monkeypatch):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    factory = sessionmaker(autocommit=False, autoflush=False, bind=engine, expire_on_commit=False)
    monkeypatch.setattr(service_module, "SessionLocal", factory)
    return factory


def _sample(**kwargs):
    data = {
        "review_status": REVIEWED_STATUS,
        "customer_quote": "manual and physical item do not match, what should customer service do",
        "full_context": "customer says the printed manual does not match the received item",
        "question_type": "\u552e\u540e",
        "correct_answer": "apologize first, ask for manual screenshot and item photo, then provide the correct material or aftersales solution",
        "csr_actual_reply": "please check the manual",
        "risk_level": "\u4e2d",
    }
    data.update(kwargs)
    return KBTrainingSample(**data)


def test_build_eval_contract_preview_is_text_only():
    sample = _sample(order_no="512345678900001", need_media=True)

    contract = build_eval_contract(sample)

    assert contract["customer_said"] == sample.customer_quote
    assert contract["suggested_answer"] == sample.correct_answer
    assert sorted(contract.keys()) == ["customer_said", "suggested_answer"]
    assert "conversation_turns" not in contract
    assert "expected_agent_turns" not in contract
    assert "media_references" not in contract
    assert "original_csr_reply" not in contract
    assert "supervisor_evaluation" not in contract


def test_convert_reviewed_only_previews_and_does_not_move_status(monkeypatch):
    factory = _session_factory(monkeypatch)
    db = factory()
    db.add(_sample())
    db.commit()
    db.close()

    result = TrainingSampleEvalSetService().convert_reviewed()

    assert result.converted == 0
    assert result.skipped == 1
    assert result.items[0]["contract"]["customer_said"]
    assert result.items[0]["contract"]["suggested_answer"]
    db = factory()
    row = db.query(KBTrainingSample).one()
    assert row.review_status == REVIEWED_STATUS
    assert row.get_eval_contract() == {}
    assert row.eval_created_at is None
    db.close()


def test_convert_curated_sample_moves_text_contract_to_eval_set(monkeypatch):
    factory = _session_factory(monkeypatch)
    db = factory()
    db.add(_sample())
    db.commit()
    db.close()

    contract = {
        "customer_said": "customer asks how to handle mismatch",
        "suggested_answer": "ask for manual screenshot and item photo before giving solution",
        "curated_by": "codex",
        "conversation_turns": [{"role": "buyer", "text": "old field should not be stored"}],
        "media_references": [{"kind": "attachment", "attachment_id": 1}],
    }
    result = TrainingSampleEvalSetService().convert_curated_sample(1, contract=contract)

    assert result["converted"] is True
    db = factory()
    row = db.query(KBTrainingSample).one()
    saved = row.get_eval_contract()
    assert row.review_status == EVAL_SET_STATUS
    assert saved["customer_said"] == contract["customer_said"]
    assert saved["suggested_answer"] == contract["suggested_answer"]
    assert sorted(saved.keys()) == ["customer_said", "suggested_answer"]
    assert "conversation_turns" not in saved
    assert "media_references" not in saved
    assert row.eval_created_at is not None
    db.close()


def test_curated_contract_requires_customer_said(monkeypatch):
    factory = _session_factory(monkeypatch)
    db = factory()
    db.add(_sample())
    db.commit()
    db.close()

    result = TrainingSampleEvalSetService().convert_curated_sample(
        1,
        contract={"suggested_answer": "answer only"},
    )

    assert result["converted"] is False
    assert result["reason"] == "missing_customer_said"
    db = factory()
    row = db.query(KBTrainingSample).one()
    assert row.review_status == REVIEWED_STATUS
    assert row.get_eval_contract() == {}
    db.close()


def test_curated_contract_requires_suggested_answer(monkeypatch):
    factory = _session_factory(monkeypatch)
    db = factory()
    db.add(_sample())
    db.commit()
    db.close()

    result = TrainingSampleEvalSetService().convert_curated_sample(
        1,
        contract={"customer_said": "customer text only"},
    )

    assert result["converted"] is False
    assert result["reason"] == "missing_suggested_answer"


def test_conversation_only_contract_is_rejected(monkeypatch):
    factory = _session_factory(monkeypatch)
    db = factory()
    db.add(_sample(correct_answer="", notes=""))
    db.commit()
    db.close()

    contract = {
        "conversation_turns": [
            {"role": "buyer", "text": "package is wrong"},
            {"role": "agent", "text": "please send label"},
        ],
        "expected_agent_turns": [
            {"customer_said": "label is gone", "expected_reply": "ask for received item photos"}
        ],
    }

    result = TrainingSampleEvalSetService().convert_curated_sample(1, contract=contract)

    assert result["converted"] is False
    assert result["reason"] == "missing_customer_said"


def test_image_only_preview_requires_manual_customer_text(monkeypatch):
    factory = _session_factory(monkeypatch)
    db = factory()
    db.add(_sample(
        customer_quote="[\u56fe\u7247\u6d88\u606f]",
        correct_answer="describe what buyer said from the screenshot before using this as eval",
        csr_actual_reply="",
        notes="",
    ))
    db.commit()
    db.close()

    result = TrainingSampleEvalSetService().convert_reviewed()

    assert result.converted == 0
    assert result.skipped == 1
    assert result.items[0]["reason"] == "missing_customer_said"
    assert result.items[0]["contract"]["customer_said"] == ""
    assert result.items[0]["contract"]["suggested_answer"]


def test_csr_reply_without_supervisor_guidance_is_not_used_as_suggested_answer(monkeypatch):
    factory = _session_factory(monkeypatch)
    db = factory()
    db.add(_sample(correct_answer="", notes="", csr_actual_reply="wrong but reviewed customer service reply"))
    db.commit()
    db.close()

    result = TrainingSampleEvalSetService().convert_reviewed()

    assert result.converted == 0
    assert result.skipped == 1
    assert result.items[0]["reason"] == "missing_suggested_answer"
    assert result.items[0]["contract"]["suggested_answer"] == ""
    db = factory()
    row = db.query(KBTrainingSample).one()
    assert row.review_status == REVIEWED_STATUS
    db.close()
