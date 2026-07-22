"""Run fixed real buyer turns against one pinned formal Agent runtime."""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import subprocess
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from app.services.long_conversation_simulation_service import (  # noqa: E402
    build_fixed_replay_turn_observation,
    classify_fixed_replay_breakpoint,
    conversation_content_digest,
    summarize_fixed_replay_results,
    validate_fixed_long_conversation_dataset,
)
from app.services.real_accuracy_gold_set_service import (  # noqa: E402
    build_gold_dataset,
    hmac_identifier,
    load_reviewed_training_samples,
)
from app.services.real_accuracy_privacy_service import sanitize_gold_text  # noqa: E402
from scripts.run_long_conversation_simulation import (  # noqa: E402
    _agent_payload,
    _post_agent,
    _report_runtime,
    _runtime_metadata,
    _source_db_fingerprint,
    _write_json_atomic,
)


REPORT_SCHEMA_VERSION = "fixed-long-conversation-replay-report/v1"
CHECKPOINT_SCHEMA_VERSION = "fixed-long-conversation-replay-checkpoint/v1"
_RUNNER_SOURCE_FILES = (
    "scripts/run_fixed_long_conversation_replay.py",
    "app/services/long_conversation_simulation_service.py",
    "app/services/canonical_conversation_turn_service.py",
    "app/services/real_accuracy_privacy_service.py",
    "app/services/admitted_answer_context_service.py",
)
_FORMAL_KNOWLEDGE_TABLES = (
    "kb_product",
    "kb_qa",
    "knowledge_entries",
    "knowledge_chunks",
)


def _canonical_hash(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _formal_knowledge_fingerprint(path: Path) -> dict[str, Any]:
    """Hash formal knowledge rows without treating runtime-table writes as KB writes."""
    connection = sqlite3.connect(f"file:{path.resolve().as_posix()}?mode=ro", uri=True)
    connection.execute("PRAGMA query_only=ON")
    table_fingerprints: list[dict[str, Any]] = []
    composite = hashlib.sha256()
    try:
        for table in _FORMAL_KNOWLEDGE_TABLES:
            exists = connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                (table,),
            ).fetchone()
            if not exists:
                table_fingerprints.append({"table": table, "exists": False, "row_count": 0, "content_sha256": ""})
                composite.update(f"{table}:missing\n".encode("utf-8"))
                continue
            columns = [str(row[1]) for row in connection.execute(f'PRAGMA table_info("{table}")')]
            table_hash = hashlib.sha256()
            row_count = 0
            for row in connection.execute(f'SELECT * FROM "{table}" ORDER BY rowid'):
                row_count += 1
                for value in row:
                    if value is None:
                        payload = b"N"
                    elif isinstance(value, bytes):
                        payload = b"B" + value
                    else:
                        payload = f"{type(value).__name__}:{value}".encode("utf-8")
                    table_hash.update(str(len(payload)).encode("ascii"))
                    table_hash.update(b":")
                    table_hash.update(payload)
                    table_hash.update(b"\0")
                table_hash.update(b"\n")
            content_sha256 = table_hash.hexdigest()
            schema_sha256 = hashlib.sha256("|".join(columns).encode("utf-8")).hexdigest()
            table_fingerprints.append({
                "table": table,
                "exists": True,
                "row_count": row_count,
                "schema_sha256": schema_sha256,
                "content_sha256": content_sha256,
            })
            composite.update(f"{table}:{row_count}:{schema_sha256}:{content_sha256}\n".encode("utf-8"))
    finally:
        connection.close()
    return {
        "basename": path.name,
        "formal_tables": table_fingerprints,
        "formal_content_sha256": composite.hexdigest(),
    }


def _runner_source_hash() -> str:
    digest = hashlib.sha256()
    for relative in _RUNNER_SOURCE_FILES:
        path = PROJECT_ROOT / relative
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def _git_text(*args: str) -> str:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=PROJECT_ROOT,
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
    except (OSError, subprocess.CalledProcessError):
        return ""
    return result.stdout.strip()


