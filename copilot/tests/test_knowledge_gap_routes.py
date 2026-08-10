from flask import Flask
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import app.db as db_module
from app.api.eval_routes import eval_bp
from app.db import Base
from app.models.eval_tables import (
    EvalFailure,
    EvalRun,
    EvalTrace,
    KnowledgeGapDraft,
    KnowledgeGapPublishAudit,
    KnowledgeGapPublishQueue,
    KnowledgeGapTask,
)
from app.services.knowledge_gap_publish_queue_service import payload_fingerprint


def _make_client(monkeypatch):
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(autocommit=False, autoflush=False, bind=engine, expire_on_commit=False)
    monkeypatch.setattr(db_module, "SessionLocal", session_factory)
    app = Flask(__name__)
    app.register_blueprint(eval_bp)
    return app.test_client(), session_factory


def _seed_run(session_factory):
    db = session_factory()
    try:
        db.add(EvalRun(run_uid="kgap_route_run", source_type="real_conversation", status="completed"))
        trace = EvalTrace(
            run_uid="kgap_route_run",
            case_uid="case_route",
            turn_uid="turn_route",
            turn_index=1,
            buyer_message="手机号 13812345678，要安装视频",
            reference_human_reply="人工参考",
            agent_reply="Agent 回复 https://demo.oss-cn/a.jpg?Signature=secret&Expires=999",
            query_fact_type="installation",
            passed=False,
            requires_human_review=True,
        )
        trace.set_product_identity({"display_product_name": "收纳柜", "sku_code": "SKU-ROUTE"})
        trace.set_selected_evidence([])
        db.add(trace)
        db.add(EvalFailure(
            run_uid="kgap_route_run",
            case_uid="case_route",
            turn_uid="turn_route",
            failure_type="unsupported_media_claim",
            severity="high",
            suggested_fix_area="media_pipeline",
            suggested_owner="media_ops",
            message="video promise for 13812345678",
        ))
        db.commit()
    finally:
        db.close()


