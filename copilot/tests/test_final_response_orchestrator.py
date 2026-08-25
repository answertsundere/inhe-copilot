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

    def create_chat_completion(self, **kwargs):
        return self.client.chat.completions.create(**kwargs)


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


def test_final_response_orchestrator_preserves_evidence_relevance_when_final_fit_passes(monkeypatch):
    """Semantic fit must not overwrite the upstream evidence relevance signal."""
    def fake_audit(response, *, customer_message, copilot_context=None):
        response["final_answer_audit"] = {"passed": True, "mode": "fake", "issues": []}
        return response

    def fake_polish(response, *, customer_message="", copilot_context=None):
        return response

    def fake_semantic_fit(response, *, customer_message, copilot_context=None):
        return {"passed": True, "issues": [], "fallback_used": False}

    monkeypatch.setattr(orchestrator, "audit_final_answer", fake_audit)
    monkeypatch.setattr(orchestrator, "polish_customer_reply", fake_polish)
    monkeypatch.setattr(orchestrator, "audit_customer_reply_semantic_fit", fake_semantic_fit)

    result = orchestrator.orchestrate_final_response(
        {
            "suggested_reply": "Please share the specific issue for review.",
            "requires_human_review": True,
            "can_send": False,
            "evidence_debug": {"answer_relevance_passed": False},
        },
        customer_message="Can you check what happened?",
    )

    assert result["evidence_debug"]["answer_relevance_passed"] is False
    assert result["evidence_debug"]["final_response_relevance_passed"] is True


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


def test_final_response_orchestrator_rejects_repolish_that_drops_short_display_name(monkeypatch):
    display_name = "儿童书架收纳柜家用多层置物架"
    original = f"亲，关于《{display_name}》：这款尺寸图可以参考下面图片。"

    def fake_audit(response, *, customer_message, copilot_context=None):
        response["final_answer_audit"] = {"passed": True, "mode": "fake", "issues": []}
        return response

    def fake_polish(response, *, customer_message="", copilot_context=None):
        response["suggested_reply"] = original
        response["display_product_name"] = display_name
        response["customer_reply_polish"] = {"checked": True, "applied": True, "mode": "fake"}
        return response

    monkeypatch.setattr(orchestrator, "audit_final_answer", fake_audit)
    monkeypatch.setattr(orchestrator, "polish_customer_reply", fake_polish)
    monkeypatch.setattr(orchestrator, "_polish_text", lambda text: text.replace(display_name, "书架"))

    result = orchestrator.orchestrate_final_response(
        {
            "suggested_reply": original,
            "display_product_name": display_name,
            "recommended_assets": [{
                "asset_type": "size_image",
                "asset_url": "https://example.com/size.png",
                "auto_send_level": "auto",
            }],
            "reply_blocks": [
                {"type": "text", "content": original},
                {"type": "image", "url": "https://example.com/size.png", "send_mode": "auto_when_platform_connected"},
            ],
        },
        customer_message="这个尺寸多大？",
    )

    assert result["suggested_reply"] == original
    assert result["evidence_debug"]["customer_reply_repolish_rejected"]["reason"] == "display_product_name_dropped"


def test_final_response_orchestrator_marks_auto_send_ready_for_matching_media_block(monkeypatch):
    def fake_audit(response, *, customer_message, copilot_context=None):
        response["final_answer_audit"] = {"passed": True, "mode": "fake", "issues": []}
        return response

    monkeypatch.setattr(orchestrator, "audit_final_answer", fake_audit)
    monkeypatch.setattr(orchestrator, "apply_no_evidence_reply_policy", lambda response, copilot_context=None: response)
    monkeypatch.setattr(orchestrator, "polish_customer_reply", lambda response, **kwargs: response)

    result = orchestrator.orchestrate_final_response(
        {
            "suggested_reply": "请参考下面的尺寸图。",
            "recommended_assets": [{
                "asset_type": "sku_image",
                "asset_url": "https://example.com/size.png?signature=secret",
                "auto_send_level": "auto",
            }],
            "reply_blocks": [
                {"type": "text", "content": "old"},
                {"type": "image", "url": "https://example.com/size.png", "send_mode": "auto_when_platform_connected"},
            ],
            "reply_delivery": {"mode": "blocks", "auto_send_ready": False, "reason": "not_synced"},
        },
        customer_message="有尺寸图吗？",
    )

    assert result["can_send"] is True
    assert result["reply_delivery"]["auto_send_ready"] is True


