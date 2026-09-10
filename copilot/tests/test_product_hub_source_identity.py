from copy import deepcopy
import json
from urllib.parse import quote

import pytest

from app.integrations.product_hub import reviewed_facts_client as hub
from app.services.product_identity_resolver import ProductIdentityResolver
from test_product_context_pack_service import product_context_db


@pytest.fixture
def source(monkeypatch):
    monkeypatch.setenv("COPILOT_KNOWLEDGE_SOURCE_MODE", "product_hub_review_only")
    monkeypatch.setenv("COPILOT_RUNTIME_ENV", "test")
    monkeypatch.setenv("COPILOT_FORMAL_KNOWLEDGE_QUERY_ONLY", "true")
    monkeypatch.setenv("COPILOT_PRODUCT_HUB_REVIEWED_FACTS_ENABLED", "true")
    monkeypatch.setenv("COPILOT_PRODUCT_HUB_BASE_URL", "http://127.0.0.1:8795")
    sku, code = "item-A 09", "product-A"
    data = {
        "sku": {"id": "sku-record", "skuCode": sku, "productCode": code, "status": "active"},
        "product": {"id": "hub-product-record", "productCode": code, "status": "active", "name": "Product A"},
    }
    data["passport"] = {
        "ok": True,
        "product": {**data["product"], "domainPolicyId": "maternal_child_home"},
        "skus": [{**data["sku"], "productId": data["product"]["id"]}],
        "timeline": [{"text": "private source history"}],
        "prompts": ["untrusted source instruction"],
    }
    calls = []

    def read(url, **_kwargs):
        calls.append(url)
        if url.endswith("/skus/" + quote(sku, safe="")):
            return {"ok": True, "sku": data["sku"]}, ""
        if url.endswith("/products/" + code + "/passport"):
            return deepcopy(data["passport"]), ""
        assert url.endswith("/products/" + code)
        return {"ok": True, "product": data["product"]}, ""

    monkeypatch.setattr(hub, "_read_json", read)

    def no_legacy(_self):
        raise AssertionError("Hub candidate must not load samples or legacy catalog")

    monkeypatch.setattr(ProductIdentityResolver, "_load_product_data", no_legacy)
    return sku, data, calls


def test_exact_sku_resolves_without_local_catalog_and_preserves_namespaces(source):
    sku, _, calls = source
    result = ProductIdentityResolver().resolve(sku_id=sku)
    assert result["status"] == "resolved"
    assert result["sku_code"] == sku and result["product_code"] == "product-A"
    assert result["display_product_name"] == "Product A"
    assert result["source"] == "product_hub_exact_sku"
    assert result["i_id"] == result["internal_i_id"] == result["resolved_product_id"] == ""
    assert result["hub_product_id"] == "hub-product-record"
    assert "facts" not in result and "can_send" not in result and len(calls) == 2


@pytest.mark.parametrize("signal", ["platform_product_id", "platform_product_id_hash", "product_url", "order_id", "internal_i_id", "product_candidates"])
def test_sku_does_not_override_other_identity_namespaces(source, signal):
    sku, _, calls = source
    result = ProductIdentityResolver().resolve(sku_id=sku, **{signal: "competing-identity"})
    assert result["status"] == "not_found" and not calls


@pytest.mark.parametrize("title, expected", [("Product A", "resolved"), ("product-A", "resolved"), ("Other product", "not_found")])
def test_exact_repeated_name_allowed_but_conflicting_title_blocked(source, title, expected):
    sku, _, _ = source
    assert ProductIdentityResolver().resolve(sku_id=sku, platform_title=title)["status"] == expected


@pytest.mark.parametrize("target, field, value", [
    ("sku", "skuCode", "neighbor"), ("sku", "id", ""), ("sku", "status", "archived"),
    ("product", "productCode", "neighbor"), ("product", "id", None), ("product", "status", "archived"),
])
def test_active_exact_identity_required_from_both_endpoints(source, target, field, value):
    sku, data, _ = source
    data[target][field] = value
    assert ProductIdentityResolver().resolve(sku_id=sku)["status"] == "not_found"