def test_knowledge_gap_routes_operator_read_and_supervisor_generate(monkeypatch, set_admin_test_principal):
    client, session_factory = _make_client(monkeypatch)
    _seed_run(session_factory)

    set_admin_test_principal("operator")
    assert client.get("/api/eval/knowledge-gaps", headers={"X-User-Role": "admin"}).status_code == 200
    forbidden = client.post(
        "/api/eval/knowledge-gaps/generate",
        json={"run_uid": "kgap_route_run"},
        headers={"X-User-Role": "admin"},
    )
    assert forbidden.status_code == 403

    set_admin_test_principal("supervisor")
    generated = client.post(
        "/api/eval/knowledge-gaps/generate",
        json={"run_uid": "kgap_route_run"},
        headers={"X-User-Role": "supervisor", "X-User-Name": "lead"},
    )
    assert generated.status_code == 201
    data = generated.get_json()
    task_uid = data["tasks"][0]["task_uid"]
    assert data["tasks"][0]["gap_type"] == "media_asset_gap"
    assert data["tasks"][0]["gap_category"] == "media_asset_gap"
    assert data["tasks"][0]["required_evidence_type"] == "installation_video"
    assert data["tasks"][0]["target_system"] == "kb_media_asset"

    db = session_factory()
    try:
        other = KnowledgeGapTask(
            task_uid="kgap_other_run",
            gap_type="product_field_gap",
            query_fact_type="material",
            missing_evidence_type="product_material",
            status="open",
            sample_count=1,
        )
        other.set_metadata({"source_run_uid": "other_run", "gap_category": "product_field_gap"})
        db.add(other)
        db.commit()
    finally:
        db.close()

    run_filtered = client.get(
        "/api/eval/knowledge-gaps?run_uid=kgap_route_run",
        headers={"X-User-Role": "operator"},
    )
    assert run_filtered.status_code == 200
    run_data = run_filtered.get_json()
    assert [item["task_uid"] for item in run_data["items"]] == [task_uid]
    assert run_data["summary"]["run_uid"] == "kgap_route_run"
    assert run_data["summary"]["filtered_by_run_uid"] is True
    assert run_data["summary"]["total"] == 1
    assert run_data["summary"]["by_gap_category"] == {"media_asset_gap": 1}

    unfiltered = client.get("/api/eval/knowledge-gaps", headers={"X-User-Role": "operator"})
    assert unfiltered.status_code == 200
    assert unfiltered.get_json()["summary"]["filtered_by_run_uid"] is False
    assert unfiltered.get_json()["summary"]["total"] == 2

    filtered = client.get(
        "/api/eval/knowledge-gaps?gap_category=media_asset_gap&required_evidence_type=installation_video&target_system=kb_media_asset",
        headers={"X-User-Role": "operator"},
    )
    assert filtered.status_code == 200
    assert len(filtered.get_json()["items"]) == 1

    detail = client.get(f"/api/eval/knowledge-gaps/{task_uid}", headers={"X-User-Role": "operator"})
    assert detail.status_code == 200
    raw = detail.get_data(as_text=True)
    assert "13812345678" not in raw
    assert "Signature=secret" not in raw

    draft = client.post(
        f"/api/eval/knowledge-gaps/{task_uid}/draft",
        headers={"X-User-Role": "admin", "X-User-Name": "qa"},
    )
    assert draft.status_code == 201
    assert draft.get_json()["draft"]["review_status"] == "pending_review"
    assert draft.get_json()["draft"]["publish_target"] == "staging"
    assert draft.get_json()["draft"]["draft_type"] == "media_asset_request"
    draft_content = draft.get_json()["draft"]["draft_content"]
    assert draft_content["publish_readiness"] == "needs_media_upload"
    assert draft_content["publish_payload"]["required_status"] == "approved"
    assert draft_content["publish_payload"]["required_usable"] is True
    assert draft_content["reviewer_checklist"]
    assert "http" not in str(draft_content["publish_payload"]).lower()

    duplicate_draft = client.post(
        f"/api/eval/knowledge-gaps/{task_uid}/draft",
        headers={"X-User-Role": "admin", "X-User-Name": "qa"},
    )
    assert duplicate_draft.status_code == 201
    assert duplicate_draft.get_json()["draft"]["draft_uid"] == draft.get_json()["draft"]["draft_uid"]

    forced_draft = client.post(
        f"/api/eval/knowledge-gaps/{task_uid}/draft",
        json={"force_regenerate": True},
        headers={"X-User-Role": "admin", "X-User-Name": "qa"},
    )
    assert forced_draft.status_code == 201
    assert forced_draft.get_json()["draft"]["draft_uid"] != draft.get_json()["draft"]["draft_uid"]

    db = session_factory()
    try:
        assert db.query(KnowledgeGapDraft).filter(KnowledgeGapDraft.task_uid == task_uid).count() == 2
    finally:
        db.close()

    mark_ready = client.post(
        f"/api/eval/knowledge-gaps/{task_uid}/draft/mark-ready",
        headers={"X-User-Role": "supervisor", "X-User-Name": "qa"},
    )
    assert mark_ready.status_code == 400
    assert "not ready" in mark_ready.get_json()["error"]

    set_admin_test_principal("operator")
    forbidden_review = client.post(
        f"/api/eval/knowledge-gaps/{task_uid}/draft/{forced_draft.get_json()['draft']['draft_uid']}/review",
        json={"decision": "approve_for_queue"},
        headers={"X-User-Role": "operator"},
    )
    assert forbidden_review.status_code == 403

    set_admin_test_principal("supervisor")
    approve_for_queue = client.post(
        f"/api/eval/knowledge-gaps/{task_uid}/draft/{forced_draft.get_json()['draft']['draft_uid']}/review",
        json={
            "decision": "approve_for_queue",
            "review_note": "approved upload request for queue",
            "verified_payload": {
                "asset_type": "video",
                "media_purpose": "installation",
                "answer_scenarios": ["installation help"],
                "bind_to_sku": "SKU-ROUTE",
                "asset_source_note": "review folder upload pending",
                "reviewer_confirms_upload_required": True,
                "review_checklist": {"asset_scope_verified": True, "source_attached": True},
            },
        },
        headers={"X-User-Role": "supervisor", "X-User-Name": "qa"},
    )
    assert approve_for_queue.status_code == 200
    queue_item = approve_for_queue.get_json()["queue_item"]
    assert queue_item["publish_target"] == "kb_media_asset"
    assert queue_item["status"] == "queued"
    assert approve_for_queue.get_json()["draft"]["review_status"] == "approved_for_queue"
    assert approve_for_queue.get_json()["task"]["status"] == "queued_for_publish"

    detail_after_draft = client.get(f"/api/eval/knowledge-gaps/{task_uid}", headers={"X-User-Role": "operator"})
    assert detail_after_draft.status_code == 200
    assert detail_after_draft.get_json()["task"]["status"] == "queued_for_publish"
    assert detail_after_draft.get_json()["drafts"]
    detail_draft_content = detail_after_draft.get_json()["drafts"][0]["draft_content"]
    assert detail_draft_content["publish_readiness"] == "needs_media_upload"
    assert detail_draft_content["publish_payload"]
    assert detail_draft_content["reviewer_checklist"]

    queue_list = client.get("/api/eval/knowledge-gap-publish-queue", headers={"X-User-Role": "supervisor"})
    assert queue_list.status_code == 200
    assert queue_list.get_json()["summary"]["total"] == 1
    assert queue_list.get_json()["items"][0]["queue_uid"] == queue_item["queue_uid"]

    dry_run = client.post(
        f"/api/eval/knowledge-gap-publish-queue/{queue_item['queue_uid']}/dry-run",
        headers={"X-User-Role": "supervisor", "X-User-Name": "qa"},
    )
    assert dry_run.status_code == 200
    assert dry_run.get_json()["dry_run"]["writes_formal_tables"] is False
    assert dry_run.get_json()["queue_item"]["publish_dry_run_status"] == "failed"
    assert dry_run.get_json()["queue_item"]["ready_for_publish"] is False
    assert any("needs_media_upload" in reason for reason in dry_run.get_json()["queue_item"]["publish_block_reasons"])

    export_preview = client.post(
        f"/api/eval/knowledge-gap-publish-queue/{queue_item['queue_uid']}/export-preview",
        headers={"X-User-Role": "supervisor"},
    )
    assert export_preview.status_code == 200
    assert export_preview.get_json()["dry_run"] is True
    assert export_preview.get_json()["writes_formal_tables"] is False
    assert export_preview.get_json()["publish_dry_run_status"] == "failed"
    assert export_preview.get_json()["ready_for_publish"] is False
    assert export_preview.get_json()["pre_publish_retest_status"] == "not_run"
    assert export_preview.get_json()["approved_to_publish"] is False
    assert export_preview.get_json()["approval_status"] in {"not_ready", "dry_run_required"}

    mark_exported = client.patch(
        f"/api/eval/knowledge-gap-publish-queue/{queue_item['queue_uid']}",
        json={"status": "exported", "note": "offline export"},
        headers={"X-User-Role": "admin", "X-User-Name": "ops"},
    )
    assert mark_exported.status_code == 200
    assert mark_exported.get_json()["queue_item"]["status"] == "exported"
    assert mark_exported.get_json()["queue_item"]["export_status"] == "exported"
    assert mark_exported.get_json()["queue_item"]["exported_at"]

    published = client.patch(
        f"/api/eval/knowledge-gap-publish-queue/{queue_item['queue_uid']}",
        json={"status": "published"},
        headers={"X-User-Role": "admin"},
    )
    assert published.status_code == 400

    db = session_factory()
    try:
        assert db.query(KnowledgeGapPublishQueue).count() == 1
    finally:
        db.close()


