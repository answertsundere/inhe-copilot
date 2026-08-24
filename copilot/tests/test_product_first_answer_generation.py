from __future__ import annotations

import pytest


def _run_post_processor(kwargs, response):
    post_processor = kwargs.get("response_post_processor")
    return post_processor(response) if callable(post_processor) else response


@pytest.fixture()
def client():
    from app.main import create_app

    return create_app().test_client()


def _structured_pack(fact_type: str, preview: str) -> dict:
    fact = {
        "evidence_id": f"kbproduct:test:{fact_type}",
        "source_table": "kb_product",
        "protocol_source_type": "product_spec",
        "fact_type": fact_type,
        "direct_answer_allowed": True,
        "can_direct_answer": True,
        "preview": preview,
    }
    return {
        "resolved_product_identity": {"product_name": "Test product", "sku": "TEST-SKU"},
        "identity_confidence": 0.95,
        "identity_sources": ["slots.sku_code"],
        "requested_fact_type": fact_type,
        "query_fact_type": fact_type,
        "answerability": "direct_answer",
        "product_structured_facts": [fact],
        "product_media_assets": [],
        "product_scoped_chunks": [],
        "generic_fallback_rules": [],
        "missing_required_evidence": [],
        "evidence_pack_trace": {
            "product_identity_locked": True,
            "generic_rules_role": "fallback_only",
        },
    }


def _state_with_pack(fact_type: str, preview: str, *, generic_rules: list[dict] | None = None) -> dict:
    pack = _structured_pack(fact_type, preview)
    return {
        "intent": "product_question",
        "customer_message": "question",
        "normalized_message": "question",
        "query_fact_type": fact_type,
        "matched_product_name": "Test product",
        "product_first_evidence_pack": pack,
        "product_context_pack": {
            "product_first_evidence_pack": pack,
            "evidence_pack": pack,
            "generic_rules": generic_rules or [],
        },
        "trace_steps": [],
    }


def test_generate_reply_prefers_product_first_material_over_generic_rule():
    from app.agent.nodes.generate_reply import generate_reply

    result = generate_reply(_state_with_pack(
        "material",
        "This product material is steel and PP.",
        generic_rules=[{
            "rule_key": "generic_material",
            "title": "Generic material wording",
            "fact_type": "material",
            "score": 99,
            "reply_template": "Generic material fallback.",
            "content": "Generic material fallback.",
        }],
    ))

    assert "steel and PP" in result["suggested_reply"]
    assert "Generic material fallback" not in result["suggested_reply"]
    assert result.get("generic_service_rule_used") is None
    trace = result["trace_steps"][-1]
    assert trace["selected_evidence_role"] == "product_structured_facts"
    assert trace["generic_fallback_used"] is False
    assert trace["final_answer_source"] == "product_structured_facts"


def test_generate_reply_drops_placeholder_material_when_concrete_fact_exists():
    from app.agent.nodes.generate_reply import generate_reply

    pack = _structured_pack(
        "material",
        "材质需要人工核实：未在现有结构化资料中明确材质，以商品详情页或人工复核结果为准。",
    )
    pack["product_structured_facts"].append({
        "evidence_id": "kbproduct:test:material:concrete",
        "source_table": "kb_product",
        "protocol_source_type": "product_spec",
        "fact_type": "material",
        "direct_answer_allowed": True,
        "can_direct_answer": True,
        "preview": "这款商品的材质为钢架和PP件。",
    })

    state = _state_with_pack("material", "")
    state["product_first_evidence_pack"] = pack
    state["product_context_pack"]["product_first_evidence_pack"] = pack
    state["product_context_pack"]["evidence_pack"] = pack

    result = generate_reply(state)

    assert "钢架和PP件" in result["suggested_reply"]
    assert "未在现有结构化资料中明确" not in result["suggested_reply"]
    assert "需要人工核实" not in result["suggested_reply"]


def test_generate_reply_does_not_direct_answer_placeholder_material_only():
    from app.agent.nodes.generate_reply import generate_reply

    result = generate_reply(_state_with_pack(
        "material",
        "材质需要人工核实：未在现有结构化资料中明确材质，以商品详情页或人工复核结果为准。",
    ))

    assert "未在现有结构化资料中明确" not in result["suggested_reply"]
    trace = result["trace_steps"][-1]
    assert trace["final_answer_source"] != "product_structured_facts"


def test_generate_reply_uses_gross_weight_without_dimension_or_load_capacity():
    from app.agent.nodes.generate_reply import generate_reply

    result = generate_reply(_state_with_pack(
        "gross_weight",
        "This product gross weight is 7.5kg.",
        generic_rules=[{
            "rule_key": "generic_size",
            "title": "Generic size wording",
            "fact_type": "dimensions",
            "score": 99,
            "reply_template": "Size is 80*40*90cm and load capacity is 20kg.",
            "content": "Size is 80*40*90cm and load capacity is 20kg.",
        }],
    ))

    assert "7.5kg" in result["suggested_reply"]
    assert "80*40*90" not in result["suggested_reply"]
    assert "20kg" not in result["suggested_reply"]


def test_real_product_facts_uses_product_pack_when_formal_convergence_is_disabled(monkeypatch):
    from app.agent.nodes.generate_reply import _real_product_facts

    monkeypatch.setenv("COPILOT_FORMAL_EVIDENCE_CONVERGENCE_ENABLED", "false")
    state = _state_with_pack("gross_weight", "This product gross weight is 7.5kg.")
    state["selected_evidence"] = []

    facts = _real_product_facts(state)

    assert [item["chunk_text"] for item in facts] == [
        "This product gross weight is 7.5kg."
    ]


