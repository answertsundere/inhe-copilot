from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import app.db as db_module
from app.db import Base
from app.models.eval_tables import EvalCase, EvalConversationTurn, EvalFailure, EvalRun, EvalTrace
from app.services.real_conversation_replay_service import RealConversationReplayService, ReplayOptions
from app.services.real_conversation_replay_service import classify_turn_failures
from app.services.real_conversation_replay_service import evaluate_replay_turn_result


def _patch_test_db(monkeypatch):
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(autocommit=False, autoflush=False, bind=engine, expire_on_commit=False)
    monkeypatch.setattr(db_module, "SessionLocal", session_factory)
    return session_factory


def _product_real_context():
    return {
        "conversation_type": "presales",
        "source_page": "product_detail",
        "product": {
            "product_title": "children storage cabinet",
            "sku_code": "SKU-TEST",
        },
        "order": {},
        "media": {"image_urls": [], "video_urls": []},
        "raw_context_sources": ["product_title", "sku_code"],
    }


def _order_real_context():
    return {
        "conversation_type": "aftersales",
        "source_page": "order_detail",
        "product": {
            "product_title": "children storage cabinet",
            "sku_code": "SKU-TEST",
        },
        "order": {
            "order_id_hash": "hash-order",
            "order_id_masked": "123***7890",
            "order_product_title": "children storage cabinet",
            "order_sku_code": "SKU-TEST",
        },
        "media": {"image_urls": [], "video_urls": []},
        "raw_context_sources": ["order_id", "order_product_title", "sku_code"],
    }

def _seed_case(session_factory):
    db = session_factory()
    try:
        case = EvalCase(case_uid="case_real_1", source_type="real_conversation", message="材质安全吗")
        case.set_metadata({"real_context": _product_real_context()})
        db.add(case)
        db.add_all([
            EvalConversationTurn(
                case_uid="case_real_1",
                conversation_uid="conv_real_1",
                turn_uid="turn_buyer_1",
                turn_index=0,
                speaker="buyer",
                sanitized_text="这个材质安全吗？",
                reference_human_reply="材质以页面资料为准。",
            ),
            EvalConversationTurn(
                case_uid="case_real_1",
                conversation_uid="conv_real_1",
                turn_uid="turn_service_1",
                turn_index=1,
                speaker="service",
                sanitized_text="材质以页面资料为准。",
            ),
            EvalConversationTurn(
                case_uid="case_real_1",
                conversation_uid="conv_real_1",
                turn_uid="turn_buyer_2",
                turn_index=2,
                speaker="buyer",
                sanitized_text="会不会容易受潮？",
                reference_human_reply="建议保持干燥。",
            ),
        ])
        db.commit()
    finally:
        db.close()


def test_replay_keeps_history_out_of_current_message_and_stores_trace(monkeypatch):
    session_factory = _patch_test_db(monkeypatch)
    _seed_case(session_factory)
    payloads = []

    class FakeReplayService(RealConversationReplayService):
        def _call_agent(self, payload):
            payloads.append(payload)
            return {
                "suggested_reply": "材质按资料说明，不建议长期受潮。",
                "requires_human_review": False,
                "evidence_debug": {
                    "query_fact_type": "material",
                    "selected_evidence": [{"fact_type": "material", "content": "板材说明"}],
                    "rejected_evidence": [],
                },
                "answer_trace": {
                    "query_fact_type": "material",
                    "required_fact_types": ["material"],
                    "evidence_answered_fact_types": ["material"],
                },
                "final_answer_audit": {"passed": True},
            }

    result = FakeReplayService().replay_cases(ReplayOptions(run_uid="run_test_1"))

    assert result["status"] == "completed"
    assert len(payloads) == 2
    assert payloads[1]["message"] == "会不会容易受潮？"
    assert "这个材质安全吗" not in payloads[1]["message"]
    assert payloads[1]["copilot_context"]["conversation_history"]

    db = session_factory()
    try:
        run = db.query(EvalRun).filter(EvalRun.run_uid == "run_test_1").one()
        traces = db.query(EvalTrace).order_by(EvalTrace.turn_index).all()
        assert run.total_turns == 2
        assert len(traces) == 2
        assert traces[0].query_fact_type == "material"
        assert traces[0].get_selected_evidence()[0]["fact_type"] == "material"
        assert traces[0].get_answer_trace()["required_fact_types"] == ["material"]
        assert db.query(EvalFailure).count() == 0
    finally:
        db.close()


