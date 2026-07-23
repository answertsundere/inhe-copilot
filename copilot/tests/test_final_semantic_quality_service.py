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

    def create_chat_completion(self, **kwargs):
        return self.client.chat.completions.create(**kwargs)


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
                "material_provenance": "structured_product_record",
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


def test_final_semantic_fit_blocks_installation_answered_with_product_facts(monkeypatch):
    from app import config

    monkeypatch.setattr(config, "COPILOT_FINAL_AUDIT_LLM_ENABLED", False)
    response = {
        "suggested_reply": "\u4eb2\uff0c\u8fd9\u6b3e\u5bbd80cm\uff0c\u6750\u8d28\u662fPP\uff0c\u5355\u5c42\u627f\u91cd\u7ea610kg\uff0c\u9002\u5408\u65e5\u5e38\u6536\u7eb3\u3002",
        "requires_human_review": False,
        "evidence_debug": {"query_fact_type": "installation"},
    }

    result = audit_customer_reply_semantic_fit(
        response,
        customer_message="\u6709\u7ec4\u88c5\u89c6\u9891\u5417\uff1f",
    )

    assert result["passed"] is False
    assert "installation_answered_with_unrelated_product_fact" in result["issues"]


def test_final_semantic_fit_does_not_accept_recommended_asset_without_reply_block(monkeypatch):
    from app import config

    monkeypatch.setattr(config, "COPILOT_FINAL_AUDIT_LLM_ENABLED", False)
    response = {
        "suggested_reply": "\u4eb2\uff0c\u4e0b\u9762\u56fe\u7247/\u89c6\u9891\u53ef\u53c2\u8003\uff0c\u6211\u518d\u53d1\u60a8\u5bf9\u5e94\u7684\u5b89\u88c5\u56fe\u6216\u89c6\u9891\u3002",
        "requires_human_review": False,
        "recommended_assets": [{
            "asset_type": "pack_guide_image",
            "asset_url": "https://asset.example/install.png",
            "auto_send_level": "auto",
        }],
        "reply_blocks": [],
        "evidence_debug": {
            "query_fact_type": "installation",
            "product_context_pack_summary": {
                "evidence_pack": {
                    "answerability": "missing_product_fact",
                    "query_fact_type": "installation",
                    "missing_fields": ["installation"],
                    "matched_facts": [],
                }
            },
        },
    }

    result = audit_customer_reply_semantic_fit(
        response,
        customer_message="\u9632\u5012\u5de5\u5177\u600e\u4e48\u7528",
    )

    assert result["passed"] is False
    assert "unsupported_media_claim" in result["issues"]


def test_final_semantic_fit_rejects_combined_media_claim_when_only_image_is_attached(monkeypatch):
    from app import config

    monkeypatch.setattr(config, "COPILOT_FINAL_AUDIT_LLM_ENABLED", False)
    response = {
        "suggested_reply": "亲，下面图片/视频可参考。",
        "requires_human_review": True,
        "reply_blocks": [{
            "type": "image",
            "url": "https://asset.example/guide.png",
            "asset_type": "pack_guide_image",
        }],
        "evidence_debug": {
            "query_fact_type": "installation",
            "answer_mode": "no_evidence_controlled_reply",
            "no_evidence_reply_policy": {"reply_strategy": "verify_installation_asset_before_send"},
        },
        "answer_trace": {
            "query_fact_type": "installation",
            "no_evidence_reply_policy": {"reply_strategy": "verify_installation_asset_before_send"},
        },
    }

    result = audit_customer_reply_semantic_fit(
        response,
        customer_message="有安装资料吗",
    )

    assert result["passed"] is False


def test_final_semantic_fit_allows_installation_handoff_about_materials(monkeypatch):
    from app import config

    monkeypatch.setattr(config, "COPILOT_FINAL_AUDIT_LLM_ENABLED", False)
    response = {
        "suggested_reply": (
            "\u4eb2\uff0c\u6211\u5148\u6309\u5f53\u524d\u8fd9\u6b3e\u5546\u54c1\u7684\u5b89\u88c5\u8d44\u6599\u6838\u5bf9\u3002"
            "\u5982\u679c\u6ca1\u6709\u660e\u786e\u5b89\u88c5\u89c6\u9891\uff0c\u4e0d\u4f1a\u76f4\u63a5\u627f\u8bfa\u89c6\u9891\uff1b"
            "\u60a8\u53ef\u4ee5\u628a\u5361\u4f4f\u7684\u4f4d\u7f6e\u62cd\u7167\u53d1\u6765\uff0c\u6211\u8fd9\u8fb9\u8f6c\u4eba\u5de5\u5e2e\u60a8\u786e\u8ba4\u3002"
        ),
        "requires_human_review": True,
        "evidence_debug": {"query_fact_type": "installation"},
    }

    result = audit_customer_reply_semantic_fit(
        response,
        customer_message="\u6709\u7ec4\u88c5\u89c6\u9891\u5417\uff1f",
    )

    assert result["passed"] is True