@pytest.mark.parametrize("mode", ["production", "unknown"])
def test_hub_identity_remains_candidate_only(source, monkeypatch, mode):
    sku, _, calls = source
    monkeypatch.setenv("COPILOT_RUNTIME_ENV", mode)
    assert ProductIdentityResolver().resolve(sku_id=sku)["status"] == "not_found"
    assert not calls


def test_disabled_reader_cannot_fall_back_to_historical_identity(source, monkeypatch):
    sku, _, calls = source
    monkeypatch.setenv("COPILOT_PRODUCT_HUB_REVIEWED_FACTS_ENABLED", "false")
    assert ProductIdentityResolver().resolve(sku_id=sku)["status"] == "not_found"
    assert not calls


def test_endpoint_failure_is_unresolved_not_legacy_fallback(source, monkeypatch):
    sku, _, _ = source
    monkeypatch.setattr(hub, "_read_json", lambda *_args, **_kwargs: (None, "unavailable"))
    assert ProductIdentityResolver().resolve(sku_id=sku)["status"] == "not_found"


def test_source_revocation_is_observed_on_next_identity_lookup(source):
    sku, data, calls = source
    resolver = ProductIdentityResolver()
    assert resolver.resolve(sku_id=sku)["status"] == "resolved"
    data["product"]["status"] = "archived"
    assert resolver.resolve(sku_id=sku)["status"] == "not_found"
    assert len(calls) == 4


def test_canonical_sku_candidate_does_not_become_internal_id(source):
    sku, _, _ = source
    from app.services.real_context_product_identity_service import augment_state_with_real_context_identity
    from app.services.product_context_pack_service import _state_identity, _identity_resolution_signals

    state = {"copilot_context": {"sku_code": sku}}
    augment_state_with_real_context_identity(state)
    identity = _state_identity(state)
    signals = _identity_resolution_signals(state, identity)
    assert signals["internal_i_id"] == ""
    assert ProductIdentityResolver().resolve(**signals)["status"] == "resolved"


def test_sku_prefix_is_not_a_verified_internal_code_in_hub_mode(source):
    from app.services.real_context_product_identity_service import build_real_context_product_identity
    from app.services.product_context_pack_service import _state_identity

    sku = "YH19K220104"
    context = {"sku_code": sku}
    assert build_real_context_product_identity(context)["i_id"] == ""
    assert _state_identity({"copilot_context": context})["i_id"] == ""
    assert ProductIdentityResolver().resolve(sku_id=sku, internal_i_id="YH19K22")["status"] == "not_found"


def test_conflicting_duplicate_sku_candidates_still_block(source):
    sku, _, calls = source
    result = ProductIdentityResolver().resolve(sku_id=sku, product_candidates=[
        {"type": "sku_code", "value": sku}, {"type": "sku_code", "value": "other-sku"},
    ])
    assert result["status"] == "not_found" and not calls


@pytest.mark.parametrize("surface", ["slots", "copilot_context", "top_level"])
@pytest.mark.parametrize("label", ["this selection", "previous item", "unknown model 27"])
def test_router_label_is_diagnostic_not_exact_sku_identity(source, surface, label):
    from app.agent.nodes.llm_intent_router import _result
    from app.services.product_context_pack_service import _state_identity, _identity_resolution_signals

    sku, _, _ = source
    state = {"sku_code": sku} if surface == "top_level" else {surface: {"sku_code": sku}}
    decision = {"intent": "product_question", "product_name": label}
    update = _result(state, decision, 0, "llm", "routing only")
    state.update(update)
    assert update["matched_product_name"] == ""
    assert update["router_decision"]["product_name"] == label
    signals = _identity_resolution_signals(state, _state_identity(state))
    resolved = ProductIdentityResolver().resolve(**signals)
    assert resolved["status"] == "resolved"
    assert resolved["sku_code"] == sku


