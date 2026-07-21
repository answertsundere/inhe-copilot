"""Run an independent AI buyer against the formal Agent HTTP pipeline.

This is Tier D exploratory evaluation. It never reports real-customer accuracy.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import os
import re
import secrets
import subprocess
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

from app.llm.client import LLMClient  # noqa: E402
from app.services.long_conversation_simulation_service import (  # noqa: E402
    assert_agent_payload_has_no_evaluation_labels,
    build_tier_d_turn_observation,
    conversation_content_digest,
    conversation_linkage_fingerprint,
    recompute_tier_d_blocking_reasons,
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
from app.services.tier_d_transcript_grader_service import TierDTranscriptGrader  # noqa: E402
from app.services.strict_decision_provider_service import (  # noqa: E402
    StrictDecisionProviderConfig,
    StrictDecisionProviderError,
    StrictDecisionProviderService,
    safe_provider_identity,
)


EVALUATOR_SCHEMA_VERSION = "tier-d-evaluator/v4"
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_RUNNER_SOURCE_FILES = (
    "scripts/run_long_conversation_simulation.py",
    "app/services/long_conversation_simulation_service.py",
    "app/services/canonical_conversation_turn_service.py",
    "app/services/real_accuracy_gold_set_service.py",
    "app/services/real_accuracy_privacy_service.py",
    "app/services/tier_d_transcript_grader_service.py",
    "app/services/strict_decision_provider_service.py",
)


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


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _canonical_hash(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    """Keep checkpoints parseable if the evaluator is interrupted mid-write."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def _runner_source_tree_sha256() -> str:
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


def _runner_identity(
    *,
    grader_qualification_report: Path,
    simulator_qualification_report: Path,
    dataset_manifest: dict[str, Any],
) -> dict[str, Any]:
    return {
        "git_commit": _git_text("rev-parse", "HEAD"),
        "source_tree_sha256": _runner_source_tree_sha256(),
        "worktree_dirty": bool(_git_text("status", "--porcelain")),
        "evaluator_schema_version": EVALUATOR_SCHEMA_VERSION,
        "grader_qualification_report_sha256": _sha256_file(grader_qualification_report),
        "simulator_qualification_report_sha256": _sha256_file(simulator_qualification_report),
        "dataset_manifest_sha256": _canonical_hash(dataset_manifest),
    }


def _require_sha256(value: Any, field: str) -> str:
    text = str(value or "")
    if not _SHA256_RE.fullmatch(text):
        raise ValueError(f"{field}_invalid")
    return text


def _load_grader_qualification(
    path: Path,
    grader_metadata: dict[str, Any],
    *,
    workers: int,
) -> dict[str, Any]:
    report = json.loads(path.read_text(encoding="utf-8"))
    provider = report.get("provider") if isinstance(report.get("provider"), dict) else {}
    if report.get("schema_version") != "tier-d-transcript-grader-qualification/v4":
        raise ValueError("grader_qualification_schema_version_mismatch")
    if report.get("configured_candidate") is not True:
        raise ValueError("grader_qualification_provider_not_configured")
    local_checks = report.get("local_contract_checks")
    if not isinstance(local_checks, dict) or not local_checks or not all(local_checks.values()):
        raise ValueError("grader_qualification_local_contract_failed")
    if int(report.get("secret_exposure_count") or 0):
        raise ValueError("grader_qualification_secret_exposure_present")
    if str(provider.get("identity") or "") != str(grader_metadata.get("identity") or ""):
        raise ValueError("grader_qualification_identity_mismatch")
    if int(report.get("timeout_attempt_count") or 0):
        raise ValueError("grader_qualification_timeout_present")
    if int(report.get("truncated_attempt_count") or 0):
        raise ValueError("grader_qualification_truncation_present")
    if int(report.get("schema_error_attempt_count") or 0):
        raise ValueError("grader_qualification_schema_error_present")
    if int(report.get("free_text_fallback_attempt_count") or 0):
        raise ValueError("grader_qualification_free_text_present")
    for field in (
        "provider_schema_success_rate",
        "positive_semantic_pass_rate",
        "negative_semantic_block_rate",
        "citation_valid_rate",
        "repeat_stability_rate",
    ):
        if (report.get(field) or {}).get("rate") != 1.0:
            raise ValueError(f"grader_qualification_{field}_incomplete")
    execution_profile = "serial" if max(1, workers) == 1 else "concurrent"
    load = report.get("long_load_qualification") or {}
    phase = load.get(execution_profile) if isinstance(load.get(execution_profile), dict) else {}
    if phase.get("status") != "qualified":
        raise ValueError(f"grader_long_load_{execution_profile}_not_qualified")
    if any(int(phase.get(field) or 0) for field in (
        "timeout_attempt_count",
        "truncated_attempt_count",
        "schema_error_attempt_count",
        "free_text_fallback_attempt_count",
    )):
        raise ValueError(f"grader_long_load_{execution_profile}_error_present")
    if any((phase.get(field) or {}).get("rate") != 1.0 for field in (
        "semantic_pass_rate",
        "citation_valid_rate",
        "repeat_stability_rate",
    )):
        raise ValueError(f"grader_long_load_{execution_profile}_metric_incomplete")
    latency = phase.get("latency_ms") if isinstance(phase.get("latency_ms"), dict) else {}
    if latency.get("p95") is None or float(latency["p95"]) >= float(phase.get("p95_limit_ms") or 0):
        raise ValueError(f"grader_long_load_{execution_profile}_latency_exceeded")
    report["selected_execution_profile"] = execution_profile
    return report


