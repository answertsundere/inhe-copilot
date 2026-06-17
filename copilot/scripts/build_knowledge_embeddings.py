"""
构建知识分片 embeddings 脚本

用法:
  python scripts/build_knowledge_embeddings.py                       # 增量构建
  python scripts/build_knowledge_embeddings.py --all                  # 全量重建
  python scripts/build_knowledge_embeddings.py --published-only       # 只处理已发布条目的 chunks
  python scripts/build_knowledge_embeddings.py --preflight            # 预检：检查配置和连通性
  python scripts/build_knowledge_embeddings.py --resume               # 续跑（跳过已完成的）
"""

import argparse
import hashlib
import json
import sys
import time
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

BATCH_SIZE = 20
MAX_RETRIES = 3
RETRY_DELAY = 2  # seconds


def preflight_check():
    """Check embedding API configuration and connectivity before building."""
    print("=== Embedding 预检 ===\n")

    # 1. Check configuration
    from app.config import EMBEDDING_API_BASE, EMBEDDING_API_KEY, EMBEDDING_MODEL
    from app.config import EMBEDDING_ENABLED, EMBEDDING_SHADOW_MODE

    print(f"EMBEDDING_ENABLED       = {EMBEDDING_ENABLED}")
    print(f"EMBEDDING_SHADOW_MODE   = {EMBEDDING_SHADOW_MODE}")
    print(f"EMBEDDING_MODEL         = {EMBEDDING_MODEL}")
    print(f"EMBEDDING_API_BASE      = {'<configured>' if EMBEDDING_API_BASE else '<MISSING>'}")
    print(f"EMBEDDING_API_KEY       = {'<configured>' if EMBEDDING_API_KEY else '<MISSING>'}")

    issues = []
    if not EMBEDDING_API_BASE:
        issues.append("EMBEDDING_API_BASE 未配置")
    if not EMBEDDING_API_KEY:
        issues.append("EMBEDDING_API_KEY 未配置")

    if issues:
        print(f"\n配置问题: {', '.join(issues)}")
        print("请在 .env 中设置相应环境变量。")
        return False

    # 2. Test API call
    print("\n测试 Embedding API 调用...")
    try:
        from app.services.embedding_service import EmbeddingService
        result = EmbeddingService.get_embeddings(["测试文本"])
        if not result or not result[0]:
            print("API 调用返回空结果")
            return False
        dim = len(result[0])
        print(f"API 调用成功，向量维度: {dim}")
    except Exception as e:
        print(f"API 调用失败: {e}")
        return False

    # 3. Check chunk coverage
    from app.db import SessionLocal, init_db
    init_db()
    from app.models.knowledge_base import KnowledgeChunk, KnowledgeEntry

    db = SessionLocal()
    try:
        total_chunks = db.query(KnowledgeChunk).count()
        chunks_with_embedding = db.query(KnowledgeChunk).filter(
            KnowledgeChunk.embedding_json.isnot(None)
        ).count()
        published_entry_ids = [
            r[0] for r in db.query(KnowledgeEntry.id).filter(
                KnowledgeEntry.status == "published"
            ).all()
        ]
        published_chunks = db.query(KnowledgeChunk).filter(
            KnowledgeChunk.entry_id.in_(published_entry_ids)
        ).count() if published_entry_ids else 0
        published_with_embedding = db.query(KnowledgeChunk).filter(
            KnowledgeChunk.entry_id.in_(published_entry_ids),
            KnowledgeChunk.embedding_json.isnot(None),
        ).count() if published_entry_ids else 0

        coverage = (chunks_with_embedding / total_chunks * 100) if total_chunks else 0
        pub_coverage = (published_with_embedding / published_chunks * 100) if published_chunks else 0

        print(f"\n=== Chunk 覆盖率 ===")
        print(f"总 chunks:                    {total_chunks}")
        print(f"已有 embedding:               {chunks_with_embedding}")
        print(f"总覆盖率:                     {coverage:.1f}%")
        print(f"已发布条目 chunks:            {published_chunks}")
        print(f"已发布 chunks 有 embedding:   {published_with_embedding}")
        print(f"已发布覆盖率:                 {pub_coverage:.1f}%")

        if pub_coverage < 95:
            print(f"\n⚠ 已发布 chunk embedding 覆盖率 ({pub_coverage:.1f}%) < 95%，不建议启用 vector 检索。")
        else:
            print(f"\n✓ 已发布 chunk embedding 覆盖率 >= 95%，可考虑启用 vector 检索。")
    finally:
        db.close()

    return True