@pytest.mark.parametrize("surface", ["matched_product_name", "slots", "copilot_context"])
@pytest.mark.parametrize("title, expected", [("Product A", "resolved"), ("Other product", "not_found")])
def test_router_preserves_explicit_title_conflict_gate(source, surface, title, expected):
    from app.agent.nodes.llm_intent_router import _result
    from app.services.product_context_pack_service import _state_identity, _identity_resolution_signals

    sku, _, _ = source
    state = {"sku_code": sku}
    if surface == "matched_product_name":
        state[surface] = title
    else:
        state[surface] = {"product_name": title}
    state.update(_result(state, {"product_name": "Product A"}, 0, "llm", "routing only"))
    signals = _identity_resolution_signals(state, _state_identity(state))
    assert signals["platform_title"] == title
    assert ProductIdentityResolver().resolve(**signals)["status"] == expected


def test_router_does_not_make_identity_without_product_evidence():
    from app.agent.nodes.llm_intent_router import _result

    update = _result({}, {"product_name": "invented item"}, 0, "llm", "routing only")
    assert update["matched_product_name"] == ""
    assert update["router_decision"]["product_name"] == "invented item"


def test_router_preserves_title_only_input_for_existing_identity_owner():
    from app.agent.nodes.llm_intent_router import _result
    from app.services.product_context_pack_service import _state_identity, _identity_resolution_signals

    state = {"slots": {"product_name": "customer supplied title"}}
    state.update(_result(state, {"product_name": "model paraphrase"}, 0, "llm", "routing only"))
    signals = _identity_resolution_signals(state, _state_identity(state))
    assert signals["platform_title"] == "customer supplied title"


def _prepared_policy(context, **request_fields):
    from app.services.analysis_pipeline_service import AnalysisPipelineRequest, AnalysisPipelineService

    request = AnalysisPipelineRequest(
        reply_service=object(), customer_message="synthetic question",
        copilot_context=context, **request_fields,
    )
    return AnalysisPipelineService()._prepare_request(request)


def _domain(prepared):
    return prepared.copilot_context["_answer_eligibility_owner_context"]["domain_policy_context"]


def test_exact_hub_policy_reaches_existing_canonical_owner_without_catalog(source, monkeypatch):
    import app.db as db_module
    from app.repositories.file_policy_repository import FilePolicyRepository

    sku, data, calls = source
    monkeypatch.setattr(db_module, "SessionLocal", lambda: pytest.fail("no local catalog access"))
    prepared = _prepared_policy({"sku_code": sku})
    domain = _domain(prepared)
    expected = FilePolicyRepository().build_trusted_domain_policy_context(
        {"catalog_metadata": {"domain_policy_id": "maternal_child_home"}},
        selection_source="verified_server_mapping",
    )
    assert domain == expected and domain["status"] == "selected"
    assert len(calls) == 3 and calls[-1].endswith("/passport")
    assert "domainPolicyId" not in data["product"]  # The real detail API omits it.
    encoded = json.dumps(prepared.copilot_context)
    for excluded in ("private source history", "untrusted source instruction", "hub-product-record"):
        assert excluded not in encoded
    for excluded in ("selected_evidence", "suggested_reply", "can_send", "reply_blocks"):
        assert excluded not in prepared.copilot_context


@pytest.mark.parametrize("field,value", [
    ("id", "other-product"), ("productCode", "other-code"), ("status", "archived"),
    ("domainPolicyId", ""), ("domainPolicyId", None), ("domainPolicyId", {}),
    ("domainPolicyId", ["maternal_child_home"]), ("domainPolicyId", True),
    ("domainPolicyId", "unregistered_pack"), ("domainPolicyId", "../maternal_child_home"),
])
def test_hub_policy_invalid_passport_never_uses_global_or_public_binding(source, monkeypatch, field, value):
    sku, data, calls = source
    data["passport"]["product"][field] = value
    monkeypatch.setenv("COPILOT_DOMAIN_POLICY_ID", "maternal_child_home")
    prepared = _prepared_policy({
        "sku_code": sku, "domainPolicyId": "maternal_child_home",
        "catalog_metadata": {"domain_policy_id": "maternal_child_home"},
        "tenant": {"domain_policy_id": "maternal_child_home"},
        "store": {"domain_policy_id": "maternal_child_home"},
    })
    assert _domain(prepared)["status"] != "selected"
    assert len(calls) == 3