def test_final_response_orchestrator_does_not_auto_send_media_without_url_or_auto_level(monkeypatch):
    def fake_audit(response, *, customer_message, copilot_context=None):
        response["final_answer_audit"] = {"passed": True, "mode": "fake", "issues": []}
        return response

    monkeypatch.setattr(orchestrator, "audit_final_answer", fake_audit)
    monkeypatch.setattr(orchestrator, "apply_no_evidence_reply_policy", lambda response, copilot_context=None: response)
    monkeypatch.setattr(orchestrator, "polish_customer_reply", lambda response, **kwargs: response)

    missing_url = orchestrator.orchestrate_final_response(
        {
            "suggested_reply": "请参考下面的尺寸图。",
            "recommended_assets": [{"asset_type": "sku_image", "auto_send_level": "auto"}],
            "reply_blocks": [{"type": "text", "content": "old"}, {"type": "image", "send_mode": "auto_when_platform_connected"}],
            "reply_delivery": {"mode": "blocks", "auto_send_ready": True},
        },
        customer_message="有尺寸图吗？",
    )
    review_asset = orchestrator.orchestrate_final_response(
        {
            "suggested_reply": "请参考下面的尺寸图。",
            "recommended_assets": [{
                "asset_type": "sku_image",
                "asset_url": "https://example.com/size.png",
                "auto_send_level": "review",
            }],
            "reply_blocks": [
                {"type": "text", "content": "old"},
                {"type": "image", "url": "https://example.com/size.png", "send_mode": "auto_when_platform_connected"},
            ],
            "reply_delivery": {"mode": "blocks", "auto_send_ready": True},
        },
        customer_message="有尺寸图吗？",
    )

    assert missing_url["can_send"] is True
    assert missing_url["reply_delivery"]["auto_send_ready"] is False
    assert review_asset["can_send"] is True
    assert review_asset["reply_delivery"]["auto_send_ready"] is False


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
    assert result["final_answer_audit"]["passed"] is True
    assert result["final_answer_audit"]["mode"] == "no_evidence_controlled_reply"


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


def test_final_response_orchestrator_aligns_combined_media_reference_to_attached_block(monkeypatch):
    from app import config
    from app.llm import client as llm_client

    def fake_audit(response, *, customer_message, copilot_context=None):
        response["final_answer_audit"] = {"passed": True, "mode": "fake", "issues": []}
        return response

    monkeypatch.setattr(config, "COPILOT_FINAL_POLISH_LLM_ENABLED", True)
    monkeypatch.setattr(orchestrator, "audit_final_answer", fake_audit)
    monkeypatch.setattr(orchestrator, "polish_customer_reply", lambda response, **kwargs: response)
    monkeypatch.setattr(orchestrator, "apply_no_evidence_reply_policy", lambda response, copilot_context=None: response)
    monkeypatch.setattr(
        llm_client,
        "get_llm_client",
        lambda: _FakeClient('{"reply": "亲，下面图片/视频可参考。", "reason": "polished"}'),
    )

    result = orchestrator.orchestrate_final_response(
        {
            "suggested_reply": "draft",
            "query_fact_type": "installation",
            "i_id": "IID-A",
            "reply_blocks": [
                {"type": "text", "content": "draft"},
                {
                    "type": "image",
                    "url": "https://asset.example/guide.png",
                    "asset_type": "pack_guide_image",
                    "i_id": "IID-A",
                },
            ],
        },
        customer_message="有安装资料吗",
    )

    assert "图片可参考" in result["suggested_reply"]
    assert "图片/视频" not in result["suggested_reply"]
    assert result["evidence_debug"]["media_reference_alignment"]["source"] == "attached_reply_blocks"