def _load_simulator_qualification(path: Path, simulator_metadata: dict[str, Any]) -> dict[str, Any]:
    report = json.loads(path.read_text(encoding="utf-8"))
    provider = report.get("provider") if isinstance(report.get("provider"), dict) else {}
    if report.get("schema_version") != "tier-d-customer-simulator-qualification/v1":
        raise ValueError("simulator_qualification_schema_version_mismatch")
    if report.get("qualification_status") != "qualified":
        raise ValueError("simulator_qualification_not_qualified")
    if str(provider.get("identity") or "") != str(simulator_metadata.get("identity") or ""):
        raise ValueError("simulator_qualification_identity_mismatch")
    for mode in ("short", "serial", "concurrent"):
        phase = report.get(mode) if isinstance(report.get(mode), dict) else {}
        if phase.get("status") != "qualified" or int(phase.get("error_attempt_count") or 0):
            raise ValueError("simulator_long_load_not_qualified")
        if any((phase.get(field) or {}).get("rate") != 1.0 for field in (
            "semantic_pass_rate",
            "repeat_stability_rate",
        )):
            raise ValueError("simulator_long_load_metric_incomplete")
        latency = phase.get("latency_ms") if isinstance(phase.get("latency_ms"), dict) else {}
        if latency.get("p95") is None or float(latency["p95"]) >= float(phase.get("p95_limit_ms") or 0):
            raise ValueError("simulator_long_load_latency_exceeded")
    if int(report.get("gold_label_leakage_count") or 0):
        raise ValueError("simulator_gold_label_leakage_present")
    return report


def _report_runtime(runtime: dict[str, Any]) -> dict[str, Any]:
    """Return typed runtime identity without endpoint or arbitrary strings."""
    return {
        "status": str(runtime.get("status") or ""),
        "version_http_status": int(runtime.get("version_http_status") or 0),
        "readiness_http_status": int(runtime.get("readiness_http_status") or 0),
        "runtime_commit": str(runtime.get("runtime_commit") or ""),
        "app_version": str(runtime.get("app_version") or ""),
        "formal_model": str(runtime.get("formal_model") or ""),
        "formal_provider_identity": dict(runtime.get("formal_provider_identity") or {}),
        "action_policy_provider_identity": dict(runtime.get("action_policy_provider_identity") or {}),
        "worktree_dirty": runtime.get("worktree_dirty"),
        "source_tree_sha256": _require_sha256(runtime.get("source_tree_sha256"), "runtime_source_tree_sha256"),
        "boot_source_tree_sha256": _require_sha256(runtime.get("boot_source_tree_sha256"), "runtime_boot_source_tree_sha256"),
        "current_source_tree_sha256": _require_sha256(runtime.get("current_source_tree_sha256"), "runtime_current_source_tree_sha256"),
        "source_tree_drift": runtime.get("source_tree_drift"),
        "build_identity_status": str(runtime.get("build_identity_status") or ""),
        "feature_flags": dict(runtime.get("feature_flags") or {}),
        "readiness": {
            "ready": bool((runtime.get("readiness") or {}).get("ready")),
            "status": str((runtime.get("readiness") or {}).get("status") or ""),
            "reasons": sorted(str(item) for item in ((runtime.get("readiness") or {}).get("reasons") or [])),
        },
    }


def _formal_provider_probe(runtime: dict[str, Any], timeout: int) -> dict[str, Any]:
    """Verify the configured formal model can answer before Tier D reads its dataset."""
    api_base = str(os.environ.get("COPILOT_LLM_API_BASE") or "").strip()
    api_key = str(os.environ.get("COPILOT_LLM_API_KEY") or "").strip()
    model = str(os.environ.get("COPILOT_LLM_MODEL") or "").strip()
    identity = safe_provider_identity(
        provider_name="formal_agent",
        api_base=api_base,
        model=model,
    )
    safe_result = {
        "status": "not_available",
        "provider_identity": identity,
        "model_name": identity.get("model_name"),
        "latency_ms": None,
        "error_category": "",
    }
    if not api_key or not identity.get("configured"):
        safe_result["error_category"] = "formal_provider_not_configured"
        return safe_result
    if identity.get("identity") != (runtime.get("formal_provider_identity") or {}).get("identity"):
        safe_result["error_category"] = "formal_provider_identity_mismatch"
        return safe_result
    started = time.perf_counter()
    try:
        transport = LLMClient(
            api_key=api_key,
            api_base=api_base,
            model=model,
        )
        transport._client = OpenAI(
            api_key=api_key,
            base_url=api_base,
            timeout=max(1, min(int(timeout), 120)),
            max_retries=0,
        )
        response = transport.create_chat_completion(
            model=model,
            messages=[
                {"role": "system", "content": "Return exactly TIER_D_PROVIDER_READY."},
                {"role": "user", "content": "Readiness probe."},
            ],
            temperature=0,
            max_tokens=16,
        )
        choice = response.choices[0] if response.choices else None
        content = str(getattr(getattr(choice, "message", None), "content", "") or "").strip()
        finish_reason = str(getattr(choice, "finish_reason", "") or "")
        if finish_reason == "length":
            safe_result["error_category"] = "formal_provider_response_truncated"
        elif content != "TIER_D_PROVIDER_READY":
            safe_result["error_category"] = "formal_provider_probe_contract_failed"
        else:
            safe_result["status"] = "available"
    except Exception as exc:
        status_code = int(getattr(exc, "status_code", 0) or 0)
        if status_code in {401, 403}:
            category = "formal_provider_authentication_failed"
        elif status_code == 402:
            category = "formal_provider_quota_unavailable"
        elif status_code == 429:
            category = "formal_provider_rate_limited"
        elif "timeout" in type(exc).__name__.lower():
            category = "formal_provider_timeout"
        else:
            category = "formal_provider_request_failed"
        safe_result["error_category"] = category
    safe_result["latency_ms"] = round((time.perf_counter() - started) * 1000, 2)
    return safe_result


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