@pytest.mark.parametrize("field,value", [
    ("id", "other-sku-id"), ("skuCode", "other-sku"), ("productId", "other-product"),
    ("status", "archived"),
])
def test_hub_policy_passport_must_bind_same_active_sku(source, field, value):
    sku, data, calls = source
    data["passport"]["skus"][0][field] = value
    assert _domain(_prepared_policy({"sku_code": sku}))["status"] != "selected"
    assert len(calls) == 3


@pytest.mark.parametrize("kind", ["missing", "duplicate", "malformed", "not_ok"])
def test_hub_policy_passport_incomplete_or_ambiguous_fails_closed(source, kind):
    sku, data, _ = source
    if kind == "duplicate":
        data["passport"]["skus"] *= 2
    elif kind == "missing":
        data["passport"]["skus"] = []
    elif kind == "malformed":
        data["passport"]["skus"] = {}
    else:
        data["passport"]["ok"] = False
    assert _domain(_prepared_policy({"sku_code": sku}))["status"] != "selected"


@pytest.mark.parametrize("context,request_fields", [
    ({}, {}),
    ({"sku_code": "item-A 09", "i_id": "other-id"}, {}),
    ({"sku_code": "item-A 09", "slots": {"sku_code": "other-sku"}}, {}),
    ({"sku_code": "item-A 09", "real_context": {"product": {"item_id": "1234567890"}}}, {}),
    ({"sku_code": "item-A 09", "item_id": "1234567890"}, {}),
    ({"sku_code": "item-A 09", "product_title": "other product"}, {}),
    ({"sku_code": "item-A 09", "front_product_title": "other product"}, {}),
    ({"sku_code": "item-A 09", "product_name": "other product"}, {"product_name": "Product A"}),
    ({"sku_code": "item-A 09", "real_context": {"product": {"product_title": "other product"}}}, {"product_name": "Product A"}),
    ({"sku_code": "item-A 09"}, {"order_id": "synthetic-order"}),
    ({"sku_code": "item-A 09"}, {"product_candidates": [{"type": "product_title", "value": "wrong title"}]}),
])
def test_hub_policy_conflicting_or_missing_identity_does_not_read_source(source, monkeypatch, context, request_fields):
    _, _, calls = source
    monkeypatch.setenv("COPILOT_DOMAIN_POLICY_ID", "maternal_child_home")
    assert _domain(_prepared_policy(context, **request_fields))["status"] != "selected"
    assert not calls


@pytest.mark.parametrize("field,value", [
    ("COPILOT_RUNTIME_ENV", "production"), ("COPILOT_FORMAL_KNOWLEDGE_QUERY_ONLY", "false"),
    ("COPILOT_PRODUCT_HUB_REVIEWED_FACTS_ENABLED", "false"),
    ("COPILOT_PRODUCT_HUB_BASE_URL", "https://example.invalid"),
])
def test_hub_policy_candidate_configuration_is_required(source, monkeypatch, field, value):
    sku, _, calls = source
    monkeypatch.setenv(field, value)
    assert _domain(_prepared_policy({"sku_code": sku}))["status"] != "selected"
    assert not calls


def test_hub_policy_rechecks_binding_and_readiness_sku_is_not_current_identity(source, monkeypatch):
    sku, data, calls = source
    monkeypatch.setenv("COPILOT_PRODUCT_HUB_READINESS_SKU", "different-probe-sku")
    assert _domain(_prepared_policy({"sku_code": sku}))["status"] == "selected"
    data["passport"]["product"]["domainPolicyId"] = ""
    assert _domain(_prepared_policy({"sku_code": sku}))["status"] != "selected"
    assert len(calls) == 6