def test_knowledge_gap_routes_update_approve_reject_verify(monkeypatch, set_admin_test_principal):
    client, session_factory = _make_client(monkeypatch)
    _seed_run(session_factory)
    set_admin_test_principal("supervisor")
    generated = client.post(
        "/api/eval/knowledge-gaps/generate",
        json={"run_uid": "kgap_route_run"},
        headers={"X-User-Role": "supervisor", "X-User-Name": "lead"},
    )
    task_uid = generated.get_json()["tasks"][0]["task_uid"]

    update = client.patch(
        f"/api/eval/knowledge-gaps/{task_uid}",
        json={"priority": "high", "suggested_owner": "media_lead"},
        headers={"X-User-Role": "supervisor"},
    )
    assert update.status_code == 200
    assert update.get_json()["task"]["suggested_owner"] == "media_lead"

    set_admin_test_principal("operator")
    forbidden_triage = client.patch(
        f"/api/eval/knowledge-gaps/{task_uid}/triage",
        json={"review_decision": "upload_media_asset"},
        headers={"X-User-Role": "operator"},
    )
    assert forbidden_triage.status_code == 403

    set_admin_test_principal("supervisor")
    triage = client.patch(
        f"/api/eval/knowledge-gaps/{task_uid}/triage",
        json={
            "review_decision": "upload_media_asset",
            "assigned_team": "media_ops",
            "assigned_to": "media_lead",
            "priority": "high",
            "due_date": "2026-07-01",
            "review_note": "phone 13812345678 must stay masked",
            "next_action": "collect approved media",
        },
        headers={"X-User-Role": "supervisor", "X-User-Name": "lead"},
    )
    assert triage.status_code == 200
    triaged_task = triage.get_json()["task"]
    assert triaged_task["status"] == "triaged"
    assert triaged_task["review_decision"] == "upload_media_asset"
    assert triaged_task["assigned_team"] == "media_ops"
    assert triaged_task["assigned_to"] == "media_lead"
    assert "13812345678" not in triaged_task["review_note"]
    assert triaged_task["status_history"][-1]["status"] == "triaged"

    bad_triage = client.patch(
        f"/api/eval/knowledge-gaps/{task_uid}/triage",
        json={"review_decision": "publish_to_formal_kb"},
        headers={"X-User-Role": "supervisor"},
    )
    assert bad_triage.status_code == 400

    status_update = client.patch(
        f"/api/eval/knowledge-gaps/{task_uid}/status",
        json={"status": "waiting_data", "review_note": "need source file"},
        headers={"X-User-Role": "admin", "X-User-Name": "ops"},
    )
    assert status_update.status_code == 200
    assert status_update.get_json()["task"]["status"] == "waiting_data"

    client.post(f"/api/eval/knowledge-gaps/{task_uid}/draft", headers={"X-User-Role": "supervisor"})
    detail = client.get(f"/api/eval/knowledge-gaps/{task_uid}", headers={"X-User-Role": "operator"})
    assert detail.status_code == 200
    detail_data = detail.get_json()
    assert detail_data["review_metadata"]["review_decision"] == "upload_media_asset"
    assert detail_data["status_history"]
    assert detail_data["drafts"]
    assert detail_data["recommended_next_action"]

    approve = client.post(
        f"/api/eval/knowledge-gaps/{task_uid}/approve",
        headers={"X-User-Role": "supervisor", "X-User-Name": "lead"},
    )
    assert approve.status_code == 200
    assert approve.get_json()["task"]["status"] == "approved"

    verify = client.post(
        f"/api/eval/knowledge-gaps/{task_uid}/verify",
        headers={"X-User-Role": "admin", "X-User-Name": "lead"},
    )
    assert verify.status_code == 200
    verified_task = verify.get_json()["task"]
    assert verified_task["status"] == "resolved_pending_retest"
    assert verified_task["metadata"]["verification"]["verification_mode"] == "manual_staging_check"

    db = session_factory()
    try:
        assert db.query(KnowledgeGapTask).one().status == "resolved_pending_retest"
    finally:
        db.close()