def test_replay_passes_structured_real_context_to_agent_and_trace(monkeypatch):
    session_factory = _patch_test_db(monkeypatch)
    db = session_factory()
    try:
        real_context = {
            "conversation_type": "mixed",
            "source_page": "order_detail",
            "product": {
                "item_id": "123456789",
                "item_id_hash": "hash-item",
                "item_id_masked": "123***6789",
                "product_url": "https://item.taobao.com/item.htm?id=123456789",
                "product_title": "儿童书架收纳柜",
                "sku_code": "SKU-A1",
            },
            "order": {
                "order_id": "123***2345",
                "order_id_hash": "hash-order",
                "order_id_masked": "123***2345",
                "order_product_title": "儿童书架收纳柜",
                "order_sku_code": "SKU-A1",
            },
            "media": {
                "image_urls": [],
                "video_urls": ["https://demo.example.com/install.mp4"],
            },
            "raw_context_sources": ["product_url", "order_id", "media_url:video"],
        }
        case = EvalCase(case_uid="case_ctx_1", source_type="real_conversation", message="这个视频不一样")
        case.set_metadata({"real_context": real_context})
        turn = EvalConversationTurn(
            case_uid="case_ctx_1",
            conversation_uid="conv_ctx_1",
            turn_uid="turn_ctx_1",
            turn_index=0,
            speaker="buyer",
            sanitized_text="这个视频和我买的不一样",
            reference_human_reply="我帮您核对",
        )
        turn.set_metadata({"real_context": real_context})
        db.add(case)
        db.add(turn)
        db.commit()
    finally:
        db.close()

    payloads = []

    class ContextReplayService(RealConversationReplayService):
        def _call_agent(self, payload):
            payloads.append(payload)
            return {
                "suggested_reply": "这个需要人工核对资料和实物是否一致。",
                "requires_human_review": True,
                "query_fact_type": "aftersales",
                "evidence_debug": {"query_fact_type": "aftersales", "selected_evidence": []},
                "answer_trace": {"query_fact_type": "aftersales", "required_fact_types": ["aftersales"]},
            }

    ContextReplayService().replay_cases(ReplayOptions(run_uid="run_ctx_1"))

    assert len(payloads) == 1
    payload = payloads[0]
    assert payload["product_name"] == "儿童书架收纳柜"
    assert any(candidate.get("item_id") == "123456789" for candidate in payload["product_candidates"])
    assert payload["copilot_context"]["source_page"] == "order_detail"
    assert payload["copilot_context"]["conversation_type"] == "mixed"
    assert payload["copilot_context"]["item_id"] == "123456789"
    assert payload["copilot_context"]["order_id_hash"] == "hash-order"
    assert payload["copilot_context"]["media_context"]["video_urls"] == ["https://demo.example.com/install.mp4"]
    assert payload["copilot_context"]["real_context_summary"]["has_product_context"] is True
    assert payload["copilot_context"]["real_context_product_identity"]["has_resolved_product_context"] is True
    assert "123456789012345" not in str(payload)

    db = session_factory()
    try:
        trace = db.query(EvalTrace).one()
        context_summary = trace.get_answer_trace()["real_context"]
        assert context_summary["source_page"] == "order_detail"
        assert context_summary["conversation_type"] == "mixed"
        assert context_summary["has_product_context"] is True
        assert context_summary["has_order_context"] is True
        assert context_summary["has_media_context"] is True
        answer_trace = trace.get_answer_trace()
        assert answer_trace["real_context_product_identity"]["has_resolved_product_context"] is True
        assert answer_trace["conversation_media_reference"]["media_context_count"] == 1
        assert context_summary["product_title_preview"] == "儿童书架收纳柜"
    finally:
        db.close()


