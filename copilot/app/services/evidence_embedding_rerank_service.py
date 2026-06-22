"""Embedding rerank scoring contract for evidence candidates.

This module only produces semantic similarity scores. It does not decide user
intent, evidence roles, fact-type compatibility, or media sendability.
"""

from __future__ import annotations

import re
from typing import Any

from app import config


def score_evidence_semantic_similarity(
    *,
    query_text: str,
    query_fact_type: str,
    required_fact_types: list[str],
    evidence_items: list[dict[str, Any]],
    context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    context = context if isinstance(context, dict) else {}
    provider = str(context.get("provider") or config.EVIDENCE_EMBEDDING_RERANK_PROVIDER or "disabled").strip().lower()
    enabled = bool(context.get("enabled", config.EVIDENCE_EMBEDDING_RERANK_ENABLED))
    result = {
        "enabled": enabled,
        "used": False,
        "provider": provider if enabled else "disabled",
        "scores": {},
        "error": "",
        "fallback_used": False,
    }
    if not enabled or provider == "disabled":
        return result

    try:
        if context.get("raise"):
            raise RuntimeError(str(context.get("raise_message") or "mock embedding rerank failure"))
        if provider not in {"mock", "local"}:
            result["provider"] = provider or "disabled"
            result["fallback_used"] = True
            result["error"] = "embedding_provider_not_available"
            return result

        overrides = context.get("scores") or context.get("mock_scores") or {}
        if not isinstance(overrides, dict):
            overrides = {}

        scores: dict[str, dict[str, Any]] = {}
        for item in evidence_items or []:
            if not isinstance(item, dict):
                continue
            key = str(item.get("rerank_key") or "").strip()
            if not key:
                continue
            override = overrides.get(key)
            if isinstance(override, dict):
                score = _clamp_score(override.get("embedding_score", override.get("score", 0)))
                reason = str(override.get("embedding_reason") or override.get("reason") or "mock override score")
                model = str(override.get("model") or provider)
            elif override is not None:
                score = _clamp_score(override)
                reason = "mock override score"
                model = provider
            elif item.get("mock_embedding_score") is not None or item.get("embedding_score") is not None:
                score = _clamp_score(item.get("mock_embedding_score", item.get("embedding_score")))
                reason = "mock item score"
                model = provider
            else:
                score = _local_similarity(query_text, _evidence_text(item))
                reason = "local lexical similarity"
                model = provider
            scores[key] = {
                "embedding_score": score,
                "embedding_reason": reason,
                "model": model,
            }

        result["scores"] = scores
        result["used"] = bool(scores)
        return result
    except Exception as exc:
        return {
            "enabled": enabled,
            "used": False,
            "provider": provider or "disabled",
            "scores": {},
            "error": str(exc),
            "fallback_used": True,
        }


def _evidence_text(item: dict[str, Any]) -> str:
    parts = []
    for field in ("title", "asset_title", "matched_title", "fact", "chunk_text", "content", "text", "preview", "description"):
        value = str(item.get(field) or "").strip()
        if value:
            parts.append(value)
    return " ".join(parts)


def _local_similarity(query_text: str, evidence_text: str) -> float:
    query_tokens = set(_tokens(query_text))
    evidence_tokens = set(_tokens(evidence_text))
    if not query_tokens or not evidence_tokens:
        return 0.0
    overlap = len(query_tokens & evidence_tokens)
    return round(overlap / max(len(query_tokens), 1), 4)


def _tokens(value: str) -> list[str]:
    text = str(value or "").lower()
    ascii_tokens = re.findall(r"[a-z0-9]+", text)
    cjk_chars = re.findall(r"[\u4e00-\u9fff]", text)
    return [*ascii_tokens, *cjk_chars]


def _clamp_score(value: Any) -> float:
    try:
        score = float(value)
    except (TypeError, ValueError):
        score = 0.0
    return max(0.0, min(1.0, score))
