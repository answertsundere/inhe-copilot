"""Run an independent AI buyer against the formal Agent HTTP pipeline.

This is Tier D exploratory evaluation. It never reports real-customer accuracy.
"""

from __future__ import annotations

import argparse
import json
import os
import secrets
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from openai import OpenAI

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from app.services.eval_sanitizer_service import sanitize_obj  # noqa: E402
from app.services.long_conversation_simulation_service import (  # noqa: E402
    assert_agent_payload_has_no_evaluation_labels,
    conversation_linkage_fingerprint,
    score_simulation_thread,
    summarize_simulation_results,
    validate_long_conversation_dataset,
    validate_simulator_output,
)
from app.services.real_accuracy_gold_set_service import (  # noqa: E402
    build_gold_dataset,
    hmac_identifier,
    load_reviewed_training_samples,
)
from app.services.real_accuracy_privacy_service import sanitize_gold_text  # noqa: E402


def _load_env_file(path: str) -> None:
    if not path:
        return
    for raw_line in Path(path).read_text(encoding="utf-8-sig").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            os.environ.setdefault(key, value)


def _post_agent(url: str, payload: dict[str, Any], timeout: int) -> tuple[int, dict[str, Any], float, str]:
    started = time.perf_counter()
    request = urllib.request.Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = json.loads(response.read().decode("utf-8"))
            return response.status, body, round((time.perf_counter() - started) * 1000, 1), ""
    except urllib.error.HTTPError as exc:
        return exc.code, {}, round((time.perf_counter() - started) * 1000, 1), f"http_{exc.code}"
    except Exception as exc:
        return 0, {}, round((time.perf_counter() - started) * 1000, 1), type(exc).__name__


def _history_text(turns: list[dict[str, Any]]) -> str:
    role_names = {"BUYER": "买家", "AGENT": "客服", "SYSTEM": "系统"}
    lines = [
        f"{role_names.get(str(turn.get('speaker_role') or ''), '未知')}: {sanitize_gold_text(turn.get('text'))}"
        for turn in turns[-30:]
        if sanitize_gold_text(turn.get("text"))
    ]
    return "\n".join(lines)[-7000:]


def _agent_payload(source: dict[str, Any], scenario: dict[str, Any], trial: int, message: str, history: list[dict[str, Any]]) -> dict[str, Any]:
    payload = {
        "message": sanitize_gold_text(message),
        "conversation_history": _history_text(history),
        "order_id": str(source.get("order_no") or "").strip(),
        "sku_code": str(source.get("sku") or "").strip(),
        "product_name": str(source.get("product_title") or "").strip(),
        "conversation_id": f"tier_d_{scenario['scenario_uid']}_t{trial}",
        "copilot_context": {
            "sidecar_context": {
                "sidecar_product_title": str(source.get("product_title") or "").strip(),
                "sidecar_sku_code": str(source.get("sku") or "").strip(),
                "sidecar_order_id": str(source.get("order_no") or "").strip(),
                "source": "tier_d_long_conversation_simulation",
            },
        },
    }
    assert_agent_payload_has_no_evaluation_labels(payload)
    return payload


def _reply_text(response: dict[str, Any]) -> str:
    return sanitize_gold_text(
        response.get("sendable_reply")
        or response.get("suggested_reply")
        or response.get("draft_reply")
        or ""
    )


