"""
混合检索评估脚本 — 在 shadow mode 下比较 BM25 vs Hybrid 检索效果

用法:
  python scripts/knowledge/evaluate_hybrid_retrieval.py
  python scripts/knowledge/evaluate_hybrid_retrieval.py --queries queries.json
  python scripts/knowledge/evaluate_hybrid_retrieval.py --top-k 5
"""

import json
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))


# 标准评估查询集：覆盖五个重点案例
DEFAULT_QUERIES = [
    {"query": "一号狮子围兜防水吗", "expected_scope": ["狮子围兜"], "intent": "product_question"},
    {"query": "六号防摔枕材质是什么？能洗吗", "expected_scope": ["防摔枕"], "intent": "product_question"},
    {"query": "刺猬桌面书架能放多少本书？结实吗", "expected_scope": ["刺猬书架", "书架"], "intent": "product_question"},
    {"query": "十一号防摔枕适合多大宝宝", "expected_scope": ["防摔枕"], "intent": "product_question"},
    {"query": "儿童书架是不是实木的", "expected_scope": ["书架"], "intent": "product_question"},
    {"query": "我的订单什么时候发货", "expected_scope": [], "intent": "logistics_eta"},
    {"query": "退款多久到账", "expected_scope": [], "intent": "aftersales_refund"},
    {"query": "爬行垫有味道吗", "expected_scope": ["爬行垫"], "intent": "product_question"},
    {"query": "围栏怎么安装", "expected_scope": ["围栏"], "intent": "installation"},
    {"query": "收到破损了怎么处理", "expected_scope": [], "intent": "aftersales_damage"},
]


def evaluate(top_k: int = 5, queries_file: str = ""):
    from app.repositories.knowledge_chunk_repository import KnowledgeChunkRepository

    repo = KnowledgeChunkRepository()
    queries = DEFAULT_QUERIES

    if queries_file and os.path.exists(queries_file):
        with open(queries_file, "r", encoding="utf-8") as f:
            queries = json.load(f)

    results = {
        "bm25": {"recall_1": 0, "recall_3": 0, "recall_5": 0, "total": 0},
        "hybrid": {"recall_1": 0, "recall_3": 0, "recall_5": 0, "total": 0},
    }
    per_query = []

    for q in queries:
        query_text = q["query"]
        expected_scope = q.get("expected_scope", [])
        intent = q.get("intent", "")

        # BM25 search
        bm25_results = repo.search_bm25(query_text, intent=intent, top_k=top_k)
        bm25_chunks = [r for r in bm25_results]

        # Hybrid search (BM25 + vector + scope)
        hybrid_results = repo.search_hybrid(query_text, intent=intent, top_k=top_k)
        hybrid_chunks = [r for r in hybrid_results]

        # Evaluate: does the correct product scope appear in results?
        def _scope_match(chunks, expected):
            if not expected:
                return True  # No scope requirement
            for c in chunks:
                scope = c.get("product_scope", []) or c.get("metadata", {}).get("product_scope", [])
                for es in expected:
                    if any(es in s for s in scope):
                        return True
            return False

        bm25_hit_1 = _scope_match(bm25_chunks[:1], expected_scope)
        bm25_hit_3 = _scope_match(bm25_chunks[:3], expected_scope)
        bm25_hit_5 = _scope_match(bm25_chunks[:5], expected_scope)

        hybrid_hit_1 = _scope_match(hybrid_chunks[:1], expected_scope)
        hybrid_hit_3 = _scope_match(hybrid_chunks[:3], expected_scope)
        hybrid_hit_5 = _scope_match(hybrid_chunks[:5], expected_scope)

        results["bm25"]["recall_1"] += int(bm25_hit_1)
        results["bm25"]["recall_3"] += int(bm25_hit_3)
        results["bm25"]["recall_5"] += int(bm25_hit_5)
        results["bm25"]["total"] += 1

        results["hybrid"]["recall_1"] += int(hybrid_hit_1)
        results["hybrid"]["recall_3"] += int(hybrid_hit_3)
        results["hybrid"]["recall_5"] += int(hybrid_hit_5)
        results["hybrid"]["total"] += 1

        per_query.append({
            "query": query_text,
            "expected_scope": expected_scope,
            "bm25_top1_scope_hit": bm25_hit_1,
            "bm25_top3_scope_hit": bm25_hit_3,
            "bm25_top5_scope_hit": bm25_hit_5,
            "hybrid_top1_scope_hit": hybrid_hit_1,
            "hybrid_top3_scope_hit": hybrid_hit_3,
            "hybrid_top5_scope_hit": hybrid_hit_5,
            "bm25_top_titles": [c.get("title", c.get("chunk_text", "")[:50]) for c in bm25_chunks[:3]],
            "hybrid_top_titles": [c.get("title", c.get("chunk_text", "")[:50]) for c in hybrid_chunks[:3]],
        })

    # Print summary
    total = results["bm25"]["total"]
    print("=== 混合检索评估结果 ===\n")
    print(f"{'方法':<12} {'Recall@1':>10} {'Recall@3':>10} {'Recall@5':>10}")
    print("-" * 45)

    for method in ("bm25", "hybrid"):
        r = results[method]
        r1 = r["recall_1"] / total * 100 if total else 0
        r3 = r["recall_3"] / total * 100 if total else 0
        r5 = r["recall_5"] / total * 100 if total else 0
        print(f"{method:<12} {r1:>9.1f}% {r3:>9.1f}% {r5:>9.1f}%")

    print("\n=== 逐查询结果 ===")
    for pq in per_query:
        hits = []
        if pq["bm25_top1_scope_hit"]:
            hits.append("BM25@1")
        if pq["hybrid_top1_scope_hit"]:
            hits.append("Hybrid@1")
        mark = "✓" if hits else "✗"
        print(f"  {mark} {pq['query']}")
        if hits:
            print(f"    命中: {', '.join(hits)}")
        print(f"    BM25 top: {pq['bm25_top_titles'][:2]}")
        print(f"    Hybrid top: {pq['hybrid_top_titles'][:2]}")

    # Takeover readiness
    bm25_r5 = results["bm25"]["recall_5"] / total * 100 if total else 0
    hybrid_r5 = results["hybrid"]["recall_5"] / total * 100 if total else 0

    print("\n=== 接管门槛 ===")
    print(f"BM25 Recall@5:    {bm25_r5:.1f}%")
    print(f"Hybrid Recall@5:  {hybrid_r5:.1f}%")
    if hybrid_r5 >= bm25_r5:
        print("✓ Hybrid Recall@5 >= BM25 Recall@5")
    else:
        print("✗ Hybrid Recall@5 < BM25 Recall@5，不建议接管")
        print("  可能原因: embedding 覆盖不足、向量维度不匹配、模型不匹配")

    return {
        "summary": results,
        "per_query": per_query,
    }


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--queries", default="")
    parser.add_argument("--top-k", type=int, default=5)
    args = parser.parse_args()
    evaluate(top_k=args.top_k, queries_file=args.queries)
