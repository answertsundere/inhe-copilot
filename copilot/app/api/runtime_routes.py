"""
Runtime Version API — 提供运行版本信息，解决版本冲突。
"""

import os
import subprocess
import time as _time
from pathlib import Path

from flask import Blueprint, jsonify

runtime_bp = Blueprint("runtime", __name__)

_BOOT_TIME = _time.strftime("%Y-%m-%d %H:%M:%S")
_PID = os.getpid()
_PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _with_admin_auth_readiness(readiness: dict) -> dict:
    """Expose only non-sensitive admin-auth status and fail readiness closed."""
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


@runtime_bp.route("/api/runtime/version", methods=["GET"])
def runtime_version():
    from app.config import (
        GRAPH_VERSION, PROMPT_VERSION, ROUTING_CONFIG_VERSION,
        TOOL_REGISTRY_VERSION, APP_VERSION, WEB_HOST, WEB_PORT,
    )
    import sys

    entrypoint = "unknown"
    main_module = sys.modules.get("__main__")
    if main_module and hasattr(main_module, "__file__") and main_module.__file__:
        fname = os.path.basename(main_module.__file__)
        entrypoint = fname

    from app.services.runtime_knowledge_readiness_service import RuntimeKnowledgeReadinessService

    readiness = _with_admin_auth_readiness(RuntimeKnowledgeReadinessService().inspect())
    return jsonify({
        "app_version": APP_VERSION,
        "graph_version": GRAPH_VERSION,
        "prompt_version": PROMPT_VERSION,
        "routing_config_version": ROUTING_CONFIG_VERSION,
        "tool_registry_version": TOOL_REGISTRY_VERSION,
        "pid": _PID,
        "boot_time": _BOOT_TIME,
        "host": WEB_HOST,
        "port": WEB_PORT,
        "entrypoint": entrypoint,
        "runtime_commit": _git_metadata("rev-parse", "HEAD"),
        "branch": _git_metadata("branch", "--show-current"),
        "feature_flags": _feature_flags(),
        "readiness": readiness,
        "execution_debug_enabled": True,
        "bad_case_enabled": True,
    })


@runtime_bp.route("/api/runtime/readiness", methods=["GET"])
def runtime_readiness():
    from app.services.runtime_knowledge_readiness_service import RuntimeKnowledgeReadinessService

    readiness = _with_admin_auth_readiness(RuntimeKnowledgeReadinessService().inspect())
    return jsonify(readiness), 200 if readiness["ready"] else 503