def test_replay_records_failure_when_agent_requires_review(monkeypatch):
    session_factory = _patch_test_db(monkeypatch)
    _seed_case(session_factory)

    class ReviewReplayService(RealConversationReplayService):
        def _call_agent(self, payload):
            return {
                "suggested_reply": "这个需要人工确认。",
                "requires_human_review": True,
                "evidence_debug": {"query_fact_type": "material", "selected_evidence": []},
                "answer_trace": {"query_fact_type": "material", "required_fact_types": ["material"]},
            }

    result = ReviewReplayService().replay_cases(ReplayOptions(run_uid="run_review_1"))

    assert result["failed"] == 2
    db = session_factory()
    try:
        failures = db.query(EvalFailure).order_by(EvalFailure.id).all()
        labels = [row.failure_type for row in failures]
        assert "needs_human_review" in labels
        assert "rag_miss" in labels
        by_type = {row.failure_type: row for row in failures}
        assert by_type["needs_human_review"].suggested_fix_area == "human_policy_risk_boundary"
        assert by_type["rag_miss"].suggested_fix_area == "knowledge_rag"
        assert by_type["rag_miss"].suggested_owner == "knowledge_ops"
        assert by_type["rag_miss"].explanation
        trace = db.query(EvalTrace).order_by(EvalTrace.id).first()
        bucket = trace.get_quality_bucket()
        assert bucket["quality_bucket"] == "knowledge_gap"
        assert bucket["is_knowledge_gap"] is True
        assert bucket["should_count_in_quality_rate"] is True
    finally:
        db.close()


def test_replay_context_gap_is_not_agent_accuracy_denominator(monkeypatch):
    session_factory = _patch_test_db(monkeypatch)
    db = session_factory()
    try:
        db.add(EvalCase(case_uid="case_context_gap", source_type="real_conversation", message="missing product"))
        db.add(EvalConversationTurn(
            case_uid="case_context_gap",
            conversation_uid="conv_context_gap",
            turn_uid="turn_context_gap",
            turn_index=0,
            speaker="buyer",
            sanitized_text="发一下安装视频",
        ))
        db.commit()
    finally:
        db.close()

    class ContextGapReplayService(RealConversationReplayService):
        def _call_agent(self, payload):
            return {
                "suggested_reply": "亲，这个需要人工核对对应款式后再发安装资料。",
                "requires_human_review": True,
                "query_fact_type": "installation",
                "evidence_debug": {"query_fact_type": "installation", "selected_evidence": []},
                "answer_trace": {"query_fact_type": "installation", "required_fact_types": ["installation"]},
            }

    result = ContextGapReplayService().replay_cases(ReplayOptions(run_uid="run_context_gap"))

    assert result["turns"] == 1
    assert result["context_gap"] == 1
    assert result["agent_accuracy_turns"] == 0
    assert result["agent_accuracy_passed"] == 0
    db = session_factory()
    try:
        trace = db.query(EvalTrace).one()
        bucket = trace.get_quality_bucket()
        assert bucket["quality_bucket"] == "context_gap"
        assert bucket["should_count_in_quality_rate"] is False
        assert trace.get_turn_understanding()["context_sufficiency"]["missing_context_fields"] == ["product"]
        labels = set(trace.get_failure_labels())
        assert "context_gap" in labels
        run = db.query(EvalRun).one()
        assert run.total_turns == 1
    finally:
        db.close()


def test_failure_classifier_covers_audit_policy_and_product_identity():
    failures = classify_turn_failures({
        "suggested_reply": "我先核实后回复。",
        "query_fact_type": "dimensions",
        "tool_policy_blocked": True,
        "product_identified": False,
        "final_answer_audit": {"passed": False},
        "evidence_debug": {"selected_evidence": []},
    })

    labels = {item["failure_type"] for item in failures}
    assert "semantic_mismatch" in labels
    assert "tool_policy_blocked" in labels
    assert "no_product_identified" in labels
    by_type = {item["failure_type"]: item for item in failures}
    assert by_type["semantic_mismatch"]["suggested_fix_area"] == "final_audit_semantic_compiler"
    assert by_type["tool_policy_blocked"]["suggested_owner"] == "agent_engineering"
    assert by_type["no_product_identified"]["explanation"]