def test_final_response_orchestrator_reaudits_final_text_after_semantic_fallback(monkeypatch):
    audit_inputs = []
    semantic_calls = []

    def fake_audit(response, *, customer_message, copilot_context=None):
        audit_inputs.append(response["suggested_reply"])
        response["final_answer_audit"] = {"passed": True, "mode": "fake", "issues": []}
        return response

    def fake_semantic(response, *, customer_message, copilot_context=None):
        semantic_calls.append(response["suggested_reply"])
        if len(semantic_calls) > 1:
            return {"passed": True, "issues": [], "reason": "settled"}
        return {"passed": False, "issues": ["unsupported_media_claim"], "reason": "fake"}

    def fake_apply_semantic(response, result, *, copilot_context=None):
        response["suggested_reply"] = "亲，我先按当前情况核对安装资料，确认后给您准确回复。"
        response["requires_human_review"] = True
        result["fallback_used"] = True
        response["final_semantic_fit_audit"] = result
        return response

    monkeypatch.setattr(orchestrator, "audit_final_answer", fake_audit)
    monkeypatch.setattr(orchestrator, "audit_customer_reply_semantic_fit", fake_semantic)
    monkeypatch.setattr(orchestrator, "apply_semantic_fit_result", fake_apply_semantic)
    monkeypatch.setattr(orchestrator, "apply_no_evidence_reply_policy", lambda response, copilot_context=None: response)
    monkeypatch.setattr(orchestrator, "polish_customer_reply", lambda response, **kwargs: response)

    result = orchestrator.orchestrate_final_response(
        {"suggested_reply": "亲，下面视频可参考。"},
        customer_message="有安装资料吗",
    )

    assert audit_inputs[-1] == result["suggested_reply"]
    assert len(audit_inputs) == 2
    assert result["final_response_pipeline"]["order"].count("post_semantic_fallback_audit") == 1
    assert result["final_semantic_fit_audit"]["passed"] is True


def test_final_response_orchestrator_reaudits_non_media_semantic_fallback(monkeypatch):
    audit_inputs = []
    semantic_calls = []

    def fake_audit(response, *, customer_message, copilot_context=None):
        audit_inputs.append(response["suggested_reply"])
        response["final_answer_audit"] = {"passed": True, "mode": "fake", "issues": []}
        return response

    def fake_semantic(response, *, customer_message, copilot_context=None):
        semantic_calls.append(response["suggested_reply"])
        return {"passed": len(semantic_calls) > 1, "issues": ["semantic_mismatch"] if len(semantic_calls) == 1 else []}

    def fake_apply_semantic(response, result, *, copilot_context=None):
        response["suggested_reply"] = "亲，我先按当前情况核对后给您回复。"
        response["requires_human_review"] = True
        result["fallback_used"] = True
        response["final_semantic_fit_audit"] = result
        return response

    monkeypatch.setattr(orchestrator, "audit_final_answer", fake_audit)
    monkeypatch.setattr(orchestrator, "audit_customer_reply_semantic_fit", fake_semantic)
    monkeypatch.setattr(orchestrator, "apply_semantic_fit_result", fake_apply_semantic)
    monkeypatch.setattr(orchestrator, "apply_no_evidence_reply_policy", lambda response, copilot_context=None: response)
    monkeypatch.setattr(orchestrator, "polish_customer_reply", lambda response, **kwargs: response)
    result = orchestrator.orchestrate_final_response({"suggested_reply": "原回复"}, customer_message="问题")
    assert len(audit_inputs) == 2
    assert result["final_semantic_fit_audit"]["passed"] is True


