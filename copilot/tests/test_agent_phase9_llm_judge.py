from app.services.final_semantic_quality_service import audit_customer_reply_semantic_fit


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
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return _FakeResponse(self.content)


class _FakeChat:
    def __init__(self, completions):
        self.completions = completions


class _FakeClient:
    api_key = "test-key"
    model = "test-model"

    def __init__(self, content):
        self.completions = _FakeCompletions(content)
        self.client = type("Client", (), {"chat": _FakeChat(self.completions)})()


def _semantic_response(fact_type: str, reply: str, *, selected_assets=None):
    return {
        "suggested_reply": reply,
        "requires_human_review": False,
        "query_fact_type": fact_type,
        "required_fact_types": [fact_type],
        "answer_blocks": [{"type": "text", "fact_type": fact_type, "content": reply}],
        "answer_trace": {
            "query_fact_type": fact_type,
            "required_fact_types": [fact_type],
            "evidence_answered_fact_types": [fact_type],
            "mode": "direct_answer",
        },
        "selected_assets": selected_assets or [],
        "evidence_debug": {
            "query_understanding": {
                "intent": "product_question",
                "query_fact_type": fact_type,
                "required_fact_types": [fact_type],
            },
            "semantic_query": {"primary_fact_type": fact_type},
            "selected_evidence": [{
                "source_type": "product_facts",
                "fact_type": fact_type,
                "entry_id": f"fact-{fact_type}",
                "preview": "test evidence",
            }],
            "product_context_pack_summary": {
                "evidence_pack": {
                    "answerability": "direct_answer",
                    "query_fact_type": fact_type,
                    "matched_facts": [{
                        "fact_type": fact_type,
                        "preview": "test evidence",
                        "direct_answer_allowed": True,
                    }],
                }
            },
        },
    }


def test_phase9_blocks_dimensions_answered_as_load_capacity(monkeypatch):
    from app import config

    monkeypatch.setattr(config, "COPILOT_FINAL_AUDIT_LLM_ENABLED", False)

    result = audit_customer_reply_semantic_fit(
        _semantic_response("dimensions", "亲亲，这款承重不错，放书不容易压塌。"),
        customer_message="这个尺寸多大？",
    )

    assert result["passed"] is False
    assert result["semantic_mismatch"] is True
    assert any(issue.startswith("off_topic:dimensions") for issue in result["issues"])


def test_phase9_blocks_certification_report_answered_as_material(monkeypatch):
    from app import config

    monkeypatch.setattr(config, "COPILOT_FINAL_AUDIT_LLM_ENABLED", False)

    result = audit_customer_reply_semantic_fit(
        _semantic_response("certification_report", "亲亲，这款材质是环保PP和钢管，日常使用可以参考。"),
        customer_message="有没有检测报告？",
    )

    assert result["passed"] is False
    assert result["semantic_mismatch"] is True
    assert any(issue.startswith("off_topic:certification_report") for issue in result["issues"])


def test_phase9_blocks_install_video_claim_without_asset(monkeypatch):
    from app import config

    monkeypatch.setattr(config, "COPILOT_FINAL_AUDIT_LLM_ENABLED", False)

    result = audit_customer_reply_semantic_fit(
        _semantic_response("installation", "亲亲，我把安装视频发您，您按视频步骤安装就可以。"),
        customer_message="怎么安装，有视频吗？",
    )

    assert result["passed"] is False
    assert result["unsupported_claim"] is True
    assert "unsupported_media_reference_without_asset" in result["issues"]


def test_phase9_llm_judge_passes_normal_reply_and_ignores_reply_field(monkeypatch):
    from app import config
    from app.llm import client as llm_client

    fake = _FakeClient(
        '{"passed": true, "issues": [], "reason": "reply answers dimensions", '
        '"semantic_mismatch": false, "risk_level": "low", "requires_human_review": false, '
        '"reply": "this must be ignored"}'
    )
    monkeypatch.setattr(config, "COPILOT_FINAL_AUDIT_LLM_ENABLED", True)
    monkeypatch.setattr(llm_client, "get_llm_client", lambda: fake)

    result = audit_customer_reply_semantic_fit(
        _semantic_response("dimensions", "亲亲，这款尺寸可以参考长宽高，建议对照家里预留位置。"),
        customer_message="这个尺寸多大？",
    )

    assert result["passed"] is True
    assert result["mode"] == "llm_semantic_judge"
    assert result["risk_level"] == "low"
    assert "reply" not in result
    assert result["rewrite_instruction"] == ""

    payload = fake.completions.calls[0]["messages"][1]["content"]
    assert "query_understanding" in payload
    assert "required_fact_types" in payload
    assert "selected_evidence_summary" in payload
    assert "answer_blocks" in payload
    assert "answer_trace_summary" in payload


def test_phase9_llm_judge_blocks_mismatch_without_rewrite(monkeypatch):
    from app import config
    from app.llm import client as llm_client

    monkeypatch.setattr(config, "COPILOT_FINAL_AUDIT_LLM_ENABLED", True)
    monkeypatch.setattr(
        llm_client,
        "get_llm_client",
        lambda: _FakeClient(
            '{"passed": false, "issues": ["semantic_mismatch"], "reason": "does not answer", '
            '"semantic_mismatch": true, "risk_level": "medium", "requires_human_review": true, '
            '"rewrite_instruction": "do not use this"}'
        ),
    )

    result = audit_customer_reply_semantic_fit(
        _semantic_response("detachable", "亲亲，这款可以先看页面说明。"),
        customer_message="这个能拆卸吗？",
    )

    assert result["passed"] is False
    assert result["mode"] == "llm_semantic_judge"
    assert result["semantic_mismatch"] is True
    assert result["requires_human_review"] is True
    assert result["rewrite_instruction"] == ""


def test_phase9_llm_invalid_json_falls_back_to_deterministic_gate(monkeypatch):
    from app import config
    from app.llm import client as llm_client

    monkeypatch.setattr(config, "COPILOT_FINAL_AUDIT_LLM_ENABLED", True)
    monkeypatch.setattr(llm_client, "get_llm_client", lambda: _FakeClient("not-json"))

    result = audit_customer_reply_semantic_fit(
        _semantic_response("dimensions", "亲亲，这款尺寸可以参考长宽高，建议对照家里预留位置。"),
        customer_message="这个尺寸多大？",
    )

    assert result["passed"] is True
    assert result["mode"] == "deterministic"
    assert result["llm_judge_fallback"] is True