def test_context_update_with_product_fact_reply_is_failed(monkeypatch):
    session_factory = _patch_test_db(monkeypatch)
    db = session_factory()
    try:
        case = EvalCase(case_uid="case_status_1", source_type="real_conversation", message="status")
        db.add(case)
        db.add(EvalConversationTurn(
            case_uid="case_status_1",
            conversation_uid="conv_status_1",
            turn_uid="turn_status_1",
            turn_index=0,
            speaker="buyer",
            sanitized_text="柜子我昨天收到已经装好了",
        ))
        db.commit()
    finally:
        db.close()

    payloads = []

    class WrongTopicReplayService(RealConversationReplayService):
        def _call_agent(self, payload):
            payloads.append(payload)
            return {
                "suggested_reply": "亲可以先量一下宽深高，再对照尺寸图确认摆放空间。",
                "requires_human_review": False,
                "query_fact_type": "",
                "evidence_debug": {
                    "query_fact_type": "",
                    "selected_evidence": [{"fact_type": "dimensions", "content": "尺寸图"}],
                },
                "answer_trace": {"query_fact_type": "", "required_fact_types": []},
                "final_answer_audit": {"passed": True, "expected_topics": []},
            }

    result = WrongTopicReplayService().replay_cases(ReplayOptions(run_uid="run_status_wrong_topic"))

    assert len(payloads) == 1
    assert payloads[0]["copilot_context"]["turn_understanding"]["turn_actionability"] == "context_update"
    assert result["failed"] == 1
    db = session_factory()
    try:
        trace = db.query(EvalTrace).one()
        assert trace.passed is False
        assert trace.get_turn_understanding()["needs_rag"] is False
        labels = set(trace.get_failure_labels())
        assert "wrong_topic_reply" in labels
        assert "query_fact_type_missing" in labels
        assert "unrequested_product_fact" in labels
        assert "unnecessary_rag_call" in labels
        bucket = trace.get_quality_bucket()
        assert bucket["quality_bucket"] == "agent_error"
        assert bucket["is_agent_error"] is True
        assert bucket["should_count_in_quality_rate"] is True
    finally:
        db.close()


def test_acknowledgement_is_traced_but_not_scored_or_sent_to_agent(monkeypatch):
    session_factory = _patch_test_db(monkeypatch)
    db = session_factory()
    try:
        db.add(EvalCase(case_uid="case_ack_1", source_type="real_conversation", message="ack"))
        db.add(EvalConversationTurn(
            case_uid="case_ack_1",
            conversation_uid="conv_ack_1",
            turn_uid="turn_ack_1",
            turn_index=0,
            speaker="buyer",
            sanitized_text="好的",
        ))
        db.commit()
    finally:
        db.close()

    class AckReplayService(RealConversationReplayService):
        def _call_agent(self, payload):
            raise AssertionError("acknowledgement turn should not call agent")

    result = AckReplayService().replay_cases(ReplayOptions(run_uid="run_ack_skip"))

    assert result["turns"] == 0
    assert result["passed"] == 0
    assert result["failed"] == 0
    db = session_factory()
    try:
        run = db.query(EvalRun).filter(EvalRun.run_uid == "run_ack_skip").one()
        trace = db.query(EvalTrace).one()
        assert run.total_turns == 0
        assert trace.get_turn_understanding()["turn_actionability"] == "acknowledgement"
        assert trace.get_turn_understanding()["should_score"] is False
        assert trace.get_failure_labels() == []
    finally:
        db.close()


