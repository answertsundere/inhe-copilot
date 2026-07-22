from __future__ import annotations

import copy
import sqlite3

import app.services.long_conversation_simulation_service as service
import scripts.build_fixed_long_conversation_replay_set as builder
from scripts.compare_fixed_long_conversation_replay import compare_reports
from scripts.run_fixed_long_conversation_replay import (
    _formal_knowledge_fingerprint,
    _layer_gate,
    _runtime_contract,
)


def _fixed_dataset() -> dict:
    dataset = {
        "schema_version": service.FIXED_REPLAY_SCHEMA_VERSION,
        "manifest": {
            "scenario_count": 1,
            "fixed_buyer_turn_count": 2,
            "privacy_scan_status": "passed",
        },
        "scenarios": [{
            "scenario_uid": "scenario-safe",
            "fixed_buyer_turns": [
                {"turn_uid": "turn-a", "speaker_role": "BUYER", "message_type": "text", "text": "请问材质是什么"},
                {"turn_uid": "turn-b", "speaker_role": "BUYER", "message_type": "text", "text": "那尺寸呢"},
            ],
        }],
    }
    payload = copy.deepcopy(dataset)
    dataset["manifest"]["content_sha256"] = service._content_hash(payload)
    return dataset


def _response(*, reply: str = "当前已审核资料显示材质为 PP。") -> dict:
    fact = {
        "evidence_uid": "fact-material",
        "evidence_role": "product_fact_direct",
        "source_type": "product_facts",
        "fact_type": "material_composition",
        "attribute_key": "material",
        "content": "主体材质为 PP。",
        "material_provenance": "structured_product_record",
        "sku_code": "SKU-A",
        "fact_review_status": "verified",
        "gate_status": "allowed",
        "direct_answer_allowed": True,
    }
    return {
        "suggested_reply": reply,
        "can_send": False,
        "requires_human_review": True,
        "reply_status": "needs_human_review",
        "reply_blocks": [{"type": "text", "content": reply}],
        "selected_evidence": [fact],
        "formal_evidence_candidates": [fact],
        "analysis_pipeline": {"version": "v1"},
        "final_answer_audit": {"passed": True, "issues": []},
        "final_semantic_fit_audit": {"passed": True, "issues": []},
        "evidence_debug": {
            "query_fact_type": "material_composition",
            "conversation_context_status": "valid",
            "admitted_answer_context": {
                "requested_claims": [{"claim_type": "material_composition"}],
                "direct_product_facts": [fact],
                "direct_policy_facts": [],
                "rejected_evidence": [],
                "claim_resolutions": [{"status": "supported"}],
            },
        },
    }


def test_fixed_dataset_validator_rejects_tamper_and_non_buyer_turn():
    dataset = _fixed_dataset()
    assert service.validate_fixed_long_conversation_dataset(dataset) == []
    tampered = copy.deepcopy(dataset)
    tampered["scenarios"][0]["fixed_buyer_turns"][0]["speaker_role"] = "AGENT"
    assert "fixed_buyer_turn_invalid" in service.validate_fixed_long_conversation_dataset(tampered)
    assert "content_sha256_mismatch" in service.validate_fixed_long_conversation_dataset(tampered)


def test_fixed_builder_uses_real_buyer_turns_and_excludes_future_agent_replies(monkeypatch):
    turns = [
        {"speaker_role": "BUYER", "message_type": "text", "text": "问题一"},
        {"speaker_role": "AGENT", "message_type": "text", "text": "旧客服回复一"},
        {"speaker_role": "BUYER", "message_type": "text", "text": "问题二"},
        {"speaker_role": "AGENT", "message_type": "text", "text": "旧客服回复二"},
        {"speaker_role": "BUYER", "message_type": "text", "text": "问题三"},
    ]
    digest = service.conversation_content_digest(turns)
    source = {"id": 1}
    scenario = {
        "scenario_uid": "scenario-safe",
        "source_conversation_digest": digest,
        "source_case_uid": "case-safe",
        "scenario_domains": ["product_fact"],
        "query_fact_types": ["material_composition"],
        "risk_levels": ["medium"],
        "sidecar_present": True,
        "sidecar_quality": "identity_present",
    }
    monkeypatch.setattr(builder, "_resolve_sources", lambda *_args: ({"scenario-safe": source}, 0, 0))
    monkeypatch.setattr(builder, "build_gold_dataset", lambda *_args: ({"cases": [{"conversation": {"turns": turns}}]}, {}))

    dataset = builder.build_fixed_replay_set({"scenarios": [scenario]}, [source], fixed_buyer_turn_count=2)

    fixed = dataset["scenarios"][0]
    assert [turn["text"] for turn in fixed["fixed_buyer_turns"]] == ["问题二", "问题三"]
    assert all(turn["speaker_role"] == "BUYER" for turn in fixed["fixed_buyer_turns"])
    assert fixed["future_agent_replies_included"] is False
    assert fixed["gold_labels_included"] is False


def test_turn_observation_is_the_single_report_safe_evidence_view():
    observation = service.build_fixed_replay_turn_observation(
        _response(),
        product_identity={"sku_code": "SKU-A"},
        sidecar_present=True,
        sidecar_quality="identity_present",
        convergence_enabled=True,
        latency_ms=100.0,
        status_code=200,
    )
    assert observation["selected_evidence_count"] == 1
    assert observation["admitted_evidence_count"] == 1
    assert observation["evidence_funnel"]["contains_evidence_text"] is False
    assert "SKU-A" not in str(observation["evidence_funnel"])
    assert service.classify_fixed_replay_breakpoint(observation) == "correct_safe_handoff"


