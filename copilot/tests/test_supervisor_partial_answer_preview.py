from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest

from app.services.agent_decision_proposal_service import build_supervisor_partial_answer_preview
from scripts.run_supervisor_partial_answer_preview_eval import evaluate


def _context(*, resolutions, facts):
    return {
        "customer_goal": "Please confirm the requested details.",
        "requested_claims": [{"claim_type": item["claim_type"]} for item in resolutions],
        "admitted_evidence": facts,
        "claim_resolutions": resolutions,
        "context_stats": {"admitted_evidence_count": len(facts)},
    }


def _resolution(uid, claim_type, status, evidence_uids=(), conflicts=()):
    return {
        "claim_uid": uid,
        "claim_type": claim_type,
        "status": status,
        "evidence_uids": list(evidence_uids),
        "conflicting_evidence_uids": list(conflicts),
        "reason": "admitted_direct_evidence" if status == "supported" else f"{status}_evidence",
    }


def test_preview_renders_all_supported_facts_and_keeps_unresolved_separate():
    context = _context(
        facts=[
            {"evidence_uid": "width", "content": "Width is 80cm."},
            {"evidence_uid": "height", "content": "Height is 120cm."},
        ],
        resolutions=[
            _resolution("claim-width", "dimensions", "supported", ["width"]),
            _resolution("claim-height", "dimensions", "supported", ["height"]),
            _resolution("claim-moisture", "moisture_resistance", "unresolved"),
        ],
    )

    preview = build_supervisor_partial_answer_preview(context)

    assert {item["claim_uid"] for item in preview["confirmed_clauses"]} == {"claim-width", "claim-height"}
    assert [item["claim_uid"] for item in preview["pending_clauses"]] == ["claim-moisture"]
    assert "Width is 80cm." in preview["candidate_text"]
    assert "Height is 120cm." in preview["candidate_text"]
    assert preview["evidence_uids"] == ["height", "width"]
    assert preview["can_send"] is False
    assert preview["requires_human_review"] is True
    assert preview["used_for_final_reply"] is False


def test_preview_is_order_independent_and_excludes_non_facts():
    facts = [
        {"evidence_uid": "material", "content": "The main material is PP."},
        {"evidence_uid": "action", "content": "service action", "non_fact": True},
    ]
    resolutions = [_resolution("claim-material", "material_composition", "supported", ["material"])]
    first = build_supervisor_partial_answer_preview(_context(facts=facts, resolutions=resolutions))
    second = build_supervisor_partial_answer_preview(_context(facts=list(reversed(facts)), resolutions=list(reversed(resolutions))))

    assert first["confirmed_clauses"] == second["confirmed_clauses"]
    assert first["candidate_text"] == second["candidate_text"]
    assert "service action" not in first["candidate_text"]


def test_conflicting_and_unrenderable_supported_claims_fail_closed_to_pending():
    context = _context(
        facts=[{"evidence_uid": "blocked-text", "content": "RAG evidence detail"}],
        resolutions=[
            _resolution("claim-material", "material_composition", "supported", ["blocked-text"]),
            _resolution("claim-load", "load_capacity", "conflicting", conflicts=["load-a", "load-b"]),
        ],
    )

    preview = build_supervisor_partial_answer_preview(context)

    assert preview["confirmed_clauses"] == []
    assert preview["pending_clauses"][0]["claim_uid"] == "claim-material"
    assert preview["conflicting_clauses"][0]["evidence_uids"] == ["load-a", "load-b"]
    assert "RAG" not in preview["candidate_text"]


def test_answer_memory_or_media_cannot_render_as_a_factual_clause():
    context = _context(
        facts=[
            {"evidence_uid": "memory", "content": "The material is PP.", "evidence_role": "answer_memory"},
            {"evidence_uid": "media", "content": "Installation video", "evidence_role": "media_reference"},
        ],
        resolutions=[
            _resolution("claim-material", "material_composition", "supported", ["memory"]),
            _resolution("claim-install", "installation_media", "supported", ["media"]),
        ],
    )

    preview = build_supervisor_partial_answer_preview(context)

    assert preview["confirmed_clauses"] == []
    assert {item["claim_uid"] for item in preview["pending_clauses"]} == {"claim-material", "claim-install"}
    assert "The material is PP." not in preview["candidate_text"]
    assert "Installation video" not in preview["candidate_text"]


def test_fixture_evaluator_has_complete_contract_coverage():
    fixture_path = Path("tests/fixtures/supervisor_partial_answer_preview/v1.json")
    report = evaluate(json.loads(fixture_path.read_text(encoding="utf-8")))

    assert report["total"] == 14
    assert report["failed"] == 0
    for name in (
        "claim_resolution_accuracy",
        "supported_claim_coverage",
        "unresolved_claim_retention",
        "conflicting_claim_retention",
        "evidence_citation_rate",
        "deterministic_order_stability",
    ):
        metric = report["metrics"][name]
        assert metric["numerator"] == metric["denominator"]
    assert report["metrics"]["can_send_change_count"] == 0
    assert report["metrics"]["formal_reply_mutation_count"] == 0
    assert report["metrics"]["unsupported_claim_count"] == 0
    assert report["metrics"]["identity_leakage_count"] == 0
    assert report["metrics"]["media_promise_violation_count"] == 0
    assert report["metrics"]["mojibake_count"] == 0