def test_final_response_orchestrator_restores_partial_claims_after_stylistic_fallback(monkeypatch):
    monkeypatch.setenv("COPILOT_FORMAL_EVIDENCE_CONVERGENCE_ENABLED", "true")
    candidate = "\u4eb2\uff0c\u8fd9\u6b3e\u4e3b\u4f53\u6750\u8d28\u662f PP\u3002\u5b89\u5168\u65b9\u9762\u8fd8\u9700\u8981\u5bf9\u7167\u4e13\u9879\u8bf4\u660e\u786e\u8ba4\u3002"

    def fake_audit(response, **kwargs):
        response["final_answer_audit"] = {"passed": True, "issues": []}
        return response

    monkeypatch.setattr(orchestrator, "apply_no_evidence_reply_policy", lambda response, copilot_context=None: response)
    monkeypatch.setattr(orchestrator, "audit_final_answer", fake_audit)
    monkeypatch.setattr(orchestrator, "polish_customer_reply", lambda response, **kwargs: {**response, "suggested_reply": "\u4eb2\uff0c\u6211\u5e2e\u60a8\u6838\u5bf9\u3002"})
    monkeypatch.setattr(orchestrator, "audit_customer_reply_semantic_fit", lambda *args, **kwargs: {"passed": True, "issues": []})

    result = orchestrator.orchestrate_final_response(
        {
            "suggested_reply": "draft",
            "evidence_debug": {"supervisor_candidate_preview": {
                "candidate_text": candidate,
                "confirmed_clauses": [{"customer_facing_clause": "\u8fd9\u6b3e\u4e3b\u4f53\u6750\u8d28\u662f PP\u3002"}],
                "pending_clauses": [{"customer_facing_clause": "\u5b89\u5168\u65b9\u9762\u8fd8\u9700\u8981\u5bf9\u7167\u4e13\u9879\u8bf4\u660e\u786e\u8ba4\u3002"}],
                "conflicting_clauses": [],
                "evidence_uids": ["evidence-material"],
                "safety_validation": {"passed": True},
            }},
        },
        customer_message="\u6750\u8d28\u5b89\u5168\u5417\uff1f",
    )

    assert "\u8fd9\u6b3e\u4e3b\u4f53\u6750\u8d28\u662f PP\u3002" in result["suggested_reply"]
    assert "\u5b89\u5168\u65b9\u9762\u8fd8\u9700\u8981\u5bf9\u7167\u4e13\u9879\u8bf4\u660e\u786e\u8ba4\u3002" in result["suggested_reply"]
    assert result["can_send"] is False
    assert result["requires_human_review"] is True
    assert result["evidence_debug"]["formal_partial_clause_restore"]["evidence_uids"] == ["evidence-material"]


def test_final_response_orchestrator_rejects_llm_polish_that_drops_current_product_anchor(monkeypatch):
    from app import config
    from app.llm import client as llm_client

    def fake_audit(response, *, customer_message, copilot_context=None):
        response["final_answer_audit"] = {"passed": True, "mode": "fake", "issues": []}
        return response

    original = "亲，我先按当前这款商品核对安装资料，确认后给您准确回复。"
    monkeypatch.setattr(config, "COPILOT_FINAL_POLISH_LLM_ENABLED", True)
    monkeypatch.setattr(orchestrator, "audit_final_answer", fake_audit)
    monkeypatch.setattr(orchestrator, "polish_customer_reply", lambda response, **kwargs: response)
    monkeypatch.setattr(
        llm_client,
        "get_llm_client",
        lambda: _FakeClient('{"reply": "亲，您已经看到视频了是吧？我帮您一起看。", "reason": "polished"}'),
    )

    result = orchestrator.orchestrate_final_response(
        {"suggested_reply": original},
        customer_message="上面有视频啊",
    )

    assert "按当前这款商品" in result["suggested_reply"]
    assert result["evidence_debug"]["llm_customer_language_polish_rejected"]["reason"] == "current_product_anchor_dropped"


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
            "recommended_assets": [{
                "asset_type": "size_image",
                "asset_url": "https://example.com/size.png",
                "auto_send_level": "auto",
            }],
            "reply_blocks": [
                {"type": "text", "content": original},
                {"type": "image", "url": "https://example.com/size.png", "send_mode": "auto_when_platform_connected"},
            ],
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
    assert result["block_reasons"] == ["最终回复语义一致性未通过"]
    assert result["reply_delivery"]["auto_send_ready"] is False


