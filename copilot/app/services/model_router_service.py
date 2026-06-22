"""Central model alias routing for Copilot model calls.

Business code should ask for a logical alias such as ``judge_model`` or
``fast_model``. This module resolves that alias to provider/model/base/key-env
metadata from environment variables while preserving legacy COPILOT_* fallbacks.
"""

from __future__ import annotations

import os
from typing import Any

from app import config


MODEL_ALIASES = {
    "fast_model": {
        "prefix": "COPILOT_FAST_MODEL",
        "legacy": "llm",
        "fallback_aliases": ["strong_model"],
        "default_provider": "openai_compatible",
        "timeout_seconds": 20,
        "max_retries": 1,
    },
    "strong_model": {
        "prefix": "COPILOT_STRONG_MODEL",
        "legacy": "llm",
        "fallback_aliases": [],
        "default_provider": "openai_compatible",
        "timeout_seconds": 45,
        "max_retries": 1,
    },
    "judge_model": {
        "prefix": "COPILOT_JUDGE_MODEL",
        "legacy": "llm",
        "fallback_aliases": ["strong_model"],
        "default_provider": "openai_compatible",
        "timeout_seconds": 30,
        "max_retries": 1,
    },
    "vision_model": {
        "prefix": "COPILOT_VISION_MODEL",
        "legacy": "vlm",
        "fallback_aliases": [],
        "default_provider": "openai_compatible",
        "timeout_seconds": 30,
        "max_retries": 0,
    },
    "embedding_model": {
        "prefix": "COPILOT_EMBEDDING_MODEL",
        "legacy": "embedding",
        "fallback_aliases": [],
        "default_provider": "openai_compatible",
        "timeout_seconds": 30,
        "max_retries": 1,
    },
}


def resolve_model(alias: str) -> dict[str, Any]:
    alias = _normalize_alias(alias)
    spec = MODEL_ALIASES[alias]
    prefix = spec["prefix"]
    provider = _env_or_empty(f"{prefix}_PROVIDER")
    model = _env_or_empty(f"{prefix}_NAME")
    api_base = _env_or_empty(f"{prefix}_API_BASE")
    api_key_env = f"{prefix}_API_KEY"
    api_key = _env_or_empty(api_key_env)

    source = "alias"
    if not (model or api_base or api_key):
        legacy = _legacy_config(spec["legacy"])
        provider = legacy["provider"]
        model = legacy["model"]
        api_base = legacy["api_base"]
        api_key_env = legacy["api_key_env"]
        api_key = legacy["api_key"]
        source = legacy["source"]
    else:
        provider = provider or spec["default_provider"]

    return {
        "alias": alias,
        "provider": provider or spec["default_provider"],
        "api_base": api_base,
        "api_key_env": api_key_env,
        "model": model,
        "timeout_seconds": _int_env(f"{prefix}_TIMEOUT_SECONDS", spec["timeout_seconds"]),
        "max_retries": _int_env(f"{prefix}_MAX_RETRIES", spec["max_retries"]),
        "fallback_aliases": get_fallback_chain(alias),
        "enabled": bool(api_key and model and api_base),
        "source": source,
    }


def resolve_model_api_key(alias: str) -> str:
    resolved = resolve_model(alias)
    key_env = str(resolved.get("api_key_env") or "")
    if key_env:
        value = _env_or_empty(key_env)
        if value:
            return value
    legacy = MODEL_ALIASES[_normalize_alias(alias)]["legacy"]
    return _legacy_config(legacy)["api_key"]


def get_fallback_chain(alias: str) -> list[str]:
    alias = _normalize_alias(alias)
    seen: set[str] = set()
    chain: list[str] = []

    def visit(current: str) -> None:
        for fallback in MODEL_ALIASES[current]["fallback_aliases"]:
            fallback = _normalize_alias(fallback)
            if fallback in seen or fallback == alias:
                continue
            seen.add(fallback)
            chain.append(fallback)
            visit(fallback)

    visit(alias)
    return chain


def _normalize_alias(alias: str) -> str:
    normalized = str(alias or "strong_model").strip()
    if normalized not in MODEL_ALIASES:
        return "strong_model"
    return normalized


def _legacy_config(kind: str) -> dict[str, str]:
    if kind == "vlm":
        return {
            "provider": "openai_compatible",
            "model": _env_or_empty("COPILOT_VLM_MODEL") or config.COPILOT_VLM_MODEL,
            "api_base": _env_or_empty("COPILOT_VLM_API_BASE") or config.COPILOT_VLM_API_BASE,
            "api_key_env": "COPILOT_VLM_API_KEY",
            "api_key": _env_or_empty("COPILOT_VLM_API_KEY") or config.COPILOT_VLM_API_KEY,
            "source": "legacy_vlm",
        }
    if kind == "embedding":
        return {
            "provider": "openai_compatible",
            "model": _env_or_empty("COPILOT_EMBEDDING_MODEL") or config.EMBEDDING_MODEL,
            "api_base": _env_or_empty("COPILOT_EMBEDDING_API_BASE") or config.EMBEDDING_API_BASE,
            "api_key_env": "COPILOT_EMBEDDING_API_KEY",
            "api_key": _env_or_empty("COPILOT_EMBEDDING_API_KEY") or config.EMBEDDING_API_KEY,
            "source": "legacy_embedding",
        }
    return {
        "provider": "openai_compatible",
        "model": _env_or_empty("COPILOT_LLM_MODEL") or config.LLM_MODEL,
        "api_base": _env_or_empty("COPILOT_LLM_API_BASE") or config.LLM_API_BASE,
        "api_key_env": "COPILOT_LLM_API_KEY",
        "api_key": _env_or_empty("COPILOT_LLM_API_KEY") or config.LLM_API_KEY,
        "source": "legacy_llm",
    }


def _env_or_empty(name: str) -> str:
    return str(os.environ.get(name) or "").strip()


def _int_env(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return int(default)