def test_final_semantic_fit_accepts_controlled_no_evidence_installation_handoff(monkeypatch):
    from app import config

    monkeypatch.setattr(config, "COPILOT_FINAL_AUDIT_LLM_ENABLED", False)
    response = {
        "suggested_reply": (
            "\u4eb2\uff0c\u5b89\u88c5\u8d44\u6599\u6211\u5e2e\u60a8\u6309\u8fd9\u6b3e\u6838\u5bf9\u4e00\u4e0b\u3002"
            "\u60a8\u5982\u679c\u5361\u5728\u54ea\u4e00\u6b65\uff0c\u4e5f\u53ef\u4ee5\u628a\u5f53\u524d\u4f4d\u7f6e\u62cd\u7ed9\u6211\uff0c\u6211\u4e00\u8d77\u770b\uff1b"
            "\u6211\u786e\u8ba4\u540e\u7ed9\u60a8\u51c6\u786e\u56de\u590d\u3002"
        ),
        "requires_human_review": True,
        "answer_trace": {
            "query_fact_type": "installation",
            "no_evidence_reply_policy": {
                "reply_strategy": "verify_installation_asset_before_send",
                "requires_human_review": True,
            },
        },
        "evidence_debug": {
            "answer_mode": "no_evidence_controlled_reply",
            "query_fact_type": "installation",
        },
    }

    result = audit_customer_reply_semantic_fit(
        response,
        customer_message="\u9632\u5012\u5de5\u5177\u600e\u4e48\u7528\uff1f",
    )

    assert result["passed"] is True
    assert result["reason"] == "Controlled no-evidence handoff reply accepted deterministically."


def test_material_semantic_fallback_does_not_present_keyword_hits_as_product_facts():
    from app.services.final_semantic_quality_service import apply_semantic_fit_result

    response = {
        "suggested_reply": "亲，这款防潮还可以。",
        "display_product_name": "英禾防夹滑门收纳架整理客厅零食桌面儿童玩具卧室可拼搭储物抽屉",
        "requires_human_review": True,
        "evidence_debug": {
            "query_fact_type": "material",
            "filtered_evidence_summary": [
                {
                    "evidence_fact_type": "material",
                    "chunk_preview": "这款产品主要采用冷轧钢管/环保PP/无纺布等材质，金属部分经过防锈喷涂处理，具有一定的防潮能力。",
                }
            ],
        },
    }

    updated = apply_semantic_fit_result(
        response,
        {
            "checked": True,
            "passed": False,
            "issues": ["material_safety_incomplete"],
            "reason": "material safety was not fully answered",
        },
    )

    reply = updated["suggested_reply"]
    assert updated["requires_human_review"] is True
    assert "材质、安全和防潮说明" in reply
    assert "里面有材质和防潮相关说明" not in reply
    assert "转人工" not in reply
    assert "口径" not in reply
    assert "复核" not in reply
    assert "英禾防夹滑门收纳架" not in reply


def test_final_semantic_fit_blocks_structure_function_answered_with_scene(monkeypatch):
    from app import config

    monkeypatch.setattr(config, "COPILOT_FINAL_AUDIT_LLM_ENABLED", False)
    response = {
        "suggested_reply": "亲，这款可以放卧室、客厅，建议旁边留出走动空间。",
        "requires_human_review": False,
        "evidence_debug": {"query_fact_type": "structure_function"},
    }

    result = audit_customer_reply_semantic_fit(
        response,
        customer_message="侧板可以翻下来吗？",
    )

    assert result["passed"] is False
    assert "structure_function_answered_with_scene_or_space" in result["issues"]