def test_knowledge_gap_mark_ready_allows_verified_product_field_draft(monkeypatch, set_admin_test_principal):
    client, session_factory = _make_client(monkeypatch)
    db = session_factory()
    try:
        task = KnowledgeGapTask(
            task_uid="kgap_verified_product",
            gap_type="product_field_gap",
            query_fact_type="dimensions",
            missing_evidence_type="product_dimensions",
            status="open",
            sample_count=1,
            summary="verified product field gap",
        )
        task.set_metadata({
            "gap_category": "product_field_gap",
            "required_evidence_type": "product_dimensions",
            "target_system": "product_profile",
            "missing_fields": ["dimensions"],
            "evidence_status": "verified",
        })
        db.add(task)
        db.commit()
    finally:
        db.close()

    set_admin_test_principal("supervisor")
    draft = client.post(
        "/api/eval/knowledge-gaps/kgap_verified_product/draft",
        headers={"X-User-Role": "supervisor", "X-User-Name": "lead"},
    )
    assert draft.status_code == 201
    assert draft.get_json()["draft"]["draft_content"]["publish_readiness"] == "ready_for_review"

    mark_ready = client.post(
        "/api/eval/knowledge-gaps/kgap_verified_product/draft/mark-ready",
        headers={"X-User-Role": "supervisor", "X-User-Name": "lead"},
    )
    assert mark_ready.status_code == 200
    assert mark_ready.get_json()["task"]["status"] == "pending_review"
    assert mark_ready.get_json()["draft"]["review_status"] == "ready_for_review"

    set_admin_test_principal("operator")
    forbidden = client.post(
        "/api/eval/knowledge-gaps/kgap_verified_product/draft/mark-ready",
        headers={"X-User-Role": "operator"},
    )
    assert forbidden.status_code == 403


