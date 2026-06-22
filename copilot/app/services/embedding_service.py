"""Embedding service using the central model alias router."""

from __future__ import annotations

import logging

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
            return [item.embedding for item in response.data]
        except Exception as exc:
            logger.error("Embedding call failed: %s", exc)
            return []
