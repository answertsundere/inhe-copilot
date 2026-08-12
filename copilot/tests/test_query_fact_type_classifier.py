import pytest

from app.main import create_app
from app.agent.nodes.query_fact_type_classifier import (
    _requested_claims_from_customer_goals,
    _turn_understanding_from_result,
    query_fact_type_classifier,
)
from app.services import semantic_fact_type_service
from app.services.analysis_pipeline_service import AnalysisPipelineService
from app.services.fact_type_service import classify_query_fact_type


@pytest.fixture(autouse=True)
def _disable_runtime_readiness_for_classifier_contracts(monkeypatch):
    monkeypatch.setattr(
        AnalysisPipelineService,
        "_knowledge_readiness_for_request",
        staticmethod(lambda _request: None),
    )


def _authoritative_llm_result(
    message: str,
    *,
    fact_type: str,
    secondary_fact_types: list[str],
) -> dict:
    goals, status, diagnostics = (
        semantic_fact_type_service._sanitize_customer_goals(
            [{
                "goal_kind": "customer_goal",
                "claim_type_status": "canonical",
                "claim_type": fact_type,
                "attribute_key": "",
                "semantic_key": "",
                "policy_intent_ref": "",
                "source_text": message,
            }],
            message=message,
        )
    )
    return {
        "query_fact_type": fact_type,
        "confidence": 1.0,
        "matched_terms": [],
        "source": "llm",
        "reason": "minimal_turn_understanding_validated",
        "risk_hint": "",
        "query_fact_type_label": fact_type,
        "secondary_fact_types": secondary_fact_types,
        "customer_goals": goals,
        "goal_understanding_status": status,
        "goal_understanding_diagnostics": diagnostics,
    }


