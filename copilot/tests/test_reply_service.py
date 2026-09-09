"""
回复建议服务测试 - Schema 校验、Pydantic 模型、无知识库降级
"""

import sys
import os
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.llm.schemas import (
    validate_llm_output,
    parse_llm_output,
    LLMReplyOutput,
    ActionProposal,
    RiskLevel,
    FallbackReplyOutput,
)
from app.models.reply import ReplySuggestion


class TestPydanticSchema:
    """Pydantic LLM 输出 Schema 校验"""

    def test_valid_full_output(self):
        """合法完整输出"""
        data = {
            "intent": "催发货",
            "risk_level": "medium",
            "customer_emotion": "焦急",
            "need_lookup": ["order", "logistics"],
            "suggested_reply": "我们正在核实您的发货进度",
            "reply_style": "温和安抚",
            "policy_warnings": ["不能承诺具体时间"],
            "action_proposal": {"action_type": "查订单", "reason": "需要核实发货状态"},
            "requires_human_review": False,
        }
        obj = LLMReplyOutput.model_validate(data)
        assert obj.intent == "催发货"
        assert obj.risk_level == RiskLevel.MEDIUM
        assert obj.action_proposal.action_type == "查订单"

    def test_valid_minimal_output(self):
        """合法最小输出"""
        data = {
            "intent": "商品咨询",
            "risk_level": "low",
            "suggested_reply": "这款书桌尺寸是120x60cm",
        }
        obj = LLMReplyOutput.model_validate(data)
        assert obj.customer_emotion == "未知"  # default
        assert obj.requires_human_review is False  # default

    def test_missing_intent_fails(self):
        """缺少 intent 校验失败"""
        is_valid, errors = validate_llm_output({
            "risk_level": "low",
            "suggested_reply": "测试",
        })
        assert is_valid is False
        assert any("intent" in e for e in errors)

    def test_invalid_risk_level(self):
        """无效 risk_level"""
        is_valid, errors = validate_llm_output({
            "intent": "测试",
            "risk_level": "critical",
            "suggested_reply": "测试回复",
        })
        assert is_valid is False
        assert any("risk_level" in e for e in errors)

    def test_empty_suggested_reply_fails(self):
        """空 suggested_reply 校验失败"""
        is_valid, errors = validate_llm_output({
            "intent": "测试",
            "risk_level": "low",
            "suggested_reply": "",
        })
        assert is_valid is False
        assert any("suggested_reply" in e for e in errors)

    def test_all_valid_risk_levels(self):
        """所有合法 risk_level"""
        for level in ["low", "medium", "high"]:
            is_valid, _ = validate_llm_output({
                "intent": "测试",
                "risk_level": level,
                "suggested_reply": "测试回复",
            })
            assert is_valid is True

    def test_risk_level_enum(self):
        """RiskLevel 枚举"""
        assert RiskLevel.LOW.value == "low"
        assert RiskLevel.MEDIUM.value == "medium"
        assert RiskLevel.HIGH.value == "high"


class TestParseOutput:
    """parse_llm_output 降级测试"""

    def test_valid_data_parsed(self):
        """合法数据正常解析"""
        data = {
            "intent": "催发货",
            "risk_level": "medium",
            "suggested_reply": "帮您查一下",
            "requires_human_review": False,
        }
        obj = parse_llm_output(data)
        assert isinstance(obj, LLMReplyOutput)
        assert obj.intent == "催发货"

    def test_invalid_data_graceful_fallback(self):
        """非法数据降级处理"""
        data = {
            "intent": "解析失败",
            "risk_level": "bad_value",
        }
        obj = parse_llm_output(data)
        assert isinstance(obj, LLMReplyOutput)
        assert obj.risk_level == RiskLevel.LOW  # 降级为 low

    def test_fallback_model(self):
        """FallbackReplyOutput"""
        fb = FallbackReplyOutput(error="未配置")
        assert fb.intent == "系统提示"
        assert fb.error == "未配置"


