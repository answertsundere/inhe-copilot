from app.services import final_response_orchestrator as orchestrator


class _FakeMessage:
    def __init__(self, content):
        self.content = content


class _FakeChoice:
    def __init__(self, content):
        self.message = _FakeMessage(content)


class _FakeResponse:
    def __init__(self, content):
        self.choices = [_FakeChoice(content)]


class _FakeCompletions:
    def __init__(self, content):
        self.content = content

    def create(self, **kwargs):
        return _FakeResponse(self.content)


class _FakeChat:
    def __init__(self, content):
        self.completions = _FakeCompletions(content)


class _FakeClient:
    api_key = "test-key"
    model = "test-model"

    def __init__(self, content):
        self.client = type("Client", (), {"chat": _FakeChat(content)})()


def test_final_response_orchestrator_runs_audit_before_polish(monkeypatch):
    calls = []

    def fake_audit(response, *, customer_message, copilot_context=None):
        calls.append("audit")
        response["suggested_reply"] = "audited draft"
        response["final_answer_audit"] = {"passed": True, "mode": "fake", "issues": []}
        return response

    def fake_polish(response, *, customer_message="", copilot_context=None):
        calls.append("polish")
        response["suggested_reply"] = response["suggested_reply"] + " polished"
        response["customer_reply_polish"] = {"checked": True, "applied": True, "mode": "fake"}
        return response

    monkeypatch.setattr(orchestrator, "audit_final_answer", fake_audit)
    monkeypatch.setattr(orchestrator, "polish_customer_reply", fake_polish)

    result = orchestrator.orchestrate_final_response(
        {"suggested_reply": "draft"},
        customer_message="question",
    )

    assert calls == ["audit", "polish"]
    assert result["suggested_reply"] == "audited draft polished"
    assert result["final_response_pipeline"]["order"][:3] == [
        "semantic_and_redline_audit",
        "customer_language_polish",
        "llm_customer_language_polish",
    ]
    assert "final_semantic_fit_audit" in result["final_response_pipeline"]["order"]


def test_final_response_orchestrator_blocks_internal_language_after_polish(monkeypatch):
    def fake_audit(response, *, customer_message, copilot_context=None):
        response["final_answer_audit"] = {"passed": True, "mode": "fake", "issues": []}
        return response

    def fake_polish(response, *, customer_message="", copilot_context=None):
        response["suggested_reply"] = "亲～这个可以看系统资料库里的内容。"
        response["customer_reply_polish"] = {"checked": True, "applied": True, "mode": "fake"}
        return response

    monkeypatch.setattr(orchestrator, "audit_final_answer", fake_audit)
    monkeypatch.setattr(orchestrator, "polish_customer_reply", fake_polish)

    result = orchestrator.orchestrate_final_response(
        {"suggested_reply": "draft", "requires_human_review": False},
        customer_message="这个可以用吗",
    )

    assert result["requires_human_review"] is True
    assert "系统" not in result["suggested_reply"]
    assert "资料库" not in result["suggested_reply"]
    assert result["evidence_debug"]["post_polish_redline"]["passed"] is False
    assert result["generation_mode"] == "post_polish_redline_fallback"


def test_final_response_orchestrator_syncs_text_reply_block(monkeypatch):
    def fake_audit(response, *, customer_message, copilot_context=None):
        response["suggested_reply"] = "final text"
        response["final_answer_audit"] = {"passed": True, "mode": "fake", "issues": []}
        return response

    def fake_polish(response, *, customer_message="", copilot_context=None):
        response["suggested_reply"] = "polished final text"
        response["customer_reply_polish"] = {"checked": True, "applied": True, "mode": "fake"}
        return response

    monkeypatch.setattr(orchestrator, "audit_final_answer", fake_audit)
    monkeypatch.setattr(orchestrator, "polish_customer_reply", fake_polish)

    result = orchestrator.orchestrate_final_response(
        {
            "suggested_reply": "draft",
            "reply_blocks": [
                {"type": "text", "content": "old text"},
                {"type": "image", "url": "https://example.com/a.png"},
            ],
        },
        customer_message="发我尺寸图",
    )

    assert result["reply_blocks"][0]["content"] == result["suggested_reply"]
    assert result["reply_blocks"][1]["type"] == "image"