def test_query_fact_type_classifier_high_frequency_fields():
    cases = {
        "\u8fd9\u4e2a\u4ec0\u4e48\u6750\u8d28\uff1f": "material",
        "\u6ca1\u6709\u7532\u919b\u7684\u68c0\u67e5\u62a5\u544a\u5417\uff1f": "certification_report",
        "\u57fa\u7840\u6b3e\u548c\u5347\u7ea7\u6b3e\u5dee\u4ec0\u4e48": "variant_compare",
        "\u8fd9\u4e2a\u627f\u91cd\u591a\u5c11\uff1f": "load_capacity",
        "\u8fd9\u4e2a\u7ed9\u5b9d\u5b9d\u7528\u7edd\u5bf9\u4e0d\u4f1a\u5012\u5427\uff1f": "stability",
        "\u8fd9\u4e2a\u9632\u503e\u5012\u5417\uff1f": "stability",
        "\u8fd9\u4e2a\u7a33\u4e0d\u7a33\uff1f": "stability",
        "\u8fd9\u4e2a\u4f1a\u4e0d\u4f1a\u5939\u624b\u6216\u8005\u6709\u5b89\u5168\u9690\u60a3\uff1f": "pinch_safety",
        "\u8fd9\u4e2a\u5c0f\u96f6\u4ef6\u4f1a\u4e0d\u4f1a\u88ab\u5b9d\u5b9d\u8bef\u541e\uff1f": "safety_small_parts",
        "\u9002\u5408\u591a\u5927\u5b9d\u5b9d\uff1f": "age_range",
        "\u53ef\u4ee5\u5f00\u53d1\u7968\u5417\uff1f": "invoice_policy",
        "\u53ef\u4ee5\u7533\u8bf7\u4ef7\u4fdd\u5417\uff1f": "price_protection",
        "\u8fd9\u662f\u53ef\u62c6\u5378\u7684\u5417\uff1f": "detachable",
        "\u4ea7\u54c1\u6709\u6c14\u5473\u5417": "odor",
        "\u8fd9\u4e2a\u6709\u5473\u513f\u5417": "odor",
        "\u6750\u8d28\u6709\u6c14\u5473\u5417": "odor",
        "\u652f\u4ed8\u5b9d\u6253\u6b3e\u591a\u4e45\u80fd\u5230\u8d26": "aftersales_policy",
        "\u6dd8\u5b9d\u5c0f\u989d\u6253\u6b3e\u4e00\u822c\u591a\u4e45": "aftersales_policy",
        "\u7269\u6d41\u5230\u54ea\u4e86": "stock_shipping",
        "\u7b7e\u6536\u540e\u6ca1\u6536\u5230": "stock_shipping",
        "\u8fd0\u5355\u53f7\u53d1\u6211\u4e00\u4e0b": "stock_shipping",
        "\u4e3a\u4ec0\u4e48\u6ca1\u6709\u4e0a\u95e8\u53d6\u4ef6": "return_pickup",
        "\u9000\u8d27\u53d6\u4ef6\u600e\u4e48\u5b89\u6392": "return_pickup",
        "\u53d6\u4ef6\u7801\u5728\u54ea\u91cc\u770b": "return_pickup",
        "\u4e70\u4e24\u4e2a\u80fd\u4e0d\u80fd\u4fbf\u5b9c\u70b9": "promotion_policy",
        "\u591a\u4e70\u6709\u798f\u5229\u5417": "promotion_policy",
        "\u8fd9\u4e2a\u600e\u4e48\u4e0b\u5355": "order_assistance",
        "\u600e\u6837\u4e0b\u5355": "order_assistance",
        "\u89c4\u683c\u600e\u4e48\u9009": "order_assistance",
        "\u5f00\u7968": "invoice_policy",
        "\u76d2\u5b50\u591a\u5927": "dimensions",
        "\u9664\u4e86\u6307\u7532\u5200\uff0c\u5176\u5b83\u4fe9\u4e2a\u4f5c\u7528\u662f\u5565": "accessory_usage",
        "\u6bdb\u91cd\u591a\u5c11": "gross_weight",
        "\u5546\u54c1\u6bdb\u91cd\u591a\u5c11": "gross_weight",
        "\u8fd9\u4e2a\u591a\u91cd": "gross_weight",
        "\u5c0f\u7bee\u5b50\u914d\u4ef6\u6709\u5356\u5417": "accessory_availability",
        "\u914d\u4ef6\u80fd\u5355\u72ec\u4e70\u5417": "accessory_availability",
        "\u4ec0\u4e48\u5851\u6599": "material",
        "\u8d34\u7eb8\u8d34\u54ea\uff1f": "installation",
        "\u8fd9\u4e2a\u4e0d\u662f\u80cc\u80f6\u5417": "installation",
        "\u87ba\u5e3d\u6ed1\u7259\u600e\u4e48\u529e": "aftersales_policy",
        "\u5e2e\u6211\u6539\u4e00\u4e0b\u5730\u5740": "order_assistance",
        "\u4eb2\u5e2e\u6211\u53d1\u5230\u8fd9\u4e2a\u5730\u5740\uff0c\u521a\u521a\u4e0b\u5355\u7684\u5730\u5740\u9519\u4e86": "order_assistance",
        "\u9001\u8d27\u4e0a\u95e8\u5417": "stock_shipping",
        "\u8fd9\u4e24\u6b3e\u54ea\u4e2a\u627f\u653e\u7684\u6570\u91cf\u66f4\u591a": "variant_compare",
    }
    for message, expected in cases.items():
        result = classify_query_fact_type(message, "product_question")
        assert result["query_fact_type"] == expected


def test_return_pickup_does_not_steal_normal_shipping_questions():
    for message in ("\u7269\u6d41\u5230\u54ea\u4e86", "\u4ec0\u4e48\u65f6\u5019\u53d1\u8d27", "\u7b7e\u6536\u540e\u6ca1\u6536\u5230", "\u8fd0\u5355\u53f7\u53d1\u6211\u4e00\u4e0b"):
        result = classify_query_fact_type(message, "product_question")
        assert result["query_fact_type"] == "stock_shipping"