class TestReplySuggestionModel:
    """ReplySuggestion Pydantic 模型测试"""

    def test_from_dict(self):
        """从字典创建"""
        data = {
            "intent": "投诉",
            "risk_level": "high",
            "customer_emotion": "愤怒",
            "need_lookup": ["order"],
            "suggested_reply": "非常抱歉给您带来不好的体验",
            "reply_style": "诚恳道歉",
            "policy_warnings": ["高风险消息，需人工复核"],
            "action_proposal": {"action_type": "转主管", "reason": "客户投诉"},
            "requires_human_review": True,
        }
        result = ReplySuggestion.from_dict(data)
        assert result.intent == "投诉"
        assert result.risk_level == "high"
        assert result.requires_human_review is True
        assert result.action_proposal.action_type == "转主管"

    def test_to_dict(self):
        """转为字典"""
        suggestion = ReplySuggestion(
            intent="商品咨询",
            risk_level="low",
            suggested_reply="这款书桌尺寸是120x60cm",
        )
        d = suggestion.to_dict()
        assert d["intent"] == "商品咨询"
        assert d["risk_level"] == "low"
        # 空 guard_warnings 和 error 不应出现在输出
        assert "guard_warnings" not in d
        assert "error" not in d

    def test_roundtrip(self):
        """from_dict -> to_dict 往返"""
        data = {
            "intent": "催发货",
            "risk_level": "medium",
            "suggested_reply": "帮您查一下",
            "requires_human_review": False,
            "action_proposal": {"action_type": "查订单", "reason": "需要核实"},
        }
        result = ReplySuggestion.from_dict(data)
        output = result.to_dict()
        assert output["intent"] == data["intent"]
        assert output["risk_level"] == data["risk_level"]

    def test_from_llm_output(self):
        """从 LLMReplyOutput 创建"""
        llm = LLMReplyOutput(
            intent="退货退款",
            risk_level=RiskLevel.HIGH,
            suggested_reply="非常抱歉，我们会为您处理",
            requires_human_review=True,
        )
        result = ReplySuggestion.from_llm_output(llm)
        assert result.intent == "退货退款"
        assert result.risk_level == "high"

    def test_guard_warnings_preserved(self):
        """guard_warnings 保留"""
        data = {
            "intent": "测试",
            "risk_level": "low",
            "suggested_reply": "测试回复",
            "guard_warnings": ["已替换 [今天一定发] 为安全表述"],
        }
        result = ReplySuggestion.from_dict(data)
        assert len(result.guard_warnings) == 1
        d = result.to_dict()
        assert "guard_warnings" in d

    def test_sendable_contract_preserved_from_dict(self):
        data = {
            "intent": "product_question",
            "risk_level": "low",
            "suggested_reply": "draft reply",
            "draft_reply": "draft reply",
            "sendable_reply": "sendable reply",
            "can_send": True,
            "reply_status": "sendable",
            "block_reasons": [],
        }

        result = ReplySuggestion.from_dict(data)
        output = result.to_dict()

        assert result.can_send is True
        assert result.sendable_reply == "sendable reply"
        assert output["draft_reply"] == "draft reply"
        assert output["sendable_reply"] == "sendable reply"
        assert output["can_send"] is True
        assert output["reply_status"] == "sendable"
        assert output["block_reasons"] == []

    def test_missing_sendable_contract_defaults_to_blocked(self):
        result = ReplySuggestion.from_dict({
            "intent": "product_question",
            "risk_level": "low",
            "suggested_reply": "draft only",
        })
        output = result.to_dict()

        assert output["draft_reply"] == "draft only"
        assert output["can_send"] is False
        assert output["sendable_reply"] == ""
        assert output["reply_status"] == "blocked"
        assert "sendable_contract_missing" in output["block_reasons"]

    def test_invalid_can_send_without_sendable_reply_is_blocked(self):
        result = ReplySuggestion.from_dict({
            "intent": "product_question",
            "risk_level": "low",
            "suggested_reply": "draft only",
            "can_send": True,
            "sendable_reply": "",
        })

        assert result.can_send is False
        assert result.sendable_reply == ""
        assert result.reply_status == "blocked"
        assert "sendable_contract_invalid" in result.block_reasons

    def test_blocked_contract_clears_sendable_reply(self):
        result = ReplySuggestion.from_dict({
            "intent": "product_question",
            "risk_level": "low",
            "suggested_reply": "draft only",
            "can_send": False,
            "sendable_reply": "must not leak",
            "block_reasons": ["needs_review"],
        })

        assert result.can_send is False
        assert result.sendable_reply == ""
        assert result.block_reasons == ["needs_review"]