def test_blocked_status_is_normalized_to_human_review(monkeypatch):
    monkeypatch.setattr(
        orchestrator,
        "audit_final_answer",
        lambda response, **_kwargs: {
            **response,
            "final_answer_audit": {"passed": True, "issues": []},
        },
    )
    monkeypatch.setattr(orchestrator, "polish_customer_reply", lambda response, **_kwargs: response)

    result = orchestrator.orchestrate_final_response(
        {
            "suggested_reply": "The supported fact is available, but the safety claim still needs review.",
            "reply_status": "blocked",
            "can_send": False,
            "requires_human_review": False,
        },
        customer_message="Can you confirm both the specification and safety claim?",
    )

    assert result["can_send"] is False
    assert result["requires_human_review"] is True
    assert result["reply_status"] == "needs_human_review"
    assert result["sendable_reply"] == ""
    assert "upstream_reply_blocked" in result["block_reasons"]


def test_formal_non_fact_only_context_cannot_create_sendable_media(monkeypatch):
    monkeypatch.setenv("COPILOT_FORMAL_EVIDENCE_CONVERGENCE_ENABLED", "true")
    monkeypatch.setattr(
        orchestrator,
        "audit_final_answer",
        lambda response, **_kwargs: {
            **response,
            "final_answer_audit": {"passed": True, "issues": []},
        },
    )
    monkeypatch.setattr(orchestrator, "polish_customer_reply", lambda response, **_kwargs: response)

    result = orchestrator.orchestrate_final_response(
        {
            "suggested_reply": "\u4eb2\uff0c\u4e0b\u9762\u56fe\u7247\u53ef\u4ee5\u53c2\u8003\u3002",
            "can_send": True,
            "requires_human_review": False,
            "reply_status": "sendable",
            "recommended_assets": [{
                "asset_type": "install_image",
                "asset_url": "https://asset.example/guide.png",
                "status": "approved",
                "usable_for_agent": True,
                "i_id": "IID-A",
                "auto_send_level": "auto",
            }],
            "reply_blocks": [
                {"type": "text", "content": "old"},
                {
                    "type": "image",
                    "url": "https://asset.example/guide.png",
                    "asset_type": "install_image",
                    "status": "approved",
                    "usable_for_agent": True,
                    "i_id": "IID-A",
                    "send_mode": "auto_when_platform_connected",
                },
            ],
            "evidence_debug": {
                "query_fact_type": "installation",
                "admitted_answer_context": {
                    "direct_product_facts": [],
                    "direct_policy_facts": [],
                    "handoff_action_guidance": [{"evidence_uid": "action-1"}],
                    "media_candidates": [{"evidence_uid": "media-1"}],
                    "unresolved_claims": [{"claim_type": "installation", "status": "unresolved"}],
                },
            },
            "i_id": "IID-A",
        },
        customer_message="How should this be installed?",
    )

    assert result["can_send"] is False
    assert result["requires_human_review"] is True
    assert result["reply_status"] == "needs_human_review"
    assert [block["type"] for block in result["reply_blocks"]] == ["text"]
    assert "\u4e0b\u9762\u56fe\u7247" not in result["suggested_reply"]
    assert "formal_non_fact_evidence_only" in result["block_reasons"]
    diagnostics = result["evidence_debug"]["formal_delivery_contract"]
    assert diagnostics["service_action_used_for_fact"] is False
    assert diagnostics["media_reference_used_for_fact"] is False
    assert diagnostics["removed_media_block_count"] == 1