def test_real_product_facts_uses_empty_canonical_selection_when_formal_convergence_is_enabled(monkeypatch):
    from app.agent.nodes.generate_reply import _real_product_facts

    monkeypatch.setenv("COPILOT_FORMAL_EVIDENCE_CONVERGENCE_ENABLED", "true")
    state = _state_with_pack("gross_weight", "This product gross weight is 7.5kg.")
    state["selected_evidence"] = []

    assert _real_product_facts(state) == []


def test_generate_reply_uses_accessory_availability_not_installation():
    from app.agent.nodes.generate_reply import generate_reply

    result = generate_reply(_state_with_pack(
        "accessory_availability",
        "Spare parts need customer service confirmation before separate purchase.",
        generic_rules=[{
            "rule_key": "generic_install",
            "title": "Generic installation wording",
            "fact_type": "installation",
            "score": 99,
            "reply_template": "Install by snapping panels together.",
            "content": "Install by snapping panels together.",
        }],
    ))

    assert "separate purchase" in result["suggested_reply"]
    assert "snapping panels" not in result["suggested_reply"]


def test_generate_reply_does_not_use_media_generic_rule_without_sendable_asset():
    from app.agent.nodes.generate_reply import generate_reply

    pack = {
        "resolved_product_identity": {"product_name": "Test product", "sku": "TEST-SKU"},
        "identity_confidence": 0.95,
        "requested_fact_type": "installation",
        "query_fact_type": "installation",
        "answerability": "generic_rule_fallback",
        "product_structured_facts": [],
        "product_media_assets": [],
        "product_scoped_chunks": [],
        "generic_fallback_rules": [{
            "rule_key": "generic_video",
            "fact_type": "media_reference",
            "score": 99,
            "preview": "I will send the video below.",
        }],
        "missing_required_evidence": [{"evidence_type": "media_asset", "asset_type": "installation_video"}],
        "evidence_pack_trace": {"product_identity_locked": True, "generic_rules_role": "fallback_only"},
    }
    result = generate_reply({
        "intent": "product_question",
        "answer_mode": "no_evidence_clarification",
        "customer_message": "installation video?",
        "normalized_message": "installation video?",
        "query_fact_type": "installation",
        "matched_product_name": "Test product",
        "product_first_evidence_pack": pack,
        "product_context_pack": {
            "product_first_evidence_pack": pack,
            "evidence_pack": pack,
            "recommended_assets": [],
            "media_assets": [],
            "generic_rules": [{
                "rule_key": "generic_video",
                "title": "Generic video promise",
                "fact_type": "media_reference",
                "score": 99,
                "reply_template": "I will send the video below.",
                "content": "I will send the video below.",
            }],
        },
        "trace_steps": [],
    })

    assert "send the video" not in result["suggested_reply"]
    assert result.get("generic_service_rule_used") is None
    assert result["trace_steps"][-1]["missing_required_evidence"] == [
        {"evidence_type": "media_asset", "asset_type": "installation_video"}
    ]


def test_api_analyze_preserves_product_first_trace_and_sendable_contract(client, monkeypatch):
    import app.services.analysis_execution_service as execution_service

    monkeypatch.setattr(
        "app.services.runtime_knowledge_readiness_service.RuntimeKnowledgeReadinessService.inspect",
        lambda *_args, **_kwargs: {"ready": True, "status": "ready", "reasons": [], "knowledge": {}, "database": {}},
    )

    pack = _structured_pack("material", "This product material is steel and PP.")

    def fake_execute_analysis(**kwargs):
        return _run_post_processor(kwargs, {
            "intent": "product_question",
            "suggested_reply": "亲亲，这款商品的材质是 steel and PP。",
            "requires_human_review": False,
            "context_used": {"product_context_pack": {"product_first_evidence_pack": pack, "evidence_pack": pack}},
            "evidence_debug": {
                "query_fact_type": "material",
                "selected_evidence": [{"fact_type": "material", "content": "steel and PP"}],
            },
            "answer_trace": {
                "query_fact_type": "material",
                "required_fact_types": ["material"],
                "selected_product_first_evidence": pack["product_structured_facts"][0],
            },
        })

    monkeypatch.setattr(execution_service, "execute_analysis", fake_execute_analysis)
    response = client.post("/api/analyze", json={"message": "material?", "product_name": "Test product"})

    assert response.status_code == 200
    data = response.get_json()
    assert data["can_send"] is True
    assert data["sendable_reply"]
    assert data["context_used"]["product_context_pack"]["product_first_evidence_pack"]["requested_fact_type"] == "material"


def test_api_analyze_missing_product_first_evidence_clears_sendable_reply(client, monkeypatch):
    import app.services.analysis_execution_service as execution_service

    def fake_execute_analysis(**kwargs):
        return _run_post_processor(kwargs, {
            "intent": "product_question",
            "suggested_reply": "我先帮您核对是否有安装视频。",
            "requires_human_review": True,
            "review_reason": "missing_required_evidence",
            "context_used": {
                "product_context_pack": {
                    "product_first_evidence_pack": {
                        "requested_fact_type": "installation",
                        "missing_required_evidence": [{"evidence_type": "media_asset", "asset_type": "installation_video"}],
                    }
                }
            },
            "evidence_debug": {"query_fact_type": "installation", "selected_evidence": []},
            "answer_trace": {"query_fact_type": "installation", "required_fact_types": ["installation"]},
        })

    monkeypatch.setattr(execution_service, "execute_analysis", fake_execute_analysis)
    response = client.post("/api/analyze", json={"message": "installation video?", "product_name": "Test product"})

    assert response.status_code == 200
    data = response.get_json()
    assert data["can_send"] is False
    assert data["sendable_reply"] == ""