class TestNoKnowledgeBaseFallback:
    """无完整知识库时的降级测试"""

    def test_empty_knowledge_repo(self):
        """空知识库不会导致崩溃"""
        from app.repositories.file_knowledge_repository import FileKnowledgeRepository
        repo = FileKnowledgeRepository()
        repo.entries = []
        results = repo.search("发货")
        assert results == []

    def test_context_builder_without_knowledge(self):
        """无知识库时上下文构建正常"""
        from app.repositories.json_order_repository import JsonOrderRepository
        from app.repositories.json_product_repository import JsonProductRepository
        from app.repositories.file_knowledge_repository import FileKnowledgeRepository
        from app.services.context_builder import ContextBuilder

        order_repo = JsonOrderRepository()
        order_repo.load()
        product_repo = JsonProductRepository()
        product_repo.load()
        knowledge_repo = FileKnowledgeRepository()
        knowledge_repo.entries = []

        builder = ContextBuilder(order_repo, product_repo, knowledge_repo)
        context = builder.build("什么时候发货")
        assert "order" not in context
        assert "knowledge" not in context or context.get("knowledge") == []

    def test_risk_service_without_llm(self):
        """无 LLM 时风险检测仍然工作"""
        from app.repositories.file_policy_repository import FilePolicyRepository
        from app.services.risk_service import RiskService

        policy_repo = FilePolicyRepository()
        policy_repo.load()
        risk_service = RiskService(policy_repo)
        assert risk_service.detect_risk("我要投诉") == "high"
        assert risk_service.detect_risk("什么时候发货") == "low"

    def test_feedback_service_with_no_file(self):
        """无反馈文件时统计正常"""
        import tempfile
        from app.services.feedback_service import FeedbackService

        tmp = os.path.join(tempfile.gettempdir(), "test_feedback_empty.jsonl")
        if os.path.exists(tmp):
            os.remove(tmp)

        service = FeedbackService(filepath=tmp)
        stats = service.get_stats()
        assert stats["total"] == 0
        assert stats["acceptance_rate"] == 0.0

        if os.path.exists(tmp):
            os.remove(tmp)


class TestLLMFallback:
    """LLM 降级回复测试"""

    def test_json_parse_error_fallback(self):
        """JSON 解析失败时返回安全降级"""
        from app.llm.client import _make_fallback

        result = _make_fallback(
            risk_level="low",
            error_type="JSON_PARSE_ERROR",
            detail="LLM 输出不是有效 JSON",
        )
        assert result["error"].startswith("JSON_PARSE_ERROR")
        assert result["intent"] == "系统提示"
        assert result["suggested_reply"]
        assert "LLM" not in result["suggested_reply"]
        assert "JSON" not in result["suggested_reply"]
        assert result["requires_human_review"] is False

    def test_schema_validation_error_fallback(self):
        """Schema 校验失败时返回安全降级"""
        from app.llm.client import _make_fallback

        result = _make_fallback(
            risk_level="medium",
            error_type="SCHEMA_VALIDATION_ERROR",
            detail="missing intent",
            partial_intent="催发货",
        )
        assert "SCHEMA_VALIDATION_ERROR" in result["error"]
        assert result["intent"] == "催发货"
        assert "会尽快帮您核实" in result["suggested_reply"]

    def test_high_risk_fallback_requires_human(self):
        """高风险降级必须 requires_human_review=True"""
        from app.llm.client import _make_fallback

        result = _make_fallback(
            risk_level="high",
            error_type="LLM_CALL_ERROR",
            detail="timeout",
        )
        assert result["requires_human_review"] is True
        assert "主管" in result["suggested_reply"]

    def test_fallback_dict_compatible_with_reply_suggestion(self):
        """降级返回的 dict 能被 ReplySuggestion.from_dict 正常消费"""
        from app.llm.client import _make_fallback

        result = _make_fallback(
            risk_level="low",
            error_type="JSON_PARSE_ERROR",
            detail="test",
        )
        suggestion = ReplySuggestion.from_dict(result)
        assert suggestion.intent == "系统提示"
        assert suggestion.error is not None