def _get_json(url: str, timeout: int) -> tuple[int, dict[str, Any]]:
    request = urllib.request.Request(url, headers={"Accept": "application/json"}, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        try:
            return exc.code, json.loads(exc.read().decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError, OSError):
            return exc.code, {}
    except (urllib.error.URLError, json.JSONDecodeError, OSError):
        return 0, {}


def _runtime_metadata(analyze_url: str, timeout: int) -> dict[str, Any]:
    parsed = urlsplit(analyze_url)
    base_url = f"{parsed.scheme}://{parsed.netloc}"
    version_status, version = _get_json(f"{base_url}/api/runtime/version", timeout)
    readiness_status, readiness = _get_json(f"{base_url}/api/runtime/readiness", timeout)
    metadata = {
        "status": "available" if version_status == 200 and readiness_status == 200 and readiness.get("ready") is True else "not_ready",
        "runtime_url": base_url,
        "version_http_status": version_status,
        "readiness_http_status": readiness_status,
        "runtime_commit": str(version.get("runtime_commit") or ""),
        "app_version": str(version.get("app_version") or ""),
        "formal_model": str(version.get("formal_model") or ""),
        "formal_provider_identity": (
            dict(version.get("formal_provider_identity"))
            if isinstance(version.get("formal_provider_identity"), dict)
            else {}
        ),
        "action_policy_provider_identity": (
            dict(version.get("action_policy_provider_identity"))
            if isinstance(version.get("action_policy_provider_identity"), dict)
            else {}
        ),
        "worktree_dirty": version.get("worktree_dirty"),
        "source_tree_sha256": str(version.get("source_tree_sha256") or ""),
        "boot_source_tree_sha256": str(version.get("boot_source_tree_sha256") or version.get("source_tree_sha256") or ""),
        "current_source_tree_sha256": str(version.get("current_source_tree_sha256") or ""),
        "source_tree_drift": version.get("source_tree_drift"),
        "build_identity_status": str(version.get("build_identity_status") or ""),
        "feature_flags": version.get("feature_flags") if isinstance(version.get("feature_flags"), dict) else {},
        "readiness": readiness,
    }
    if version_status != 200 or readiness_status == 0:
        metadata["status"] = "unavailable"
    return metadata


def _source_db_fingerprint(path: str) -> dict[str, Any]:
    source = Path(path)
    try:
        digest = hashlib.sha256()
        with source.open("rb") as handle:
            for block in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(block)
        return {"basename": source.name, "size_bytes": source.stat().st_size, "sha256": digest.hexdigest()}
    except OSError:
        return {"basename": source.name, "status": "unavailable"}


def _provider_identities(
    runtime: dict[str, Any],
    *,
    simulator_metadata: dict[str, Any],
    grader_metadata: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    formal = runtime.get("formal_provider_identity")
    if not isinstance(formal, dict):
        formal = {}
    return {
        "formal_agent": {
            "provider_name": str(formal.get("provider_name") or "formal_agent"),
            "host_fingerprint": str(formal.get("host_fingerprint") or ""),
            "model_name": str(formal.get("model_name") or runtime.get("formal_model") or ""),
            "configured": bool(formal.get("configured")),
            "identity": str(formal.get("identity") or ""),
        },
        "customer_simulator": {
            "provider_name": str(simulator_metadata.get("provider_name") or "customer_simulator"),
            "host_fingerprint": str(simulator_metadata.get("host_fingerprint") or ""),
            "model_name": str(simulator_metadata.get("model_name") or ""),
            "configured": bool(simulator_metadata.get("configured")),
            "identity": str(simulator_metadata.get("identity") or ""),
        },
        "transcript_grader": {
            "provider_name": str(grader_metadata.get("provider_name") or "transcript_grader"),
            "host_fingerprint": str(grader_metadata.get("host_fingerprint") or ""),
            "model_name": str(grader_metadata.get("model_name") or ""),
            "configured": bool(grader_metadata.get("configured")),
            "identity": str(grader_metadata.get("identity") or ""),
        },
    }


def _provider_independence(identities: dict[str, dict[str, Any]]) -> dict[str, Any]:
    unknown_roles = sorted(role for role, identity in identities.items() if not identity.get("configured") or not identity.get("identity"))
    role_pairs = [("formal_agent", "customer_simulator"), ("formal_agent", "transcript_grader"), ("customer_simulator", "transcript_grader")]
    conflicts = [
        {"roles": list(pair), "identity": identities[pair[0]]["identity"]}
        for pair in role_pairs
        if not unknown_roles and identities[pair[0]]["identity"] == identities[pair[1]]["identity"]
    ]
    same_model_different_host = [
        {"roles": list(pair), "model_name": identities[pair[0]]["model_name"]}
        for pair in role_pairs
        if not unknown_roles
        and identities[pair[0]]["model_name"] == identities[pair[1]]["model_name"]
        and identities[pair[0]]["host_fingerprint"] != identities[pair[1]]["host_fingerprint"]
    ]
    configured_hosts = {
        str(identity.get("host_fingerprint") or "")
        for identity in identities.values()
        if identity.get("configured") and identity.get("host_fingerprint")
    }
    same_provider_family_risk = not unknown_roles and len(configured_hosts) == 1
    return {
        "passed": not unknown_roles and not conflicts,
        "status": (
            "single_provider_family_diagnostic"
            if not unknown_roles and not conflicts and same_provider_family_risk
            else "independent"
            if not unknown_roles and not conflicts
            else "provider_independence_failed"
        ),
        "same_provider_family_risk": same_provider_family_risk,
        "independent_acceptance_allowed": bool(not unknown_roles and not conflicts and not same_provider_family_risk),
        "unknown_roles": unknown_roles,
        "conflicts": conflicts,
        "same_model_different_host_risks": same_model_different_host,
        "identities": identities,
    }


def _history_text(turns: list[dict[str, Any]]) -> list[dict[str, Any]]:
    from app.services.canonical_conversation_turn_service import normalize_conversation_turns

    history, _ = normalize_conversation_turns([
        {
            "role": turn.get("speaker_role"),
            "content": sanitize_gold_text(turn.get("text")),
            "turn_uid": turn.get("turn_uid"),
            "turn_index": index,
            "message_type": turn.get("message_type"),
        }
        for index, turn in enumerate(turns[-30:])
        if sanitize_gold_text(turn.get("text"))
    ], strict=True, max_turns=30)
    return history


def _agent_payload(source: dict[str, Any], scenario: dict[str, Any], trial: int, message: str, history: list[dict[str, Any]]) -> dict[str, Any]:
    payload = {
        "message": sanitize_gold_text(message),
        "conversation_history": _history_text(history),
        "order_id": str(source.get("order_no") or "").strip(),
        "sku_code": str(source.get("sku") or "").strip(),
        "product_name": str(source.get("product_title") or "").strip(),
        "conversation_id": f"tier_d_{scenario['scenario_uid']}_t{trial}",
        "copilot_context": {
            "evaluation_context_contract": "strict",
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


class CustomerSimulator:
    def __init__(
        self,
        *,
        api_key: str,
        api_base: str,
        model: str,
        timeout: int,
        provider: StrictDecisionProviderService | None = None,
        allow_unqualified: bool = False,
    ) -> None:
        self.allow_unqualified = allow_unqualified
        self.provider = provider or StrictDecisionProviderService(config=StrictDecisionProviderConfig(
            provider_name=str(os.environ.get("COPILOT_CUSTOMER_SIMULATOR_PROVIDER") or "customer_simulator"),
            api_base=api_base,
            api_key=api_key,
            model=model,
            capability=str(os.environ.get("COPILOT_CUSTOMER_SIMULATOR_CAPABILITY") or "").lower(),
            timeout_seconds=max(1, min(int(timeout), 300)),
            qualified=str(os.environ.get("COPILOT_CUSTOMER_SIMULATOR_QUALIFIED") or "").lower() in {"1", "true", "yes", "on"},
            disable_thinking=str(os.environ.get("COPILOT_CUSTOMER_SIMULATOR_DISABLE_THINKING") or "").lower() in {"1", "true", "yes", "on"},
        ))

    def metadata(self) -> dict[str, Any]:
        metadata = dict(self.provider.metadata())
        metadata["role"] = "tier_d_customer_simulator"
        return metadata

    def ready(self) -> bool:
        return self.provider.ready_for_shadow()

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
            "State contract: buyer_state=continue requires stop=false and a non-empty next_message. "
            "buyer_state=satisfied, handoff_accepted, or blocked requires stop=true and next_message=''. "
            "Never return stop=false with an empty next_message."
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
        schema = {
            "type": "object",
            "additionalProperties": False,
            "required": ["next_message", "observed_action_ids", "buyer_state", "stop", "stop_reason"],
            "properties": {
                "next_message": {"type": "string", "maxLength": 500},
                "observed_action_ids": {
                    "type": "array",
                    "items": {"type": "string", "enum": sorted(allowed_actions)} if allowed_actions else {"type": "string"},
                    **({"maxItems": 0} if not allowed_actions else {}),
                },
                "buyer_state": {"type": "string", "enum": sorted({"continue", "satisfied", "handoff_accepted", "blocked"})},
                "stop": {"type": "boolean"},
                "stop_reason": {"type": "string", "enum": sorted({"continue", "resolved", "handoff_accepted", "cannot_continue"})},
            },
        }
        for validation_attempt in range(2):
            try:
                parsed = self.provider.request(
                    name="tier_d_customer_simulator_turn",
                    schema=schema,
                    system_prompt=system_prompt,
                    payload=user_payload,
                    max_tokens=260,
                    allow_unqualified=self.allow_unqualified,
                )
            except StrictDecisionProviderError as exc:
                raise ValueError(f"simulator_{exc}") from exc
            try:
                decision = validate_simulator_output(parsed, allowed_actions)
            except ValueError:
                if validation_attempt == 0:
                    continue
                raise
            decision["validation_retry_count"] = validation_attempt
            return decision
        raise AssertionError("unreachable_simulator_validation_state")


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
    fingerprint_sources: dict[str, list[tuple[str, dict[str, Any]]]] = {}
    for case in rebuilt.get("cases") or []:
        turns = list((case.get("conversation") or {}).get("turns") or [])
        source = source_by_rebuilt_uid.get(str(case.get("case_uid") or ""))
        if source is None:
            continue
        conversation_digest = conversation_content_digest(turns)
        for position, turn in enumerate(turns):
            if turn.get("speaker_role") != "BUYER" or str(turn.get("message_type") or "text") != "text":
                continue
            fingerprint = conversation_linkage_fingerprint(turns[:position], str(turn.get("text") or ""))
            fingerprint_sources.setdefault(fingerprint, []).append((conversation_digest, source))

    missing_count = 0
    ambiguous_count = 0
    for scenario in unresolved:
        matches = fingerprint_sources.get(str(scenario.get("source_linkage_fingerprint") or ""), [])
        expected_digest = str(scenario.get("source_conversation_digest") or "")
        if expected_digest:
            matches = [item for item in matches if item[0] == expected_digest]
        unique = {
            json.dumps({
                "customer_quote": item.get("customer_quote"),
                "full_context": item.get("full_context"),
                "product_title": item.get("product_title"),
                "sku": item.get("sku"),
                "order_no": item.get("order_no"),
            }, ensure_ascii=False, sort_keys=True): item
            for _digest, item in matches
        }
        if len(unique) == 1:
            resolved[str(scenario["scenario_uid"])] = next(iter(unique.values()))
        elif not unique:
            missing_count += 1
        else:
            ambiguous_count += 1
    return resolved, missing_count, ambiguous_count


def _run_trial(
    *,
    scenario: dict[str, Any],
    source: dict[str, Any],
    trial: int,
    simulator: CustomerSimulator,
    analyze_url: str,
    agent_timeout: int,
    max_generated_turns: int,
    grader: TierDTranscriptGrader,
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
        observation = build_tier_d_turn_observation(response)
        internal_turn = {
            "buyer_message": current_message,
            "status_code": status,
            "latency_ms": latency,
            "agent_error": agent_error,
            "observation": observation,
        }
        internal_turns.append(internal_turn)
        report_turns.append({
            "turn_number": len(internal_turns),
            "buyer_message": sanitize_gold_text(current_message),
            "status_code": status,
            "latency_ms": latency,
            "agent_error": agent_error,
            "observation": observation,
        })
        transcript.extend([
            {"speaker_role": "BUYER", "text": current_message},
            {"speaker_role": "AGENT", "text": observation["reply"]},
        ])
        if agent_error or status != 200 or not observation["reply"]:
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

    grader_error = ""
    try:
        score = score_simulation_thread(
            scenario,
            internal_turns,
            terminal_buyer_state=terminal_state,
            terminal_stop_reason=terminal_reason,
            observed_action_ids=observed_actions,
            grader=grader,
        )
    except Exception as exc:
        grader_error = str(exc) if isinstance(exc, ValueError) else type(exc).__name__
        required_actions = sorted(
            str(item) for item in ((scenario.get("hidden_goal_contract") or {}).get("required_action_ids") or [])
        )
        score = {
            "passed": False,
            "contract_passed": False,
            "buyer_outcome_passed": False,
            "required_action_count": len(required_actions),
            "graded_required_action_count": 0,
            "action_coverage_rate": None,
            "transcript_action_grade": {
                "status": "grader_not_qualified",
                "reason": grader_error or "grader_infrastructure_error",
                "covered_action_ids": [],
                "uncovered_action_ids": required_actions,
                "action_coverage_rate": None,
            },
            "counterfactual_comparisons": [],
            "simulator_observed_action_ids": sorted(set(required_actions).intersection(observed_actions)),
            "blocking_reasons": ["grader_infrastructure_error"],
            "terminal_buyer_state": terminal_state,
            "terminal_stop_reason": terminal_reason,
            "accuracy_metric": None,
            "accuracy_claim_allowed": False,
        }
    return {
        "scenario_uid": scenario["scenario_uid"],
        "trial": trial,
        "primary_domain": scenario.get("primary_domain"),
        "source_turn_count": scenario.get("source_turn_count"),
        "seed_history_turn_count": len(scenario.get("seed_history") or []),
        "executed_agent_turn_count": len(internal_turns),
        "simulator_error": simulator_error,
        "grader_error": grader_error,
        "observed_action_ids": sorted(observed_actions),
        "evaluation_contract": {
            "must_handoff": bool((scenario.get("hidden_goal_contract") or {}).get("must_handoff")),
            "required_action_ids": sorted(
                str(item) for item in ((scenario.get("hidden_goal_contract") or {}).get("required_action_ids") or [])
            ),
        },
        "turns": report_turns,
        "score": score,
    }


def _trial_execution_failure(scenario: dict[str, Any], trial: int, exc: Exception) -> dict[str, Any]:
    error_type = type(exc).__name__
    required_actions = sorted(
        str(item) for item in ((scenario.get("hidden_goal_contract") or {}).get("required_action_ids") or [])
    )
    return {
        "scenario_uid": str(scenario.get("scenario_uid") or ""),
        "trial": trial,
        "primary_domain": scenario.get("primary_domain"),
        "source_turn_count": scenario.get("source_turn_count"),
        "seed_history_turn_count": len(scenario.get("seed_history") or []),
        "executed_agent_turn_count": 0,
        "simulator_error": "",
        "grader_error": "",
        "trial_execution_error": error_type,
        "observed_action_ids": [],
        "evaluation_contract": {
            "must_handoff": bool((scenario.get("hidden_goal_contract") or {}).get("must_handoff")),
            "required_action_ids": required_actions,
        },
        "turns": [],
        "score": {
            "passed": False,
            "contract_passed": False,
            "buyer_outcome_passed": False,
            "required_action_count": len(required_actions),
            "graded_required_action_count": 0,
            "action_coverage_rate": None,
            "transcript_action_grade": {
                "status": "grader_not_qualified",
                "reason": "trial_execution_error",
                "covered_action_ids": [],
                "uncovered_action_ids": required_actions,
                "action_coverage_rate": None,
            },
            "counterfactual_comparisons": [],
            "simulator_observed_action_ids": [],
            "blocking_reasons": ["trial_execution_error"],
            "terminal_buyer_state": "blocked",
            "terminal_stop_reason": "cannot_continue",
            "accuracy_metric": None,
            "accuracy_claim_allowed": False,
        },
    }


def _load_resume_results(
    checkpoint: Path,
    *,
    checkpoint_identity: dict[str, Any],
    allowed_keys: set[tuple[str, int]],
) -> list[dict[str, Any]]:
    payload = json.loads(checkpoint.read_text(encoding="utf-8"))
    if payload.get("schema_version") != "tier-d-checkpoint-v2":
        raise ValueError("checkpoint_schema_version_mismatch")
    if payload.get("checkpoint_identity") != checkpoint_identity:
        raise ValueError("checkpoint_identity_mismatch")
    results = list(payload.get("results") or [])
    completed_keys = [(str(item.get("scenario_uid") or ""), int(item.get("trial") or 0)) for item in results]
    if len(completed_keys) != len(set(completed_keys)) or not set(completed_keys).issubset(allowed_keys):
        raise ValueError("checkpoint_results_invalid")
    return results


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
        replies = [str((turn.get("observation") or {}).get("reply") or "").strip() for turn in result.get("turns") or []]
        for previous, current in zip(replies, replies[1:]):
            transition_count += 1
            if previous and previous == current:
                repeated_reply_count += 1
    gap_counts: dict[str, int] = {}
    action_status_counts: dict[str, int] = {}
    shadow_available_count = 0
    for turn in turns:
        shadow = ((turn.get("observation") or {}).get("evidence_action_shadow") or {})
        if not shadow.get("available"):
            continue
        shadow_available_count += 1
        gap = str((shadow.get("evidence_funnel") or {}).get("gap_classification") or "unknown")
        gap_counts[gap] = gap_counts.get(gap, 0) + 1
        status = str((shadow.get("action_policy") or {}).get("status") or "unknown")
        action_status_counts[status] = action_status_counts.get(status, 0) + 1
    return {
        "agent_latency_p50_ms": percentile(0.5),
        "agent_latency_p95_ms": percentile(0.95),
        "can_send_turn_count": sum(bool((turn.get("observation") or {}).get("can_send")) for turn in turns),
        "requires_human_review_turn_count": sum(bool((turn.get("observation") or {}).get("requires_human_review")) for turn in turns),
        "selected_evidence_turn_count": sum(int((turn.get("observation") or {}).get("selected_evidence_count") or 0) > 0 for turn in turns),
        "selected_evidence_total_count": sum(int((turn.get("observation") or {}).get("selected_evidence_count") or 0) for turn in turns),
        "final_audit_failed_turn_count": sum(not bool(((turn.get("observation") or {}).get("final_answer_audit") or {}).get("passed", True)) for turn in turns),
        "repeated_consecutive_reply_count": repeated_reply_count,
        "reply_transition_count": transition_count,
        "consecutive_reply_repetition_rate": round(repeated_reply_count / transition_count, 4) if transition_count else None,
        "evidence_action_shadow_turn_count": shadow_available_count,
        "evidence_gap_classification_counts": dict(sorted(gap_counts.items())),
        "action_policy_status_counts": dict(sorted(action_status_counts.items())),
    }


def _offline_recomputed_score(result: dict[str, Any]) -> dict[str, Any]:
    score = result.get("score") or {}
    contract = result.get("evaluation_contract") or {}
    transcript_grade = score.get("transcript_action_grade") or {}
    blockers = recompute_tier_d_blocking_reasons(
        must_handoff=bool(contract.get("must_handoff")),
        turns=list(result.get("turns") or []),
        transcript_grade=transcript_grade,
    )
    action_rate = transcript_grade.get("action_coverage_rate")
    buyer_outcome = (
        score.get("terminal_buyer_state") in {"satisfied", "handoff_accepted"}
        and score.get("terminal_stop_reason") in {"resolved", "handoff_accepted"}
    )
    contract_passed = not blockers
    return {
        "blocking_reasons": blockers,
        "contract_passed": contract_passed,
        "buyer_outcome_passed": buyer_outcome,
        "passed": contract_passed and buyer_outcome and action_rate == 1.0,
    }


def _score_consistency_findings(report: dict[str, Any]) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    for result in report.get("results") or []:
        expected = _offline_recomputed_score(result)
        score = result.get("score") or {}
        mismatched = sorted(
            key for key, value in expected.items()
            if score.get(key) != value
        )
        if mismatched:
            findings.append({
                "scenario_uid": str(result.get("scenario_uid") or ""),
                "trial": int(result.get("trial") or 0),
                "fields": mismatched,
            })
    return findings


def _failure_classification(result: dict[str, Any]) -> list[dict[str, Any]]:
    """Classify evaluator-visible failures without scenario or product rules."""
    score = result.get("score") if isinstance(result.get("score"), dict) else {}
    turns = list(result.get("turns") or [])
    classified: dict[str, dict[str, Any]] = {}

    def add(reason: str, turn_numbers: list[int] | None = None) -> None:
        row = classified.setdefault(reason, {"reason": reason, "turn_numbers": [], "evidence_summary": []})
        row["turn_numbers"] = sorted(set(row["turn_numbers"]).union(turn_numbers or []))

    direct = {
        "unsupported_media_promise",
        "required_handoff_missing",
    }
    for reason in score.get("blocking_reasons") or []:
        if reason in direct:
            add(str(reason), list(range(1, len(turns) + 1)))

    replies: list[str] = []
    for index, turn in enumerate(turns, start=1):
        observation = turn.get("observation") if isinstance(turn.get("observation"), dict) else {}
        reply = str(observation.get("reply") or "").strip()
        replies.append(reply)
        evidence = list(observation.get("selected_evidence_summary") or [])
        if observation.get("can_send") and any(bool(item.get("is_placeholder")) for item in evidence):
            add("placeholder_fact_auto_send", [index])
        audit_issues = {str(item) for item in ((observation.get("final_answer_audit") or {}).get("issues") or [])}
        unsupported_fact = any(item.startswith("unsupported_") and "media" not in item for item in audit_issues)
        if unsupported_fact and not evidence:
            add("evidence_free_product_claim", [index])
        semantic_audit = observation.get("final_semantic_fit_audit") or {}
        if semantic_audit.get("passed") is False or semantic_audit.get("issues"):
            add("query_reply_mismatch", [index])
        for row in classified.values():
            if index in row["turn_numbers"] and evidence and not row["evidence_summary"]:
                row["evidence_summary"] = evidence[:3]

    repeated_turns = [
        index + 1
        for index, (previous, current) in enumerate(zip(replies, replies[1:]), start=1)
        if previous and previous == current
    ]
    if repeated_turns:
        add("repeated_generic_reply", repeated_turns)
    if (
        len(turns) > 1
        and not result.get("simulator_error")
        and score.get("terminal_buyer_state") == "blocked"
        and score.get("terminal_stop_reason") == "cannot_continue"
    ):
        add("context_followup_failure", list(range(1, len(turns) + 1)))
    transcript_grade = score.get("transcript_action_grade") or {}
    if transcript_grade.get("uncovered_action_ids"):
        add("action_not_completed")
    return [classified[key] for key in sorted(classified)]


def _failure_classification_summary(results: list[dict[str, Any]]) -> dict[str, Any]:
    counts: dict[str, int] = {}
    representatives: dict[str, dict[str, Any]] = {}
    for result in results:
        rows = _failure_classification(result)
        result["failure_classification"] = rows
        for row in rows:
            reason = row["reason"]
            counts[reason] = counts.get(reason, 0) + 1
            representatives.setdefault(reason, {
                "scenario_uid": str(result.get("scenario_uid") or ""),
                "trial": int(result.get("trial") or 0),
                "turn_numbers": row["turn_numbers"],
                "evidence_summary": row["evidence_summary"],
            })
    return {"counts": dict(sorted(counts.items())), "representatives": dict(sorted(representatives.items()))}


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
    parser.add_argument("--runtime-timeout", type=int, default=10)
    parser.add_argument("--expected-api-commit", default="")
    parser.add_argument("--expected-source-tree-sha256", default="")
    parser.add_argument("--expected-runner-source-tree-sha256", default="")
    parser.add_argument("--expected-formal-model", default="")
    parser.add_argument("--expected-feature-flags-json", default="")
    parser.add_argument("--grader-qualification-report", default="")
    parser.add_argument("--simulator-qualification-report", default="")
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--checkpoint", default="")
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args(argv)
    _load_env_file(args.env_file)

    boot_runner_hash = _runner_source_tree_sha256()
    runner_dirty = bool(_git_text("status", "--porcelain"))
    if runner_dirty and not args.expected_runner_source_tree_sha256:
        print(json.dumps({"error": "dirty_runner_requires_expected_source_tree_sha256"}, ensure_ascii=False))
        return 2
    if args.expected_runner_source_tree_sha256 and boot_runner_hash != args.expected_runner_source_tree_sha256:
        print(json.dumps({"error": "expected_runner_source_tree_sha256_mismatch"}, ensure_ascii=False))
        return 2

    runtime = _runtime_metadata(args.analyze_url, args.runtime_timeout)
    if runtime.get("status") != "available":
        print(json.dumps({"error": "runtime_not_ready", "runtime": runtime}, ensure_ascii=False))
        return 2
    if args.expected_api_commit and runtime.get("runtime_commit") != args.expected_api_commit:
        print(json.dumps({"error": "expected_api_commit_mismatch", "runtime": runtime}, ensure_ascii=False))
        return 2
    if runtime.get("source_tree_drift") is not False:
        print(json.dumps({"error": "runtime_source_tree_drift", "runtime": runtime}, ensure_ascii=False))
        return 2
    if runtime.get("worktree_dirty") is True and not args.expected_source_tree_sha256:
        print(json.dumps({"error": "dirty_runtime_requires_expected_source_tree_sha256", "runtime": runtime}, ensure_ascii=False))
        return 2
    if args.expected_source_tree_sha256 and runtime.get("boot_source_tree_sha256") != args.expected_source_tree_sha256:
        print(json.dumps({"error": "expected_source_tree_sha256_mismatch", "runtime": runtime}, ensure_ascii=False))
        return 2
    if args.expected_formal_model and runtime.get("formal_model") != args.expected_formal_model:
        print(json.dumps({"error": "expected_formal_model_mismatch", "runtime": runtime}, ensure_ascii=False))
        return 2
    if args.expected_feature_flags_json:
        try:
            expected_flags = json.loads(args.expected_feature_flags_json)
        except json.JSONDecodeError:
            print(json.dumps({"error": "expected_feature_flags_json_invalid"}, ensure_ascii=False))
            return 2
        if not isinstance(expected_flags, dict) or runtime.get("feature_flags") != expected_flags:
            print(json.dumps({"error": "expected_feature_flags_mismatch", "runtime": runtime}, ensure_ascii=False))
            return 2

    grader = TierDTranscriptGrader()
    required_env = {
        "simulator_key": os.environ.get("COPILOT_CUSTOMER_SIMULATOR_API_KEY", ""),
        "simulator_base": os.environ.get("COPILOT_CUSTOMER_SIMULATOR_API_BASE", ""),
        "simulator_model": os.environ.get("COPILOT_CUSTOMER_SIMULATOR_MODEL", ""),
    }
    simulator_candidate = CustomerSimulator(
        api_key=required_env["simulator_key"],
        api_base=required_env["simulator_base"],
        model=required_env["simulator_model"],
        timeout=args.simulator_timeout,
    )
    provider_independence = _provider_independence(_provider_identities(
        runtime,
        simulator_metadata=simulator_candidate.metadata(),
        grader_metadata=grader.metadata(),
    ))
    if not provider_independence["passed"]:
        print(json.dumps({
            "error": "provider_independence_failed",
            "blocked_by": "provider_independence",
            "conflicting_roles": provider_independence["conflicts"],
            "unknown_roles": provider_independence["unknown_roles"],
            "provider_identities": provider_independence["identities"],
        }, ensure_ascii=False))
        return 2
    formal_provider_probe = _formal_provider_probe(runtime, args.runtime_timeout)
    if formal_provider_probe["status"] != "available":
        print(json.dumps({
            "error": "formal_provider_not_available",
            "formal_provider_probe": formal_provider_probe,
        }, ensure_ascii=False))
        return 2
    if not grader.ready():
        print(json.dumps({"error": "grader_not_qualified", "grader": grader.metadata()}, ensure_ascii=False))
        return 2
    if not simulator_candidate.ready():
        print(json.dumps({"error": "simulator_not_qualified", "simulator": simulator_candidate.metadata()}, ensure_ascii=False))
        return 2
    if not args.simulator_qualification_report:
        print(json.dumps({"error": "simulator_qualification_report_required"}, ensure_ascii=False))
        return 2
    simulator_qualification_path = Path(args.simulator_qualification_report)
    try:
        _load_simulator_qualification(simulator_qualification_path, simulator_candidate.metadata())
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False))
        return 2
    if not args.grader_qualification_report:
        print(json.dumps({"error": "grader_qualification_report_required"}, ensure_ascii=False))
        return 2
    qualification_path = Path(args.grader_qualification_report)
    try:
        grader_qualification = _load_grader_qualification(
            qualification_path,
            grader.metadata(),
            workers=max(1, min(args.workers, 4)),
        )
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False))
        return 2
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

    scenarios = list(dataset.get("scenarios") or [])
    if args.limit:
        scenarios = scenarios[:args.limit]
    source_by_scenario, missing_source_count, ambiguous_source_count = _resolve_sources(
        scenarios,
        samples,
        os.environ.get("COPILOT_GOLD_SET_HMAC_KEY", ""),
    )
    if missing_source_count or ambiguous_source_count or len(source_by_scenario) != len(scenarios):
        print(json.dumps({
            "error": "tier_d_source_resolution_failed",
            "scenario_count": len(scenarios),
            "resolved_count": len(source_by_scenario),
            "source_missing_count": missing_source_count,
            "source_ambiguous_count": ambiguous_source_count,
        }, ensure_ascii=False))
        return 2
    try:
        runner_identity = _runner_identity(
            grader_qualification_report=qualification_path,
            simulator_qualification_report=simulator_qualification_path,
            dataset_manifest=dict(dataset.get("manifest") or {}),
        )
    except (OSError, ValueError) as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False))
        return 2
    runner_identity["boot_source_tree_sha256"] = boot_runner_hash
    jobs: list[tuple[dict[str, Any], dict[str, Any], int]] = []
    for scenario in scenarios:
        source = source_by_scenario.get(str(scenario.get("scenario_uid") or ""))
        if source is None:
            continue
        for trial in range(1, max(1, args.trials) + 1):
            jobs.append((scenario, source, trial))

    checkpoint = Path(args.checkpoint) if args.checkpoint else Path(args.json_output).with_suffix(".checkpoint.json")
    checkpoint_identity = {
        key: runner_identity[key]
        for key in (
            "git_commit",
            "boot_source_tree_sha256",
            "evaluator_schema_version",
            "grader_qualification_report_sha256",
            "simulator_qualification_report_sha256",
            "dataset_manifest_sha256",
        )
    }
    results: list[dict[str, Any]] = []
    if args.resume:
        try:
            allowed_keys = {(str(item[0].get("scenario_uid") or ""), item[2]) for item in jobs}
            results = _load_resume_results(
                checkpoint,
                checkpoint_identity=checkpoint_identity,
                allowed_keys=allowed_keys,
            )
            completed_key_set = {
                (str(item.get("scenario_uid") or ""), int(item.get("trial") or 0))
                for item in results
            }
            jobs = [job for job in jobs if (str(job[0].get("scenario_uid") or ""), job[2]) not in completed_key_set]
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            print(json.dumps({"error": str(exc)}, ensure_ascii=False))
            return 2

    def checkpoint_payload() -> dict[str, Any]:
        return {
            "schema_version": "tier-d-checkpoint-v2",
            "checkpoint_identity": checkpoint_identity,
            "completed_trial_count": len(results),
            "results": sorted(results, key=lambda item: (item["scenario_uid"], item["trial"])),
        }

    def run_job(job: tuple[dict[str, Any], dict[str, Any], int]) -> dict[str, Any]:
        scenario, source, trial = job
        simulator = CustomerSimulator(
            api_key=required_env["simulator_key"],
            api_base=required_env["simulator_base"],
            model=required_env["simulator_model"],
            timeout=args.simulator_timeout,
        )
        try:
            return _run_trial(
                scenario=scenario,
                source=source,
                trial=trial,
                simulator=simulator,
                analyze_url=args.analyze_url,
                agent_timeout=args.agent_timeout,
                max_generated_turns=max(0, args.max_generated_turns),
                grader=grader,
            )
        except Exception as exc:
            return _trial_execution_failure(scenario, trial, exc)

    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, min(args.workers, 4))) as executor:
        futures = [executor.submit(run_job, job) for job in jobs]
        for future in concurrent.futures.as_completed(futures):
            results.append(future.result())
            _write_json_atomic(checkpoint, checkpoint_payload())
    results.sort(key=lambda item: (item["scenario_uid"], item["trial"]))

    summary = summarize_simulation_results(results)
    summary.update({
        "source_missing_count": missing_source_count,
        "source_ambiguous_count": ambiguous_source_count,
        "safe_source_exclusion_count": missing_source_count + ambiguous_source_count,
        "simulator_error_count": sum(bool(item.get("simulator_error")) for item in results),
        "grader_error_count": sum(bool(item.get("grader_error")) for item in results),
        "trial_execution_error_count": sum(bool(item.get("trial_execution_error")) for item in results),
        "agent_turn_count": sum(int(item.get("executed_agent_turn_count") or 0) for item in results),
    })
    summary.update(_turn_metrics(results))
    failure_classification = _failure_classification_summary(results)
    _write_json_atomic(checkpoint, checkpoint_payload())
    grader_metadata = grader.metadata()
    end_runner_hash = _runner_source_tree_sha256()
    runner_identity["end_source_tree_sha256"] = end_runner_hash
    runner_identity["source_tree_drift"] = end_runner_hash != boot_runner_hash
    report = {
        "schema_version": "long-conversation-simulation-report-v3",
        "evaluation_tier": "tier_d_simulated_multiturn",
        "dataset_manifest": dataset.get("manifest") or {},
        "execution_path": "ai_buyer_to_http_formal_analysis_pipeline",
        "metric_boundary": {
            "exploratory_pass_rate_only": True,
            "real_customer_accuracy_measured": False,
            "unapproved_product_claims_scored_as_truth": False,
            "grader_type": "strict_schema_transcript_grader",
            "simulator_observations_are_diagnostic_only": True,
            "grader_execution_profile": grader_qualification["selected_execution_profile"],
            "per_turn_semantic_grader_calls": 0,
            "transcript_semantic_grader_calls_per_trial_max": 1,
        },
        "runtime": _report_runtime(runtime),
        "runner_identity": runner_identity,
        "uncommitted_candidate": runtime.get("worktree_dirty") is True,
        "source_database": _source_db_fingerprint(args.source_db),
        "provider": {
            "identities": provider_independence["identities"],
            "independence": provider_independence,
            "formal_provider_probe": formal_provider_probe,
            "grader": grader_metadata,
            "credentials_reported": False,
        },
        "summary": summary,
        "failure_classification": failure_classification,
        "results": results,
    }
    prewrite_consistency_findings = _score_consistency_findings(report)
    checkpoint_payload = json.loads(checkpoint.read_text(encoding="utf-8"))
    checkpoint_matches = _canonical_hash(checkpoint_payload.get("results") or []) == _canonical_hash(results)
    report["integrity"] = {
        "score_recomputation_status": "passed" if not prewrite_consistency_findings else "failed",
        "score_consistency_finding_count": len(prewrite_consistency_findings),
        "checkpoint_matches_report": checkpoint_matches,
    }
    output = Path(args.json_output)
    _write_json_atomic(output, report)
    persisted_report = json.loads(output.read_text(encoding="utf-8"))
    consistency_findings = _score_consistency_findings(persisted_report)
    print(json.dumps(summary, ensure_ascii=False))
    expected_trial_count = len(scenarios) * max(1, args.trials)
    infrastructure_ok = (
        bool(results)
        and len(results) == expected_trial_count
        and not runner_identity["source_tree_drift"]
        and not consistency_findings
        and checkpoint_matches
        and not any(item.get("simulator_error") for item in results)
        and not any(item.get("grader_error") for item in results)
        and not any(item.get("trial_execution_error") for item in results)
        and not any(
            str(reason).startswith("grader_")
            for item in results
            for reason in ((item.get("score") or {}).get("blocking_reasons") or [])
        )
    )
    if not infrastructure_ok:
        print(json.dumps({
            "error": "tier_d_infrastructure_validation_failed",
            "expected_trial_count": expected_trial_count,
            "actual_trial_count": len(results),
            "runner_source_tree_drift": runner_identity["source_tree_drift"],
            "score_consistency_findings": consistency_findings,
            "checkpoint_matches_report": checkpoint_matches,
            "simulator_error_count": sum(bool(item.get("simulator_error")) for item in results),
        }, ensure_ascii=False))
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