class CustomerSimulator:
    def __init__(self, *, api_key: str, api_base: str, model: str, timeout: int) -> None:
        self.model = model
        self.client = OpenAI(api_key=api_key, base_url=api_base, timeout=timeout)

    def next_turn(
        self,
        scenario: dict[str, Any],
        transcript: list[dict[str, Any]],
        observed_action_ids: set[str],
    ) -> dict[str, Any]:
        goal = scenario.get("hidden_goal_contract") or {}
        allowed_actions = set(goal.get("required_action_ids") or [])
        compact_transcript = [
            {"role": str(turn.get("speaker_role") or ""), "text": sanitize_gold_text(turn.get("text"))}
            for turn in transcript[-18:]
        ]
        system_prompt = (
            "你是电商客服评测中的买家模拟器。你只扮演买家，不回答客服问题。"
            "根据对话自然追问，一次只推进一到两个点，不编造商品参数、订单状态、伤情或新证据。"
            "必须紧扣 current_focus，不得切换回前文已经结束的其他商品或话题。"
            "不得声称已经发送新的截图、照片、视频、订单号或实物资料。"
            "如果客服已给出可执行答复，标记 satisfied；如果合理转人工并说明下一步，标记 handoff_accepted；"
            "如果你下一句只会表示愿意等待、接受核对或准备按要求补资料，应直接标记 handoff_accepted 并停止，"
            "不要再生成一句口头接受后继续对话。"
            "如果仍需追问，标记 continue。只输出一个 JSON 对象，不要 Markdown。JSON。"
        )
        user_payload = {
            "scenario_domain": scenario.get("scenario_domains") or [],
            "current_focus": scenario.get("initial_buyer_message"),
            "query_fact_types": scenario.get("query_fact_types") or [],
            "buyer_style": scenario.get("buyer_style") or {},
            "buyer_goal": goal.get("goal"),
            "required_action_ids": sorted(allowed_actions),
            "already_observed_action_ids": sorted(observed_action_ids),
            "fact_correctness_scorable": False,
            "transcript": compact_transcript,
            "output_schema": {
                "next_message": "string; stop=true 时可为空",
                "observed_action_ids": "仅可从 required_action_ids 选择",
                "buyer_state": "continue|satisfied|handoff_accepted|blocked",
                "stop": "boolean",
                "stop_reason": "continue|resolved|handoff_accepted|cannot_continue",
            },
        }
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False)},
            ],
            temperature=0.35,
            max_tokens=260,
            response_format={"type": "json_object"},
        )
        choice = response.choices[0]
        if str(getattr(choice, "finish_reason", "") or "") == "length":
            raise ValueError("simulator_output_truncated")
        raw = str(choice.message.content or "").strip()
        parsed = json.loads(raw)
        return validate_simulator_output(parsed, allowed_actions)


def _resolve_sources(
    scenarios: list[dict[str, Any]],
    samples: list[dict[str, Any]],
    hmac_key: str,
) -> tuple[dict[str, dict[str, Any]], int, int]:
    """Resolve source records without persisting raw IDs or requiring the old HMAC key."""
    resolved: dict[str, dict[str, Any]] = {}
    if hmac_key:
        direct = {
            hmac_identifier(hmac_key, "training_sample", sample.get("id")): sample
            for sample in samples
        }
        for scenario in scenarios:
            source = direct.get(str(scenario.get("source_case_uid") or ""))
            if source is not None:
                resolved[str(scenario["scenario_uid"])] = source

    unresolved = [scenario for scenario in scenarios if str(scenario["scenario_uid"]) not in resolved]
    if not unresolved:
        return resolved, 0, 0

    ephemeral_key = secrets.token_hex(32)
    rebuilt, _ = build_gold_dataset(ephemeral_key, samples)
    source_by_rebuilt_uid = {
        hmac_identifier(ephemeral_key, "training_sample", sample.get("id")): sample
        for sample in samples
    }
    fingerprint_sources: dict[str, list[dict[str, Any]]] = {}
    for case in rebuilt.get("cases") or []:
        turns = list((case.get("conversation") or {}).get("turns") or [])
        source = source_by_rebuilt_uid.get(str(case.get("case_uid") or ""))
        if source is None:
            continue
        for position, turn in enumerate(turns):
            if turn.get("speaker_role") != "BUYER" or str(turn.get("message_type") or "text") != "text":
                continue
            fingerprint = conversation_linkage_fingerprint(turns[:position], str(turn.get("text") or ""))
            fingerprint_sources.setdefault(fingerprint, []).append(source)

    missing_count = 0
    ambiguous_count = 0
    for scenario in unresolved:
        matches = fingerprint_sources.get(str(scenario.get("source_linkage_fingerprint") or ""), [])
        unique = {
            json.dumps({
                "customer_quote": item.get("customer_quote"),
                "full_context": item.get("full_context"),
                "product_title": item.get("product_title"),
                "sku": item.get("sku"),
                "order_no": item.get("order_no"),
            }, ensure_ascii=False, sort_keys=True): item
            for item in matches
        }
        if len(unique) == 1:
            resolved[str(scenario["scenario_uid"])] = next(iter(unique.values()))
        elif not unique:
            missing_count += 1
        else:
            ambiguous_count += 1
    return resolved, missing_count, ambiguous_count


