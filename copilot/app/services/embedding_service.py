"""Embedding service using the central model alias router."""

from __future__ import annotations

import logging
import time

from app.services.model_call_ledger_service import record_model_call
from app.services.model_router_service import resolve_model, resolve_model_api_key

logger = logging.getLogger(__name__)


class EmbeddingService:
    """OpenAI-compatible embedding service."""

    @staticmethod
    def get_embeddings(texts: list) -> list:
        if not texts:
            return []

        resolved = resolve_model("embedding_model")
        api_key = resolve_model_api_key("embedding_model")
        if not resolved.get("api_base") or not api_key or not resolved.get("model"):
            logger.warning("Embedding model is not configured; skip embedding generation")
            return []

        started = time.monotonic()
        try:
            from openai import OpenAI

            client = OpenAI(
                base_url=resolved.get("api_base", ""),
                api_key=api_key,
            )
            response = client.embeddings.create(
                model=resolved.get("model", ""),
                input=texts,
            )
            usage = _usage_dict(getattr(response, "usage", None))
            record_model_call(
                node_name="embedding_service",
                alias="embedding_model",
                provider=str(resolved.get("provider") or ""),
                model=str(resolved.get("model") or ""),
                api_base=str(resolved.get("api_base") or ""),
                prompt_tokens=usage["prompt_tokens"],
                completion_tokens=0,
                total_tokens=usage["total_tokens"],
                latency_ms=int((time.monotonic() - started) * 1000),
                status="success",
                metadata={
                    "input_count": len(texts),
                    "total_chars": sum(len(str(text or "")) for text in texts),
                    "usage_missing": not bool(getattr(response, "usage", None)),
                },
            )
            return [item.embedding for item in response.data]
        except Exception as exc:
            logger.error("Embedding call failed: %s", exc)
            record_model_call(
                node_name="embedding_service",
                alias="embedding_model",
                provider=str(resolved.get("provider") or ""),
                model=str(resolved.get("model") or ""),
                api_base=str(resolved.get("api_base") or ""),
                latency_ms=int((time.monotonic() - started) * 1000),
                status="error",
                error_type=type(exc).__name__,
                error_message=str(exc),
                metadata={
                    "input_count": len(texts),
                    "total_chars": sum(len(str(text or "")) for text in texts),
                    "usage_missing": True,
                },
            )
            return []


def _usage_dict(usage) -> dict[str, int]:
    if not usage:
        return {"prompt_tokens": 0, "total_tokens": 0}
    prompt = int(getattr(usage, "prompt_tokens", 0) or 0)
    total = int(getattr(usage, "total_tokens", prompt) or 0)
    return {"prompt_tokens": prompt, "total_tokens": total}