def test_off_observation_reuses_shared_admission_when_shadow_context_is_absent():
    response = _response()
    response["evidence_debug"].pop("admitted_answer_context")
    observation = service.build_fixed_replay_turn_observation(
        response,
        product_identity={"sku_code": "SKU-A"},
        sidecar_present=True,
        sidecar_quality="identity_present",
        convergence_enabled=False,
        latency_ms=100.0,
        status_code=200,
    )
    assert observation["candidate_evidence_count"] == 1
    assert observation["admitted_evidence_count"] == 1
    assert observation["evidence_funnel"]["earliest_breakpoint"] == "selected_successfully"


def test_summary_recomputes_media_safety_and_repetition_from_observations():
    first = service.build_fixed_replay_turn_observation(
        _response(reply="我给您发安装视频。"),
        product_identity={"sku_code": "SKU-A"},
        sidecar_present=True,
        sidecar_quality="identity_present",
        convergence_enabled=False,
        latency_ms=100.0,
        status_code=200,
    )
    second = copy.deepcopy(first)
    second["repeated_from_previous"] = True
    summary = service.summarize_fixed_replay_results([{"turns": [{"observation": first}, {"observation": second}]}])
    assert summary["unsupported_media_promise_count"] == 2
    assert summary["consecutive_reply_repetition_rate"] == {"numerator": 1, "denominator": 1, "rate": 1.0}
    assert _layer_gate(summary, knowledge_db_changed=False)["passed"] is False


def test_media_role_mismatch_in_either_audit_fails_layer_gate():
    observation = service.build_fixed_replay_turn_observation(
        _response(),
        product_identity={"sku_code": "SKU-A"},
        sidecar_present=True,
        sidecar_quality="identity_present",
        convergence_enabled=True,
        latency_ms=100.0,
        status_code=200,
    )
    observation["final_semantic_fit_audit"] = {
        "passed": False,
        "issues": ["unsupported_media_claim"],
    }
    summary = service.summarize_fixed_replay_results([{"turns": [{"observation": observation}]}])
    assert summary["media_role_mismatch_count"] == 1
    assert _layer_gate(summary, knowledge_db_changed=False) == {
        "passed": False,
        "blockers": ["media_role_mismatch"],
    }


def test_runtime_contract_requires_exact_mode_and_pinned_identity():
    runtime = {
        "status": "available",
        "runtime_commit": "commit-a",
        "source_tree_sha256": "hash-a",
        "source_tree_drift": False,
        "formal_model": "Model-A",
        "feature_flags": {"formal_evidence_convergence": False},
        "readiness": {"ready": True},
    }
    assert _runtime_contract(
        runtime,
        run_mode="OFF",
        expected_commit="commit-a",
        expected_source_hash="hash-a",
        expected_model="Model-A",
    ) == []
    assert "formal_evidence_convergence_mode_mismatch" in _runtime_contract(
        runtime,
        run_mode="ON",
        expected_commit="commit-a",
        expected_source_hash="hash-a",
        expected_model="Model-A",
    )


def test_formal_knowledge_fingerprint_ignores_runtime_tables_but_detects_fact_changes(tmp_path):
    database = tmp_path / "knowledge.db"
    connection = sqlite3.connect(database)
    for table in ("kb_product", "kb_qa", "knowledge_entries", "knowledge_chunks"):
        connection.execute(f'CREATE TABLE "{table}" (id INTEGER PRIMARY KEY, content TEXT)')
        connection.execute(f'INSERT INTO "{table}" (content) VALUES (?)', (f"{table}-fact",))
    connection.execute("CREATE TABLE eval_traces (id INTEGER PRIMARY KEY, payload TEXT)")
    connection.commit()
    before = _formal_knowledge_fingerprint(database)
    connection.execute("INSERT INTO eval_traces (payload) VALUES ('runtime-only')")
    connection.commit()
    assert _formal_knowledge_fingerprint(database) == before
    connection.execute("UPDATE kb_product SET content='changed-fact' WHERE id=1")
    connection.commit()
    connection.close()
    assert _formal_knowledge_fingerprint(database) != before


def test_paired_comparison_fails_on_unsafe_on_regression():
    base = {
        "dataset": {"content_sha256": "a", "scenario_count": 1, "fixed_buyer_turn_count": 1},
        "runtime": {"runtime_commit": "c", "source_tree_sha256": "s", "formal_model": "m"},
        "formal_knowledge_database_before": {"formal_content_sha256": "k", "formal_tables": []},
        "results": [{"scenario_uid": "x", "turns": [{"turn_index": 1, "observation": {}}]}],
        "summary": {"unsafe_auto_send_count": 0},
    }
    off = {**copy.deepcopy(base), "run_mode": "OFF"}
    on = {**copy.deepcopy(base), "run_mode": "ON"}
    on["results"][0]["turns"][0]["observation"] = {
        "can_send": True,
        "unresolved_claim_count": 1,
        "status_code": 200,
        "reply": "答复",
    }
    comparison = compare_reports(off, on)
    assert comparison["comparison_valid"] is False
    assert "on_unsafe_auto_send_regression" in comparison["contract_findings"]
