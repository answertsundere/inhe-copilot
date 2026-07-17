"""
Runtime Version API — 提供运行版本信息，解决版本冲突。
"""

import os
import subprocess
import sys
import time as _time
from pathlib import Path

from flask import Blueprint, jsonify

runtime_bp = Blueprint("runtime", __name__)

_BOOT_TIME = _time.strftime("%Y-%m-%d %H:%M:%S")
_PID = os.getpid()
_PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _with_admin_auth_readiness(readiness: dict) -> dict:
    """Build the detailed, admin-only runtime readiness contract."""
    from app.api.admin_auth import admin_auth_readiness

    result = dict(readiness)
    result["reasons"] = list(readiness.get("reasons") or [])
    auth = admin_auth_readiness()
    result.update(auth)
    if not auth["admin_auth_ready"]:
        result["ready"] = False
        result["status"] = "not_ready"
        if auth["reason"] and auth["reason"] not in result["reasons"]:
            result["reasons"].append(auth["reason"])
    return result


def public_readiness_payload(readiness: dict) -> dict:
    """Return a stable public readiness projection without infrastructure detail."""
    safe_reasons = {
        "knowledge_db_missing",
        "knowledge_db_unreadable",
        "knowledge_db_query_failed",
        "knowledge_entries_empty",
        "knowledge_chunks_empty",
        "kb_qa_empty",
        "knowledge_db_changed_during_fingerprint",
        "admin_auth_configuration_missing",
        "browser_origin_configuration_missing",
        "audit_redaction_configuration_missing",
        "route_policy_governance_failed",
        "admin_auth_mode_not_ready",
        "development_auth_forbidden_in_production",
        "role_map_missing",
        "role_map_invalid",
        "role_map_empty",
    }
    reasons = []
    for reason in readiness.get("reasons") or []:
        normalized = str(reason or "").strip()
        if normalized.startswith("required_table_missing:"):
            normalized = "knowledge_schema_incomplete"
        elif normalized not in safe_reasons:
            normalized = "runtime_not_ready"
        if normalized and normalized not in reasons:
            reasons.append(normalized)
    return {
        "ready": bool(readiness.get("ready")),
        "status": "ready" if readiness.get("ready") else "not_ready",
        "reasons": reasons,
    }


def _git_metadata(*args: str) -> str:
    """Read deployment metadata without exposing any runtime configuration."""
    try:
        return subprocess.check_output(
            ["git", "-C", str(_PROJECT_ROOT), *args],
            text=True,
            encoding="utf-8",
            stderr=subprocess.DEVNULL,
        ).strip() or "unavailable"
    except (OSError, subprocess.SubprocessError):
        return "unavailable"


def _feature_flags() -> dict[str, bool]:
    from app.config import COPILOT_DECISION_LLM_QUALIFIED, COPILOT_VLM_ENABLED

    def enabled(name: str) -> bool:
        return str(os.getenv(name, "")).strip().lower() in {"1", "true", "yes", "on"}

    return {
        "formal_evidence_convergence": enabled("COPILOT_FORMAL_EVIDENCE_CONVERGENCE_ENABLED"),
        "answer_memory_shadow": enabled("COPILOT_ANSWER_MEMORY_SHADOW_ENABLED"),
        "grounded_reasoning_shadow": enabled("COPILOT_GROUNDED_REASONING_SHADOW_ENABLED"),
        "llm_decision_shadow": enabled("COPILOT_LLM_DECISION_SHADOW_ENABLED"),
        "strict_decision_provider_qualified": bool(COPILOT_DECISION_LLM_QUALIFIED),
        "vlm": bool(COPILOT_VLM_ENABLED),
    }


def _runtime_identity() -> dict[str, str]:
    from app.config import APP_VERSION

    return {
        "app_version": APP_VERSION,
        "runtime_commit": _git_metadata("rev-parse", "HEAD"),
    }


@runtime_bp.route("/api/runtime/version", methods=["GET"])
def runtime_version():
    from app.services.runtime_knowledge_readiness_service import RuntimeKnowledgeReadinessService

    readiness = _with_admin_auth_readiness(RuntimeKnowledgeReadinessService().inspect())
    return jsonify({**_runtime_identity(), "readiness": public_readiness_payload(readiness)})


@runtime_bp.route("/api/runtime/readiness", methods=["GET"])
def runtime_readiness():
    from app.services.runtime_knowledge_readiness_service import RuntimeKnowledgeReadinessService

    readiness = public_readiness_payload(
        _with_admin_auth_readiness(RuntimeKnowledgeReadinessService().inspect())
    )
    return jsonify(readiness), 200 if readiness["ready"] else 503


@runtime_bp.route("/api/admin/runtime/diagnostics", methods=["GET"])
def runtime_diagnostics():
    """Return detailed runtime state only after the app-level admin RBAC gate."""
    from app.config import GRAPH_VERSION, PROMPT_VERSION, ROUTING_CONFIG_VERSION, TOOL_REGISTRY_VERSION
    from app.services.runtime_knowledge_readiness_service import RuntimeKnowledgeReadinessService

    readiness = _with_admin_auth_readiness(RuntimeKnowledgeReadinessService().inspect())
    return jsonify({
        "runtime": {
            **_runtime_identity(),
            "entrypoint": os.path.basename(getattr(sys.modules.get("__main__"), "__file__", "") or "unknown"),
            "boot_time": _BOOT_TIME,
            "pipeline_versions": {
                "graph": GRAPH_VERSION,
                "prompt": PROMPT_VERSION,
                "routing": ROUTING_CONFIG_VERSION,
                "tool_registry": TOOL_REGISTRY_VERSION,
            },
            "feature_flags": _feature_flags(),
        },
        "readiness": readiness,
    })