def test_accessory_installation_question_is_not_availability():
    result = classify_query_fact_type("\u8fd9\u4e2a\u914d\u4ef6\u600e\u4e48\u88c5", "product_question")

    assert result["query_fact_type"] in {"installation", "accessory_usage"}
    assert result["query_fact_type"] != "accessory_availability"


def test_service_aliases_do_not_steal_ambiguous_short_turns():
    for message in ("\u8fd9\u4e2a\u5462", "\u53ef\u4ee5\u5417", "\u5728\u5417", "\u94fe\u63a5"):
        result = classify_query_fact_type(message, "product_question")
        assert result["query_fact_type"] not in {
            "stock_shipping",
            "promotion_policy",
            "aftersales_policy",
            "order_assistance",
        }


def test_weight_units_with_pressure_context_are_load_capacity():
    for message in ("放几斤不压扁", "放多少斤会不会压弯", "能放几斤书", "中间再加个双层隔板可以放32.5公斤吗"):
        result = classify_query_fact_type(message, "product_question")
        assert result["query_fact_type"] == "load_capacity"


def test_plain_product_weight_questions_remain_gross_weight():
    for message in ("这个多重", "毛重多少", "商品重量几斤"):
        result = classify_query_fact_type(message, "product_question")
        assert result["query_fact_type"] == "gross_weight"


def test_structure_or_capacity_terms_do_not_steal_space_fit():
    result = classify_query_fact_type("这个柜子能不能放阳台", "product_question")

    assert result["query_fact_type"] == "placement_scene"


def test_child_suitability_age_terms_are_age_range():
    for message in ("有没有适合2周岁宝宝的", "这个适合几岁宝宝", "两岁小孩能不能用", "宝宝多大能用"):
        result = classify_query_fact_type(message, "product_question")
        assert result["query_fact_type"] == "age_range"


def test_baby_product_name_with_installation_request_stays_installation():
    result = classify_query_fact_type("宝宝书架有安装视频吗", "product_question")

    assert result["query_fact_type"] == "installation"


def test_promotion_terms_are_not_misrouted_to_aftersales():
    for message in ("有没有福利", "有什么优惠", "晒图返多少"):
        result = classify_query_fact_type(message, "product_question")
        assert result["query_fact_type"] == "promotion_policy"
        assert result.get("secondary_fact_types", []) == []


def test_aftersales_promotion_multi_intent_keeps_promotion_secondary():
    result = classify_query_fact_type("退货后晒图福利还给吗", "product_question")

    assert result["query_fact_type"] == "aftersales_policy"
    assert "promotion_policy" in result.get("secondary_fact_types", [])


def test_material_care_question_keeps_cleaning_and_moisture_as_independent_claims():
    result = classify_query_fact_type("\u8fd9\u4e2a\u53ef\u4ee5\u6c34\u6d17\u5417\uff0c\u4f1a\u4e0d\u4f1a\u53d7\u6f6e\u53d1\u9709\uff1f", "product_question")

    assert result["query_fact_type"] == "cleaning_care"
    assert "moisture_resistance" in result.get("secondary_fact_types", [])


def test_bite_or_toxicity_is_a_distinct_high_risk_fact_type():
    result = classify_query_fact_type("\u5b69\u5b50\u8bef\u54ac\u4e86\u4e00\u4e0b\uff0c\u4f1a\u4e0d\u4f1a\u4e2d\u6bd2\uff1f", "product_question")

    assert result["query_fact_type"] == "bite_or_toxicity"


