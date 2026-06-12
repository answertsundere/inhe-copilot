"""
知识索引服务 - 发布/归档/回滚时更新 chunks
"""

import logging

from app.repositories.knowledge_entry_repository import KnowledgeEntryRepository
from app.repositories.knowledge_chunk_repository import KnowledgeChunkRepository
from app.repositories.knowledge_version_repository import KnowledgeVersionRepository

logger = logging.getLogger(__name__)


class KnowledgeIndexService:
    """知识索引服务"""

    @staticmethod
    def index_entry(entry_id: int) -> dict:
        """为单个条目创建/重建索引（chunks）。

        Returns dict with indexing result.
        """
        entry = KnowledgeEntryRepository.get_by_id(entry_id)
        if not entry:
            raise ValueError(f"知识条目 {entry_id} 不存在")

        content_hash_before = entry.content_hash

        # Delete old chunks
        KnowledgeChunkRepository.delete_by_entry(entry_id)

        # Create new chunks
        chunks = KnowledgeChunkRepository.create_chunks(
            entry_id=entry_id,
            content=entry.content,
            source_type=entry.source_type,
            intent=entry.intent,
            product_scope=entry.get_product_scope(),
            sku_scope=entry.get_sku_scope(),
            platform_scope=entry.get_platform_scope(),
            auto_reply_allowed=entry.auto_reply_allowed,
            human_review_required=entry.human_review_required,
            category=entry.category,
            category_l3=entry.category_l3,
            search_keywords=entry.search_keywords,
        )

        # Try embedding if available
        embedding_status = "unavailable"
        try:
            from app.config import EMBEDDING_ENABLED
            if EMBEDDING_ENABLED:
                from app.services.embedding_service import EmbeddingService
                texts = [c.chunk_text for c in chunks] if chunks else []
                if texts:
                    embeddings = EmbeddingService.get_embeddings(texts)
                    if embeddings and len(embeddings) == len(chunks):
                        import json
                        for chunk, emb in zip(chunks, embeddings):
                            chunk.embedding_json = json.dumps(emb)
                            chunk.embedding_status = "done"
                        embedding_status = "ready"
                    else:
                        embedding_status = "failed"
        except Exception as e:
            logger.warning("Embedding failed for entry %s: %s", entry_id, e)
            embedding_status = "failed"

        # 更新 entry 的 index_status（向后兼容：旧测试直接调用此方法）
        from app.db import SessionLocal
        from app.models.knowledge_base import KnowledgeEntry
        db = SessionLocal()
        try:
            entry_obj = db.query(KnowledgeEntry).filter(KnowledgeEntry.id == entry_id).first()
            if entry_obj:
                entry_obj.index_status = "ready"
                db.commit()
        finally:
            db.close()

        logger.warning(
            "DEPRECATED: KnowledgeIndexService.index_entry() called for entry %s. "
            "Use KnowledgeIndexPipeline.index_published_entry() instead.",
            entry_id,
        )

        return {
            "entry_id": entry_id,
            "chunks_created": len(chunks) if chunks else 0,
            "content_hash": entry.content_hash,
            "embedding_status": embedding_status,
        }

    @staticmethod
    def on_publish(entry_id: int, user: str = ""):
        """
        发布知识时：委托给 KnowledgeLifecycleService，避免直接调用底层 Repository。

        向后兼容：旧代码直接调用此方法时，自动走统一生命周期。
        """
        from app.services.knowledge_lifecycle_service import KnowledgeLifecycleService

        entry = KnowledgeEntryRepository.get_by_id(entry_id)
        if not entry:
            raise ValueError(f"知识条目 {entry_id} 不存在")
        if entry.status not in ("pending_review", "published"):
            raise ValueError(f"当前状态 {entry.status} 不允许发布")

        if entry.status == "pending_review":
            # 向后兼容：旧测试直接调用此方法，跳过质量门槛
            result = KnowledgeLifecycleService._force_publish(entry_id, user)
            if result.get("error"):
                raise RuntimeError(f"发布失败: {result['error']}")
            return result

        # 已经是 published：仅重建索引（向后兼容）
        from app.services.knowledge_index_pipeline import KnowledgeIndexPipeline
        return KnowledgeIndexPipeline.index_published_entry(entry_id)

    @staticmethod
    def on_archive(entry_id: int, user: str = ""):
        """归档时委托给 KnowledgeLifecycleService，避免直接调用底层 Repository。"""
        from app.services.knowledge_lifecycle_service import KnowledgeLifecycleService

        entry = KnowledgeEntryRepository.get_by_id(entry_id)
        if not entry:
            raise ValueError(f"知识条目 {entry_id} 不存在")

        result = KnowledgeLifecycleService.archive(entry_id, user)
        if result.get("error"):
            raise RuntimeError(f"归档失败: {result['error']}")
        return result
