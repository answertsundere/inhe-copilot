"""Contract tests for /ask/api/analyze fact_type routing.

These exercise the SAME logical config path as run_prod.py:

* COPILOT_FACT_TYPE_LLM_ENABLED=True (the production default), with the LLM
  classifier stubbed so the run is deterministic and network-free. The
  deterministic ``rule_precheck`` must still win, proving the material path
  cannot drift to load_capacity just because an LLM is reachable.

* The aftersales disambiguation: a 补发/少件 question that happens to mention
  螺丝 must be classified as ``aftersales_policy`` (not ``installation``), and
  the final-answer audit must NOT replace the correct aftersales reply with an
  installation clarification.

Together these lock the P0-1 fixes: material/installation/dimensions never
surface the wrong FAQ, and aftersales never drifts to installation.
"""

from app.main import create_app
from app.services import final_answer_auditor, semantic_fact_type_service
from app.services.fact_type_service import classify_query_fact_type


SKU = "YH06K53B05S13"


def _stub_llm_misclassify(state, message, intent):
    """Pretend the LLM is reachable but confidently wrong.

    The deterministic rule_precheck runs before the LLM, so for keyword-clear
    questions this stub is never even consulted -- which is exactly the point.
    """
    return {
        "query_fact_type": "load_capacity",
        "confidence": 0.9,
        "matched_terms": [],
        "source": "llm",
        "reason": "stub_misclassify",
        "risk_hint": "",
        "secondary_fact_types": [],
    }


def _post(client, message: str) -> dict:
    return client.post("/ask/api/analyze", json={
        "message": message,
        "conversation_id": f"contract_{abs(hash(message)) & 0xFFFFFFFF}",
        "sku_code": SKU,
        "product_candidates": [
            {"value": SKU, "type": "sku_id_candidate", "verified": True},
        ],
        "copilot_context": {
            "product_candidates": [
                {"value": SKU, "type": "sku_id_candidate", "verified": True},
            ],
        },
    }).get_json()


def _assert_sendable_contract(result: dict) -> None:
    assert "draft_reply" in result
    assert "sendable_reply" in result
    assert "can_send" in result
    assert "reply_status" in result
    assert "block_reasons" in result
    assert isinstance(result["can_send"], bool)
    assert isinstance(result["block_reasons"], list)
    assert result["draft_reply"] == result["suggested_reply"]
    if result["can_send"]:
        assert result["sendable_reply"] == result["draft_reply"]
        assert result["reply_status"] == "sendable"
    else:
        assert result["sendable_reply"] == ""
        assert result["reply_status"] in {"blocked", "needs_human_review"}


# ---------------------------------------------------------------------------
# Unit-level: fact_type classifier aftersales/installation disambiguation
# ---------------------------------------------------------------------------

def test_classify_missing_screw_reissue_is_aftersales_not_installation():
    result = classify_query_fact_type("少了一个螺丝，图上这个能补发不？", "aftersales")
    assert result["query_fact_type"] == "aftersales_policy"
    assert result["source"] == "unicode_rule"


def test_classify_explicit_installation_with_missing_screw_stays_installation():
    # 安装 is an explicit installation verb -> installation wins even though
    # the message also mentions 螺丝.
    result = classify_query_fact_type("安装的时候螺丝少了一个", "installation")
    assert result["query_fact_type"] == "installation"


def test_classify_pinched_child_still_safety_not_aftersales():
    # Safety markers must block the aftersales override.
    result = classify_query_fact_type("宝宝用的时候被夹到了，你们这个是不是有质量问题？", "aftersales")
    assert result["query_fact_type"] == "pinch_safety"


# ---------------------------------------------------------------------------
# Unit-level: final-answer auditor expected topics
# ---------------------------------------------------------------------------

def test_auditor_expected_topics_for_missing_screw_is_aftersales():
    response = {
        "intent": "aftersales",
        "evidence_debug": {"query_fact_type": "aftersales_policy"},
    }
    expected = final_answer_auditor._expected_topics(
        "少了一个螺丝，图上这个能补发不？", response
    )
    assert "aftersales" in expected
    assert "installation" not in expected


def test_auditor_detect_topics_does_not_flag_installation_from_screw_when_aftersales():
    topics = final_answer_auditor._detect_topics("少了一个螺丝，能补发不？")
    assert "aftersales" in topics
    assert "installation" not in topics


# ---------------------------------------------------------------------------
# End-to-end contract via test_client on the run_prod config path
# ---------------------------------------------------------------------------