class TestProductKnowledgeInContext:
    """产品知识库在上下文中的接入测试"""

    def test_context_builder_with_product_knowledge(self):
        """产品知识库接入后能搜索到产品"""
        import json
        import tempfile
        from app.repositories.json_order_repository import JsonOrderRepository
        from app.repositories.json_product_repository import JsonProductRepository
        from app.repositories.file_knowledge_repository import FileKnowledgeRepository
        from app.repositories.product_knowledge_repository import ProductKnowledgeRepository
        from app.services.context_builder import ContextBuilder

        with tempfile.TemporaryDirectory() as tmpdir:
            cards = [{
                "i_id": "CTX001",
                "product_name": "北欧风书架",
                "category": "家具-书架",
                "brand": "INHE",
                "sku_summary": {
                    "sku_count": 1,
                    "sku_list": [{
                        "sku_id": "SKU_CTX001",
                        "sku_name": "书架 白色",
                        "properties_value": "颜色:白色",
                        "sale_price": 399.0,
                        "stock_qty": 10,
                    }],
                },
                "customer_service_facts": {
                    "material": "松木",
                    "weight": 15.0,
                },
            }]
            with open(os.path.join(tmpdir, "product_cards.json"), "w", encoding="utf-8") as f:
                json.dump(cards, f, ensure_ascii=False)

            pk_repo = ProductKnowledgeRepository(knowledge_dir=tmpdir)
            pk_repo.load()
            assert pk_repo.count() == 1

            order_repo = JsonOrderRepository()
            order_repo.load()
            product_repo = JsonProductRepository()
            product_repo.load()
            knowledge_repo = FileKnowledgeRepository()
            knowledge_repo.entries = []

            builder = ContextBuilder(
                order_repo, product_repo, knowledge_repo,
                product_knowledge_repo=pk_repo,
            )
            context = builder.build("你们有北欧风书架吗")
            assert "product_knowledge" in context
            assert len(context["product_knowledge"]) >= 1
            assert context["product_knowledge"][0]["i_id"] == "CTX001"

    def test_context_builder_without_product_knowledge(self):
        """无产品知识库时上下文正常（不崩溃）"""
        from app.repositories.json_order_repository import JsonOrderRepository
        from app.repositories.json_product_repository import JsonProductRepository
        from app.repositories.file_knowledge_repository import FileKnowledgeRepository
        from app.services.context_builder import ContextBuilder

        order_repo = JsonOrderRepository()
        order_repo.load()
        product_repo = JsonProductRepository()
        product_repo.load()
        knowledge_repo = FileKnowledgeRepository()
        knowledge_repo.entries = []

        builder = ContextBuilder(order_repo, product_repo, knowledge_repo)
        context = builder.build("你们有书桌吗")
        assert "product_knowledge" not in context


class _FakeGraph:
    def __init__(self, response):
        self.response = response
        self.state = None

    def invoke(self, state, config=None):
        self.state = dict(state)
        return dict(self.response)


def _reply_service():
    from app.services.reply_service import ReplyService

    return ReplyService(None, None, None)


@pytest.mark.parametrize("source", ["api", "sidecar", "replay", "agent_benchmark"])
def test_reply_service_preserves_queue_execution_identity(monkeypatch, tmp_path, source):
    import app.agent.graph as graph
    from app.services.review_queue_service import ReviewQueueService

    fake = _FakeGraph({
        "intent": "general", "suggested_reply": "review candidate",
        "requires_human_review": True, "can_send": False,
        "sendable_reply": "", "reply_status": "needs_human_review",
    })
    monkeypatch.setattr(graph, "customer_service_graph", fake)
    queue = ReviewQueueService(str(tmp_path / "queue.jsonl"))
    service = _reply_service()
    service._review_queue_service = queue
    kwargs = dict(source=source, conversation_id="conversation-a",
                  message_id="message-a", request_id="request-a",
                  copilot_context={"shop_id": "shop-a"})
    first = service.analyze("hello", **kwargs)
    second = service.analyze("hello", **kwargs)
    assert first.review_id == second.review_id
    assert queue.count_pending() == 1
    expected = ReviewQueueService(str(tmp_path / "expected.jsonl")).enqueue(
        first.to_dict(), "hello", source=source, conversation_id="conversation-a",
        message_id="message-a", request_id="request-a", shop_id="shop-a",
    )
    assert queue.get_by_id(first.review_id)["enqueue_identity"] == expected["enqueue_identity"]
    assert first.can_send is False and second.can_send is False
    assert first.requires_human_review is True and second.requires_human_review is True
    assert first.suggested_reply == second.suggested_reply == "review candidate"