def test_final_response_orchestrator_reapplies_no_evidence_policy_after_polish(monkeypatch):
    def fake_audit(response, *, customer_message, copilot_context=None):
        response["final_answer_audit"] = {"passed": True, "mode": "fake", "issues": []}
        return response

    def fake_polish(response, *, customer_message="", copilot_context=None):
        response["suggested_reply"] = "亲，您可以参考下面发您的商品图/尺寸图。"
        response["customer_reply_polish"] = {"checked": True, "applied": True, "mode": "fake"}
        return response

    monkeypatch.setattr(orchestrator, "audit_final_answer", fake_audit)
    monkeypatch.setattr(orchestrator, "polish_customer_reply", fake_polish)

    result = orchestrator.orchestrate_final_response(
        {
            "suggested_reply": "亲，我先帮您核对对应尺寸资料。",
            "query_fact_type": "dimensions",
            "evidence_debug": {"query_fact_type": "dimensions", "selected_evidence": []},
            "answer_trace": {"query_fact_type": "dimensions", "required_fact_types": ["dimensions"]},
            "recommended_assets": [],
        },
        customer_message="这个多高，有图吗？",
        copilot_context={
            "product_name": "demo product",
            "turn_understanding": {
                "turn_actionability": "actionable_question",
                "query_fact_type": "dimensions",
            },
        },
    )

    assert result["generation_mode"] == "no_evidence_reply_policy"
    assert result["requires_human_review"] is True
    assert "下面发" not in result["suggested_reply"]
    assert "商品图/尺寸图" not in result["suggested_reply"]
    assert result["answer_trace"]["no_evidence_reply_policy"]["reply_strategy"] == "verify_dimensions_for_known_product"
    assert result["reply_blocks"][0]["content"] == result["suggested_reply"]


def test_final_response_orchestrator_keeps_placement_scene_no_evidence_handoff():
    result = orchestrator.orchestrate_final_response(
        {
            "suggested_reply": "亲，放在卧室、客厅都可以，建议摆在干燥平整的位置，不建议长期暴晒。",
            "query_fact_type": "placement_scene",
            "evidence_debug": {"query_fact_type": "placement_scene", "selected_evidence": []},
            "answer_trace": {"query_fact_type": "placement_scene", "required_fact_types": ["placement_scene"]},
            "recommended_assets": [],
        },
        customer_message="可以放在飘窗上晒吗？",
        copilot_context={
            "product_name": "demo product",
            "turn_understanding": {
                "turn_actionability": "actionable_question",
                "query_fact_type": "placement_scene",
            },
        },
    )

    assert result["requires_human_review"] is True
    assert result["answer_trace"]["no_evidence_reply_policy"]["reply_strategy"] == "verify_placement_scene_for_known_product"
    assert "卧室" not in result["suggested_reply"]
    assert "客厅" not in result["suggested_reply"]
    assert "长期暴晒" not in result["suggested_reply"]
    assert result.get("generation_mode") != "final_answer_audit_fallback"


def test_final_response_orchestrator_can_use_llm_language_expert(monkeypatch):
    from app import config
    from app.llm import client as llm_client

    def fake_audit(response, *, customer_message, copilot_context=None):
        response["final_answer_audit"] = {"passed": True, "mode": "fake", "issues": []}
        return response

    def fake_polish(response, *, customer_message="", copilot_context=None):
        response["customer_reply_polish"] = {"checked": True, "applied": False, "mode": "fake"}
        return response

    monkeypatch.setattr(config, "COPILOT_FINAL_POLISH_LLM_ENABLED", True)
    monkeypatch.setattr(orchestrator, "audit_final_answer", fake_audit)
    monkeypatch.setattr(orchestrator, "polish_customer_reply", fake_polish)
    monkeypatch.setattr(
        llm_client,
        "get_llm_client",
        lambda: _FakeClient('{"reply": "亲～这款可以参考下面的尺寸图，您可以先对照家里预留位置看一下。", "reason": "polished"}'),
    )

    result = orchestrator.orchestrate_final_response(
        {"suggested_reply": "draft", "reply_blocks": [{"type": "text", "content": "draft"}]},
        customer_message="可以告诉我产品大小吗",
    )

    assert result["llm_customer_language_polish"]["applied"] is True
    assert "尺寸图" in result["suggested_reply"]
    assert result["reply_blocks"][0]["content"] == result["suggested_reply"]


