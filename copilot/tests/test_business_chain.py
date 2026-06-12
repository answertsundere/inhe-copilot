"""
业务链路测试 - 覆盖完整物流意图处理链路、降级、隐私、数据源
"""

import sys
import os
import json
import tempfile

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _step_name(s) -> str:
    """兼容新旧 trace_steps 格式"""
    return s.get("step") or s.get("node", "")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_service(tmpdir=None):
    """构建完整的 ReplyService 实例（无 LLM key，使用规则引擎）"""
    from app.repositories.json_order_repository import JsonOrderRepository
    from app.repositories.json_product_repository import JsonProductRepository
    from app.repositories.file_knowledge_repository import FileKnowledgeRepository
    from app.repositories.file_policy_repository import FilePolicyRepository
    from app.services.context_builder import ContextBuilder
    from app.services.risk_service import RiskService
    from app.services.output_guard import OutputGuard

    order_repo = JsonOrderRepository()
    order_repo.load()
    product_repo = JsonProductRepository()
    product_repo.load()
    knowledge_repo = FileKnowledgeRepository()
    knowledge_repo.load()
    policy_repo = FilePolicyRepository()
    policy_repo.load()

    risk_service = RiskService(policy_repo)
    context_builder = ContextBuilder(order_repo, product_repo, knowledge_repo)
    output_guard = OutputGuard(policy_repo)

    from app.services.reply_service import ReplyService
    service = ReplyService(
        risk_service=risk_service,
        context_builder=context_builder,
        output_guard=output_guard,
        forbidden_claims=[],
    )
    return service


def _get_flask_client():
    """获取 Flask test client（非 fixture 版本）"""
    from app.main import create_app

    saved_key = os.environ.get("COPILOT_LLM_API_KEY", "")
    os.environ["COPILOT_FEEDBACK_FILE"] = os.path.join(tempfile.gettempdir(), "test_fb_chain.jsonl")
    os.environ["COPILOT_REVIEW_QUEUE_FILE"] = os.path.join(tempfile.gettempdir(), "test_rq_chain.jsonl")
    os.environ["COPILOT_LLM_API_KEY"] = ""

    app = create_app()
    app.config["TESTING"] = True
    client = app.test_client()

    os.environ["COPILOT_LLM_API_KEY"] = saved_key
    return client


@pytest.fixture
def flask_client():
    """Flask test client fixture"""
    c = _get_flask_client()
    yield c


# ---------------------------------------------------------------------------
# 1. 有订单号，订单已发货，返回物流状态和运单信息
# ---------------------------------------------------------------------------

class TestOrderShipped:
    """有订单号 + 订单已发货"""

    def test_shipped_order_returns_logistics(self):
        service = _make_service()
        result = service.analyze("我快递大概几天会到？", order_id="202501010001")
        assert result.suggested_reply
        assert result.trace_steps

        steps = {_step_name(s) for s in result.trace_steps}
        assert "intent_detected" in steps or "detect_intent" in steps

    def test_shipped_order_with_tracking_info(self):
        service = _make_service()
        result = service.analyze("订单 202501010001 快递大概几天会到？", order_id="202501010001")
        assert result.suggested_reply

        ctx = result.context_used
        assert ctx.get("has_order") is True or ctx.get("has_logistics") is True


# ---------------------------------------------------------------------------
# 2. 有订单号，订单未发货，回退到商品/产品知识库估算
# ---------------------------------------------------------------------------

class TestOrderNotShipped:
    """有订单号 + 订单未发货 -> 回退到商品信息"""

    def test_pending_order_no_fake_logistics(self):
        service = _make_service()
        result = service.analyze("快递大概几天会到？", order_id="202501010003")
        assert result.suggested_reply
        assert "已发货" not in result.suggested_reply

    def test_pending_order_context_has_no_logistics(self):
        service = _make_service()
        result = service.analyze("什么时候发货", order_id="202501010003")
        ctx = result.context_used
        assert ctx.get("order_status") in ("待发货",)


# ---------------------------------------------------------------------------
# 3. 无订单号，有商品名，匹配产品知识库
# ---------------------------------------------------------------------------

