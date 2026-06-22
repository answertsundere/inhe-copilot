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
    assert result["reason_for_review"] == "最终润色后命中红线，已改为保守客服话术"
    assert "鏈€缁堟鼎" not in result["reason_for_review"]


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


def test_final_response_orchestrator_rejects_llm_polish_that_keeps_only_short_product_name(monkeypatch):
    from app import config
    from app.llm import client as llm_client

    display_name = "儿童书架收纳柜家用多层置物架"

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
        lambda: _FakeClient('{"reply": "亲，这款书架的尺寸可以参考页面标注。", "reason": "shortened"}'),
    )

    original = f"亲，关于「{display_name}」，尺寸可以参考页面标注。"
    result = orchestrator.orchestrate_final_response(
        {
            "suggested_reply": original,
            "display_product_name": display_name,
        },
        customer_message="这个尺寸多大？",
    )

    assert "llm_customer_language_polish" not in result
    assert result["suggested_reply"] == original
    rejected = result["evidence_debug"]["llm_customer_language_polish_rejected"]
    assert rejected["reason"] == "display_product_name_dropped"


def test_final_response_orchestrator_accepts_llm_polish_that_preserves_display_name(monkeypatch):
    from app import config
    from app.llm import client as llm_client

    display_name = "儿童书架收纳柜家用多层置物架"
    polished = f"亲，{display_name}的尺寸可以先参考页面标注，您也可以把预留空间发我，我帮您一起核对。"

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
        lambda: _FakeClient(f'{{"reply": "{polished}", "reason": "polished"}}'),
    )

    original = f"亲，关于「{display_name}」，尺寸可以参考页面标注。"
    result = orchestrator.orchestrate_final_response(
        {
            "suggested_reply": original,
            "display_product_name": display_name,
        },
        customer_message="这个尺寸多大？",
    )

    assert result["llm_customer_language_polish"]["applied"] is True
    assert result["suggested_reply"] == polished
