"""Net weight must never be inferred from gross weight or load capacity."""

import pytest

from app.services.admitted_answer_context_service import AdmittedAnswerContextService
from app.services.claim_resolution_service import build_claim_resolutions
from app.services.fact_type_service import fact_type_matches, is_strict_fact_type
from app.services.product_context_pack_service import _product_hub_facts_for_query
from app.services.semantic_fact_type_service import _canonical_fact_type_candidates


def _fact(**overrides):
    return {
        "id": "net-fact", "product_code": "test-product", "sku_code": "test-sku",
        "type": "weight", "attr": "净重", "value": "6.25", "unit": "kg",
        "scope": "商品整体", "applies": "", "source": "dingtalk-sku",
        "status": "confirmed", "conflict": False, **overrides,
    }


def _candidates(facts, query="net_weight", claims=None):
    return _product_hub_facts_for_query(
        {"state": "ready", "product_code": "test-product", "resolved_sku_code": "test-sku", "facts": facts},
        identity={"i_id": "test-product", "sku": "test-sku", "product_identity_resolution": {"status": "resolved"}},
        query_fact_type=query,
        requested_claims=claims,
    )


def test_net_weight_is_a_distinct_strict_canonical_type():
    candidates = {item["fact_type_id"]: item for item in _canonical_fact_type_candidates()}
    assert "net_weight" in candidates
    assert candidates["net_weight"]["meaning"] != candidates["gross_weight"]["meaning"]
    assert is_strict_fact_type("net_weight")
    assert fact_type_matches("net_weight", "net_weight")
    assert not fact_type_matches("net_weight", "gross_weight")
    assert not fact_type_matches("net_weight", "load_capacity")


def test_net_weight_survives_existing_admission_and_claim_resolution():
    gross = _fact(id="gross-fact", attr="毛重", scope="包装", value="8.1")
    candidates = _candidates([gross, _fact()])
    assert len(candidates) == 1
    assert candidates[0]["evidence_uid"] == "producthub:net-fact"
    assert candidates[0]["subject_scope"] == "product"
    claim = {"claim_type": "net_weight", "question": "Weight without packaging?", "risk_level": "low"}
    admitted = AdmittedAnswerContextService().build_for_response(
        {"product_context_pack": {"facts": candidates}},
        product_identity={"i_id": "test-product", "sku_code": "test-sku"},
        understanding={"requested_claims": [claim]},
    )
    facts = admitted["direct_product_facts"]
    assert [fact["evidence_uid"] for fact in facts] == ["producthub:net-fact"]
    resolution = build_claim_resolutions([claim], direct_product_facts=facts, direct_policy_facts=[], conflicts=[])
    assert resolution[0]["status"] == "supported"
    assert resolution[0]["evidence_uids"] == ["producthub:net-fact"]


@pytest.mark.parametrize("changes", [
    {"attr": "毛重", "scope": "包装"}, {"scope": "包装"}, {"scope": "配件"},
    {"unit": "g"}, {"attr": "重量"}, {"type": "load"}, {"status": "draft"},
    {"conflict": True}, {"sku_code": "other-sku"}, {"product_code": "other-product"},
])
def test_net_weight_rejects_ineligible_or_different_measurement(changes):
    assert _candidates([_fact(**changes)]) == []


@pytest.mark.parametrize("query", ["gross_weight", "load_capacity", "dimensions", "product_overview"])
def test_net_weight_does_not_answer_other_properties(query):
    assert _candidates([_fact()], query) == []


@pytest.mark.parametrize("primary", ["material_composition", "net_weight"])
def test_each_current_goal_gets_its_own_supported_hub_fact(primary):
    material = _fact(id="material-fact", type="material", attr="材质", value="PP", unit="")
    claims = [{"claim_type": kind, "question": kind, "risk_level": "low"}
              for kind in ("material_composition", "net_weight")]
    candidates = _candidates([material, _fact()], primary, claims)
    assert {c["evidence_uid"] for c in candidates} == {"producthub:material-fact", "producthub:net-fact"}
    admitted = AdmittedAnswerContextService().build_for_response(
        {"product_context_pack": {"facts": candidates}},
        product_identity={"i_id": "test-product", "sku_code": "test-sku"},
        understanding={"requested_claims": claims},
    )
    resolution = build_claim_resolutions(claims, direct_product_facts=admitted["direct_product_facts"],
                                        direct_policy_facts=[], conflicts=[])
    assert [r["status"] for r in resolution] == ["supported", "supported"]
    assert resolution[1]["evidence_uids"] == ["producthub:net-fact"]


@pytest.mark.parametrize("changes", [
    {"attr": "毛重", "scope": "包装"}, {"scope": "包装"}, {"scope": "配件"},
    {"unit": "g"}, {"attr": "重量"}, {"type": "load"}, {"status": "draft"},
    {"conflict": True}, {"sku_code": "other-sku"}, {"product_code": "other-product"},
])
def test_secondary_goal_keeps_all_existing_net_weight_gates(changes):
    claims = [{"claim_type": "material_composition"}, {"claim_type": "net_weight"}]
    assert _candidates([_fact(**changes)], "material_composition", claims) == []


def test_multi_goal_deduplicates_same_evidence_without_conflating_measurements():
    claims = [{"claim_type": kind} for kind in ("material_composition", "net_weight", "gross_weight", "net_weight")]
    gross = _fact(id="gross-fact", attr="毛重", scope="包装", value="8.1")
    candidates = _candidates([gross, _fact()], "material_composition", claims)
    assert {c["evidence_uid"] for c in candidates} == {"producthub:net-fact", "producthub:gross-fact"}
    assert len(candidates) == 2
    assert {c["fact_type"]: c["value"] for c in candidates} == {"net_weight": "6.25kg", "gross_weight": "8.1kg"}


@pytest.mark.parametrize("claim", [None, "net_weight", {}, {"claim_type": ["net_weight"]},
    {"claim_type": "net_weight", "claim_type_status": "unmapped"},
    {"claim_type": "net_weight", "customer_goal_eligible": False},
    {"claim_type": "net_weight", "prohibited": True},
    {"claim_type": "net_weight", "supporting_only": True}])
def test_non_customer_or_invalid_secondary_goal_does_not_expand_fact_request(claim):
    assert _candidates([_fact()], "material_composition", [claim]) == []