def test_queue_only_changes_review_id_not_candidate_contract(monkeypatch, tmp_path):
    import app.agent.graph as graph
    from app.services.review_queue_service import ReviewQueueService

    fake = _FakeGraph({
        "intent": "general", "suggested_reply": "review candidate",
        "requires_human_review": True, "can_send": False,
        "sendable_reply": "", "reply_status": "needs_human_review",
        "reply_blocks": [{"type": "text", "content": "review candidate"}],
        "selected_evidence": [{"evidence_uid": "fact-a"}],
    })
    monkeypatch.setattr(graph, "customer_service_graph", fake)
    service = _reply_service()
    identity = dict(source="test", conversation_id="conversation-a",
                    message_id="message-a", request_id="request-a")
    baseline = service.analyze("hello", **identity).to_dict()
    service._review_queue_service = ReviewQueueService(str(tmp_path / "queue.jsonl"))
    after = service.analyze("hello", **identity).to_dict()
    assert after.pop("review_id")
    baseline.pop("review_id", None)
    assert after == baseline


@pytest.mark.parametrize("source", ["api", "sidecar", "replay", "agent_benchmark"])
def test_execution_service_generated_ids_reach_queue(monkeypatch, tmp_path, source):
    import app.agent.graph as graph
    import app.services.analysis_execution_service as execution
    import app.tracing.repository as trace_repository
    import app.tracing.recorder as trace_recorder
    from app.services.review_queue_service import ReviewQueueService

    monkeypatch.setattr(trace_repository, "init_trace_tables", lambda: None)
    monkeypatch.setattr(trace_recorder, "start_trace", lambda **_: "")
    monkeypatch.setattr(trace_recorder, "start_span", lambda **_: "")
    monkeypatch.setattr(execution, "_save_file_snapshot", lambda **_: None)
    monkeypatch.setattr(graph, "customer_service_graph", _FakeGraph({
        "intent": "general", "suggested_reply": "review candidate",
        "requires_human_review": True, "can_send": False,
        "sendable_reply": "", "reply_status": "needs_human_review",
    }))
    service = _reply_service()
    queue = ReviewQueueService(str(tmp_path / "queue.jsonl"))
    service._review_queue_service = queue
    first = execution.execute_analysis(service, "hello", conversation_id="conversation-a",
                                       source=source, final_orchestration=False)
    second = execution.execute_analysis(service, "hello", conversation_id="conversation-a",
                                        source=source, final_orchestration=False)
    assert first["message_id"] != second["message_id"]
    assert first["request_id"] != second["request_id"]
    assert first["review_id"] != second["review_id"]
    records = queue.list_reviews()
    assert len(records) == 2
    assert all(record["enqueue_identity"] for record in records)
    assert first["can_send"] is second["can_send"] is False
    assert first["requires_human_review"] is second["requires_human_review"] is True


def test_reply_service_preserves_graph_sendable_contract(monkeypatch):
    import app.agent.graph as graph

    fake = _FakeGraph({
        "intent": "general",
        "risk_level": "low",
        "suggested_reply": "draft reply",
        "draft_reply": "draft reply",
        "sendable_reply": "sendable reply",
        "can_send": True,
        "reply_status": "sendable",
        "block_reasons": [],
        "requires_human_review": False,
        "evidence_debug": {},
        "trace_steps": [],
    })
    monkeypatch.setattr(graph, "customer_service_graph", fake)

    suggestion = _reply_service().analyze("hello")
    output = suggestion.to_dict()

    assert output["suggested_reply"] == "draft reply"
    assert output["draft_reply"] == "draft reply"
    assert output["sendable_reply"] == "sendable reply"
    assert output["can_send"] is True
    assert output["reply_status"] == "sendable"
    assert output["block_reasons"] == []
    assert suggestion.evidence_debug["sendable_reply_contract"]["can_send"] is True


def test_reply_service_preserves_formal_evidence_convergence_diagnostics(monkeypatch):
    import app.agent.graph as graph

    fake = _FakeGraph({
        "intent": "general",
        "suggested_reply": "draft reply",
        "selected_evidence": [{"evidence_uid": "fact-1"}],
        "minimal_decision_context": {"schema_version": "minimal-decision-context-v1"},
        "supervisor_candidate_preview": {"can_send": False, "requires_human_review": True},
        "evidence_debug": {},
        "trace_steps": [],
    })
    monkeypatch.setattr(graph, "customer_service_graph", fake)

    output = _reply_service().analyze("hello").to_dict()

    assert output["selected_evidence"] == [{"evidence_uid": "fact-1"}]
    assert output["minimal_decision_context"]["schema_version"] == "minimal-decision-context-v1"
    assert output["supervisor_candidate_preview"]["can_send"] is False