def test_local_source_keeps_existing_selector_and_never_reads_hub(source, monkeypatch):
    monkeypatch.setenv("COPILOT_KNOWLEDGE_SOURCE_MODE", "local")
    monkeypatch.delenv("COPILOT_DOMAIN_POLICY_ID", raising=False)
    assert _domain(_prepared_policy({}))["status"] == "missing"
    assert not source[2]


def _category_pack(source, monkeypatch, **context):
    from app.services import product_context_pack_service as packs

    # The source fixture exercises real identity/passport reads; unrelated facts
    # and media are empty so category cannot acquire evidence authority.
    monkeypatch.setattr(packs, "_load_product_hub_reviewed_facts", lambda *_: {"facts": []})
    monkeypatch.setattr(packs, "_load_product_hub_reviewed_media", lambda *a, **k: {"assets": []})
    return packs.build_product_context_pack(
        {"copilot_context": {"sku_code": source[0], **context}},
        query="ordinary care", query_fact_type="cleaning_care",
    )


def _category_admitted(pack, sku, **kwargs):
    from app.services.admitted_answer_context_service import AdmittedAnswerContextService

    return AdmittedAnswerContextService().build_for_response(
        {"product_context_pack": pack}, product_identity={"sku_code": sku}, **kwargs,
    )


@pytest.mark.parametrize("category", ["Storage furniture", "Outdoor accessories"])
def test_exact_hub_category_reaches_admission_without_local_product(
    source, product_context_db, monkeypatch, category,
):
    source[1]["passport"]["product"]["category"] = category
    pack = _category_pack(source, monkeypatch)
    before = deepcopy(pack)
    admitted = _category_admitted(pack, source[0])
    assert admitted["product_context_capabilities"].get("product_category", {}).get("available") is True
    assert pack["structured_profile"] == {}
    assert pack["facts"] == []
    assert admitted["direct_product_facts"] == []
    assert admitted["can_change_can_send"] is False
    assert pack == before
    encoded = json.dumps(pack)
    for forbidden in (category, "private source history", "untrusted source instruction"):
        assert forbidden not in encoded
    assert sum(url.endswith("/passport") for url in source[2]) == 1


@pytest.mark.parametrize("value", [None, "", " ", {}, [], True, 17, "a" * 257, "a\x00b"])
def test_missing_or_invalid_hub_category_does_not_enable_capability(
    source, product_context_db, monkeypatch, value,
):
    source[1]["passport"]["product"]["category"] = value
    pack = _category_pack(source, monkeypatch, product_category_context={
        "source": "product_hub.agent_passport", "category_available": True,
    }, structured_profile={"source": "kb_product", "category": {"l1": "injected"}})
    assert _category_admitted(pack, source[0])["product_context_capabilities"] == {}


@pytest.mark.parametrize("target,field,value", [
    ("product", "id", "other"), ("product", "productCode", "other"),
    ("product", "status", "archived"), ("sku", "id", "other"),
    ("sku", "skuCode", "other"), ("sku", "productId", "other"),
    ("sku", "status", "archived"),
])
def test_category_requires_same_active_passport_product_and_sku(
    source, product_context_db, monkeypatch, target, field, value,
):
    passport = source[1]["passport"]
    passport["product"]["category"] = "Storage"
    item = passport["product"] if target == "product" else passport["skus"][0]
    item[field] = value
    pack = _category_pack(source, monkeypatch)
    assert _category_admitted(pack, source[0])["product_context_capabilities"] == {}