def test_final_response_orchestrator_rejects_llm_polish_with_internal_language(monkeypatch):
    from app import config
    from app.llm import client as llm_client

    def fake_audit(response, *, customer_message, copilot_context=None):
        response["final_answer_audit"] = {"passed": True, "mode": "fake", "issues": []}
        return response

    def fake_polish(response, *, customer_message="", copilot_context=None):
        response["suggested_reply"] = "亲～我这边继续帮您看。"
        response["customer_reply_polish"] = {"checked": True, "applied": True, "mode": "fake"}
        return response

    monkeypatch.setattr(config, "COPILOT_FINAL_POLISH_LLM_ENABLED", True)
    monkeypatch.setattr(orchestrator, "audit_final_answer", fake_audit)
    monkeypatch.setattr(orchestrator, "polish_customer_reply", fake_polish)
    monkeypatch.setattr(
        llm_client,
        "get_llm_client",
        lambda: _FakeClient('{"reply": "亲～系统资料库里显示可以。", "reason": "bad"}'),
    )

    result = orchestrator.orchestrate_final_response(
        {"suggested_reply": "draft"},
        customer_message="这个可以用吗",
    )

    assert "llm_customer_language_polish" not in result
    assert result["suggested_reply"] == "亲～我这边继续帮您看。"


def test_final_response_orchestrator_rejects_llm_polish_that_shortens_display_name(monkeypatch):
    from app import config
    from app.llm import client as llm_client

    display_name = "英禾防夹滑门收纳架整理客厅零食桌面儿童玩具卧室可拼搭储物抽屉"

    def fake_audit(response, *, customer_message, copilot_context=None):
        response["final_answer_audit"] = {"passed": True, "mode": "fake", "issues": []}
        return response

    def fake_polish(response, *, customer_message="", copilot_context=None):
        response["customer_reply_polish"] = {"checked": True, "applied": False, "mode": "fake"}
        return response

    monkeypatch.setattr(config, "COPILOT_FINAL_POLISH_LLM_ENABLED", True)
    monkeypatch.setattr(orchestrator, "audit_final_answer", fake_audit)
    monkeypatch.setattr(orchestrator, "polish_customer_reply", fake_polish)
    monkeypatch.setattr(
        llm_client,
        "get_llm_client",
        lambda: _FakeClient('{"reply": "亲～英禾防夹滑门收纳架的尺寸可以参考下面图片。", "reason": "shortened"}'),
    )

    original = f"亲～关于「{display_name}」：这款商品的尺寸可以参考下面发送的尺寸/规格图片。"
    result = orchestrator.orchestrate_final_response(
        {
            "suggested_reply": original,
            "display_product_name": display_name,
        },
        customer_message="可以告诉我产品大小吗",
    )

    assert "llm_customer_language_polish" not in result
    assert result["suggested_reply"] == original


def test_final_response_orchestrator_exposes_blocked_sendable_contract(monkeypatch):
    def fake_audit(response, *, customer_message, copilot_context=None):
        response["final_answer_audit"] = {"passed": True, "mode": "fake", "issues": []}
        return response

    def fake_polish(response, *, customer_message="", copilot_context=None):
        response["customer_reply_polish"] = {"checked": True, "applied": False, "mode": "fake"}
        return response

    monkeypatch.setattr(orchestrator, "audit_final_answer", fake_audit)
    monkeypatch.setattr(orchestrator, "polish_customer_reply", fake_polish)

    result = orchestrator.orchestrate_final_response(
        {
            "suggested_reply": "\u4eb2\uff0c\u8fd9\u6b3e\u5355\u5c42\u627f\u91cd\u7ea620kg\uff0c\u653e\u4e66\u548c\u73a9\u5177\u90fd\u591f\u7528\u3002",
            "requires_human_review": False,
            "evidence_debug": {
                "query_fact_type": "gross_weight",
                "selected_evidence": [{"fact_type": "gross_weight", "content": "\u6bdb\u91cd\u8bc1\u636e"}],
            },
            "reply_delivery": {"auto_send_ready": True},
        },
        customer_message="\u8fd9\u4e2a\u591a\u91cd\uff1f",
    )

    assert result["draft_reply"] == result["suggested_reply"]
    assert result["sendable_reply"] == ""
    assert result["can_send"] is False
    assert result["reply_status"] == "needs_human_review"
    assert "gross_weight_answered_with_load_capacity" in result["block_reasons"]
    assert result["reply_delivery"]["auto_send_ready"] is False