def test_reply_service_defaults_legacy_graph_result_to_blocked(monkeypatch):
    import app.agent.graph as graph

    fake = _FakeGraph({
        "intent": "general",
        "risk_level": "low",
        "suggested_reply": "draft reply",
        "requires_human_review": False,
        "evidence_debug": {},
        "trace_steps": [],
    })
    monkeypatch.setattr(graph, "customer_service_graph", fake)

    suggestion = _reply_service().analyze("hello")
    output = suggestion.to_dict()

    assert output["draft_reply"] == "draft reply"
    assert output["can_send"] is False
    assert output["sendable_reply"] == ""
    assert output["reply_status"] == "blocked"
    assert "sendable_contract_missing" in output["block_reasons"]
    assert suggestion.evidence_debug["sendable_reply_contract"]["reply_status"] == "blocked"


def test_reply_service_clears_sendable_when_gate_blocks(monkeypatch):
    import app.agent.graph as graph

    fake = _FakeGraph({
        "intent": "general",
        "risk_level": "low",
        "suggested_reply": "draft reply",
        "sendable_reply": "must not leak",
        "can_send": False,
        "reply_status": "blocked",
        "block_reasons": ["final_audit_failed"],
        "requires_human_review": False,
        "evidence_debug": {},
        "trace_steps": [],
    })
    monkeypatch.setattr(graph, "customer_service_graph", fake)

    suggestion = _reply_service().analyze("hello")
    output = suggestion.to_dict()

    assert output["can_send"] is False
    assert output["sendable_reply"] == ""
    assert output["block_reasons"] == ["final_audit_failed"]


def test_reply_service_blocks_product_fact_when_query_fact_type_missing(monkeypatch):
    import app.agent.graph as graph

    fake = _FakeGraph({
        "intent": "product_question",
        "risk_level": "low",
        "suggested_reply": "这款尺寸是宽80厘米，材质为PP。",
        "requires_human_review": False,
        "evidence_debug": {},
        "trace_steps": [],
    })
    monkeypatch.setattr(graph, "customer_service_graph", fake)

    suggestion = _reply_service().analyze(
        "这个呢",
        copilot_context={
            "turn_understanding": {
                "turn_actionability": "actionable_question",
                "query_fact_type": "",
                "should_score": True,
            },
            "real_context_summary": {"has_product_context": True},
        },
    )
    output = suggestion.to_dict()

    assert suggestion.requires_human_review is True
    assert suggestion.reason_for_review == "query_fact_type_missing_should_not_expand_product_fact"
    assert "宽80厘米" not in suggestion.suggested_reply
    assert "PP" not in suggestion.suggested_reply
    assert output["can_send"] is False
    assert output["sendable_reply"] == ""
    assert suggestion.evidence_debug["turn_contract_controlled"] is True


def test_reply_service_promotes_turn_understanding_fact_type_to_graph_state(monkeypatch):
    import app.agent.graph as graph

    fake = _FakeGraph({
        "intent": "general",
        "risk_level": "low",
        "suggested_reply": "我先帮您核对一下。",
        "requires_human_review": True,
        "evidence_debug": {},
        "trace_steps": [],
    })
    monkeypatch.setattr(graph, "customer_service_graph", fake)

    suggestion = _reply_service().analyze(
        "资料和实物不一致",
        copilot_context={
            "turn_understanding": {
                "turn_actionability": "actionable_question",
                "query_fact_type": "aftersales",
            }
        },
    )

    assert fake.state["query_fact_type"] == "aftersales"
    assert fake.state["required_fact_types"] == ["aftersales"]
    assert suggestion.evidence_debug["query_fact_type"] == "aftersales"
    assert suggestion.evidence_debug["required_fact_types"] == ["aftersales"]


def test_reply_service_controls_deictic_followup_that_expands_product_fact(monkeypatch):
    import app.agent.graph as graph

    fake = _FakeGraph({
        "intent": "product_question",
        "risk_level": "low",
        "suggested_reply": "这款尺寸是宽80厘米，材质为PP。",
        "query_fact_type": "dimensions",
        "requires_human_review": False,
        "evidence_debug": {"query_fact_type": "dimensions"},
        "trace_steps": [],
    })
    monkeypatch.setattr(graph, "customer_service_graph", fake)

    suggestion = _reply_service().analyze(
        "这样的可以吗",
        copilot_context={
            "turn_understanding": {
                "turn_actionability": "deictic_followup",
                "should_score": True,
            }
        },
    )

    assert suggestion.requires_human_review is True
    assert suggestion.reason_for_review == "turn_deictic_followup_should_not_expand_product_fact"
    assert "尺寸" not in suggestion.suggested_reply
    assert suggestion.evidence_debug["turn_contract_controlled"] is True