def test_url_only_turn_is_traced_but_not_sent_to_agent(monkeypatch):
    session_factory = _patch_test_db(monkeypatch)
    db = session_factory()
    try:
        db.add(EvalCase(case_uid="case_url_1", source_type="real_conversation", message="url"))
        db.add(EvalConversationTurn(
            case_uid="case_url_1",
            conversation_uid="conv_url_1",
            turn_uid="turn_url_1",
            turn_index=0,
            speaker="buyer",
            sanitized_text="https://img.alicdn.com/imgextra/demo.jpg",
        ))
        db.commit()
    finally:
        db.close()

    class UrlReplayService(RealConversationReplayService):
        def _call_agent(self, payload):
            raise AssertionError("URL-only media reference should not call agent")

    result = UrlReplayService().replay_cases(ReplayOptions(run_uid="run_url_skip"))

    assert result["turns"] == 0
    assert result["passed"] == 0
    assert result["failed"] == 0
    db = session_factory()
    try:
        trace = db.query(EvalTrace).one()
        understanding = trace.get_turn_understanding()
        assert understanding["turn_actionability"] == "media_reference"
        assert understanding["should_score"] is False
        assert trace.agent_reply == ""
        assert trace.get_failure_labels() == []
    finally:
        db.close()


def test_media_reference_with_history_is_context_gap_without_agent_call(monkeypatch):
    session_factory = _patch_test_db(monkeypatch)
    db = session_factory()
    try:
        case = EvalCase(case_uid="case_media_ref_1", source_type="real_conversation", message="media")
        case.set_metadata({"real_context": _product_real_context()})
        db.add(case)
        db.add(EvalConversationTurn(
            case_uid="case_media_ref_1",
            conversation_uid="conv_media_ref_1",
            turn_uid="turn_media_service_1",
            turn_index=0,
            speaker="service",
            sanitized_text="请看图片确认位置",
        ))
        db.add(EvalConversationTurn(
            case_uid="case_media_ref_1",
            conversation_uid="conv_media_ref_1",
            turn_uid="turn_media_buyer_1",
            turn_index=1,
            speaker="buyer",
            sanitized_text="图里圈出来这块板",
        ))
        db.commit()
    finally:
        db.close()

    class MediaReferenceReplayService(RealConversationReplayService):
        def _call_agent(self, payload):
            raise AssertionError("non-question media reference should not call agent")

    result = MediaReferenceReplayService().replay_cases(ReplayOptions(run_uid="run_media_reference_context_gap"))

    assert result["failed"] == 1
    db = session_factory()
    try:
        trace = db.query(EvalTrace).filter(EvalTrace.turn_uid == "turn_media_buyer_1").one()
        understanding = trace.get_turn_understanding()
        assert understanding["turn_actionability"] == "media_reference"
        assert understanding["needs_agent_reply"] is False
        assert understanding["skip_reason"] == "context_insufficient"
        assert trace.agent_reply == ""
        assert "context_insufficient" in trace.get_failure_labels()
        assert trace.get_quality_bucket()["quality_bucket"] == "context_gap"
    finally:
        db.close()


def test_accessory_retention_update_skips_agent_without_answer_incomplete(monkeypatch):
    session_factory = _patch_test_db(monkeypatch)
    db = session_factory()
    try:
        case = EvalCase(case_uid="case_accessory_retention_1", source_type="real_conversation", message="retention")
        case.set_metadata({"real_context": _product_real_context()})
        db.add(case)
        db.add(EvalConversationTurn(
            case_uid="case_accessory_retention_1",
            conversation_uid="conv_accessory_retention_1",
            turn_uid="turn_accessory_retention_service_1",
            turn_index=0,
            speaker="service",
            sanitized_text="这个后面还会用到",
        ))
        db.add(EvalConversationTurn(
            case_uid="case_accessory_retention_1",
            conversation_uid="conv_accessory_retention_1",
            turn_uid="turn_accessory_retention_buyer_1",
            turn_index=1,
            speaker="buyer",
            sanitized_text="护栏后面还要用螺丝刀",
        ))
        db.commit()
    finally:
        db.close()

    class AccessoryRetentionReplayService(RealConversationReplayService):
        def _call_agent(self, payload):
            raise AssertionError("accessory retention context update should not call agent")

    result = AccessoryRetentionReplayService().replay_cases(ReplayOptions(run_uid="run_accessory_retention_context_update"))

    assert result["passed"] == 1
    db = session_factory()
    try:
        trace = db.query(EvalTrace).filter(EvalTrace.turn_uid == "turn_accessory_retention_buyer_1").one()
        understanding = trace.get_turn_understanding()
        labels = trace.get_failure_labels()
        assert understanding["turn_actionability"] == "context_update"
        assert understanding["needs_agent_reply"] is False
        assert trace.agent_reply == ""
        assert "answer_incomplete" not in labels
        assert trace.get_quality_bucket()["quality_bucket"] == "unscored_or_noise"
    finally:
        db.close()


