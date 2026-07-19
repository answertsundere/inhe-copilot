"""
Runtime Version API — 提供运行版本信息，解决版本冲突。
"""

import os
import hashlib
import subprocess
import sys
import time as _time
from pathlib import Path

from flask import Blueprint, jsonify

runtime_bp = Blueprint("runtime", __name__)

_BOOT_TIME = _time.strftime("%Y-%m-%d %H:%M:%S")
_PID = os.getpid()
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_RUNTIME_SOURCE_ROOTS = ("app",)
_RUNTIME_SOURCE_FILES = ("run_prod.py", "requirements.txt")


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


def _runtime_source_files() -> list[Path]:
    files: list[Path] = []
    for root_name in _RUNTIME_SOURCE_ROOTS:
        root = _PROJECT_ROOT / root_name
        if root.exists():
            files.extend(path for path in root.rglob("*.py") if "__pycache__" not in path.parts)
    files.extend(_PROJECT_ROOT / name for name in _RUNTIME_SOURCE_FILES if (_PROJECT_ROOT / name).is_file())
    return sorted(files, key=lambda path: path.relative_to(_PROJECT_ROOT).as_posix())


def _source_tree_sha256() -> str:
    """Fingerprint executable source only; never include DBs, outputs, or secrets."""
    digest = hashlib.sha256()
    try:
        for path in _runtime_source_files():
            digest.update(path.relative_to(_PROJECT_ROOT).as_posix().encode("utf-8"))
            digest.update(b"\0")
            digest.update(path.read_bytes())
            digest.update(b"\0")
    except OSError:
        return "unavailable"
    return digest.hexdigest()


def _runtime_worktree_dirty() -> bool | None:
    """Inspect executable source paths only, excluding generated runtime data."""
    try:
        output = subprocess.check_output(
            ["git", "-C", str(_PROJECT_ROOT), "status", "--porcelain", "--", *_RUNTIME_SOURCE_ROOTS, *_RUNTIME_SOURCE_FILES],
            text=True,
            encoding="utf-8",
            stderr=subprocess.DEVNULL,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return bool(output.strip())


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


def _capture_boot_build_identity() -> dict[str, str | bool | None | dict[str, bool]]:
    """Freeze the executable identity once when this process imports routes."""
    from app.config import APP_VERSION, LLM_API_BASE, LLM_MODEL
    from app.services.strict_decision_provider_service import safe_provider_identity

    dirty = _runtime_worktree_dirty()
    source_hash = _source_tree_sha256()
    if dirty is True:
        identity_status = "dirty_candidate"
    elif dirty is False and source_hash != "unavailable":
        identity_status = "clean_commit"
    else:
        identity_status = "source_identity_unavailable"
    return {
        "app_version": APP_VERSION,
        "runtime_commit": _git_metadata("rev-parse", "HEAD"),
        "formal_model": str(LLM_MODEL or ""),
        "formal_provider_identity": safe_provider_identity(
            provider_name="formal_agent",
            api_base=str(LLM_API_BASE or ""),
            model=str(LLM_MODEL or ""),
        ),
        "feature_flags": _feature_flags(),
        "boot_worktree_dirty": dirty,
        "boot_source_tree_sha256": source_hash,
        "build_identity_status": identity_status,
    }


_BOOT_BUILD_IDENTITY = _capture_boot_build_identity()


def _runtime_identity() -> dict[str, str | bool | None | dict[str, bool]]:
    """Report frozen process identity and detect source changes after boot."""
    boot = dict(_BOOT_BUILD_IDENTITY)
    boot_hash = str(boot.get("boot_source_tree_sha256") or "")
    current_hash = _source_tree_sha256()
    current_dirty = _runtime_worktree_dirty()
    comparable_hashes = bool(boot_hash and boot_hash != "unavailable" and current_hash != "unavailable")
    source_drift = (boot_hash != current_hash) if comparable_hashes else None
    return {
        "app_version": str(boot.get("app_version") or ""),
        "runtime_commit": str(boot.get("runtime_commit") or "unavailable"),
        "formal_model": str(boot.get("formal_model") or ""),
        "formal_provider_identity": dict(boot.get("formal_provider_identity") or {}),
        "feature_flags": dict(boot.get("feature_flags") or {}),
        # Compatibility fields deliberately identify the booted process.
        "worktree_dirty": boot.get("boot_worktree_dirty"),
        "source_tree_sha256": boot_hash,
        "boot_worktree_dirty": boot.get("boot_worktree_dirty"),
        "boot_source_tree_sha256": boot_hash,
        "current_source_tree_sha256": current_hash,
        "current_worktree_dirty": current_dirty,
        "source_tree_drift": source_drift,
        "build_identity_status": str(boot.get("build_identity_status") or "source_identity_unavailable"),
    }


@runtime_bp.route("/api/runtime/version", methods=["GET"])
def runtime_version():
    from app.services.runtime_knowledge_readiness_service import RuntimeKnowledgeReadinessService

    readiness = _with_admin_auth_readiness(RuntimeKnowledgeReadinessService().inspect())
    return jsonify({
        **_runtime_identity(),
        "readiness": public_readiness_payload(readiness),
    })


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
        },
        "readiness": readiness,
    })