def test_api_exposes_query_fact_type_debug(monkeypatch):
    message = "\u6ca1\u6709\u7532\u919b\u7684\u68c0\u67e5\u62a5\u544a\u5417\uff1f"
    def fake_classify(_state, _message, _intent, **kwargs):
        diagnostics_sink = kwargs.get("diagnostics_sink")
        if isinstance(diagnostics_sink, dict):
            diagnostics_sink.update({
                "schema_version": "turn-understanding-diagnostics/v4",
                "status": "passed",
                "reason_code": "",
                "provider": {
                    "provider_family": "formal_agent",
                    "model": "configured-model",
                    "host_fingerprint": "a" * 12,
                    "http_status": None,
                    "provider_error_category": "",
                },
            })
        return _authoritative_llm_result(
            message,
            fact_type="certification_report",
            secondary_fact_types=[],
        )

    monkeypatch.setattr(
        semantic_fact_type_service.config,
        "COPILOT_FACT_TYPE_LLM_ENABLED",
        True,
    )
    monkeypatch.setattr(
        semantic_fact_type_service,
        "_classify_with_llm",
        fake_classify,
    )
    app = create_app()
    client = app.test_client()

    result = client.post("/ask/api/analyze", json={
        "message": message,
        "conversation_id": "test_query_fact_type_debug",
        "sku_code": "YH06K53B05S13",
        "product_candidates": [
            {"value": "YH06K53B05S13", "type": "sku_id_candidate", "verified": True},
        ],
    }).get_json()

    debug = result["evidence_debug"]
    assert debug["query_fact_type"] == "certification_report"
    assert debug["query_fact_type_label"]
    assert debug["turn_understanding_model_diagnostics"] == {
        "schema_version": "turn-understanding-diagnostics/v4",
        "status": "passed",
        "reason_code": "",
        "provider": {
            "provider_family": "formal_agent",
            "model": "configured-model",
            "host_fingerprint": "a" * 12,
            "http_status": None,
            "provider_error_category": "",
        },
    }
    assert result["requires_human_review"] is True


def test_turn_understanding_requests_only_customer_goals():
    result = {
        "query_fact_type": "material",
        "secondary_fact_types": ["moisture_resistance"],
        "risk_hint": "medium",
        "goal_understanding_status": "valid",
        "goal_understanding_diagnostics": [],
        "customer_goals": [
            {
                "goal_ref": "goal-material",
                "goal_kind": "customer_goal",
                "claim_type": "material_composition",
                "attribute_key": "material",
                "semantic_key": "",
                "goal_summary": "confirm material",
                "source": "current_customer_message",
                "source_span_start": 0,
                "source_span_end": 10,
                "source_span_sha256": "a" * 64,
            },
            {
                "goal_ref": "goal-moisture",
                "goal_kind": "customer_goal",
                "claim_type": "moisture_resistance",
                "attribute_key": "",
                "semantic_key": "",
                "goal_summary": "confirm moisture boundary",
                "source": "current_customer_message",
                "source_span_start": 11,
                "source_span_end": 20,
                "source_span_sha256": "b" * 64,
            },
            {
                "goal_ref": "goal-support",
                "goal_kind": "evidence_dependency",
                "claim_type": "material_composition",
                "attribute_key": "material",
                "semantic_key": "",
                "goal_summary": "supporting material",
            },
            {
                "goal_ref": "goal-action",
                "goal_kind": "service_action",
                "claim_type": "aftersales_policy",
                "attribute_key": "",
                "semantic_key": "",
                "goal_summary": "service action",
            },
        ],
    }

    understanding = _turn_understanding_from_result(
        {"customer_message": "multi-goal customer turn"},
        result,
    )

    assert [item["goal_ref"] for item in understanding["requested_claims"]] == [
        "goal-material",
        "goal-moisture",
    ]
    assert {
        item["source"] for item in understanding["requested_claims"]
    } == {"current_customer_message"}
    assert understanding["customer_goals"] == result["customer_goals"]