def test_deictic_followup_without_context_fails_context_insufficient_without_agent(monkeypatch):
    session_factory = _patch_test_db(monkeypatch)
    db = session_factory()
    try:
        db.add(EvalCase(case_uid="case_deictic_1", source_type="real_conversation", message="deictic"))
        db.add(EvalConversationTurn(
            case_uid="case_deictic_1",
            conversation_uid="conv_deictic_1",
            turn_uid="turn_deictic_1",
            turn_index=0,
            speaker="buyer",
            sanitized_text="抽屉的也可以",
        ))
        db.commit()
    finally:
        db.close()

    class DeicticReplayService(RealConversationReplayService):
        def _call_agent(self, payload):
            raise AssertionError("context-insufficient deictic turn should not call agent")

    result = DeicticReplayService().replay_cases(ReplayOptions(run_uid="run_deictic_context_missing"))

    assert result["failed"] == 1
    db = session_factory()
    try:
        trace = db.query(EvalTrace).one()
        understanding = trace.get_turn_understanding()
        assert understanding["turn_actionability"] == "deictic_followup"
        assert understanding["needs_rag"] is False
        assert trace.passed is False
        assert "context_insufficient" in trace.get_failure_labels()
        assert trace.get_selected_evidence() == []
    finally:
        db.close()


def test_aftersales_refund_question_is_actionable_without_query_fact_type_missing(monkeypatch):
    session_factory = _patch_test_db(monkeypatch)
    db = session_factory()
    try:
        case = EvalCase(case_uid="case_refund_1", source_type="real_conversation", message="refund")
        case.set_metadata({"real_context": _order_real_context()})
        db.add(case)
        db.add(EvalConversationTurn(
            case_uid="case_refund_1",
            conversation_uid="conv_refund_1",
            turn_uid="turn_refund_1",
            turn_index=0,
            speaker="buyer",
            sanitized_text="可以退吗",
        ))
        db.commit()
    finally:
        db.close()

    payloads = []

    class RefundReplayService(RealConversationReplayService):
        def _call_agent(self, payload):
            payloads.append(payload)
            return {
                "suggested_reply": "可以帮您核实售后退换规则，请先提供订单信息。",
                "requires_human_review": False,
                "query_fact_type": "aftersales",
                "answer_trace": {"query_fact_type": "aftersales", "required_fact_types": ["aftersales"]},
                "final_answer_audit": {"passed": True, "expected_topics": ["aftersales"]},
            }

    result = RefundReplayService().replay_cases(ReplayOptions(run_uid="run_refund_actionable"))

    assert len(payloads) == 1
    assert payloads[0]["copilot_context"]["turn_understanding"]["query_fact_type"] == "aftersales"
    assert result["passed"] == 1
    db = session_factory()
    try:
        trace = db.query(EvalTrace).one()
        assert trace.get_turn_understanding()["turn_actionability"] == "actionable_question"
        assert trace.query_fact_type == "aftersales"
        assert "query_fact_type_missing" not in trace.get_failure_labels()
        assert "rag_miss" not in trace.get_failure_labels()
    finally:
        db.close()


def test_replay_result_fails_empty_query_fact_type_with_product_reply():
    passed, failures = evaluate_replay_turn_result(
        {
            "turn_actionability": "context_update",
            "needs_rag": False,
            "should_score": True,
            "forbidden_reply_topics": ["dimensions", "material", "load_capacity"],
        },
        {
            "suggested_reply": "这款尺寸是宽80厘米，材质为PP。",
            "query_fact_type": "",
            "final_answer_audit": {"passed": True, "expected_topics": []},
        },
        [],
    )

    labels = {item["failure_type"] for item in failures}
    assert passed is False
    assert "wrong_topic_reply" in labels
    assert "query_fact_type_missing" in labels
    assert "unrequested_product_fact" in labels