def test_fixture_has_no_precomputed_resolution_and_expected_is_not_available_to_builder():
    fixture_path = Path("tests/fixtures/supervisor_partial_answer_preview/v1.json")
    dataset = json.loads(fixture_path.read_text(encoding="utf-8"))
    original = deepcopy(dataset["scenarios"][0])
    assert "claim_resolutions" not in original["raw_context"]
    original["expected"] = {"claims": [{"claim_type": "material_composition", "attribute_key": "", "status": "conflicting", "evidence_uids": []}]}
    report = evaluate({**dataset, "scenarios": [original]})

    assert report["rows"][0]["preview"]["claim_resolutions"][0]["status"] == "supported"
    assert report["failed"] == 1


@pytest.mark.parametrize(
    "mutator",
    [
        lambda preview: {**preview, "confirmed_clauses": []},
        lambda preview: {**preview, "conflicting_clauses": []},
        lambda preview: {**preview, "candidate_text": preview["candidate_text"] + " It is waterproof."},
        lambda preview: {**preview, "candidate_text": preview["candidate_text"] + " SKU-ANON"},
        lambda preview: {**preview, "candidate_text": preview["candidate_text"] + " 下面发视频给您。"},
        lambda preview: {**preview, "candidate_text": preview["candidate_text"] + " 锛"},
        lambda preview: {**preview, "can_send": True},
        lambda preview: {**preview, "used_for_final_reply": True},
    ],
)
def test_evaluator_mutations_fail_the_scenario(mutator):
    fixture_path = Path("tests/fixtures/supervisor_partial_answer_preview/v1.json")
    dataset = json.loads(fixture_path.read_text(encoding="utf-8"))
    target = next(item for item in dataset["scenarios"] if item["scenario_uid"] == "supported_conflicting")

    report = evaluate({**dataset, "scenarios": [target]}, preview_mutator=mutator)

    assert report["failed"] == 1


def test_evaluator_rejects_unknown_evidence_uid_and_order_mutation():
    fixture_path = Path("tests/fixtures/supervisor_partial_answer_preview/v1.json")
    dataset = json.loads(fixture_path.read_text(encoding="utf-8"))
    target = next(item for item in dataset["scenarios"] if item["scenario_uid"] == "single_supported")

    def unknown_uid(preview):
        preview["confirmed_clauses"][0]["evidence_uids"] = ["unknown-evidence"]
        preview["evidence_uids"] = ["unknown-evidence"]
        return preview

    report = evaluate({**dataset, "scenarios": [target]}, preview_mutator=unknown_uid)

    assert report["failed"] == 1
    assert report["metrics"]["deterministic_order_stability"]["numerator"] == 0


def test_evaluator_rejects_an_unresolved_claim_promoted_to_supported():
    fixture_path = Path("tests/fixtures/supervisor_partial_answer_preview/v1.json")
    dataset = json.loads(fixture_path.read_text(encoding="utf-8"))
    target = next(item for item in dataset["scenarios"] if item["scenario_uid"] == "all_unresolved")

    def promote(preview):
        preview["claim_resolutions"][0]["status"] = "supported"
        return preview

    report = evaluate({**dataset, "scenarios": [target]}, preview_mutator=promote)

    assert report["failed"] == 1


def test_safety_validation_fails_closed_for_audit_failure(monkeypatch):
    context = _context(
        facts=[{"evidence_uid": "material", "content": "The main material is PP."}],
        resolutions=[_resolution("claim-material", "material_composition", "supported", ["material"])],
    )
    from app.services import final_answer_auditor

    monkeypatch.setattr(final_answer_auditor, "audit_final_answer", lambda response, **_: {**response, "final_answer_audit": {"passed": False}})

    preview = build_supervisor_partial_answer_preview(context)

    assert preview["safety_validation"]["passed"] is False
    assert "final_answer_audit_failed" in preview["safety_validation"]["issues"]


def test_safety_validation_fails_closed_for_semantic_error_and_exception(monkeypatch):
    context = _context(
        facts=[{"evidence_uid": "material", "content": "The main material is PP."}],
        resolutions=[_resolution("claim-material", "material_composition", "supported", ["material"])],
    )
    from app.services import final_semantic_quality_service

    monkeypatch.setattr(final_semantic_quality_service, "audit_customer_reply_semantic_fit", lambda *_args, **_kwargs: {"passed": False})
    preview = build_supervisor_partial_answer_preview(context)
    assert "semantic_fit_failed" in preview["safety_validation"]["issues"]

    def raise_error(*_args, **_kwargs):
        raise RuntimeError("test failure")

    monkeypatch.setattr(final_semantic_quality_service, "audit_customer_reply_semantic_fit", raise_error)
    preview = build_supervisor_partial_answer_preview(context)
    assert preview["safety_validation"]["passed"] is False
    assert "safety_diagnostic_error" in preview["safety_validation"]["issues"]
