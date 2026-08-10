from flask import Flask
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import app.db as db_module
import app.models.kb_tables  # noqa: F401 - register formal KB tables for negative write checks
from app.api.eval_routes import eval_bp
from app.db import Base
from app.models.eval_tables import (
    EvalCase,
    EvalConversationTurn,
    EvalRun,
    KnowledgeGapPublishQueue,
    KnowledgeGapTask,
    KnowledgeGapTaskSample,
)
from app.models.kb_tables import KBMediaAsset, KBProduct
from app.services.knowledge_gap_pre_publish_retest_service import KnowledgeGapPrePublishRetestService
from app.services.real_conversation_replay_service import RealConversationReplayService


def _session_factory():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    return sessionmaker(autocommit=False, autoflush=False, bind=engine, expire_on_commit=False)


def _make_client(monkeypatch):
    session_factory = _session_factory()
    monkeypatch.setattr(db_module, "SessionLocal", session_factory)
    app = Flask(__name__)
    app.register_blueprint(eval_bp)
    return app.test_client(), session_factory


def _seed_queue(session_factory, *, queue_status="queued", dry_run_passed=True, related_turns=None):
    related_turns = related_turns if related_turns is not None else ["turn_prepub_1", "turn_prepub_2"]
    db = session_factory()
    try:
        db.add(EvalRun(run_uid="source_run_prepub", source_type="real_conversation", status="completed"))
        case = EvalCase(case_uid="case_prepub_1", source_type="real_conversation", status="active")
        case.message = "material questions"
        case.set_metadata({
            "real_context": {
                "conversation_type": "presales",
                "product": {"product_title": "storage item", "sku_code": "SKU-PREPUB"},
                "order": {},
                "media": {"image_urls": [], "video_urls": []},
            }
        })
        db.add(case)
        db.add_all([
            EvalConversationTurn(
                case_uid="case_prepub_1",
                conversation_uid="conv_prepub_1",
                turn_uid="turn_prepub_1",
                turn_index=0,
                speaker="buyer",
                sanitized_text="材质安全吗",
            ),
            EvalConversationTurn(
                case_uid="case_prepub_1",
                conversation_uid="conv_prepub_1",
                turn_uid="turn_prepub_2",
                turn_index=1,
                speaker="buyer",
                sanitized_text="会不会受潮",
            ),
            EvalConversationTurn(
                case_uid="case_prepub_1",
                conversation_uid="conv_prepub_1",
                turn_uid="turn_unrelated",
                turn_index=2,
                speaker="buyer",
                sanitized_text="unrelated",
            ),
        ])
        task = KnowledgeGapTask(
            task_uid="kgap_prepub_1",
            gap_type="product_field_gap",
            query_fact_type="material",
            failure_type="rag_miss",
            suggested_fix_area="knowledge_rag",
            suggested_owner="knowledge_ops",
            missing_evidence_type="product_material",
            status="queued_for_publish",
            sample_count=len(related_turns),
        )
        task.set_related_case_uids(["case_prepub_1"] if related_turns else [])
        task.set_related_turn_uids(related_turns)
        task.set_metadata({
            "source_run_uid": "source_run_prepub",
            "gap_category": "product_field_gap",
            "required_evidence_type": "product_material",
        })
        db.add(task)
        for turn_uid in related_turns:
            db.add(KnowledgeGapTaskSample(
                task_uid="kgap_prepub_1",
                run_uid="source_run_prepub",
                case_uid="case_prepub_1",
                turn_uid=turn_uid,
                buyer_message="buyer",
                agent_reply="agent",
                failure_type="rag_miss",
                query_fact_type="material",
            ))
        item = KnowledgeGapPublishQueue(
            queue_uid="kgpub_prepub_1",
            task_uid="kgap_prepub_1",
            draft_uid="kgdraft_prepub_1",
            source_run_uid="source_run_prepub",
            publish_target="product_profile",
            payload_fingerprint="fingerprint-current",
            status=queue_status,
            export_status="not_exported",
            reviewer="lead",
        )
        item.publish_dry_run_status = "passed" if dry_run_passed else "failed"
        item.ready_for_publish = bool(dry_run_passed)
        item.approval_status = "retest_required" if dry_run_passed else "dry_run_required"
        item.set_payload({
            "product_identity": {"item_id": "item-prepub", "sku_code": "SKU-PREPUB"},
            "fields": {"material": "verified material"},
        })
        db.add(item)
        db.commit()
        return item.queue_uid
    finally:
        db.close()


def _passing_agent(self, payload):
    return {
        "suggested_reply": "material answer with verified evidence",
        "requires_human_review": False,
        "evidence_debug": {
            "query_fact_type": "material",
            "selected_evidence": [{"fact_type": "material", "content": "verified material"}],
        },
        "answer_trace": {
            "query_fact_type": "material",
            "required_fact_types": ["material"],
            "evidence_answered_fact_types": ["material"],
        },
        "final_answer_audit": {"passed": True},
    }


def _failing_agent(self, payload):
    return {
        "suggested_reply": "generic fallback",
        "requires_human_review": False,
        "evidence_debug": {"query_fact_type": "material", "selected_evidence": []},
        "answer_trace": {"query_fact_type": "material", "required_fact_types": ["material"]},
        "final_answer_audit": {"passed": False},
    }


