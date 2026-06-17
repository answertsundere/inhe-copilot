"""
Embedding 覆盖率检查脚本

用法:
  python scripts/knowledge/check_embedding_coverage.py
  python scripts/knowledge/check_embedding_coverage.py --verbose
"""

import json
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))


def check_coverage(verbose: bool = False):
    from app.db import SessionLocal, init_db
    from app.models.knowledge_base import KnowledgeChunk, KnowledgeEntry

    init_db()
    db = SessionLocal()

    try:
        # Entry-level stats
        entries = db.query(KnowledgeEntry).all()
        status_counts = {}
        source_type_counts = {}
        for e in entries:
            status_counts[e.status] = status_counts.get(e.status, 0) + 1
            key = f"{e.source_type}:{e.status}"
            source_type_counts[key] = source_type_counts.get(key, 0) + 1

        print("=== 知识条目统计 ===")
        print(f"总数: {len(entries)}")
        for status, count in sorted(status_counts.items()):
            print(f"  {status}: {count}")

        # Chunk-level stats
        total_chunks = db.query(KnowledgeChunk).count()
        chunks_with_embedding = db.query(KnowledgeChunk).filter(
            KnowledgeChunk.embedding_json.isnot(None)
        ).count()
        chunks_done = db.query(KnowledgeChunk).filter(
            KnowledgeChunk.embedding_status == "done"
        ).count()

        print(f"\n=== Chunk 统计 ===")
        print(f"总 chunks:          {total_chunks}")
        print(f"有 embedding:       {chunks_with_embedding}")
        print(f"embedding_status=done: {chunks_done}")
        print(f"覆盖率:            {chunks_with_embedding / total_chunks * 100:.1f}%" if total_chunks else "N/A")

        # Published-only coverage
        published_ids = [e.id for e in entries if e.status == "published"]
        if published_ids:
            pub_chunks = db.query(KnowledgeChunk).filter(
                KnowledgeChunk.entry_id.in_(published_ids)
            ).count()
            pub_embedded = db.query(KnowledgeChunk).filter(
                KnowledgeChunk.entry_id.in_(published_ids),
                KnowledgeChunk.embedding_json.isnot(None),
            ).count()
            print(f"\n=== 已发布条目覆盖 ===")
            print(f"已发布条目:        {len(published_ids)}")
            print(f"已发布 chunks:     {pub_chunks}")
            print(f"已嵌入:            {pub_embedded}")
            coverage = pub_embedded / pub_chunks * 100 if pub_chunks else 0
            print(f"覆盖率:            {coverage:.1f}%")
            if coverage >= 95:
                print("[OK] 已发布覆盖 >= 95%，满足启用 vector 检索门槛")
            else:
                gap = pub_chunks - pub_embedded
                print(f"[X] 距离 95% 门槛还差 {gap} 个 chunks")
                print("  运行: python scripts/build_knowledge_embeddings.py --published-only")

        # Source type breakdown
        print(f"\n=== Source Type 分布 ===")
        for key, count in sorted(source_type_counts.items()):
            print(f"  {key}: {count}")

        # Ready check
        print(f"\n=== 启用就绪检查 ===")
        from app.config import EMBEDDING_API_BASE, EMBEDDING_API_KEY, EMBEDDING_MODEL
        from app.config import EMBEDDING_ENABLED, EMBEDDING_SHADOW_MODE

        checks = {
            "API Base 已配置": bool(EMBEDDING_API_BASE),
            "API Key 已配置": bool(EMBEDDING_API_KEY),
            "Embedding 模型": EMBEDDING_MODEL or "未配置",
            "已发布覆盖率 >= 95%": (pub_embedded / pub_chunks * 100 >= 95) if pub_chunks else False,
        }
        for name, result in checks.items():
            mark = "[OK]" if result else "[X]"
            print(f"  {mark} {name}: {result}")

        all_ready = all(v for v in checks.values() if isinstance(v, bool))
        print(f"\n{'[OK] 就绪' if all_ready else '[X] 未就绪'}")

        if verbose:
            # Show draft entries with product scope (candidates for publish review)
            draft_with_scope = [
                e for e in entries
                if e.status == "draft"
                and json.loads(e.product_scope_json or "[]")
            ]
            print(f"\n=== Draft 条目有 product_scope ({len(draft_with_scope)}) ===")
            for e in draft_with_scope[:20]:
                scope = json.loads(e.product_scope_json or "[]")
                print(f"  [{e.id}] {e.title[:50]} scope={scope} source={e.source_type}")

    finally:
        db.close()


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args()
    check_coverage(verbose=args.verbose)