def test_promotion_policy_reply_topics_are_compatible_with_promotion():
    response = {
        "suggested_reply": "亲，我先帮您核对当前活动/福利，优惠规则需要按页面和下单数量确认。",
        "query_fact_type": "promotion_policy",
        "answer_trace": {
            "query_fact_type": "promotion_policy",
            "required_fact_types": ["promotion_policy"],
        },
        "final_answer_audit": {"passed": True, "expected_topics": ["promotion"]},
        "requires_human_review": True,
    }
    passed, failures = evaluate_replay_turn_result(
        {
            "turn_actionability": "actionable_question",
            "needs_rag": True,
            "should_score": True,
            "query_fact_type": "promotion",
            "forbidden_reply_topics": [],
        },
        response,
        classify_turn_failures(response),
    )

    labels = {item["failure_type"] for item in failures}
    assert passed is False
    assert "rag_miss" in labels
    assert "needs_human_review" in labels
    assert "evidence_misuse" not in labels
    assert "intent_contract_mismatch" not in labels


def test_actionable_aftersales_turn_fails_generic_reply_with_missing_agent_fact_type():
    passed, failures = evaluate_replay_turn_result(
        {
            "turn_actionability": "actionable_question",
            "needs_rag": False,
            "should_score": True,
            "query_fact_type": "aftersales",
            "forbidden_reply_topics": [],
        },
        {
            "suggested_reply": "亲~我在处理，刚才的回复如果没帮到您，可以直接说具体问题，我会重新按事实查。",
            "query_fact_type": "",
            "answer_trace": {"query_fact_type": ""},
            "final_answer_audit": {"passed": True, "expected_topics": ["aftersales"]},
        },
        [],
    )

    labels = {item["failure_type"] for item in failures}
    assert passed is False
    assert "query_fact_type_missing" in labels
    assert "generic_reply_to_actionable_issue" in labels


def test_actionable_aftersales_turn_fails_when_agent_trace_switches_to_installation():
    passed, failures = evaluate_replay_turn_result(
        {
            "turn_actionability": "actionable_question",
            "needs_rag": False,
            "should_score": True,
            "query_fact_type": "aftersales",
            "forbidden_reply_topics": [],
        },
        {
            "suggested_reply": "可以按安装说明书把配件装好。",
            "query_fact_type": "installation",
            "answer_trace": {"query_fact_type": "installation", "required_fact_types": ["installation"]},
            "final_answer_audit": {"passed": True, "expected_topics": ["installation"]},
        },
        [],
    )

    labels = {item["failure_type"] for item in failures}
    assert passed is False
    assert "intent_contract_mismatch" in labels


def test_replay_intent_contract_allows_fact_type_aliases():
    aftersales_passed, aftersales_failures = evaluate_replay_turn_result(
        {
            "turn_actionability": "actionable_question",
            "needs_rag": False,
            "should_score": True,
            "query_fact_type": "aftersales",
            "forbidden_reply_topics": [],
        },
        {
            "suggested_reply": "可以按售后规则先核对订单和凭证。",
            "query_fact_type": "after_sales",
            "answer_trace": {"query_fact_type": "after_sales", "required_fact_types": ["after_sales"]},
            "final_answer_audit": {"passed": True, "expected_topics": ["aftersales"]},
        },
        [],
    )
    installation_passed, installation_failures = evaluate_replay_turn_result(
        {
            "turn_actionability": "actionable_question",
            "needs_rag": True,
            "should_score": True,
            "query_fact_type": "accessory_usage",
            "forbidden_reply_topics": [],
        },
        {
            "suggested_reply": "防倒器用于辅助固定，安装时按配件说明确认位置。",
            "query_fact_type": "installation",
            "evidence_debug": {"selected_evidence": [{"fact_type": "installation", "content": "配件安装说明"}]},
            "answer_trace": {"query_fact_type": "installation", "required_fact_types": ["installation"]},
            "final_answer_audit": {"passed": True, "expected_topics": ["installation"]},
        },
        [],
    )

    assert aftersales_passed is True
    assert {item["failure_type"] for item in aftersales_failures} == set()
    assert installation_passed is True
    assert {item["failure_type"] for item in installation_failures} == set()