def test_reply_service_controls_aftersales_mismatch_not_installation(monkeypatch):
    import app.agent.graph as graph

    fake = _FakeGraph({
        "intent": "installation_question",
        "risk_level": "low",
        "suggested_reply": "您可以按安装说明把配件装好。",
        "query_fact_type": "installation",
        "requires_human_review": False,
        "evidence_debug": {"query_fact_type": "installation"},
        "trace_steps": [],
    })
    monkeypatch.setattr(graph, "customer_service_graph", fake)

    suggestion = _reply_service().analyze(
        "资料和实物不一致",
        copilot_context={
            "turn_understanding": {
                "turn_actionability": "actionable_question",
                "query_fact_type": "aftersales",
            }
        },
    )

    assert suggestion.requires_human_review is True
    assert suggestion.reason_for_review == "turn_contract_fact_type_mismatch"
    assert suggestion.evidence_debug["query_fact_type"] == "aftersales"
    assert "售后" in suggestion.suggested_reply
    assert "安装说明" not in suggestion.suggested_reply


def test_reply_service_controls_accessory_usage_without_evidence(monkeypatch):
    import app.agent.graph as graph

    fake = _FakeGraph({
        "intent": "installation_question",
        "risk_level": "low",
        "suggested_reply": "亲~我在处理，您可以直接说具体问题。",
        "requires_human_review": False,
        "evidence_debug": {},
        "trace_steps": [],
    })
    monkeypatch.setattr(graph, "customer_service_graph", fake)

    suggestion = _reply_service().analyze(
        "这个部件怎么用",
        copilot_context={
            "turn_understanding": {
                "turn_actionability": "actionable_question",
                "query_fact_type": "installation",
            }
        },
    )

    assert suggestion.requires_human_review is True
    assert suggestion.evidence_debug["query_fact_type"] == "installation"
    assert "我在处理" not in suggestion.suggested_reply
    assert suggestion.evidence_debug["no_evidence_reply_policy"]["reply_strategy"] == "verify_accessory_usage_with_photo"
    assert suggestion.can_send is False
    assert suggestion.sendable_reply == ""


def test_reply_service_no_evidence_policy_does_not_request_known_product_context(monkeypatch):
    import app.agent.graph as graph

    fake = _FakeGraph({
        "intent": "product_question",
        "risk_level": "low",
        "suggested_reply": "亲，这个需要结合具体款式和尺寸图核对。麻烦您发一下商品链接、截图或预留位置尺寸，我再帮您确认。",
        "query_fact_type": "dimensions",
        "requires_human_review": False,
        "evidence_debug": {"query_fact_type": "dimensions", "selected_evidence": []},
        "trace_steps": [],
    })
    monkeypatch.setattr(graph, "customer_service_graph", fake)

    suggestion = _reply_service().analyze(
        "最窄是什么尺寸",
        copilot_context={
            "turn_understanding": {
                "turn_actionability": "actionable_question",
                "query_fact_type": "dimensions",
            },
            "real_context_summary": {"has_product_context": True},
            "real_context_product_identity": {"has_resolved_product_context": True},
            "i_id": "DEMO_ITEM_ID",
        },
    )

    assert suggestion.requires_human_review is True
    assert "商品链接" not in suggestion.suggested_reply
    assert "SKU" not in suggestion.suggested_reply
    assert suggestion.evidence_debug["no_evidence_reply_policy"]["reply_strategy"] == "verify_dimensions_for_known_product"
    assert suggestion.can_send is False
    assert suggestion.sendable_reply == ""


def test_reply_service_no_evidence_policy_blocks_installation_media_promise_without_asset(monkeypatch):
    import app.agent.graph as graph

    fake = _FakeGraph({
        "intent": "installation_question",
        "risk_level": "low",
        "suggested_reply": "亲，我把视频发您参考，您先看一下。",
        "query_fact_type": "installation",
        "requires_human_review": False,
        "evidence_debug": {"query_fact_type": "installation", "selected_evidence": []},
        "recommended_assets": [],
        "trace_steps": [],
    })
    monkeypatch.setattr(graph, "customer_service_graph", fake)

    suggestion = _reply_service().analyze(
        "需要安装资料",
        copilot_context={
            "turn_understanding": {
                "turn_actionability": "actionable_question",
                "query_fact_type": "installation",
            },
            "real_context_summary": {"has_product_context": True, "has_media_context": True},
            "media_context": {"video_urls": ["https://chat.example.com/old.mp4"]},
        },
    )

    assert suggestion.requires_human_review is True
    assert "我把视频发您" not in suggestion.suggested_reply
    assert "发您参考" not in suggestion.suggested_reply
    assert suggestion.evidence_debug["no_evidence_reply_policy"]["reply_strategy"] == "verify_installation_asset_before_send"
    assert suggestion.can_send is False
    assert suggestion.sendable_reply == ""