def _content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", errors="ignore")).hexdigest()[:16]


def build_embeddings(rebuild_all: bool = False, published_only: bool = False,
                     resume: bool = False):
    """构建知识分片的 embedding 向量"""
    from app.db import SessionLocal, init_db
    from app.models.knowledge_base import KnowledgeChunk, KnowledgeEntry
    from app.services.embedding_service import EmbeddingService

    init_db()
    db = SessionLocal()

    try:
        query = db.query(KnowledgeChunk)

        if published_only:
            published_ids = [
                r[0] for r in db.query(KnowledgeEntry.id).filter(
                    KnowledgeEntry.status == "published"
                ).all()
            ]
            if not published_ids:
                print("没有已发布的知识条目。")
                return
            query = query.filter(KnowledgeChunk.entry_id.in_(published_ids))

        if not rebuild_all and not resume:
            query = query.filter(KnowledgeChunk.embedding_json.is_(None))
        elif resume:
            # resume: skip chunks that already have embedding and content hasn't changed
            query = query.filter(
                (KnowledgeChunk.embedding_json.is_(None)) |
                (KnowledgeChunk.embedding_status != "done")
            )

        chunks = query.all()
        total = len(chunks)

        if total == 0:
            print("没有需要处理的 chunks。")
            return

        print(f"共 {total} 条 chunks 需要生成 embedding...")

        processed = 0
        failed = 0

        for i in range(0, total, BATCH_SIZE):
            batch = chunks[i: i + BATCH_SIZE]
            texts = [c.chunk_text for c in batch]

            # Retry logic
            embeddings = None
            for attempt in range(MAX_RETRIES):
                embeddings = EmbeddingService.get_embeddings(texts)
                if embeddings and len(embeddings) == len(batch):
                    break
                if attempt < MAX_RETRIES - 1:
                    print(f"  批次 {i // BATCH_SIZE + 1}: 重试 {attempt + 1}/{MAX_RETRIES}...")
                    time.sleep(RETRY_DELAY * (attempt + 1))

            if not embeddings or len(embeddings) != len(batch):
                print(f"  批次 {i // BATCH_SIZE + 1}: embedding 调用失败（已重试 {MAX_RETRIES} 次），跳过 {len(batch)} 条")
                failed += len(batch)
                continue

            for chunk, embedding in zip(batch, embeddings):
                chunk.embedding_json = json.dumps(embedding, ensure_ascii=False)
                chunk.embedding_status = "done"
                chunk.updated_at = datetime.utcnow()

            db.commit()
            processed += len(batch)
            print(f"  批次 {i // BATCH_SIZE + 1}: 已处理 {processed}/{total}")

        print(f"完成！成功: {processed}, 失败: {failed}, 总计: {total}")

        if failed > 0:
            print("提示：使用 --resume 参数可续跑失败的部分。")

    except Exception as e:
        print(f"构建 embedding 出错: {e}")
        db.rollback()
    finally:
        db.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="构建知识分片 embeddings")
    parser.add_argument("--all", action="store_true", help="全量重建所有 chunks 的 embeddings")
    parser.add_argument("--published-only", action="store_true", help="只处理已发布条目的 chunks")
    parser.add_argument("--preflight", action="store_true", help="预检：检查配置和连通性")
    parser.add_argument("--resume", action="store_true", help="续跑（跳过已完成的）")
    args = parser.parse_args()

    if args.preflight:
        ok = preflight_check()
        sys.exit(0 if ok else 1)
    else:
        build_embeddings(
            rebuild_all=args.all,
            published_only=args.published_only,
            resume=args.resume,
        )