def test_final_semantic_fit_blocks_structure_compatibility_answered_with_space(monkeypatch):
    from app import config

    monkeypatch.setattr(config, "COPILOT_FINAL_AUDIT_LLM_ENABLED", False)
    response = {
        "suggested_reply": "亲，这款能不能放下主要看您家预留位置的宽度、进深和高度，旁边也要留走动空间。",
        "requires_human_review": False,
        "evidence_debug": {"query_fact_type": "structure_function"},
    }

    result = audit_customer_reply_semantic_fit(
        response,
        customer_message="三面围栏，想补第四面，这款能用吗",
    )

    assert result["passed"] is False
    assert "structure_function_answered_with_scene_or_space" in result["issues"]


def test_final_semantic_fit_allows_damaged_aftersales_handoff(monkeypatch):
    from app import config

    monkeypatch.setattr(config, "COPILOT_FINAL_AUDIT_LLM_ENABLED", False)
    response = {
        "suggested_reply": "亲，收到。麻烦您拍一下断裂/破损位置、配件整体和外包装，我这边核实后给您处理补发、换件或售后方案。",
        "requires_human_review": True,
        "evidence_debug": {"query_fact_type": "aftersales_policy"},
    }

    result = audit_customer_reply_semantic_fit(
        response,
        customer_message="这个断了",
    )

    assert result["passed"] is True


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


def test_semantic_payload_contains_only_admitted_direct_facts():
    from app.services.final_semantic_quality_service import _semantic_payload

    response = {
        "suggested_reply": "主体材质为PP。",
        "selected_evidence": [{
            "evidence_uid": "direct",
            "source_type": "product_facts",
            "evidence_role": "product_fact_direct",
            "fact_type": "material",
            "attribute_key": "material",
            "content": "主体材质为PP。",
            "sku_code": "SKU-A",
            "fact_review_status": "verified",
                "gate_status": "allowed",
                "direct_answer_allowed": True,
                "material_provenance": "structured_product_record",
            }],
        "context_used": {
            "product_context_pack": {
                "matched_facts": [{
                    "evidence_uid": "reference",
                    "source_type": "faq",
                    "evidence_role": "faq_direct",
                    "fact_type": "material",
                    "preview": "待核实材质",
                    "reference_only": True,
                    "direct_answer_allowed": False,
                }],
                "generic_rules": [{
                    "evidence_uid": "generic",
                    "source_type": "generic_rule",
                    "evidence_role": "service_action",
                    "content": "转人工核对。",
                }],
            }
        },
        "answer_memory_guidance": {"answer_text": "历史客服说安全。"},
        "grounded_reasoning_draft": {"used_facts": [{"evidence_uid": "shadow"}]},
        "evidence_debug": {"query_fact_type": "material"},
    }

    payload = _semantic_payload(response, "什么材质？", {"sku_code": "SKU-A"})

    assert [item["evidence_uid"] for item in payload["admitted_direct_facts"]] == ["direct"]
    serialized = str(payload)
    assert "reference" not in serialized
    assert "generic" not in serialized
    assert "历史客服说安全" not in serialized
    assert "shadow" not in serialized


def test_semantic_payload_preserves_model_first_review_and_reasoning_contract():
    from app.services.final_semantic_quality_service import _semantic_payload

    response = {
        "suggested_reply": "这款是ABS材质，普通轻微磕碰通常不像玻璃那样碎裂，但不能保证耐摔。",
        "requires_human_review": True,
        "minimal_decision_context": {
            "product_identity": {"resolved": True},
        },
        "model_first_answer_composer": {
            "status": "accepted",
            "allowed_low_risk_reasoning": [
                "对普通塑料说明轻微磕碰通常不像玻璃一样碎裂，但不得保证耐摔",
            ],
        },
        "selected_evidence": [{
            "evidence_uid": "material-direct",
            "source_type": "product_facts",
            "evidence_role": "product_fact_direct",
            "fact_type": "material",
            "content": "这款是ABS材质",
            "sku_code": "SKU-A",
            "fact_review_status": "verified",
            "gate_status": "allowed",
            "direct_answer_allowed": True,
        }],
        "evidence_debug": {"query_fact_type": "material"},
    }

    payload = _semantic_payload(
        response,
        "这款是什么材质，耐摔吗？",
        {"sku_code": "SKU-A"},
    )

    contract = payload["model_first_candidate_contract"]
    assert contract["enabled"] is True
    assert contract["review_only"] is True
    assert contract["product_identity_resolved"] is True
    assert contract["full_product_title_required"] is False
    assert contract["allowed_low_risk_reasoning"]