def test_reply_service_keeps_explicit_sidebar_order_type_for_slot_extraction(monkeypatch):
    """A local sidebar order reference must not be reclassified after privacy sanitization."""
    import app.agent.graph as graph
    from app.agent.nodes.slot_extract import slot_extract
    from app.services.sidecar_context_service import normalize_explicit_order_reference

    class SlotCapturingGraph:
        def __init__(self):
            self.slots = {}
            self.state = {}

        def invoke(self, state, config=None):
            self.state = dict(state)
            self.slots = slot_extract(state)["slots"]
            return {
                "intent": "logistics_trace",
                "risk_level": "low",
                "suggested_reply": "候选回复",
                "requires_human_review": True,
                "can_send": False,
                "reply_status": "needs_human_review",
                "evidence_debug": {},
                "trace_steps": [],
            }

    sidebar_order = "9999999999999999999"
    context = normalize_explicit_order_reference({}, order_id=sidebar_order)
    fake = SlotCapturingGraph()
    monkeypatch.setattr(graph, "customer_service_graph", fake)

    _reply_service().analyze(
        "现在快递到哪里了",
        order_id=sidebar_order,
        copilot_context=context,
    )

    assert fake.slots["identifier_type"] == "unknown_identifier"
    assert fake.slots["platform_trade_id"] == ""
    assert fake.state["_runtime_explicit_order_reference"] == {
        "source": "explicit_request",
        "identifier_type": "unknown_identifier",
    }
    assert fake.state["_runtime_explicit_order_reference"].get("order_id") is None


def test_agent_state_preserves_runtime_order_provenance_for_slot_extraction():
    """The LangGraph state schema must retain non-sensitive sidebar provenance."""
    from langgraph.graph import END, StateGraph

    from app.agent.nodes.slot_extract import slot_extract
    from app.agent.state import AgentState

    graph = StateGraph(AgentState)
    graph.add_node("slot_extract", slot_extract)
    graph.set_entry_point("slot_extract")
    graph.add_edge("slot_extract", END)

    result = graph.compile().invoke({
        "customer_message": "现在快递到哪里了",
        "order_id": "9999999999999999999",
        "copilot_context": {
            "order_id": "[LONG_ID_REDACTED:example]",
            "order_identifier_type": "unknown_identifier",
            "order_reference_source": "explicit_request",
        },
        "_runtime_explicit_order_reference": {
            "source": "explicit_request",
            "identifier_type": "unknown_identifier",
        },
        "trace_steps": [],
    })

    assert result["slots"]["identifier_type"] == "unknown_identifier"
    assert result["_runtime_explicit_order_reference"] == {
        "source": "explicit_request",
        "identifier_type": "unknown_identifier",
    }


def test_reply_service_completes_a_legal_long_graph_path_without_fallback(monkeypatch):
    """A valid path longer than LangGraph's default budget must reach its candidate."""
    from langgraph.graph import END, StateGraph

    from app.agent.state import AgentState
    import app.agent.graph as graph_module

    builder = StateGraph(AgentState)
    node_names = [f"linear_step_{index}" for index in range(30)]
    for node_name in node_names[:-1]:
        builder.add_node(node_name, lambda _state: {})

    def finish(_state):
        return {
            "intent": "general",
            "risk_level": "low",
            "suggested_reply": "long-path-candidate",
            "requires_human_review": True,
            "can_send": False,
            "reply_status": "needs_human_review",
            "evidence_debug": {},
            "trace_steps": [],
        }

    builder.add_node(node_names[-1], finish)
    builder.set_entry_point(node_names[0])
    for source, target in zip(node_names, node_names[1:]):
        builder.add_edge(source, target)
    builder.add_edge(node_names[-1], END)
    monkeypatch.setattr(graph_module, "customer_service_graph", builder.compile())

    suggestion = _reply_service().analyze("请帮我看一下")

    assert suggestion.suggested_reply == "long-path-candidate"
    assert not any(step.get("node") == "graph_fallback" for step in suggestion.trace_steps)