def test_formal_non_fact_only_preserves_validated_media_for_manual_review(monkeypatch):
    monkeypatch.setenv("COPILOT_FORMAL_EVIDENCE_CONVERGENCE_ENABLED", "true")
    monkeypatch.setattr(
        orchestrator,
        "audit_final_answer",
        lambda response, **_kwargs: {
            **response,
            "final_answer_audit": {"passed": True, "issues": []},
        },
    )
    monkeypatch.setattr(
        orchestrator,
        "polish_customer_reply",
        lambda response, **_kwargs: response,
    )

    result = orchestrator.orchestrate_final_response(
        {
            "suggested_reply": "亲，安装视频随本次回复附上，拆装方式还需要人工确认。",
            "can_send": True,
            "requires_human_review": False,
            "reply_status": "sendable",
            "recommended_assets": [{
                "asset_type": "install_video",
                "asset_url": "https://asset.example/install.mp4",
                "status": "approved",
                "usable_for_agent": True,
                "i_id": "IID-A",
                "auto_send_level": "auto",
                "delivery_candidate_source": "product_context_pack",
            }],
            "reply_blocks": [
                {"type": "text", "content": "old"},
                {
                    "type": "video",
                    "url": "https://asset.example/install.mp4",
                    "asset_type": "install_video",
                    "status": "approved",
                    "usable_for_agent": True,
                    "i_id": "IID-A",
                    "delivery_candidate_source": "product_context_pack",
                    "send_mode": "auto_when_platform_connected",
                },
            ],
            "evidence_debug": {
                "query_fact_type": "installation",
                "admitted_answer_context": {
                    "direct_product_facts": [],
                    "direct_policy_facts": [],
                    "handoff_action_guidance": [],
                    "media_candidates": [{"evidence_uid": "media-1"}],
                    "unresolved_claims": [
                        {"claim_type": "installation", "status": "unresolved"},
                    ],
                },
                "media_delivery_contract": {
                    "candidate_source": "product_context_pack",
                    "candidate_count": 1,
                    "eligible_asset_count": 1,
                    "actual_attached_media_count": 1,
                    "attached_media": [{
                        "type": "video",
                        "asset_type": "install_video",
                        "delivery_candidate_source": "product_context_pack",
                        "review_status": "approved",
                        "review_approved": True,
                        "usable_for_agent": True,
                        "identity_present": True,
                        "identity_matched": True,
                        "role_matched": True,
                    }],
                },
            },
            "i_id": "IID-A",
        },
        customer_message="请发这个商品对应的安装视频。",
    )

    assert [block["type"] for block in result["reply_blocks"]] == ["text", "video"]
    assert result["reply_blocks"][1]["send_mode"] == "manual"
    assert result["can_send"] is False
    assert result["requires_human_review"] is True
    diagnostics = result["evidence_debug"]["formal_delivery_contract"]
    assert diagnostics["removed_media_block_count"] == 0
    assert diagnostics["actual_attached_media_count"] == 1
    assert diagnostics["validated_media_review_only"] is True


def test_model_first_candidate_skips_semantic_polish_and_stays_review_only(
    monkeypatch,
):
    calls = []

    def fake_final(response, **_kwargs):
        calls.append("final")
        return {
            **response,
            "final_answer_audit": {
                "passed": True,
                "issues": [],
                "model_call_count": 0,
            },
        }

    def fake_unified(*_args, **_kwargs):
        calls.append("unified")
        return {
            "passed": True,
            "issues": [],
            "mode": "test",
            "provider_diagnostics": {
                "model_call_count": 1,
                "retry_count": 0,
                "repair_count": 0,
            },
        }

    monkeypatch.setattr(
        orchestrator,
        "audit_final_answer",
        fake_final,
    )
    monkeypatch.setattr(
        orchestrator,
        "audit_customer_reply_semantic_fit",
        fake_unified,
    )
    monkeypatch.setattr(
        orchestrator,
        "polish_customer_reply",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("semantic polisher must not run")
        ),
    )
    monkeypatch.setattr(
        orchestrator,
        "_optional_llm_language_polish",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("LLM polisher must not run")
        ),
    )

    result = orchestrator.orchestrate_final_response(
        {
            "suggested_reply": "宽度是80厘米。\n\n儿童安全方面目前没有直接依据。",
            "can_send": True,
            "requires_human_review": False,
            "reply_status": "sendable",
            "reply_blocks": [{"type": "text", "content": "old"}],
            "model_first_answer_composer": {
                "status": "accepted",
                "used_for_final_reply": True,
                "can_change_can_send": False,
            },
        },
        customer_message="尺寸和安全怎么样",
    )

    assert result["suggested_reply"] == "宽度是80厘米。\n\n儿童安全方面目前没有直接依据。"
    assert calls == ["final", "unified"]
    assert result["final_response_pipeline"]["mode"] == "model_first_candidate"
    assert result["final_response_pipeline"]["order"] == [
        "non_semantic_cleanup",
        "model_first_preflight_redline",
        "model_first_deterministic_final_contract",
        "model_first_unified_textual_audit",
        "reply_block_sync",
    ]
    assert [
        item["model_call_count"]
        for item in result["final_response_pipeline"]["stages"]
        if "model_call_count" in item
    ] == [0, 1]
    assert result["customer_reply_polish"]["mode"] == "non_semantic_cleanup_only"
    assert result["can_send"] is False
    assert result["requires_human_review"] is True
    assert result["sendable_reply"] == ""
    assert result["reply_blocks"][0]["content"] == result["suggested_reply"]


