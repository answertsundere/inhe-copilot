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


def test_final_semantic_fit_blocks_gross_weight_answered_with_capacity(monkeypatch):
    from app import config

    monkeypatch.setattr(config, "COPILOT_FINAL_AUDIT_LLM_ENABLED", False)
    response = {
        "suggested_reply": "\u4eb2\uff0c\u8fd9\u6b3e\u5355\u5c42\u627f\u91cd\u7ea620kg\uff0c\u653e\u4e66\u548c\u73a9\u5177\u90fd\u591f\u7528\u3002",
        "requires_human_review": False,
        "evidence_debug": {"query_fact_type": "gross_weight"},
    }

    result = audit_customer_reply_semantic_fit(
        response,
        customer_message="\u8fd9\u4e2a\u591a\u91cd\uff1f",
    )

    assert result["passed"] is False
    assert "gross_weight_answered_with_load_capacity" in result["issues"]


def test_final_semantic_fit_blocks_gross_weight_answered_with_dimensions(monkeypatch):
    from app import config

    monkeypatch.setattr(config, "COPILOT_FINAL_AUDIT_LLM_ENABLED", False)
    response = {
        "suggested_reply": "\u4eb2\uff0c\u8fd9\u6b3e\u5bbd80cm\u3001\u6df140cm\u3001\u9ad890cm\uff0c\u60a8\u53ef\u4ee5\u5148\u91cf\u4e00\u4e0b\u9884\u7559\u4f4d\u7f6e\u3002",
        "requires_human_review": False,
        "evidence_debug": {"query_fact_type": "gross_weight"},
    }

    result = audit_customer_reply_semantic_fit(
        response,
        customer_message="\u5546\u54c1\u6bdb\u91cd\u591a\u5c11\uff1f",
    )

    assert result["passed"] is False
    assert "gross_weight_answered_with_dimensions_or_capacity" in result["issues"]


def test_final_semantic_fit_blocks_accessory_availability_answered_with_installation(monkeypatch):
    from app import config

    monkeypatch.setattr(config, "COPILOT_FINAL_AUDIT_LLM_ENABLED", False)
    response = {
        "suggested_reply": "\u4eb2\uff0c\u8fd9\u4e2a\u914d\u4ef6\u6309\u8bf4\u660e\u4e66\u7684\u5b89\u88c5\u6b65\u9aa4\u5148\u5361\u4e0a\u4fa7\u677f\u5c31\u53ef\u4ee5\u3002",
        "requires_human_review": False,
        "evidence_debug": {"query_fact_type": "accessory_availability"},
    }

    result = audit_customer_reply_semantic_fit(
        response,
        customer_message="\u914d\u4ef6\u80fd\u5355\u72ec\u4e70\u5417\uff1f",
    )

    assert result["passed"] is False
    assert "accessory_availability_answered_with_installation" in result["issues"]


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