def _compact_response(response: dict[str, Any]) -> dict[str, Any]:
    evidence_summary = [
        {
            "evidence_uid": str(item.get("evidence_uid") or item.get("chunk_uid") or item.get("id") or ""),
            "source_type": str(item.get("source_type") or ""),
            "evidence_role": str(item.get("evidence_role") or ""),
            "query_fact_type": str(item.get("query_fact_type") or ""),
        }
        for item in (response.get("selected_evidence") or [])
        if isinstance(item, dict)
    ]
    return sanitize_obj({
        "reply": _reply_text(response),
        "can_send": bool(response.get("can_send")),
        "requires_human_review": bool(response.get("requires_human_review")),
        "reply_status": str(response.get("reply_status") or ""),
        "reply_block_types": [str(item.get("type") or "") for item in (response.get("reply_blocks") or []) if isinstance(item, dict)],
        "selected_evidence_count": len(evidence_summary),
        "selected_evidence_summary": evidence_summary,
        "final_answer_audit": {
            "passed": bool((response.get("final_answer_audit") or {}).get("passed", True)),
            "issues": list((response.get("final_answer_audit") or {}).get("issues") or []),
        },
        "final_semantic_fit_audit": {
            "passed": bool((response.get("final_semantic_fit_audit") or {}).get("passed", True)),
            "issues": list((response.get("final_semantic_fit_audit") or {}).get("issues") or []),
        },
        "analysis_pipeline_version": str((response.get("analysis_pipeline") or {}).get("version") or ""),
    })


def _run_trial(
    *,
    scenario: dict[str, Any],
    source: dict[str, Any],
    trial: int,
    simulator: CustomerSimulator,
    analyze_url: str,
    agent_timeout: int,
    max_generated_turns: int,
) -> dict[str, Any]:
    transcript = [dict(turn) for turn in scenario.get("seed_history") or []]
    current_message = str(scenario.get("initial_buyer_message") or "")
    observed_actions: set[str] = set()
    internal_turns: list[dict[str, Any]] = []
    report_turns: list[dict[str, Any]] = []
    terminal_state = "blocked"
    terminal_reason = "cannot_continue"
    simulator_error = ""
    generated_count = 0

    while True:
        payload = _agent_payload(source, scenario, trial, current_message, transcript)
        status, response, latency, agent_error = _post_agent(analyze_url, payload, agent_timeout)
        internal_turn = {
            "buyer_message": current_message,
            "status_code": status,
            "latency_ms": latency,
            "agent_error": agent_error,
            "agent_response": response,
        }
        internal_turns.append(internal_turn)
        report_turns.append({
            "turn_number": len(internal_turns),
            "buyer_message": sanitize_gold_text(current_message),
            "status_code": status,
            "latency_ms": latency,
            "agent_error": agent_error,
            "agent_response": _compact_response(response),
        })
        transcript.extend([
            {"speaker_role": "BUYER", "text": current_message},
            {"speaker_role": "AGENT", "text": _reply_text(response)},
        ])
        if agent_error or status != 200 or not _reply_text(response):
            terminal_state, terminal_reason = "blocked", "cannot_continue"
            break
        try:
            decision = simulator.next_turn(scenario, transcript, observed_actions)
        except Exception as exc:
            simulator_error = type(exc).__name__ if not isinstance(exc, ValueError) else str(exc)
            terminal_state, terminal_reason = "blocked", "cannot_continue"
            break
        observed_actions.update(decision["observed_action_ids"])
        report_turns[-1]["simulator_decision"] = decision
        terminal_state = decision["buyer_state"]
        terminal_reason = decision["stop_reason"]
        if decision["stop"]:
            break
        if generated_count >= max_generated_turns:
            terminal_state, terminal_reason = "blocked", "cannot_continue"
            break
        current_message = decision["next_message"]
        generated_count += 1

    score = score_simulation_thread(
        scenario,
        internal_turns,
        terminal_buyer_state=terminal_state,
        terminal_stop_reason=terminal_reason,
        observed_action_ids=observed_actions,
    )
    return {
        "scenario_uid": scenario["scenario_uid"],
        "trial": trial,
        "primary_domain": scenario.get("primary_domain"),
        "source_turn_count": scenario.get("source_turn_count"),
        "seed_history_turn_count": len(scenario.get("seed_history") or []),
        "executed_agent_turn_count": len(internal_turns),
        "simulator_error": simulator_error,
        "observed_action_ids": sorted(observed_actions),
        "turns": report_turns,
        "score": score,
    }