def test_category_revocation_and_summary_keep_the_same_admission_result(
    source, product_context_db, monkeypatch,
):
    from app.agent.nodes.build_response import _summarize_product_context_pack
    from app.services.admitted_answer_context_service import AdmittedAnswerContextService

    source[1]["passport"]["product"]["category"] = "Storage"
    pack = _category_pack(source, monkeypatch)
    admitted = _category_admitted(pack, source[0])
    summarized = AdmittedAnswerContextService().build_for_response(
        {"evidence_debug": {"product_context_pack_summary": _summarize_product_context_pack(pack)}},
        product_identity={"sku_code": source[0]},
    )
    assert admitted["product_context_capabilities"].get("product_category", {}).get("available") is True
    assert summarized["product_context_capabilities"] == admitted["product_context_capabilities"]
    source[1]["passport"]["product"]["category"] = ""
    changed = _category_pack(source, monkeypatch)
    assert _category_admitted(changed, source[0])["product_context_capabilities"] == {}
    assert sum(url.endswith("/passport") for url in source[2]) == 2


@pytest.mark.parametrize("key", ["sku_code", "product_code", "hub_product_id", "hub_sku_id"])
def test_category_provenance_tampering_or_current_sku_change_is_rejected(
    source, product_context_db, monkeypatch, key,
):
    source[1]["passport"]["product"]["category"] = "Storage"
    pack = _category_pack(source, monkeypatch)
    assert _category_admitted(pack, "other-sku")["product_context_capabilities"] == {}
    assert pack.get("product_category_context")
    pack["product_category_context"]["identity_scope"][key] = "other"
    assert _category_admitted(pack, source[0])["product_context_capabilities"] == {}


@pytest.mark.parametrize("mutation", ["duplicate", "missing", "not_ok", "transport_error"])
def test_category_invalid_passport_is_not_retried_or_guessed(
    source, product_context_db, monkeypatch, mutation,
):
    passport = source[1]["passport"]
    passport["product"]["category"] = "Storage"
    if mutation == "duplicate":
        passport["skus"] *= 2
    elif mutation == "missing":
        passport["skus"] = []
    elif mutation == "not_ok":
        passport["ok"] = False
    else:
        original_read = hub._read_json

        def unavailable(url, **kwargs):
            if url.endswith("/passport"):
                source[2].append(url)
                return None, "unavailable"
            return original_read(url, **kwargs)

        monkeypatch.setattr(hub, "_read_json", unavailable)
    pack = _category_pack(source, monkeypatch)
    assert _category_admitted(pack, source[0])["product_context_capabilities"] == {}
    assert sum(url.endswith("/passport") for url in source[2]) == 1


@pytest.mark.parametrize("field,value", [
    ("COPILOT_KNOWLEDGE_SOURCE_MODE", "local"),
    ("COPILOT_RUNTIME_ENV", "production"),
    ("COPILOT_FORMAL_KNOWLEDGE_QUERY_ONLY", "false"),
    ("COPILOT_PRODUCT_HUB_REVIEWED_FACTS_ENABLED", "false"),
    ("COPILOT_PRODUCT_HUB_BASE_URL", "https://example.invalid"),
])
def test_category_projection_off_has_no_transport(source, monkeypatch, field, value):
    identity = ProductIdentityResolver().resolve(sku_id=source[0])
    source[2].clear()
    monkeypatch.setenv(field, value)
    assert hub.ProductHubReviewedFactsClient().fetch_product_category_context(identity) == {}
    assert source[2] == []


@pytest.mark.parametrize("same_sku", [True, False])
def test_category_identity_is_compared_before_lossy_privacy_projection(
    source, product_context_db, monkeypatch, same_sku,
):
    source[1]["passport"]["product"]["category"] = "Storage"
    pack = _category_pack(source, monkeypatch)
    # Fictional numeric natural keys collide under the content phone redactor.
    bound_sku = "SKU-" + "138" + "0" * 8
    current_sku = bound_sku if same_sku else "SKU-" + "139" + "0" * 8
    pack["identity"]["sku"] = bound_sku
    pack["identity"]["product_identity_resolution"]["sku_code"] = bound_sku
    pack["product_category_context"]["identity_scope"]["sku_code"] = bound_sku
    pack["evidence_pack"]["identity"]["sku"] = bound_sku
    result = _category_admitted(pack, current_sku)["product_context_capabilities"]
    assert bool(result.get("product_category", {}).get("available")) is same_sku