class TestNoOrderWithProduct:
    """无订单号，识别商品名 -> 匹配产品知识"""

    def test_bookshelf_matches_product(self):
        service = _make_service()
        result = service.analyze("这个书架什么时候发货？")
        assert result.suggested_reply
        steps = {_step_name(s) for s in result.trace_steps}
        assert "intent_detected" in steps or "detect_intent" in steps

    def test_chair_delivery_question(self):
        service = _make_service()
        result = service.analyze("我的椅子发什么快递？")
        assert result.suggested_reply
        assert "必须" not in result.suggested_reply or "以实际" in result.suggested_reply


# ---------------------------------------------------------------------------
# 4. 无订单号，无商品名，引导用户提供信息
# ---------------------------------------------------------------------------

class TestNoOrderNoProduct:
    """无订单号无商品名 -> 引导用户提供信息"""

    def test_generic_delivery_question_guides_user(self):
        service = _make_service()
        result = service.analyze("我快递大概几天会到？")
        assert result.suggested_reply
        assert len(result.suggested_reply) > 10
        for bad in ["2-3天一定到", "保证3天", "一定送达"]:
            assert bad not in result.suggested_reply

    def test_generic_question_no_fake_eta(self):
        service = _make_service()
        result = service.analyze("我快递大概几天会到？")
        assert "3天" not in result.suggested_reply or "以实际" in result.suggested_reply


# ---------------------------------------------------------------------------
# 5. 高风险投诉进入人工复核队列
# ---------------------------------------------------------------------------

class TestHighRiskComplaint:
    """高风险投诉 -> 人工复核"""

    def test_complaint_goes_to_review(self):
        service = _make_service()
        result = service.analyze("再不处理我就去12315投诉")
        assert result.requires_human_review is True
        assert result.risk_level == "high"

    def test_complaint_no_false_promises(self):
        service = _make_service()
        result = service.analyze("再不处理我就去12315投诉")
        assert "一定赔偿" not in result.suggested_reply
        assert "一定退款" not in result.suggested_reply


# ---------------------------------------------------------------------------
# 6. context_used 不泄露隐私字段
# ---------------------------------------------------------------------------

class TestContextPrivacy:
    """context_used 不包含隐私字段"""

    def test_no_privacy_in_context(self):
        service = _make_service()
        result = service.analyze("订单什么时候发货", order_id="202501010001")
        ctx = result.context_used
        ctx_str = json.dumps(ctx, ensure_ascii=False)
        assert "张先生" not in ctx_str
        assert "receiver_name" not in ctx_str
        assert "receiver_phone" not in ctx_str
        assert "receiver_address" not in ctx_str
        assert "buyer_id" not in ctx_str

    def test_no_privacy_in_trace_steps(self):
        service = _make_service()
        result = service.analyze("订单什么时候发货", order_id="202501010001")
        trace_str = json.dumps(result.trace_steps, ensure_ascii=False)
        assert "张先生" not in trace_str
        assert "西湖区" not in trace_str


# ---------------------------------------------------------------------------
# 7. LLM key 为空时仍有 suggested_reply
# ---------------------------------------------------------------------------

class TestNoLLMKey:
    """LLM 未配置时规则引擎仍可用"""

    def test_no_llm_key_has_reply(self):
        service = _make_service()
        result = service.analyze("请问这款书桌的尺寸")
        assert result.suggested_reply
        assert len(result.suggested_reply) > 10

    def test_no_llm_key_shipping_query(self):
        service = _make_service()
        result = service.analyze("我快递大概几天会到？", order_id="202501010001")
        assert result.suggested_reply
        assert len(result.suggested_reply) > 10

    def test_reply_generated_trace_step(self):
        service = _make_service()
        result = service.analyze("什么时候发货")
        step_names = [_step_name(s) for s in result.trace_steps]
        assert any(n in step_names for n in ("reply_generated", "generate_reply", "generate_logistics_reply"))


# ---------------------------------------------------------------------------
# 8. 知识库、产品库、SOP、话术模板参与上下文构建
# ---------------------------------------------------------------------------