def test_publish_queue_routes_hide_and_block_superseded_items(monkeypatch):
    client, session_factory = _make_client(monkeypatch)
    db = session_factory()
    try:
        task = KnowledgeGapTask(
            task_uid="kgap_route_superseded",
            gap_type="product_field_gap",
            query_fact_type="dimensions",
            missing_evidence_type="product_dimensions",
            status="open",
            sample_count=1,
            summary="verified product field gap",
        )
        task.set_metadata({
            "gap_category": "product_field_gap",
            "required_evidence_type": "product_dimensions",
            "target_system": "product_profile",
            "missing_fields": ["dimensions"],
        })
        db.add(task)
        db.commit()
    finally:
        db.close()

    first_draft = client.post(
        "/api/eval/knowledge-gaps/kgap_route_superseded/draft",
        json={"force_regenerate": True},
        headers={"X-User-Role": "supervisor", "X-User-Name": "lead"},
    ).get_json()["draft"]
    first_review = client.post(
        f"/api/eval/knowledge-gaps/kgap_route_superseded/draft/{first_draft['draft_uid']}/review",
        json={
            "decision": "approve_for_queue",
            "verified_payload": {
                "product_identity": {"item_id": "item-001", "sku_code": "sku-001"},
                "fields": {"dimensions": "100x40x120cm"},
                "source_reference": "product manual page 3",
                "sku_scope": "sku-001 only",
                "reviewer_confirmation": True,
            },
            "review_checklist": {"product_verified": True, "source_attached": True},
        },
        headers={"X-User-Role": "supervisor", "X-User-Name": "lead"},
    )
    assert first_review.status_code == 200
    first_queue_uid = first_review.get_json()["queue_item"]["queue_uid"]

    second_draft = client.post(
        "/api/eval/knowledge-gaps/kgap_route_superseded/draft",
        json={"force_regenerate": True},
        headers={"X-User-Role": "supervisor", "X-User-Name": "lead"},
    ).get_json()["draft"]
    second_review = client.post(
        f"/api/eval/knowledge-gaps/kgap_route_superseded/draft/{second_draft['draft_uid']}/review",
        json={
            "decision": "approve_for_queue",
            "verified_payload": {
                "product_identity": {"item_id": "item-001", "sku_code": "sku-001"},
                "fields": {"dimensions": "120x45x160cm"},
                "source_reference": "product manual page 3",
                "sku_scope": "sku-001 only",
                "reviewer_confirmation": True,
            },
            "review_checklist": {"product_verified": True, "source_attached": True},
        },
        headers={"X-User-Role": "supervisor", "X-User-Name": "lead2"},
    )
    assert second_review.status_code == 200
    second_queue_uid = second_review.get_json()["queue_item"]["queue_uid"]

    default_list = client.get("/api/eval/knowledge-gap-publish-queue", headers={"X-User-Role": "supervisor"})
    assert default_list.status_code == 200
    assert [item["queue_uid"] for item in default_list.get_json()["items"]] == [second_queue_uid]
    assert default_list.get_json()["summary"]["active_count"] == 1
    assert default_list.get_json()["summary"]["superseded_count"] == 0

    included = client.get(
        "/api/eval/knowledge-gap-publish-queue?include_superseded=true",
        headers={"X-User-Role": "supervisor"},
    )
    assert included.status_code == 200
    assert {item["queue_uid"] for item in included.get_json()["items"]} == {first_queue_uid, second_queue_uid}
    assert included.get_json()["summary"]["active_count"] == 1
    assert included.get_json()["summary"]["superseded_count"] == 1

    preview = client.post(
        f"/api/eval/knowledge-gap-publish-queue/{first_queue_uid}/export-preview",
        headers={"X-User-Role": "supervisor"},
    )
    assert preview.status_code == 200
    assert preview.get_json()["blocked_reason"] == "superseded queue items cannot be exported"

    dry_run = client.post(
        f"/api/eval/knowledge-gap-publish-queue/{first_queue_uid}/dry-run",
        headers={"X-User-Role": "supervisor"},
    )
    assert dry_run.status_code == 400

    exported = client.patch(
        f"/api/eval/knowledge-gap-publish-queue/{first_queue_uid}",
        json={"status": "exported"},
        headers={"X-User-Role": "admin"},
    )
    assert exported.status_code == 400


