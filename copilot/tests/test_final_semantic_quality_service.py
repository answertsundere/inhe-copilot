from app.services.final_semantic_quality_service import (
    apply_semantic_fit_result,
    audit_customer_reply_semantic_fit,
)


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


def test_final_semantic_fit_uses_llm_judge_to_block_wrong_answer(monkeypatch):
    from app import config
    from app.llm import client as llm_client

    monkeypatch.setattr(config, "COPILOT_FINAL_AUDIT_LLM_ENABLED", True)
    monkeypatch.setattr(
        llm_client,
        "get_llm_client",
        lambda: _FakeClient(
            '{"passed": false, "issues": ["answered_space_fit_as_load_capacity"], "reason": "Customer asks fit/space but reply answers load capacity."}'
        ),
    )
    response = {
        "suggested_reply": "亲～这款单层均匀承重约15-30kg，放书和玩具都够用。",
        "requires_human_review": False,
        "evidence_debug": {
            "semantic_query": {"primary_fact_type": "space_fit"},
            "product_context_pack_summary": {
                "evidence_pack": {
                    "answerability": "direct_answer",
                    "query_fact_type": "space_fit",
                    "matched_facts": [
                        {
                            "fact_type": "space_fit",
                            "preview": "尺寸图可参考预留宽度、进深和高度。",
                            "direct_answer_allowed": True,
                        }
                    ],
                }
            },
        },
    }

    result = audit_customer_reply_semantic_fit(
        response,
        customer_message="卧室空间比较小，这个放得下吗？",
    )

    assert result["passed"] is False
    assert result["mode"] == "llm_semantic_fit"
    assert "answered_space_fit_as_load_capacity" in result["issues"]


def test_final_semantic_fit_blocks_missing_evidence_without_human_review(monkeypatch):
    from app import config

    monkeypatch.setattr(config, "COPILOT_FINAL_AUDIT_LLM_ENABLED", False)
    response = {
        "suggested_reply": "亲～这款可以拆卸，日常移动很方便。",
        "requires_human_review": False,
        "evidence_debug": {
            "semantic_query": {"primary_fact_type": "detachable"},
            "product_context_pack_summary": {
                "evidence_pack": {
                    "answerability": "missing_product_fact",
                    "query_fact_type": "detachable",
                    "missing_fields": ["detachable"],
                    "matched_facts": [],
                }
            },
        },
    }

    result = audit_customer_reply_semantic_fit(
        response,
        customer_message="这个可以拆卸吗？",
    )

    assert result["passed"] is False
    assert "missing_evidence_without_human_review" in result["issues"]


def test_apply_semantic_fit_result_replaces_bad_reply():
    response = {
        "suggested_reply": "bad answer",
        "display_product_name": "英禾防夹滑门收纳架整理客厅零食桌面儿童玩具卧室可拼搭储物抽屉",
        "requires_human_review": False,
    }
    result = {
        "checked": True,
        "passed": False,
        "issues": ["semantic_mismatch"],
        "reason": "bad",
        "mode": "llm_semantic_fit",
    }

    updated = apply_semantic_fit_result(response, result)

    assert updated["requires_human_review"] is True
    assert updated["generation_mode"] == "final_semantic_fit_fallback"
    assert "bad answer" != updated["suggested_reply"]
    assert updated["final_semantic_fit_audit"]["fallback_used"] is True


def test_final_semantic_fit_allows_direct_evidence_answer(monkeypatch):
    from app import config

    monkeypatch.setattr(config, "COPILOT_FINAL_AUDIT_LLM_ENABLED", False)
    response = {
        "suggested_reply": "亲～这款尺寸可以参考下面的尺寸图，建议对照家里预留位置的宽度、进深和高度。",
        "requires_human_review": False,
        "evidence_debug": {
            "semantic_query": {"primary_fact_type": "space_fit"},
            "product_context_pack_summary": {
                "evidence_pack": {
                    "answerability": "direct_answer",
                    "query_fact_type": "space_fit",
                    "matched_facts": [
                        {
                            "fact_type": "space_fit",
                            "preview": "尺寸图可参考预留宽度、进深和高度。",
                            "direct_answer_allowed": True,
                        }
                    ],
                }
            },
        },
    }

    result = audit_customer_reply_semantic_fit(
        response,
        customer_message="卧室空间比较小，这个放得下吗？",
    )

    assert result["passed"] is True


def test_quality_gate_rejects_off_topic_answer(monkeypatch):
    from app import config

    monkeypatch.setattr(config, "COPILOT_FINAL_AUDIT_LLM_ENABLED", False)
    response = {
        "suggested_reply": "亲亲，这款每层承重约20kg，正常放书比较结实。",
        "requires_human_review": False,
        "evidence_debug": {
            "semantic_query": {"primary_fact_type": "dimensions"},
            "product_context_pack_summary": {
                "evidence_pack": {
                    "answerability": "direct_answer",
                    "query_fact_type": "dimensions",
                    "matched_facts": [{
                        "fact_type": "dimensions",
                        "preview": "尺寸为80*40*90cm。",
                        "direct_answer_allowed": True,
                    }],
                }
            },
        },
    }

    result = audit_customer_reply_semantic_fit(
        response,
        customer_message="可以直接告诉我你们产品的大小吗",
    )

    assert result["passed"] is False
    assert result["off_topic"] is True
    assert "off_topic:dimensions_answered_as_load_capacity" in result["issues"]


def test_quality_gate_rejects_internal_language(monkeypatch):
    from app import config

    monkeypatch.setattr(config, "COPILOT_FINAL_AUDIT_LLM_ENABLED", False)
    response = {
        "suggested_reply": "亲亲，知识库里没有这款商品的尺寸资料，我不能凭感觉判断。",
        "requires_human_review": True,
        "evidence_debug": {
            "semantic_query": {"primary_fact_type": "dimensions"},
            "product_context_pack_summary": {
                "evidence_pack": {
                    "answerability": "missing_product_fact",
                    "query_fact_type": "dimensions",
                    "matched_facts": [],
                }
            },
        },
    }

    result = audit_customer_reply_semantic_fit(
        response,
        customer_message="这个多大",
    )

    assert result["passed"] is False
    assert result["internal_language_leak"] is True
    assert any(issue.startswith("internal_language_leak") for issue in result["issues"])


def test_quality_gate_rejects_internal_product_name_when_display_name_exists(monkeypatch):
    from app import config

    monkeypatch.setattr(config, "COPILOT_FINAL_AUDIT_LLM_ENABLED", False)
    response = {
        "suggested_reply": "亲亲，九号防夹滑门收纳柜可以参考尺寸图。",
        "product_name": "九号防夹滑门收纳柜",
        "display_product_name": "英禾防夹滑门收纳架整理客厅零食桌面儿童玩具卧室可拼搭储物抽屉",
        "requires_human_review": False,
        "evidence_debug": {
            "semantic_query": {"primary_fact_type": "dimensions"},
            "product_context_pack_summary": {
                "evidence_pack": {
                    "answerability": "direct_answer",
                    "query_fact_type": "dimensions",
                    "matched_facts": [{
                        "fact_type": "dimensions",
                        "preview": "尺寸图可参考宽度、进深和高度。",
                        "direct_answer_allowed": True,
                    }],
                }
            },
        },
    }

    result = audit_customer_reply_semantic_fit(
        response,
        customer_message="有没有尺寸图",
    )

    assert result["passed"] is False
    assert result["product_name_leak"] is True
    assert any(issue.startswith("product_name_leak") for issue in result["issues"])