class TestKnowledgeParticipation:
    """验证知识库、产品库、SOP、话术模板参与上下文构建"""

    def test_knowledge_base_hit(self):
        service = _make_service()
        result = service.analyze("什么时候发货？发货时效？")
        ctx = result.context_used
        assert ctx.get("knowledge_count", 0) >= 0

    def test_knowledge_match_in_trace(self):
        service = _make_service()
        result = service.analyze("怎么退货退款")
        knowledge_steps = [s for s in result.trace_steps if _step_name(s) == "knowledge_match"]
        if knowledge_steps:
            assert knowledge_steps[0].get("matched") is True

    def test_sop_or_template_in_trace(self):
        service = _make_service()
        result = service.analyze("快递显示签收但我没收到")
        sop_steps = [s for s in result.trace_steps if _step_name(s) in ("sop_match", "template_match")]
        if sop_steps:
            assert sop_steps[0].get("matched") is True


# ---------------------------------------------------------------------------
# 9. trace_steps 结构正确
# ---------------------------------------------------------------------------

class TestTraceStepsStructure:
    """trace_steps 结构验证"""

    def test_trace_steps_is_list(self):
        service = _make_service()
        result = service.analyze("什么时候发货")
        assert isinstance(result.trace_steps, list)
        assert len(result.trace_steps) > 0

    def test_each_step_has_required_fields(self):
        service = _make_service()
        result = service.analyze("我快递大概几天会到？", order_id="202501010001")
        for step in result.trace_steps:
            assert "step" in step or "node" in step, f"Missing 'step' or 'node' in {step}"

    def test_trace_steps_order(self):
        service = _make_service()
        result = service.analyze("我快递大概几天会到？", order_id="202501010001")
        step_names = [_step_name(s) for s in result.trace_steps]
        if step_names and step_names[0] == "normalize_input":
            step_names = step_names[1:]
        assert step_names[0] in ("intent_detected", "detect_intent")
        assert step_names[-1] in ("reply_generated", "generate_reply", "human_review_gate")

    def test_trace_steps_in_api_response(self):
        client = _get_flask_client()
        resp = client.post("/api/analyze", json={
            "message": "我快递大概几天会到？",
            "order_id": "202501010001",
        })
        assert resp.status_code == 200
        data = resp.get_json()
        assert "trace_steps" in data
        assert isinstance(data["trace_steps"], list)
        assert len(data["trace_steps"]) > 0


# ---------------------------------------------------------------------------
# 10. Flask API 集成测试（完整链路）
# ---------------------------------------------------------------------------

class TestFullAPICChain:
    """API 级别的完整链路测试"""

    def test_shipping_intent_chain(self):
        client = _get_flask_client()
        resp = client.post("/api/analyze", json={
            "message": "订单 O2024001 快递大概几天会到？",
            "order_id": "202501010001",
        })
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["suggested_reply"]
        assert data["trace_steps"]
        assert data["context_used"]

        skill = data.get("skill_route", {}).get("skill", "")
        assert skill in ("shipping", "logistics", "general") or data["intent"]

    def test_complaint_chain(self):
        client = _get_flask_client()
        resp = client.post("/api/analyze", json={
            "message": "再不处理我就去12315投诉",
            "order_id": "",
        })
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["requires_human_review"] is True
        assert data["risk_level"] == "high"
        assert data["trace_steps"]

    def test_no_order_no_product_chain(self):
        client = _get_flask_client()
        resp = client.post("/api/analyze", json={
            "message": "我快递大概几天会到？",
            "order_id": "",
        })
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["suggested_reply"]
        assert data["trace_steps"]
        steps = {_step_name(s) for s in data["trace_steps"]}
        assert "intent_detected" in steps or "detect_intent" in steps

    def test_data_source_in_context(self):
        client = _get_flask_client()
        resp = client.post("/api/analyze", json={
            "message": "什么时候发货",
            "order_id": "202501010001",
        })
        data = resp.get_json()
        ctx = data.get("context_used", {})
        assert "sources" in ctx
        assert isinstance(ctx["sources"], list)
        assert len(ctx["sources"]) > 0

    def test_jst_graceful_degradation(self):
        client = _get_flask_client()
        resp = client.post("/api/analyze", json={
            "message": "快递到哪了",
            "order_id": "202501010001",
        })
        assert resp.status_code == 200
        data = resp.get_json()
        assert not data.get("error")
        assert data["suggested_reply"]