def test_publish_simulation_route_requires_admin_and_adds_audit_to_preview(monkeypatch, set_admin_test_principal):
    client, session_factory = _make_client(monkeypatch)
    payload = {
        "product_identity": {"item_id": "item-001", "sku_code": "sku-001"},
        "fields": {"dimensions": "100x40x120cm"},
        "source_reference": "manual page 3",
    }
    fingerprint = payload_fingerprint("product_profile", payload)
    db = session_factory()
    try:
        queue_item = KnowledgeGapPublishQueue(
            queue_uid="kgpub_route_gate",
            task_uid="kgap_route_gate",
            draft_uid="kgdraft_route_gate",
            publish_target="product_profile",
            payload_fingerprint=fingerprint,
            reviewer="lead",
            risk_level="medium",
            status="queued",
            export_status="not_exported",
            publish_dry_run_status="passed",
            ready_for_publish=True,
            pre_publish_retest_status="passed",
            approved_to_publish=True,
            approval_status="approved_to_publish",
            locked_payload_fingerprint=fingerprint,
        )
        queue_item.set_payload(payload)
        db.add(queue_item)
        db.commit()
    finally:
        db.close()

    set_admin_test_principal("supervisor")
    supervisor = client.post(
        "/api/eval/knowledge-gap-publish-queue/kgpub_route_gate/simulate-publish",
        headers={"X-User-Role": "supervisor", "X-User-Name": "lead"},
    )
    assert supervisor.status_code == 403

    set_admin_test_principal("admin")
    admin = client.post(
        "/api/eval/knowledge-gap-publish-queue/kgpub_route_gate/simulate-publish",
        headers={"X-User-Role": "admin", "X-User-Name": "admin"},
    )
    assert admin.status_code == 200
    data = admin.get_json()
    assert data["ok"] is True
    assert data["writes_formal_tables"] is False
    assert data["transaction_plan"]["plan_version"] == "v1"
    assert data["transaction_plan"]["publish_enabled"] is False
    assert data["transaction_plan"]["steps"][1]["target_table"] == "kb_product"
    assert data["audit_uid"]

    preview = client.post(
        "/api/eval/knowledge-gap-publish-queue/kgpub_route_gate/export-preview",
        headers={"X-User-Role": "supervisor"},
    )
    assert preview.status_code == 200
    latest_audit = preview.get_json()["latest_publish_audit"]
    assert latest_audit["audit_uid"] == data["audit_uid"]
    assert latest_audit["status"] == "passed"
    assert latest_audit["writes_formal_tables"] is False

    db = session_factory()
    try:
        audit = db.query(KnowledgeGapPublishAudit).filter(KnowledgeGapPublishAudit.audit_uid == data["audit_uid"]).one()
        assert audit.status == "passed"
        assert audit.writes_formal_tables is False
    finally:
        db.close()


def test_publish_capabilities_route_is_supervisor_readable(monkeypatch, set_admin_test_principal):
    client, _session_factory = _make_client(monkeypatch)

    set_admin_test_principal("operator")
    operator = client.get(
        "/api/eval/knowledge-gap-publish-capabilities",
        headers={"X-User-Role": "operator"},
    )
    assert operator.status_code == 403

    set_admin_test_principal("supervisor")
    supervisor = client.get(
        "/api/eval/knowledge-gap-publish-capabilities",
        headers={"X-User-Role": "supervisor"},
    )
    assert supervisor.status_code == 200
    data = supervisor.get_json()
    assert data["plan_version"] == "v1"
    assert data["publish_enabled"] is False
    assert data["writes_formal_tables"] is False
    for target in [
        "product_profile",
        "kb_product",
        "kb_media_asset",
        "activity_rules",
        "aftersales_policy",
        "context_extractor",
    ]:
        assert target in data["targets"]
        assert data["targets"][target]["supports_formal_publish"] is False