def test_pre_publish_retest_requires_dry_run_passed(monkeypatch):
    session_factory = _session_factory()
    monkeypatch.setattr(db_module, "SessionLocal", session_factory)
    _seed_queue(session_factory, dry_run_passed=False)

    try:
        KnowledgeGapPrePublishRetestService().run("kgpub_prepub_1", triggered_by="lead")
        assert False, "expected dry-run guard to reject retest"
    except ValueError as exc:
        assert "dry-run" in str(exc)


def test_superseded_queue_item_retest_is_rejected(monkeypatch):
    session_factory = _session_factory()
    monkeypatch.setattr(db_module, "SessionLocal", session_factory)
    _seed_queue(session_factory, queue_status="superseded", dry_run_passed=True)

    try:
        KnowledgeGapPrePublishRetestService().preview("kgpub_prepub_1")
        assert False, "expected superseded guard to reject retest"
    except ValueError as exc:
        assert "superseded" in str(exc)


def test_pre_publish_retest_without_related_samples_cannot_approve(monkeypatch):
    session_factory = _session_factory()
    monkeypatch.setattr(db_module, "SessionLocal", session_factory)
    _seed_queue(session_factory, related_turns=[])

    try:
        KnowledgeGapPrePublishRetestService().preview("kgpub_prepub_1")
        assert False, "expected missing samples to block retest"
    except ValueError as exc:
        assert "related" in str(exc)


def test_pre_publish_retest_preview_does_not_create_eval_run(monkeypatch):
    session_factory = _session_factory()
    monkeypatch.setattr(db_module, "SessionLocal", session_factory)
    _seed_queue(session_factory)

    preview = KnowledgeGapPrePublishRetestService().preview("kgpub_prepub_1")

    assert preview["dry_run"] is True
    assert preview["sample_count"] == 2
    assert preview["checked_turn_uids"] == ["turn_prepub_1", "turn_prepub_2"]
    db = session_factory()
    try:
        assert db.query(EvalRun).count() == 1
    finally:
        db.close()


def test_pre_publish_retest_failure_blocks_publish_approval(monkeypatch):
    session_factory = _session_factory()
    monkeypatch.setattr(db_module, "SessionLocal", session_factory)
    _seed_queue(session_factory)
    monkeypatch.setattr(RealConversationReplayService, "_call_agent", _failing_agent)

    result = KnowledgeGapPrePublishRetestService().run("kgpub_prepub_1", triggered_by="lead")

    assert result["ok"] is False
    assert result["queue_item"]["pre_publish_retest_status"] == "failed"
    assert result["queue_item"]["approved_to_publish"] is False
    assert result["queue_item"]["approval_status"] == "retest_required"
    assert result["queue_item"]["pre_publish_block_reasons"]
    assert "semantic_mismatch" in result["summary"]["remaining_failure_types"]


def test_pre_publish_retest_passed_locks_payload_fingerprint(monkeypatch):
    session_factory = _session_factory()
    monkeypatch.setattr(db_module, "SessionLocal", session_factory)
    _seed_queue(session_factory)
    monkeypatch.setattr(RealConversationReplayService, "_call_agent", _passing_agent)

    result = KnowledgeGapPrePublishRetestService().run("kgpub_prepub_1", triggered_by="lead")

    assert result["ok"] is True
    assert result["queue_item"]["pre_publish_retest_status"] == "passed"
    assert result["queue_item"]["approved_to_publish"] is True
    assert result["queue_item"]["approval_status"] == "approved_to_publish"
    assert result["queue_item"]["locked_payload_fingerprint"] == "fingerprint-current"
    assert result["summary"]["failed_turns"] == 0
    db = session_factory()
    try:
        assert db.query(KBProduct).count() == 0
        assert db.query(KBMediaAsset).count() == 0
    finally:
        db.close()


def test_pre_publish_retest_api_permissions_preview_and_apply(monkeypatch, set_admin_test_principal):
    client, session_factory = _make_client(monkeypatch)
    _seed_queue(session_factory)
    monkeypatch.setattr(RealConversationReplayService, "_call_agent", _passing_agent)

    set_admin_test_principal("operator")
    forbidden = client.post(
        "/api/eval/knowledge-gap-publish-queue/kgpub_prepub_1/pre-publish-retest",
        headers={"X-User-Role": "admin"},
    )
    assert forbidden.status_code == 403

    set_admin_test_principal("supervisor")
    preview = client.post(
        "/api/eval/knowledge-gap-publish-queue/kgpub_prepub_1/pre-publish-retest-preview",
        headers={"X-User-Role": "operator"},
    )
    assert preview.status_code == 200
    assert preview.get_json()["sample_count"] == 2
    db = session_factory()
    try:
        assert db.query(EvalRun).count() == 1
    finally:
        db.close()

    set_admin_test_principal("admin")
    retest = client.post(
        "/api/eval/knowledge-gap-publish-queue/kgpub_prepub_1/pre-publish-retest",
        headers={"X-User-Role": "operator", "X-User-Name": "spoofed"},
    )
    assert retest.status_code == 200
    assert retest.get_json()["queue_item"]["approved_to_publish"] is True
    assert retest.get_json()["summary"]["total_turns"] == 2
