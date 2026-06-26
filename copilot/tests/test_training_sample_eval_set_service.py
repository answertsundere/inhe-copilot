from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.models.kb_tables import KBTrainingSample, KBTrainingSampleAttachment
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


def test_build_eval_contract_uses_supervisor_review_as_contract_not_knowledge():
    sample = _sample(order_no="512345678900001", need_media=True)

    contract = build_eval_contract(sample)

    assert contract["source"] == "training_sample_review"
    assert contract["expected_fact_type"] == "aftersales_policy"
    assert contract["supervisor_evaluation"]
    assert contract["conversation_context_text"]
    assert contract["conversation_turns"] == []
    assert contract["expected_agent_turns"] == []
    assert contract["must_do"]
    assert contract["needs_order_context"] is True
    assert contract["needs_media_understanding"] is True
    assert contract["can_auto_score"] is True


def test_convert_reviewed_only_previews_and_does_not_move_status(monkeypatch):
    factory = _session_factory(monkeypatch)
    db = factory()
    db.add(_sample())
    db.commit()
    db.close()

    result = TrainingSampleEvalSetService().convert_reviewed()

    assert result.converted == 0
    assert result.skipped == 1
    assert result.items[0]["contract"]["must_do"]
    db = factory()
    row = db.query(KBTrainingSample).one()
    assert row.review_status == REVIEWED_STATUS
    assert row.get_eval_contract() == {}
    assert row.eval_created_at is None
    db.close()


def test_convert_curated_sample_moves_it_to_eval_set(monkeypatch):
    factory = _session_factory(monkeypatch)
    db = factory()
    db.add(_sample())
    db.commit()
    db.close()

    contract = {
        "customer_message": "customer asks how to handle mismatch",
        "expected_fact_type": "aftersales_policy",
        "supervisor_evaluation": "ask for manual screenshot and item photo before giving solution",
        "must_do": ["ask for manual screenshot and item photo before giving solution"],
        "must_not_do": ["do not copy the wrong customer service reply"],
        "can_auto_score": True,
        "curated_by": "codex",
    }
    result = TrainingSampleEvalSetService().convert_curated_sample(1, contract=contract)

    assert result["converted"] is True
    db = factory()
    row = db.query(KBTrainingSample).one()
    assert row.review_status == EVAL_SET_STATUS
    assert row.get_eval_contract()["source"] == "training_sample_manual_eval_curation"
    assert row.get_eval_contract()["must_do"]
    assert row.eval_created_at is not None
    db.close()


def test_convert_curated_conversation_eval_set_does_not_require_supervisor_field(monkeypatch):
    factory = _session_factory(monkeypatch)
    db = factory()
    db.add(_sample(correct_answer="", notes=""))
    db.commit()
    db.close()

    contract = {
        "conversation_context_text": "buyer: package is wrong\nagent: please send label\nbuyer: label is gone",
        "conversation_turns": [
            {"role": "buyer", "text": "package is wrong"},
            {"role": "agent", "text": "please send label"},
            {"role": "buyer", "text": "label is gone"},
        ],
        "expected_agent_turns": [
            {
                "after_customer_turn": 3,
                "customer_said": "label is gone",
                "expected_reply": "ask buyer to photograph all received items and then verify mismatch",
                "must_do": ["ask for photos of all received items", "verify before offering solution"],
            }
        ],
        "media_references": [
            {"kind": "attachment", "attachment_id": 1, "role": "conversation_evidence_for_vision_eval"}
        ],
    }

    result = TrainingSampleEvalSetService().convert_curated_sample(1, contract=contract)

    assert result["converted"] is True
    db = factory()
    row = db.query(KBTrainingSample).one()
    saved = row.get_eval_contract()
    assert row.review_status == EVAL_SET_STATUS
    assert saved["source"] == "training_sample_manual_eval_curation"
    assert saved["expected_agent_turns"][0]["expected_reply"]
    assert saved["media_references"][0]["role"] == "conversation_evidence_for_vision_eval"
    db.close()


def test_image_only_sample_without_supervisor_guidance_is_skipped(monkeypatch):
    factory = _session_factory(monkeypatch)
    db = factory()
    sample = _sample(
        customer_quote="[\u56fe\u7247\u6d88\u606f]",
        correct_answer="",
        csr_actual_reply="",
        notes="",
    )
    db.add(sample)
    db.flush()
    db.add(KBTrainingSampleAttachment(
        sample_id=sample.id,
        field_name="full_context",
        original_filename="image.png",
        stored_filename="image.png",
        file_path="/tmp/image.png",
        file_size=100,
        mime_type="image/png",
    ))
    db.commit()
    db.close()

    result = TrainingSampleEvalSetService().convert_reviewed()

    assert result.converted == 0
    assert result.skipped == 1
    assert result.items[0]["reason"] == "missing_supervisor_guidance"
    db = factory()
    row = db.query(KBTrainingSample).one()
    assert row.review_status == REVIEWED_STATUS
    db.close()


def test_csr_reply_without_supervisor_guidance_is_not_used_as_eval_contract(monkeypatch):
    factory = _session_factory(monkeypatch)
    db = factory()
    db.add(_sample(correct_answer="", notes="", csr_actual_reply="wrong but reviewed customer service reply"))
    db.commit()
    db.close()

    result = TrainingSampleEvalSetService().convert_reviewed()

    assert result.converted == 0
    assert result.skipped == 1
    assert result.items[0]["reason"] == "missing_supervisor_guidance"
    assert result.items[0]["contract"]["must_do"] == []
    db = factory()
    row = db.query(KBTrainingSample).one()
    assert row.review_status == REVIEWED_STATUS
    db.close()