def test_model_first_noop_keeps_legacy_orchestration(monkeypatch):
    def fail_model_first(*_args, **_kwargs):
        raise AssertionError("non-applicable composition is not a candidate")

    def fake_final(response, **_kwargs):
        response["final_answer_audit"] = {
            "passed": True,
            "mode": "fake",
            "issues": [],
        }
        return response

    monkeypatch.setattr(
        orchestrator,
        "_orchestrate_model_first_response",
        fail_model_first,
    )
    monkeypatch.setattr(orchestrator, "audit_final_answer", fake_final)
    monkeypatch.setattr(
        orchestrator,
        "polish_customer_reply",
        lambda response, **_kwargs: response,
    )
    monkeypatch.setattr(
        orchestrator,
        "_optional_llm_language_polish",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        orchestrator,
        "audit_customer_reply_semantic_fit",
        lambda *_args, **_kwargs: {
            "passed": True,
            "issues": [],
            "mode": "fake",
        },
    )

    result = orchestrator.orchestrate_final_response(
        {
            "suggested_reply": "legacy reply",
            "can_send": False,
            "requires_human_review": True,
            "model_first_answer_composer": {
                "status": "accepted",
                "composition_applicable": False,
                "used_for_final_reply": False,
            },
        },
        customer_message="request a service action",
    )

    assert result["suggested_reply"] == "legacy reply"
    assert result["final_response_pipeline"].get("mode") != (
        "model_first_candidate"
    )


def test_model_first_final_failure_skips_unified_audit_without_rewrite(
    monkeypatch,
):
    calls = []
    candidate = "宽度是80厘米。"

    def fake_final(response, **_kwargs):
        calls.append("final")
        response["final_answer_audit"] = {
            "passed": False,
            "issues": ["model_first_candidate_unknown_evidence"],
            "model_call_count": 0,
        }
        response["can_send"] = False
        response["requires_human_review"] = True
        response["sendable_reply"] = ""
        return response

    monkeypatch.setattr(orchestrator, "audit_final_answer", fake_final)
    monkeypatch.setattr(
        orchestrator,
        "audit_customer_reply_semantic_fit",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("unified audit must not run")
        ),
    )

    result = orchestrator.orchestrate_final_response(
        {
            "suggested_reply": candidate,
            "can_send": True,
            "sendable_reply": candidate,
            "requires_human_review": False,
            "model_first_answer_composer": {
                "status": "accepted",
                "used_for_final_reply": True,
                "can_change_can_send": False,
            },
        },
        customer_message="宽度多少",
    )

    assert calls == ["final"]
    assert result["suggested_reply"] == candidate
    assert result["can_send"] is False
    assert result["requires_human_review"] is True
    assert result["sendable_reply"] == ""
    assert result["final_semantic_fit_audit"]["mode"] == (
        "unified_textual_audit_not_run"
    )
    assert result["final_semantic_fit_audit"][
        "provider_diagnostics"
    ]["model_call_count"] == 0
    assert all(
        item.get("fallback_used") is not True
        for item in result["final_response_pipeline"]["stages"]
    )
