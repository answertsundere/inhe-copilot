"""
检索工厂 - 根据配置返回检索实现

配置:
  COPILOT_RETRIEVER_BACKEND=current_sqlite (默认)
  未来可扩展: llamaindex, elasticsearch 等
"""

from __future__ import annotations

import logging
from typing import Optional

from app.retrieval.base import BaseKnowledgeRetriever

logger = logging.getLogger(__name__)

_instances: dict[str, BaseKnowledgeRetriever] = {}


def get_retriever(backend: str = "") -> BaseKnowledgeRetriever:
    """根据配置获取检索实现。"""
    if not backend:
        from app.config import _env_bool
        import os
        backend = os.environ.get("COPILOT_RETRIEVER_BACKEND", "current_sqlite")

    if backend in _instances:
        return _instances[backend]

    if backend == "current_sqlite":
        from app.retrieval.current_sqlite_retriever import CurrentSQLiteRetriever
        instance = CurrentSQLiteRetriever()
    else:
        logger.warning("Unknown retriever backend '%s', falling back to current_sqlite", backend)
        from app.retrieval.current_sqlite_retriever import CurrentSQLiteRetriever
        instance = CurrentSQLiteRetriever()

    _instances[backend] = instance
    return instance


def reset_retrievers():
    """重置所有检索实例（测试用）。"""
    _instances.clear()
