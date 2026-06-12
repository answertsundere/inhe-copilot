"""
知识索引流水线 - 唯一索引入口

KnowledgeIndexPipeline 是所有索引操作的唯一入口。
底层 KnowledgeIndexService 保留切片能力，但不负责业务状态流转。
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from typing import Optional

logger = logging.getLogger(__name__)


def _compute_full_hash(entry) -> str:
    """计算包含所有影响检索字段的完整 content_hash。"""
    parts = [
        entry.title or "",
        entry.content or "",
        entry.source_type or "",
        str(entry.version),
        json.dumps(entry.get_product_scope(), sort_keys=True, ensure_ascii=False),
        json.dumps(entry.get_sku_scope(), sort_keys=True, ensure_ascii=False),
        json.dumps(entry.get_platform_scope(), sort_keys=True, ensure_ascii=False),
    ]
    raw = "|".join(parts)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]


def _get_db():
    from app.db import SessionLocal
    return SessionLocal()


class KnowledgeIndexPipeline:
    """统一的增量索引流水线 - 唯一正式入口。"""

    @staticmethod
    def index_published_entry(entry_id: int) -> dict:
        """为已发布条目执行完整的索引流水线。

        只有 status=published 才允许索引。
        非 published 调用将被拒绝。
        """
        from app.repositories.knowledge_entry_repository import KnowledgeEntryRepository
        from app.models.knowledge_base import KnowledgeEntry, KnowledgeChunk

        db = _get_db()
        try:
            entry = db.query(KnowledgeEntry).filter(
                KnowledgeEntry.id == entry_id
            ).first()
            if not entry:
                return {"error": f"Entry {entry_id} not found", "entry_id": entry_id}

            if entry.status != "published":
                return {
                    "entry_id": entry_id,
                    "rejected": True,
                    "reason": f"status={entry.status}, only published entries can be indexed",
                }

            # 计算 full hash
            new_hash = _compute_full_hash(entry)

            # 检查是否需要重建
            if (entry.content_hash == new_hash
                    and entry.index_status == "ready"):
                # 验证 chunks 确实存在
                chunk_count = db.query(KnowledgeChunk).filter(
                    KnowledgeChunk.entry_id == entry_id
                ).count()
                if chunk_count > 0:
                    return {
                        "entry_id": entry_id,
                        "skipped": True,
                        "reason": "content and scope unchanged, index already ready",
                        "content_hash": new_hash,
                        "chunk_count": chunk_count,
                    }

            # 设置 indexing 状态
            entry.index_status = "indexing"
            db.commit()

            start = time.time()
            old_chunk_count = db.query(KnowledgeChunk).filter(
                KnowledgeChunk.entry_id == entry_id
            ).count()

            try:
                # 调用底层索引服务执行切片
                from app.services.knowledge_index_service import KnowledgeIndexService
                result = KnowledgeIndexService.index_entry(entry_id)

                # 验证 chunks 是否创建成功
                chunk_count = db.query(KnowledgeChunk).filter(
                    KnowledgeChunk.entry_id == entry_id
                ).count()

                if chunk_count == 0:
                    raise RuntimeError("Index produced zero chunks")

                # 成功：设置 ready
                entry = db.query(KnowledgeEntry).filter(
                    KnowledgeEntry.id == entry_id
                ).first()
                entry.index_status = "ready"
                entry.content_hash = new_hash
                db.commit()

                duration_ms = round((time.time() - start) * 1000, 1)

                return {
                    "entry_id": entry_id,
                    "index_status": "ready",
                    "content_hash": new_hash,
                    "chunks_created": chunk_count,
                    "old_chunk_count": old_chunk_count,
                    "duration_ms": duration_ms,
                    "embedding_status": result.get("embedding_status", "unavailable"),
                }

            except Exception as e:
                # 索引失败：补偿回滚
                logger.error("Index failed for entry %s: %s", entry_id, e)

                # 删除可能创建的部分 chunks
                db.query(KnowledgeChunk).filter(
                    KnowledgeChunk.entry_id == entry_id
                ).delete()

                entry = db.query(KnowledgeEntry).filter(
                    KnowledgeEntry.id == entry_id
                ).first()
                if entry:
                    entry.index_status = "failed"
                    entry.content_hash = ""
                db.commit()

                return {
                    "entry_id": entry_id,
                    "index_status": "failed",
                    "error": str(e),
                    "error_code": type(e).__name__,
                    "duration_ms": round((time.time() - start) * 1000, 1),
                }
        finally:
            db.close()

    @staticmethod
    def remove_entry(entry_id: int) -> dict:
        """从索引中移除条目（归档时调用）。

        删除 chunks 并设置 index_status=removed。
        """
        from app.repositories.knowledge_chunk_repository import KnowledgeChunkRepository
        from app.models.knowledge_base import KnowledgeEntry, KnowledgeChunk

        db = _get_db()
        try:
            # 删除 chunks
            deleted = db.query(KnowledgeChunk).filter(
                KnowledgeChunk.entry_id == entry_id
            ).delete()

            # 更新 index_status
            entry = db.query(KnowledgeEntry).filter(
                KnowledgeEntry.id == entry_id
            ).first()
            if entry:
                entry.index_status = "removed"
                entry.content_hash = ""

            db.commit()

            return {
                "entry_id": entry_id,
                "chunks_deleted": deleted,
                "index_status": "removed",
            }
        finally:
            db.close()

    @staticmethod
    def rebuild_entry(entry_id: int) -> dict:
        """重建单个条目的索引。

        只允许 published 条目。
        即使 content 未变也强制重建。
        """
        from app.models.knowledge_base import KnowledgeEntry

        db = _get_db()
        try:
            entry = db.query(KnowledgeEntry).filter(
                KnowledgeEntry.id == entry_id
            ).first()
            if not entry:
                return {"error": f"Entry {entry_id} not found", "entry_id": entry_id}

            if entry.status != "published":
                return {
                    "entry_id": entry_id,
                    "rejected": True,
                    "reason": f"status={entry.status}, only published entries can be rebuilt",
                }

            old_hash = entry.content_hash
            old_index_status = entry.index_status

            # 清除 hash 强制重建
            entry.content_hash = ""
            entry.index_status = "indexing"
            db.commit()
        finally:
            db.close()

        result = KnowledgeIndexPipeline.index_published_entry(entry_id)
        result["old_hash"] = old_hash
        result["old_index_status"] = old_index_status
        result["force_rebuilt"] = True
        return result

    @staticmethod
    def get_index_status(entry_id: int) -> dict:
        """获取条目的索引状态。"""
        from app.repositories.knowledge_entry_repository import KnowledgeEntryRepository
        from app.models.knowledge_base import KnowledgeChunk, KnowledgeEntry

        db = _get_db()
        try:
            entry = db.query(KnowledgeEntry).filter(
                KnowledgeEntry.id == entry_id
            ).first()
            if not entry:
                return {"entry_id": entry_id, "error": "not found"}

            chunk_count = db.query(KnowledgeChunk).filter(
                KnowledgeChunk.entry_id == entry_id
            ).count()
            embedded_count = db.query(KnowledgeChunk).filter(
                KnowledgeChunk.entry_id == entry_id,
                KnowledgeChunk.embedding_status == "done",
            ).count()

            return {
                "entry_id": entry_id,
                "status": entry.status,
                "index_status": getattr(entry, "index_status", "unknown"),
                "content_hash": entry.content_hash,
                "chunk_count": chunk_count,
                "embedded_count": embedded_count,
            }
        finally:
            db.close()

    @staticmethod
    def validate_index_consistency(entry_id: int) -> dict:
        """验证索引一致性。

        published entry 必须有 chunks 且 index_status=ready。
        非 published entry 不应有 chunks。
        """
        from app.models.knowledge_base import KnowledgeEntry, KnowledgeChunk

        db = _get_db()
        try:
            entry = db.query(KnowledgeEntry).filter(
                KnowledgeEntry.id == entry_id
            ).first()
            if not entry:
                return {"entry_id": entry_id, "error": "not found", "consistent": False}

            chunk_count = db.query(KnowledgeChunk).filter(
                KnowledgeChunk.entry_id == entry_id
            ).count()

            issues = []

            if entry.status == "published":
                if entry.index_status != "ready":
                    issues.append(f"published but index_status={entry.index_status}")
                if chunk_count == 0:
                    issues.append("published but has zero chunks")
                if not entry.content_hash:
                    issues.append("published but no content_hash")
            else:
                # 非 published 不应有 chunks
                if chunk_count > 0:
                    issues.append(
                        f"status={entry.status} but has {chunk_count} chunks"
                    )
                if entry.index_status == "ready":
                    issues.append(
                        f"status={entry.status} but index_status=ready"
                    )

            return {
                "entry_id": entry_id,
                "consistent": len(issues) == 0,
                "issues": issues,
                "status": entry.status,
                "index_status": entry.index_status,
                "chunk_count": chunk_count,
            }
        finally:
            db.close()

    @staticmethod
    def reindex_entries(entry_ids: list[int]) -> list[dict]:
        """批量重建索引（仅 published）。"""
        results = []
        for eid in entry_ids:
            try:
                r = KnowledgeIndexPipeline.index_published_entry(eid)
                results.append(r)
            except Exception as e:
                results.append({"entry_id": eid, "error": str(e)})
        return results

    @staticmethod
    def rebuild_all() -> dict:
        """重建所有 published 条目的索引。仅管理员调用。"""
        from app.models.knowledge_base import KnowledgeEntry

        db = _get_db()
        try:
            published = db.query(KnowledgeEntry).filter(
                KnowledgeEntry.status == "published"
            ).all()
            entry_ids = [e.id for e in published]
        finally:
            db.close()

        results = KnowledgeIndexPipeline.reindex_entries(entry_ids)
        succeeded = sum(1 for r in results if r.get("index_status") == "ready")
        failed = sum(1 for r in results if r.get("index_status") == "failed")
        skipped = sum(1 for r in results if r.get("skipped"))

        return {
            "total": len(entry_ids),
            "succeeded": succeeded,
            "failed": failed,
            "skipped": skipped,
            "results": results,
        }

    @staticmethod
    def invalidate_cache(entry) -> dict:
        """使缓存失效。当前无缓存系统，保留接口。"""
        return {
            "tags": [f"knowledge_entry:{entry.id}"],
            "invalidated": 0,
            "note": "No cache system active",
        }

    # ---- 向后兼容方法（内部仍走新逻辑） ----

    @staticmethod
    def index_entry(entry_id: int) -> dict:
        """向后兼容：内部调用 index_published_entry。"""
        return KnowledgeIndexPipeline.index_published_entry(entry_id)

    @staticmethod
    def remove_entry_from_index(entry_id: int) -> dict:
        """向后兼容：内部调用 remove_entry。"""
        return KnowledgeIndexPipeline.remove_entry(entry_id)
