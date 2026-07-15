from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

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
    ):
        metric = report["metrics"][name]
        assert metric["numerator"] == metric["denominator"]
    assert report["metrics"]["can_send_change_count"] == 0
    assert report["metrics"]["formal_reply_mutation_count"] == 0


def test_fixture_expected_contract_is_not_available_to_preview_builder(monkeypatch):
    fixture_path = Path("tests/fixtures/supervisor_partial_answer_preview/v1.json")
    dataset = json.loads(fixture_path.read_text(encoding="utf-8"))
    original = deepcopy(dataset["scenarios"][0])
    original["expected"] = {"statuses": ["conflicting"]}
    report = evaluate({**dataset, "scenarios": [original]})

    assert report["rows"][0]["actual_statuses"] == ["supported"]
    assert report["failed"] == 1