def test_requested_claim_risk_is_scoped_to_each_customer_goal():
    """A restricted goal cannot promote a separate practical goal to high risk."""
    goals = [
        {
            "goal_ref": "goal-absolute",
            "goal_kind": "customer_goal",
            "claim_type": "",
            "attribute_key": "durability",
            "semantic_key": "durability",
            "policy_intent_ref": "durability_absolute_guarantee",
            "policy_goal_family": "product_durability",
            "policy_intent_kind": "absolute_guarantee",
            "goal_summary": "confirm absolute durability guarantee",
            "source": "current_customer_message",
            "source_span_start": 0,
            "source_span_end": 10,
            "source_span_sha256": "a" * 64,
        },
        {
            "goal_ref": "goal-practical",
            "goal_kind": "customer_goal",
            "claim_type": "",
            "attribute_key": "durability",
            "semantic_key": "durability",
            "policy_intent_ref": "durability_practical_guidance",
            "policy_goal_family": "product_durability",
            "policy_intent_kind": "practical_guidance",
            "goal_summary": "confirm ordinary-use durability guidance",
            "source": "current_customer_message",
            "source_span_start": 11,
            "source_span_end": 21,
            "source_span_sha256": "b" * 64,
        },
    ]

    claims = _requested_claims_from_customer_goals(
        goals,
        question="multi-goal customer turn",
        risk_hint="high",
    )

    assert {
        item["goal_ref"]: item["risk_level"] for item in claims
    } == {
        "goal-absolute": "high",
        "goal-practical": "medium",
    }


def test_requested_claim_high_risk_fact_type_is_never_downgraded():
    claims = _requested_claims_from_customer_goals(
        [{
            "goal_ref": "goal-safety",
            "goal_kind": "customer_goal",
            "claim_type": "stability",
            "attribute_key": "",
            "semantic_key": "",
            "policy_intent_ref": "",
            "policy_goal_family": "",
            "policy_intent_kind": "",
            "goal_summary": "confirm stability",
            "source": "current_customer_message",
            "source_span_start": 0,
            "source_span_end": 10,
            "source_span_sha256": "a" * 64,
        }],
        question="single high-risk customer turn",
        risk_hint="low",
    )

    assert claims[0]["risk_level"] == "high"


def test_unmapped_customer_goal_is_preserved_without_new_fact_type():
    claims = _requested_claims_from_customer_goals(
        [{
            "goal_ref": "goal-durability",
            "goal_kind": "customer_goal",
            "claim_type": "",
            "attribute_key": "durability",
            "semantic_key": "durability",
            "policy_intent_ref": "",
            "policy_goal_family": "",
            "policy_intent_kind": "",
            "goal_summary": "confirm durability boundary",
            "source": "current_customer_message",
            "source_span_start": 0,
            "source_span_end": 11,
            "source_span_sha256": "c" * 64,
        }],
        question="multi-goal customer turn",
        risk_hint="medium",
    )

    assert claims == [{
        "goal_ref": "goal-durability",
        "goal_kind": "customer_goal",
        "claim_type": "",
        "attribute_key": "durability",
        "semantic_key": "durability",
        "policy_intent_ref": "",
        "policy_goal_family": "",
        "policy_intent_kind": "",
        "goal_summary": "confirm durability boundary",
        "source": "current_customer_message",
        "source_span_start": 0,
        "source_span_end": 11,
        "source_span_sha256": "c" * 64,
        "owner": "turn_understanding_owner",
        "source_stage": "query_fact_type_classifier",
        "question": "multi-goal customer turn",
        "risk_level": "medium",
    }]


def test_trusted_policy_intent_fields_are_projected_to_requested_claim():
    claims = _requested_claims_from_customer_goals(
        [{
            "goal_ref": "goal-durability",
            "goal_kind": "customer_goal",
            "claim_type": "",
            "attribute_key": "drop_durability",
            "semantic_key": "diagnostic_only",
            "policy_intent_ref": (
                "product_durability_practical_guidance"
            ),
            "policy_goal_family": "product_durability",
            "policy_intent_kind": "practical_guidance",
            "goal_summary": "confirm practical durability boundary",
            "source": "current_customer_message",
            "source_span_start": 0,
            "source_span_end": 11,
            "source_span_sha256": "c" * 64,
        }],
        question="multi-goal customer turn",
        risk_hint="medium",
    )

    assert claims[0]["policy_intent_ref"] == (
        "product_durability_practical_guidance"
    )
    assert claims[0]["policy_goal_family"] == "product_durability"
    assert claims[0]["policy_intent_kind"] == "practical_guidance"


