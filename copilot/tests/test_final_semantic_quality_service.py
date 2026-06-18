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
    assert result["mode"] == "deterministic"
    assert any(issue.startswith("off_topic:space_fit") for issue in result["issues"])


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


def test_final_semantic_fit_does_not_discard_grounded_reply_for_review_flag_only(monkeypatch):
    from app import config
    from app.llm import client as llm_client

    monkeypatch.setattr(config, "COPILOT_FINAL_AUDIT_LLM_ENABLED", True)
    monkeypatch.setattr(
        llm_client,
        "get_llm_client",
        lambda: _FakeClient(
            '{"passed": false, "issues": ["requires_human_review is true despite direct evidence"], "reason": "The final reply turns to human review while direct evidence is available."}'
        ),
    )
    response = {
        "suggested_reply": "\u4eb2\uff0c\u8fd9\u6b3e\u4e3b\u8981\u91c7\u7528\u51b7\u8f67\u94a2\u7ba1\u3001\u73af\u4fddPP\u548c\u65e0\u7eba\u5e03\u7b49\u6750\u8d28\uff0c\u91d1\u5c5e\u90e8\u5206\u7ecf\u8fc7\u9632\u9508\u55b7\u6d82\u5904\u7406\uff0c\u5177\u5907\u4e00\u5b9a\u9632\u6f6e\u80fd\u529b\u3002",
        "requires_human_review": True,
        "evidence_debug": {
            "semantic_query": {"primary_fact_type": "material"},
            "product_context_pack_summary": {
                "evidence_pack": {
                    "answerability": "direct_answer",
                    "query_fact_type": "material",
                    "matched_facts": [{
                        "fact_type": "material",
                        "preview": "\u51b7\u8f67\u94a2\u7ba1\u3001\u73af\u4fddPP\u548c\u65e0\u7eba\u5e03",
                        "direct_answer_allowed": True,
                    }],
                }
            },
        },
    }

    result = audit_customer_reply_semantic_fit(
        response,
        customer_message="\u8fd9\u4e2a\u6750\u8d28\u5b89\u5168\u5417\uff1f\u4f1a\u4e0d\u4f1a\u5bb9\u6613\u53d7\u6f6e\uff1f",
    )

    assert result["passed"] is True
    assert result["mode"] == "deterministic_review_flag_override"


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


def _semantic_response(fact_type: str, reply: str, *, selected_assets=None, requires_human_review=False):
    return {
        "suggested_reply": reply,
        "requires_human_review": requires_human_review,
        "selected_assets": selected_assets or [],
        "evidence_debug": {
            "semantic_query": {"primary_fact_type": fact_type},
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


def test_deterministic_gate_rejects_space_fit_answered_as_load_capacity(monkeypatch):
    from app import config

    monkeypatch.setattr(config, "COPILOT_FINAL_AUDIT_LLM_ENABLED", False)
    result = audit_customer_reply_semantic_fit(
        _semantic_response("space_fit", "亲亲，这款每层承重约15-30kg，放书和玩具都够用。"),
        customer_message="卧室空间比较小，这个放得下吗？",
    )

    assert result["passed"] is False
    assert result["off_topic"] is True
    assert any(issue.startswith("off_topic:space_fit") for issue in result["issues"])


def test_deterministic_gate_rejects_placement_scene_answered_as_material(monkeypatch):
    from app import config

    monkeypatch.setattr(config, "COPILOT_FINAL_AUDIT_LLM_ENABLED", False)
    result = audit_customer_reply_semantic_fit(
        _semantic_response("placement_scene", "亲亲，这款材质是钢管和PP，表面防潮防锈，卫生间潮湿可能生锈。"),
        customer_message="这个在卧室可以用吗？",
    )

    assert result["passed"] is False
    assert result["off_topic"] is True
    assert any(issue.startswith("off_topic:placement_scene") for issue in result["issues"])


def test_deterministic_gate_allows_placement_scene_with_room_and_ventilation(monkeypatch):
    from app import config

    monkeypatch.setattr(config, "COPILOT_FINAL_AUDIT_LLM_ENABLED", False)
    result = audit_customer_reply_semantic_fit(
        _semantic_response("placement_scene", "亲亲，这款放在卧室、客厅、书房这类日常收纳区域可以参考，建议放在干燥通风、平整的位置。"),
        customer_message="这个在卧室可以用吗？",
    )

    assert result["passed"] is True


def test_deterministic_gate_allows_dimensions_answer(monkeypatch):
    from app import config

    monkeypatch.setattr(config, "COPILOT_FINAL_AUDIT_LLM_ENABLED", False)
    result = audit_customer_reply_semantic_fit(
        _semantic_response("dimensions", "亲亲，这款可以参考尺寸图，重点看长宽高、宽度、进深和高度是否适合家里预留位置。"),
        customer_message="可以直接告诉我产品大小吗？",
    )

    assert result["passed"] is True


def test_deterministic_gate_allows_load_capacity_answer(monkeypatch):
    from app import config

    monkeypatch.setattr(config, "COPILOT_FINAL_AUDIT_LLM_ENABLED", False)
    result = audit_customer_reply_semantic_fit(
        _semantic_response("load_capacity", "亲亲，这款单层均匀承重约15-30kg，放书、玩具和日用品可以参考这个承重范围。"),
        customer_message="放书会不会压塌？",
    )

    assert result["passed"] is True


def test_deterministic_gate_rejects_visual_asset_without_asset_or_visual_answer(monkeypatch):
    from app import config

    monkeypatch.setattr(config, "COPILOT_FINAL_AUDIT_LLM_ENABLED", False)
    result = audit_customer_reply_semantic_fit(
        _semantic_response("visual_asset", "亲亲，这款主要是钢管和PP材质，日常放书比较结实。"),
        customer_message="有没有图片看一下？",
    )

    assert result["passed"] is False
    assert result["missing_answer"] is True or result["off_topic"] is True
    assert any("visual_asset" in issue for issue in result["issues"])


def test_deterministic_gate_rejects_age_range_answered_as_load_capacity(monkeypatch):
    from app import config

    monkeypatch.setattr(config, "COPILOT_FINAL_AUDIT_LLM_ENABLED", False)
    result = audit_customer_reply_semantic_fit(
        _semantic_response("age_range", "\u4eb2\uff0c\u8fd9\u6b3e\u5355\u5c42\u627f\u91cd\u7ea615-30kg\uff0c\u6750\u8d28\u7ed3\u5b9e\u8010\u7528\u3002"),
        customer_message="\u8fd9\u4e2a\u9002\u5408\u4e00\u5c81\u5b9d\u5b9d\u5417\uff1f",
    )

    assert result["passed"] is False
    assert result["off_topic"] is True
    assert any(issue.startswith("off_topic:age_range") for issue in result["issues"])
