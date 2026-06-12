"""
Embedding 服务 - 使用 OpenAI 兼容接口生成向量
"""

import json
import logging

from app.config import EMBEDDING_API_BASE, EMBEDDING_API_KEY, EMBEDDING_MODEL

logger = logging.getLogger(__name__)


class EmbeddingService:
    """Embedding 服务 - OpenAI 兼容 API"""

    @staticmethod
    def get_embeddings(texts: list) -> list:
        """
        批量获取文本 embedding 向量

        Args:
            texts: 文本列表

        Returns:
            嵌入向量列表，每个元素是 float 列表。失败时返回空列表。
        """
        if not texts:
            return []

        if not EMBEDDING_API_BASE or not EMBEDDING_API_KEY:
            logger.warning("Embedding API 未配置 (EMBEDDING_API_BASE/EMBEDDING_API_KEY)，跳过向量生成")
            return []

        try:
            from openai import OpenAI

            client = OpenAI(
                base_url=EMBEDDING_API_BASE,
                api_key=EMBEDDING_API_KEY,
            )

            response = client.embeddings.create(
                model=EMBEDDING_MODEL,
                input=texts,
            )

            embeddings = [item.embedding for item in response.data]
            return embeddings

        except Exception as e:
            logger.error(f"Embedding 调用失败: {e}")
            return []