@pytest.mark.parametrize("mutation", [
    "none", "missing_premise", "unreviewed", "wrong_identity", "reference_only",
    "media_reference", "service_action", "blocked", "conflicting", "missing_policy",
])
def test_hub_category_does_not_replace_premise_or_policy_in_composer_input(
    source, product_context_db, monkeypatch, mutation,
):
    import socket
    from app.services.admitted_answer_context_service import (
        AdmittedAnswerContextService, build_minimal_decision_context,
    )
    from app.services.model_first_answer_composer_service import ModelFirstAnswerComposerService
    from app.repositories.file_policy_repository import FilePolicyRepository
    from app.agent.nodes.query_fact_type_classifier import _turn_understanding_from_result
    from test_domain_policy_canonical_claim_types import _loaded_pack, _daily_care_policy, _material_care_goals

    monkeypatch.setattr(socket.socket, "connect", lambda *a, **k: pytest.fail("network forbidden"))
    source[1]["passport"]["product"]["category"] = "Storage"
    pack = _category_pack(source, monkeypatch)
    policy = _loaded_pack()
    question = "composition request; ordinary care request"
    understanding = _turn_understanding_from_result(
        {"customer_message": question},
        {"customer_goals": _material_care_goals(_daily_care_policy(policy)),
         "goal_understanding_status": "valid"},
    )
    fact = {
        "evidence_uid": "material-direct", "source_type": "product_facts",
        "evidence_role": "product_fact_direct", "fact_type": "material_composition",
        "attribute_key": "material", "content": "PP", "value": "PP", "sku_code": source[0],
        "material_provenance": "structured_product_record", "fact_review_status": "verified",
        "gate_status": "allowed", "direct_answer_allowed": True,
    }
    if mutation == "unreviewed":
        fact["fact_review_status"] = "draft"
    elif mutation == "wrong_identity":
        fact["sku_code"] = "another-sku"
    elif mutation in {"reference_only", "media_reference", "service_action"}:
        fact["evidence_role"] = mutation
    elif mutation == "blocked":
        fact["gate_status"] = "blocked"
    facts = [] if mutation == "missing_premise" else [fact]
    if mutation == "conflicting":
        facts.append({**fact, "evidence_uid": "conflict", "content": "PE", "value": "PE"})
    response = {"product_context_pack": pack, "selected_evidence": facts,
                "can_send": False, "requires_human_review": True}
    trusted = FilePolicyRepository().build_trusted_domain_policy_context(
        {"catalog_metadata": {"domain_policy_id": "maternal_child_home"}},
        selection_source="evaluation_fixture",
    )
    admitted = AdmittedAnswerContextService().build_for_response(
        response, product_identity={"sku_code": source[0]}, understanding=understanding,
        current_customer_message=question,
        answer_eligibility_inputs={} if mutation == "missing_policy" else {
            "domain_policy_pack": policy, "trusted_domain_policy_context": trusted,
        },
    )
    material, care = admitted["claim_resolutions"]
    assert admitted["product_context_capabilities"]["product_category"]["available"] is True
    assert care["status"] == "unresolved" and care["evidence_uids"] == []
    if mutation != "none":
        assert care["eligible_policy_options"] == []
        return
    assert material["status"] == "supported"
    assert len(care["eligible_policy_options"]) == 1
    option = care["eligible_policy_options"][0]
    assert option["premise_evidence_refs"] == ["material-direct"]
    assert option["review_only"] is True and option["can_change_can_send"] is False
    response["admitted_answer_context"] = admitted
    response["minimal_decision_context"] = build_minimal_decision_context(admitted, customer_message=question)
    decision, error = ModelFirstAnswerComposerService().build_composer_decision_input(
        response, customer_message=question,
    )
    assert not error and decision
    assert response["can_send"] is False and response["requires_human_review"] is True
    encoded = json.dumps(response["minimal_decision_context"])
    assert "Storage" not in encoded and "hub-product-record" not in encoded