@pytest.mark.parametrize("goal_kind", ["evidence_dependency", "service_action"])
def test_server_understanding_clears_injected_requested_claims_without_customer_goal(
    goal_kind,
):
    understanding = _turn_understanding_from_result(
        {
            "customer_message": "请核对一下",
            "turn_understanding": {
                "requested_claims": [{
                    "goal_ref": "goal-injected",
                    "goal_kind": "customer_goal",
                    "claim_type": "material_composition",
                    "source": "current_customer_message",
                    "source_span_start": 0,
                    "source_span_end": 4,
                    "source_span_sha256": "a" * 64,
                }],
                "customer_goals": [{"goal_kind": "customer_goal"}],
                "goal_understanding_status": "valid",
            },
        },
        {
            "query_fact_type": "",
            "customer_goals": [{
                "goal_ref": "goal-evidence",
                "goal_kind": goal_kind,
                "claim_type": "material_composition",
            }],
            "goal_understanding_status": "valid",
            "goal_understanding_diagnostics": [],
        },
    )

    assert understanding["requested_claims"] == []
    assert understanding["customer_goals"][0]["goal_kind"] == goal_kind


def test_preclassified_top_level_fact_type_does_not_override_multi_goal_owner(
    monkeypatch,
):
    monkeypatch.setattr(
        "app.agent.nodes.query_fact_type_classifier."
        "classify_query_fact_type_llm_first",
        lambda _state, **_kwargs: {
            "query_fact_type": "",
            "confidence": 0.9,
            "source": "llm",
            "reason": "multi-goal understanding",
            "risk_hint": "medium",
            "secondary_fact_types": [],
            "semantic_query": {},
            "customer_goals": [{
                "goal_ref": "goal-unmapped",
                "goal_kind": "customer_goal",
                "claim_type_status": "unmapped",
                "claim_type": "",
                "attribute_key": "durability",
                "semantic_key": "product_drop_durability",
                "goal_summary": "confirm durability boundary",
                "source": "current_customer_message",
                "source_span_start": 0,
                "source_span_end": 10,
                "source_span_sha256": "a" * 64,
            }],
            "goal_understanding_status": "valid",
            "goal_understanding_diagnostics": [],
        },
    )

    result = query_fact_type_classifier({
        "customer_message": "multi goal",
        "query_fact_type": "material",
    })

    assert result["query_fact_type"] == ""
    assert result["turn_understanding"]["customer_goals"][0][
        "claim_type_status"
    ] == "unmapped"


def test_classifier_projects_safe_turn_understanding_model_diagnostics(
    monkeypatch,
):
    def fake_classify(_state, *, diagnostics_sink=None):
        diagnostics_sink.update({
            "schema_version": "turn-understanding-diagnostics/v4",
            "status": "failed",
            "reason_code": "provider_rate_limited",
            "provider": {
                "provider_family": "formal_agent",
                "model": "configured-model",
                "host_fingerprint": "a" * 12,
                "http_status": 429,
                "provider_error_category": "provider_rate_limited",
            },
        })
        return {
            "query_fact_type": "material_composition",
            "confidence": 0.5,
            "source": "fallback",
            "reason": "fallback",
            "risk_hint": "medium",
            "secondary_fact_types": [],
            "semantic_query": {},
            "customer_goals": [],
            "goal_understanding_status": "degraded",
            "goal_understanding_diagnostics": [
                "provider_rate_limited",
            ],
        }

    monkeypatch.setattr(
        "app.agent.nodes.query_fact_type_classifier."
        "classify_query_fact_type_llm_first",
        fake_classify,
    )

    result = query_fact_type_classifier({"customer_message": "question"})

    assert result["turn_understanding_model_diagnostics"] == {
        "schema_version": "turn-understanding-diagnostics/v4",
        "status": "failed",
        "reason_code": "provider_rate_limited",
        "provider": {
            "provider_family": "formal_agent",
            "model": "configured-model",
            "host_fingerprint": "a" * 12,
            "http_status": 429,
            "provider_error_category": "provider_rate_limited",
        },
    }