def test_structure_function_replay_fails_scene_or_space_answer():
    response = {
        "suggested_reply": "亲，这款可以放在卧室或客厅，建议留出走动空间。",
        "query_fact_type": "placement_scene",
        "answer_trace": {"query_fact_type": "placement_scene", "required_fact_types": ["placement_scene"]},
        "final_answer_audit": {"passed": False, "issues": ["wrong_topic:structure_function->placement_scene"]},
    }
    passed, failures = evaluate_replay_turn_result(
        {
            "turn_actionability": "actionable_question",
            "needs_rag": True,
            "should_score": True,
            "query_fact_type": "structure_function",
            "forbidden_reply_topics": [],
        },
        response,
        classify_turn_failures(response),
    )

    labels = {item["failure_type"] for item in failures}
    assert passed is False
    assert "intent_contract_mismatch" in labels
    assert "semantic_mismatch" in labels


def test_damaged_aftersales_handoff_is_not_semantic_mismatch():
    passed, failures = evaluate_replay_turn_result(
        {
            "turn_actionability": "actionable_question",
            "needs_rag": False,
            "should_score": True,
            "query_fact_type": "aftersales",
            "forbidden_reply_topics": [],
        },
        {
            "suggested_reply": "亲，收到。麻烦您拍一下断裂/破损位置、配件整体和外包装，我这边按订单核实后给您处理补发、换件或售后方案。",
            "query_fact_type": "aftersales_policy",
            "answer_trace": {"query_fact_type": "aftersales_policy", "required_fact_types": ["aftersales_policy"]},
            "final_answer_audit": {"passed": True, "expected_topics": ["aftersales"]},
            "requires_human_review": True,
        },
        [],
    )

    labels = {item["failure_type"] for item in failures}
    assert passed is True
    assert "semantic_mismatch" not in labels
    assert "intent_contract_mismatch" not in labels


def test_replay_stores_expected_actual_and_effective_query_fact_type_contract(monkeypatch):
    session_factory = _patch_test_db(monkeypatch)
    db = session_factory()
    try:
        db.add(EvalCase(case_uid="case_contract_1", source_type="real_conversation", message="contract"))
        db.add(EvalConversationTurn(
            case_uid="case_contract_1",
            conversation_uid="conv_contract_1",
            turn_uid="turn_contract_1",
            turn_index=0,
            speaker="buyer",
            sanitized_text="发过来的说明书和物品不对",
        ))
        db.commit()
    finally:
        db.close()

    class MismatchReplayService(RealConversationReplayService):
        def _call_agent(self, payload):
            return {
                "suggested_reply": "请按安装说明书确认配件安装位置。",
                "requires_human_review": False,
                "query_fact_type": "installation",
                "answer_trace": {"query_fact_type": "installation", "required_fact_types": ["installation"]},
                "final_answer_audit": {"passed": True, "expected_topics": ["installation"]},
            }

    result = MismatchReplayService().replay_cases(ReplayOptions(run_uid="run_contract_mismatch"))

    assert result["failed"] == 1
    db = session_factory()
    try:
        trace = db.query(EvalTrace).one()
        understanding = trace.get_turn_understanding()
        answer_trace = trace.get_answer_trace()
        labels = set(trace.get_failure_labels())
        assert trace.query_fact_type == "aftersales"
        assert understanding["expected_query_fact_type"] == "aftersales"
        assert understanding["actual_query_fact_type"] == "installation"
        assert understanding["effective_query_fact_type"] == "aftersales"
        assert understanding["intent_contract_status"] == "mismatch"
        assert answer_trace["expected_query_fact_type"] == "aftersales"
        assert answer_trace["actual_query_fact_type"] == "installation"
        assert "intent_contract_mismatch" in labels
    finally:
        db.close()