def _turn_metrics(results: list[dict[str, Any]]) -> dict[str, Any]:
    turns = [turn for result in results for turn in (result.get("turns") or [])]
    latencies = sorted(float(turn.get("latency_ms") or 0) for turn in turns)

    def percentile(fraction: float) -> float | None:
        if not latencies:
            return None
        index = min(len(latencies) - 1, max(0, round((len(latencies) - 1) * fraction)))
        return round(latencies[index], 1)

    repeated_reply_count = 0
    transition_count = 0
    for result in results:
        replies = [str((turn.get("agent_response") or {}).get("reply") or "").strip() for turn in result.get("turns") or []]
        for previous, current in zip(replies, replies[1:]):
            transition_count += 1
            if previous and previous == current:
                repeated_reply_count += 1
    return {
        "agent_latency_p50_ms": percentile(0.5),
        "agent_latency_p95_ms": percentile(0.95),
        "can_send_turn_count": sum(bool((turn.get("agent_response") or {}).get("can_send")) for turn in turns),
        "requires_human_review_turn_count": sum(bool((turn.get("agent_response") or {}).get("requires_human_review")) for turn in turns),
        "selected_evidence_turn_count": sum(int((turn.get("agent_response") or {}).get("selected_evidence_count") or 0) > 0 for turn in turns),
        "selected_evidence_total_count": sum(int((turn.get("agent_response") or {}).get("selected_evidence_count") or 0) for turn in turns),
        "final_audit_failed_turn_count": sum(not bool(((turn.get("agent_response") or {}).get("final_answer_audit") or {}).get("passed", True)) for turn in turns),
        "repeated_consecutive_reply_count": repeated_reply_count,
        "reply_transition_count": transition_count,
        "consecutive_reply_repetition_rate": round(repeated_reply_count / transition_count, 4) if transition_count else None,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", required=True)
    parser.add_argument("--source-db", required=True)
    parser.add_argument("--analyze-url", default="http://127.0.0.1:5011/api/analyze")
    parser.add_argument("--json-output", required=True)
    parser.add_argument("--env-file", default="")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--trials", type=int, default=1)
    parser.add_argument("--max-generated-turns", type=int, default=3)
    parser.add_argument("--agent-timeout", type=int, default=45)
    parser.add_argument("--simulator-timeout", type=int, default=45)
    parser.add_argument(
        "--allow-safe-source-exclusions",
        action="store_true",
        help="Exclude missing or ambiguous source linkage instead of failing the whole exploratory run",
    )
    args = parser.parse_args(argv)
    _load_env_file(args.env_file)

    required_env = {
        "simulator_key": os.environ.get("COPILOT_CUSTOMER_SIMULATOR_API_KEY", ""),
        "simulator_base": os.environ.get("COPILOT_CUSTOMER_SIMULATOR_API_BASE", ""),
        "simulator_model": os.environ.get("COPILOT_CUSTOMER_SIMULATOR_MODEL", ""),
    }
    missing = [key for key, value in required_env.items() if not value]
    if missing:
        print(json.dumps({"error": "simulator_configuration_missing", "fields": missing}, ensure_ascii=False))
        return 2
    try:
        dataset = json.loads(Path(args.dataset).read_text(encoding="utf-8"))
        findings = validate_long_conversation_dataset(dataset)
        if findings:
            raise ValueError(f"simulation_dataset_invalid:{','.join(findings)}")
        samples = load_reviewed_training_samples(args.source_db)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False))
        return 2

    simulator = CustomerSimulator(
        api_key=required_env["simulator_key"],
        api_base=required_env["simulator_base"],
        model=required_env["simulator_model"],
        timeout=args.simulator_timeout,
    )
    scenarios = list(dataset.get("scenarios") or [])
    if args.limit:
        scenarios = scenarios[:args.limit]
    source_by_scenario, missing_source_count, ambiguous_source_count = _resolve_sources(
        scenarios,
        samples,
        os.environ.get("COPILOT_GOLD_SET_HMAC_KEY", ""),
    )
    results: list[dict[str, Any]] = []
    for scenario in scenarios:
        source = source_by_scenario.get(str(scenario.get("scenario_uid") or ""))
        if source is None:
            continue
        for trial in range(1, max(1, args.trials) + 1):
            results.append(_run_trial(
                scenario=scenario,
                source=source,
                trial=trial,
                simulator=simulator,
                analyze_url=args.analyze_url,
                agent_timeout=args.agent_timeout,
                max_generated_turns=max(0, args.max_generated_turns),
            ))

    summary = summarize_simulation_results(results)
    summary.update({
        "source_missing_count": missing_source_count,
        "source_ambiguous_count": ambiguous_source_count,
        "safe_source_exclusion_count": missing_source_count + ambiguous_source_count,
        "simulator_error_count": sum(bool(item.get("simulator_error")) for item in results),
        "agent_turn_count": sum(int(item.get("executed_agent_turn_count") or 0) for item in results),
    })
    summary.update(_turn_metrics(results))
    simulator_host = urlsplit(required_env["simulator_base"]).hostname or "configured"
    report = {
        "schema_version": "long-conversation-simulation-report-v1",
        "evaluation_tier": "tier_d_simulated_multiturn",
        "dataset_manifest": dataset.get("manifest") or {},
        "execution_path": "ai_buyer_to_http_formal_analysis_pipeline",
        "metric_boundary": {
            "exploratory_pass_rate_only": True,
            "real_customer_accuracy_measured": False,
            "unapproved_product_claims_scored_as_truth": False,
            "grader_type": "deterministic_contract_plus_simulated_buyer_outcome",
        },
        "provider": {
            "simulator_model": required_env["simulator_model"],
            "simulator_host": simulator_host,
            "same_model_as_formal_agent": (
                required_env["simulator_model"] == os.environ.get("COPILOT_LLM_MODEL", "")
                and simulator_host == (urlsplit(os.environ.get("COPILOT_LLM_API_BASE", "")).hostname or "")
            ),
            "credentials_reported": False,
        },
        "summary": summary,
        "results": results,
    }
    output = Path(args.json_output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False))
    source_ok = (
        missing_source_count == 0 and ambiguous_source_count == 0
    ) or args.allow_safe_source_exclusions
    return 0 if results and source_ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