def _resolve_sources_by_conversation_digest(
    scenarios: list[dict[str, Any]],
    samples: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    ephemeral_key = "fixed-replay-ephemeral-source-key"
    rebuilt, _ = build_gold_dataset(ephemeral_key, samples)
    sources_by_case_uid = {
        hmac_identifier(ephemeral_key, "training_sample", source.get("id")): source
        for source in samples
    }
    by_digest: dict[str, list[dict[str, Any]]] = {}
    for case in rebuilt.get("cases") or []:
        source = sources_by_case_uid.get(str(case.get("case_uid") or ""))
        if source is None:
            continue
        turns = list(((case.get("conversation") or {}).get("turns") or []))
        by_digest.setdefault(conversation_content_digest(turns), []).append(source)
    resolved: dict[str, dict[str, Any]] = {}
    for scenario in scenarios:
        matches = by_digest.get(str(scenario.get("source_conversation_digest") or ""), [])
        if len(matches) != 1:
            raise ValueError("fixed_replay_source_not_unique")
        resolved[str(scenario["scenario_uid"])] = matches[0]
    return resolved


def _runtime_contract(
    runtime: dict[str, Any],
    *,
    run_mode: str,
    expected_commit: str,
    expected_source_hash: str,
    expected_model: str,
) -> list[str]:
    findings: list[str] = []
    flags = runtime.get("feature_flags") if isinstance(runtime.get("feature_flags"), dict) else {}
    expected_enabled = run_mode == "ON"
    if runtime.get("status") != "available" or (runtime.get("readiness") or {}).get("ready") is not True:
        findings.append("runtime_not_ready")
    if expected_commit and runtime.get("runtime_commit") != expected_commit:
        findings.append("runtime_commit_mismatch")
    if expected_source_hash and runtime.get("source_tree_sha256") != expected_source_hash:
        findings.append("runtime_source_hash_mismatch")
    if expected_model and runtime.get("formal_model") != expected_model:
        findings.append("formal_model_mismatch")
    if runtime.get("source_tree_drift") is not False:
        findings.append("runtime_source_tree_drift")
    if bool(flags.get("formal_evidence_convergence")) is not expected_enabled:
        findings.append("formal_evidence_convergence_mode_mismatch")
    return findings


def _layer_gate(summary: dict[str, Any], *, knowledge_db_changed: bool) -> dict[str, Any]:
    blockers: list[str] = []
    if int(summary.get("error_count") or 0):
        blockers.append("execution_error")
    if int(summary.get("empty_reply_count") or 0):
        blockers.append("empty_reply")
    if int(summary.get("timeout_count") or 0):
        blockers.append("timeout")
    if int(summary.get("unsupported_media_promise_count") or 0):
        blockers.append("unsupported_media_promise")
    if int(summary.get("media_role_mismatch_count") or 0):
        blockers.append("media_role_mismatch")
    if int(summary.get("unsafe_auto_send_count") or 0):
        blockers.append("unsafe_auto_send")
    if knowledge_db_changed:
        blockers.append("knowledge_database_changed")
    return {"passed": not blockers, "blockers": sorted(set(blockers))}


def run(args: argparse.Namespace) -> tuple[dict[str, Any], int]:
    dataset_path = Path(args.dataset)
    source_db_path = Path(args.source_db)
    knowledge_db_path = Path(args.knowledge_db)
    dataset = json.loads(dataset_path.read_text(encoding="utf-8"))
    dataset_findings = validate_fixed_long_conversation_dataset(dataset)
    if dataset_findings:
        raise ValueError(f"fixed_replay_dataset_invalid:{','.join(dataset_findings)}")

    run_mode = str(args.run_mode).upper()
    if run_mode not in {"OFF", "ON"}:
        raise ValueError("run_mode_invalid")
    runner_boot_hash = _runner_source_hash()
    if args.expected_runner_source_sha256 and runner_boot_hash != args.expected_runner_source_sha256:
        raise ValueError("runner_source_hash_mismatch")

    runtime_raw = _runtime_metadata(args.analyze_url, args.agent_timeout)
    runtime_findings = _runtime_contract(
        runtime_raw,
        run_mode=run_mode,
        expected_commit=args.expected_api_commit,
        expected_source_hash=args.expected_source_tree_sha256,
        expected_model=args.expected_formal_model,
    )
    if runtime_findings:
        raise ValueError(f"runtime_contract_failed:{','.join(runtime_findings)}")
    runtime = _report_runtime(runtime_raw)

    samples = load_reviewed_training_samples(source_db_path)
    scenarios = list(dataset.get("scenarios") or [])[: max(1, int(args.limit))]
    sources = _resolve_sources_by_conversation_digest(scenarios, samples)
    knowledge_before = _formal_knowledge_fingerprint(knowledge_db_path)
    results: list[dict[str, Any]] = []
    checkpoint_path = Path(args.checkpoint)

    for scenario in scenarios:
        scenario_uid = str(scenario["scenario_uid"])
        source = sources[scenario_uid]
        transcript = list(scenario.get("seed_history") or [])
        turns: list[dict[str, Any]] = []
        previous_reply = ""
        for turn_number, buyer_turn in enumerate(scenario.get("fixed_buyer_turns") or [], start=1):
            buyer_message = sanitize_gold_text(buyer_turn.get("text"))
            payload = _agent_payload(source, scenario, 1, buyer_message, transcript)
            status_code, response, latency_ms, error_type = _post_agent(
                args.analyze_url,
                payload,
                args.agent_timeout,
            )
            observation = build_fixed_replay_turn_observation(
                response,
                product_identity={
                    "sku_code": str(source.get("sku") or "").strip(),
                    "i_id": str(source.get("i_id") or "").strip(),
                    "product_id": str(source.get("product_id") or "").strip(),
                },
                sidecar_present=bool(scenario.get("sidecar_present")),
                sidecar_quality=str(scenario.get("sidecar_quality") or "unknown"),
                convergence_enabled=run_mode == "ON",
                latency_ms=latency_ms,
                status_code=status_code,
                error_type=error_type,
                previous_reply=previous_reply,
            )
            observation.update({
                "scenario_uid": scenario_uid,
                "run_mode": run_mode,
                "turn_index": turn_number,
            })
            observation["earliest_breakpoint"] = classify_fixed_replay_breakpoint(observation)
            turns.append({
                "turn_index": turn_number,
                "buyer_turn_uid": str(buyer_turn.get("turn_uid") or ""),
                "buyer_message": buyer_message,
                "observation": observation,
            })
            reply = str(observation.get("reply") or "")
            transcript.extend([
                {
                    "speaker_role": "BUYER",
                    "message_type": "text",
                    "text": buyer_message,
                    "turn_uid": str(buyer_turn.get("turn_uid") or ""),
                },
                {
                    "speaker_role": "AGENT",
                    "message_type": "text",
                    "text": reply,
                    "turn_uid": f"agent_{scenario_uid}_{turn_number}",
                },
            ])
            previous_reply = reply
        results.append({
            "scenario_uid": scenario_uid,
            "primary_domain": str(scenario.get("primary_domain") or ""),
            "turns": turns,
        })
        _write_json_atomic(checkpoint_path, {
            "schema_version": CHECKPOINT_SCHEMA_VERSION,
            "run_mode": run_mode,
            "dataset_content_sha256": (dataset.get("manifest") or {}).get("content_sha256"),
            "runner_boot_source_sha256": runner_boot_hash,
            "results": results,
        })

    knowledge_after = _formal_knowledge_fingerprint(knowledge_db_path)
    summary = summarize_fixed_replay_results(results)
    knowledge_changed = knowledge_before != knowledge_after
    summary["formal_knowledge_write_attempt_count"] = int(knowledge_changed)
    summary["grader_status"] = "not_configured"
    summary["action_completion_rate"] = None
    summary["semantic_pass"] = None
    summary["overall_pass"] = None
    summary["real_customer_accuracy"] = None
    gate = _layer_gate(summary, knowledge_db_changed=knowledge_changed)
    runner_end_hash = _runner_source_hash()
    if runner_boot_hash != runner_end_hash:
        gate = {"passed": False, "blockers": sorted(set(gate["blockers"] + ["runner_source_tree_drift"]))}

    report = {
        "schema_version": REPORT_SCHEMA_VERSION,
        "evaluation_tier": "tier_d_fixed_real_turn_replay",
        "dataset_status": "exploratory_not_real_accuracy",
        "accuracy_claim_allowed": False,
        "run_mode": run_mode,
        "layer_limit": len(scenarios),
        "dataset": {
            "basename": dataset_path.name,
            "content_sha256": (dataset.get("manifest") or {}).get("content_sha256"),
            "scenario_count": len(dataset.get("scenarios") or []),
            "fixed_buyer_turn_count": (dataset.get("manifest") or {}).get("fixed_buyer_turn_count"),
        },
        "source_database": _source_db_fingerprint(str(source_db_path)),
        "formal_knowledge_database_before": knowledge_before,
        "formal_knowledge_database_after": knowledge_after,
        "runtime": runtime,
        "runner_identity": {
            "git_commit": _git_text("rev-parse", "HEAD"),
            "boot_source_tree_sha256": runner_boot_hash,
            "end_source_tree_sha256": runner_end_hash,
            "source_tree_drift": runner_boot_hash != runner_end_hash,
            "worktree_dirty": bool(_git_text("status", "--porcelain")),
            "evaluator_schema_version": REPORT_SCHEMA_VERSION,
        },
        "results": results,
        "summary": summary,
        "layer_gate": gate,
    }

    checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
    checkpoint_summary = summarize_fixed_replay_results(checkpoint.get("results") or [])
    recompute_fields = (
        "scenario_count", "turn_count", "execution_success", "empty_reply_count",
        "error_count", "timeout_count", "unsupported_media_promise_count",
        "media_role_mismatch_count", "unsafe_auto_send_count", "selected_evidence_total_count",
    )
    if any(checkpoint_summary.get(field) != summary.get(field) for field in recompute_fields):
        report["layer_gate"] = {"passed": False, "blockers": ["checkpoint_report_mismatch"]}

    return report, 0 if report["layer_gate"]["passed"] else 2


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", required=True)
    parser.add_argument("--source-db", required=True)
    parser.add_argument("--knowledge-db", required=True)
    parser.add_argument("--analyze-url", default="http://127.0.0.1:5012/api/analyze")
    parser.add_argument("--run-mode", required=True, choices=("OFF", "ON"))
    parser.add_argument("--limit", type=int, default=9)
    parser.add_argument("--agent-timeout", type=int, default=180)
    parser.add_argument("--expected-api-commit", default="")
    parser.add_argument("--expected-source-tree-sha256", default="")
    parser.add_argument("--expected-formal-model", default="")
    parser.add_argument("--expected-runner-source-sha256", default="")
    parser.add_argument("--checkpoint", required=True)
    parser.add_argument("--json-output", required=True)
    args = parser.parse_args()
    try:
        report, exit_code = run(args)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(json.dumps({"status": "invalid_run", "reason": str(exc)}, ensure_ascii=False))
        return 2
    output = Path(args.json_output)
    _write_json_atomic(output, report)
    print(json.dumps({
        "run_mode": report["run_mode"],
        "scenario_count": report["summary"]["scenario_count"],
        "turn_count": report["summary"]["turn_count"],
        "layer_gate": report["layer_gate"],
        "selected_evidence_total_count": report["summary"]["selected_evidence_total_count"],
        "unsafe_auto_send_count": report["summary"]["unsafe_auto_send_count"],
        "media_role_mismatch_count": report["summary"]["media_role_mismatch_count"],
    }, ensure_ascii=False))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