def test_api_final_audit_blocks_pinch_as_battery_topic(monkeypatch):
    message = "\u5bb6\u91cc\u6709\u4e24\u5c81\u5b9d\u5b9d\uff0c\u8fd9\u4e2a\u4f1a\u4e0d\u4f1a\u5939\u624b\u6216\u8005\u6709\u5b89\u5168\u9690\u60a3\uff1f"
    monkeypatch.setattr(
        semantic_fact_type_service.config,
        "COPILOT_FACT_TYPE_LLM_ENABLED",
        True,
    )
    monkeypatch.setattr(
        semantic_fact_type_service,
        "_classify_with_llm",
        lambda _state, _message, _intent, **_kwargs: (
            _authoritative_llm_result(
                message,
                fact_type="pinch_safety",
                secondary_fact_types=[],
            )
        ),
    )
    app = create_app()
    client = app.test_client()

    result = client.post("/ask/api/analyze", json={
        "message": message,
        "product_title": "\u82f1\u79be\u9632\u5939\u6ed1\u95e8\u6536\u7eb3\u67b6\u6574\u7406\u5ba2\u5385\u96f6\u98df\u684c\u9762\u513f\u7ae5\u73a9\u5177\u5367\u5ba4\u53ef\u62fc\u642d\u50a8\u7269\u62bd\u5c49",
        "conversation_id": "test_api_final_audit_pinch_safety",
    }).get_json()

    debug = result["evidence_debug"]
    assert debug["query_fact_type"] == "pinch_safety"
    assert result["final_answer_audit"]["passed"] is False
    assert result["final_answer_audit"]["fallback_used"] is True
    assert "\u5939\u624b" in result["suggested_reply"]
    assert "\u5c0f\u96f6\u4ef6/\u7535\u6c60\u5b89\u5168" not in result["suggested_reply"]


def test_llm_fact_type_classification_can_override_rule_hint(monkeypatch):
    monkeypatch.setattr(semantic_fact_type_service.config, "COPILOT_FACT_TYPE_LLM_ENABLED", True)
    monkeypatch.setattr(
        semantic_fact_type_service,
        "_classify_with_llm",
        lambda state, message, intent, **_kwargs: _authoritative_llm_result(
            message,
            fact_type="odor",
            secondary_fact_types=["material"],
        ),
    )

    result = semantic_fact_type_service.classify_query_fact_type_llm_first({
        "normalized_message": "\u6750\u8d28\u6709\u6c14\u5473\u5417",
        "intent": "product_question",
    })

    assert result["query_fact_type"] == "odor"
    assert result["source"] == "llm"
    assert result["secondary_fact_types"] == ["material"]


def test_llm_fact_type_space_fit_is_not_overridden_by_rule_hint(monkeypatch):
    monkeypatch.setattr(semantic_fact_type_service.config, "COPILOT_FACT_TYPE_LLM_ENABLED", True)
    monkeypatch.setattr(
        semantic_fact_type_service,
        "_classify_with_llm",
        lambda state, message, intent, **_kwargs: _authoritative_llm_result(
            message,
            fact_type="space_fit",
            secondary_fact_types=["dimensions"],
        ),
    )

    result = semantic_fact_type_service.classify_query_fact_type_llm_first({
        "normalized_message": "\u5367\u5ba4\u653e\u7684\u4e0b\u5417\uff0c\u7a7a\u95f4\u53ef\u80fd\u6bd4\u8f83\u5c0f",
        "intent": "product_question",
    })

    assert result["query_fact_type"] == "space_fit"
    assert result["source"] == "llm"