def test_material_question_stays_material_under_llm_config(monkeypatch):
    monkeypatch.setattr(
        semantic_fact_type_service.config, "COPILOT_FACT_TYPE_LLM_ENABLED", True
    )
    monkeypatch.setattr(
        semantic_fact_type_service, "_classify_with_llm", _stub_llm_misclassify
    )
    result = _post(create_app().test_client(), "这个材质安全吗？会不会容易受潮？")

    ed = result["evidence_debug"]
    assert ed["query_fact_type"] == "material"
    assert ed["query_fact_type_source"] == "semantic_consistency_guard"
    reply = result["suggested_reply"]
    assert any(token in reply for token in ("冷轧钢", "钢管", "环保PP", "无纺布"))
    assert "承重" not in reply
    assert "15-30kg" not in reply


def test_installation_question_stays_installation_under_llm_config(monkeypatch):
    monkeypatch.setattr(
        semantic_fact_type_service.config, "COPILOT_FACT_TYPE_LLM_ENABLED", True
    )
    monkeypatch.setattr(
        semantic_fact_type_service, "_classify_with_llm", _stub_llm_misclassify
    )
    result = _post(create_app().test_client(), "这个怎么安装？需要视频")

    ed = result["evidence_debug"]
    assert ed["query_fact_type"] == "installation"
    assert "承重" not in result["suggested_reply"]


def test_dimensions_question_does_not_answer_load_or_material(monkeypatch):
    monkeypatch.setattr(
        semantic_fact_type_service.config, "COPILOT_FACT_TYPE_LLM_ENABLED", True
    )
    monkeypatch.setattr(
        semantic_fact_type_service, "_classify_with_llm", _stub_llm_misclassify
    )
    result = _post(create_app().test_client(), "尺寸多少？有没有尺寸图？")

    ed = result["evidence_debug"]
    assert ed["query_fact_type"] == "dimensions"
    reply = result["suggested_reply"]
    assert "承重" not in reply
    assert "冷轧钢" not in reply


def test_aftersales_missing_screw_does_not_drift_to_installation():
    result = _post(create_app().test_client(), "少了一个螺丝，图上这个能补发不？")

    ed = result["evidence_debug"]
    assert ed["query_fact_type"] == "aftersales_policy"
    assert result["intent"] == "aftersales"
    audit = result.get("final_answer_audit") or {}
    # The correct aftersales reply must survive the audit (not be replaced by an
    # installation clarification).
    assert audit.get("passed") is True
    assert audit.get("fallback_used") is not True
    reply = result["suggested_reply"]
    assert any(token in reply for token in ("补发", "少件", "缺配件", "漏发", "发错", "售后"))
    assert "安装视频" not in reply
    assert "安装方式" not in reply


def test_analyze_response_exposes_sendable_contract(monkeypatch):
    monkeypatch.setattr(
        semantic_fact_type_service.config, "COPILOT_FACT_TYPE_LLM_ENABLED", True
    )
    monkeypatch.setattr(
        semantic_fact_type_service, "_classify_with_llm", _stub_llm_misclassify
    )
    result = _post(create_app().test_client(), "\u5546\u54c1\u6bdb\u91cd\u591a\u5c11\uff1f")

    _assert_sendable_contract(result)


def test_gross_weight_without_evidence_returns_draft_but_not_sendable(monkeypatch):
    monkeypatch.setattr(
        semantic_fact_type_service.config, "COPILOT_FACT_TYPE_LLM_ENABLED", True
    )
    monkeypatch.setattr(
        semantic_fact_type_service, "_classify_with_llm", _stub_llm_misclassify
    )
    result = _post(create_app().test_client(), "商品毛重多少？")

    assert result["suggested_reply"]
    assert result["draft_reply"] == result["suggested_reply"]
    assert result["can_send"] is False
    assert result["sendable_reply"] == ""
    assert result["block_reasons"]
    assert result["reply_status"] in {"blocked", "needs_human_review"}


def test_accessory_availability_without_evidence_is_not_installation_fallback(monkeypatch):
    monkeypatch.setattr(
        semantic_fact_type_service.config, "COPILOT_FACT_TYPE_LLM_ENABLED", True
    )
    monkeypatch.setattr(
        semantic_fact_type_service, "_classify_with_llm", _stub_llm_misclassify
    )
    result = _post(create_app().test_client(), "这个小篮子配件有卖吗")

    assert result["can_send"] is False
    assert result["sendable_reply"] == ""
    reply = result["suggested_reply"]
    assert reply
    assert "安装资料" not in reply
    assert "安装视频" not in reply
    assert "说明书" not in reply
